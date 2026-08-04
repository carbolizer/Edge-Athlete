import hashlib
import json
import math
import re
from datetime import date

from django.db import transaction
from django.utils import timezone

from ..models import (
    Athlete,
    AthleteDayPlan,
    AthleteDayPlanExercise,
    AthleteDayPlanWorkout,
    AthleteDayProgress,
    AthleteSchedule,
    AthleteScheduleEntry,
    AthleteSchedulePlan,
    AthleteSchedulePlanExercise,
    AthleteSchedulePlanWorkout,
    AthleteWorkoutExerciseOverride,
    AthleteWorkoutProgramAssignment,
    Workout,
    WorkoutExercise,
    WorkoutProgram,
)
from .training_days import lock_training_day
from .training_limits import (
    MAX_SESSION_SETS,
    MAX_SCHEDULE_CLIENT_ID_LENGTH,
    MAX_SCHEDULE_ENTRIES,
    MAX_SCHEDULE_EXERCISES_PER_WORKOUT,
    MAX_SCHEDULE_EXERCISES_TOTAL,
    MAX_SCHEDULE_LOAD_LBS,
    MAX_SCHEDULE_NAME_LENGTH,
    MAX_SCHEDULE_PLANS,
    MAX_SCHEDULE_REPS,
    MAX_SCHEDULE_SETS,
    MAX_SCHEDULE_WORKOUTS_PER_PLAN,
)


class ScheduleError(Exception):
    def __init__(self, code, detail, *, errors=None, dimensions=None):
        self.code = code
        self.detail = detail
        self.errors = errors
        self.dimensions = dimensions
        super().__init__(detail)


def _reject_unknown(body, allowed, context):
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise ScheduleError("unknown_fields", f"Unknown {context} field(s): {', '.join(unknown)}.")


def _bounded_list(value, field, maximum, *, nonempty=True):
    if not isinstance(value, list) or (nonempty and not value):
        qualifier = "nonempty " if nonempty else ""
        raise ScheduleError("scheduled_plan_invalid", f"{field} must be a {qualifier}list.")
    if len(value) > maximum:
        raise ScheduleError("scheduled_plan_invalid", f"{field} may contain at most {maximum} items.")
    return value


def prevalidate_schedule_payload(payload):
    """Bound and type-check the complete request before catalog or athlete queries."""
    _reject_unknown(payload, {"expected_version", "plans", "entries"}, "schedule")
    expected = payload.get("expected_version")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise ScheduleError("scheduled_plan_invalid", "expected_version must be a nonnegative integer.")
    plans = _bounded_list(payload.get("plans"), "plans", MAX_SCHEDULE_PLANS)
    entries = _bounded_list(payload.get("entries"), "entries", MAX_SCHEDULE_ENTRIES)
    exercise_total = 0
    for plan in plans:
        if not isinstance(plan, dict):
            raise ScheduleError("scheduled_plan_invalid", "Each plan must be an object.")
        _reject_unknown(plan, {
            "client_id", "key", "name", "workout_program_id", "source_program_id", "workouts",
        }, "plan")
        client_id = plan.get("client_id", plan.get("key"))
        if client_id is not None and (
            isinstance(client_id, bool) or not isinstance(client_id, (str, int))
            or len(str(client_id)) > MAX_SCHEDULE_CLIENT_ID_LENGTH
        ):
            raise ScheduleError(
                "scheduled_plan_invalid",
                f"Plan client_id must be at most {MAX_SCHEDULE_CLIENT_ID_LENGTH} characters.",
            )
        name = plan.get("name")
        if name is not None and (
            not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_SCHEDULE_NAME_LENGTH
        ):
            raise ScheduleError(
                "scheduled_plan_invalid",
                f"Plan name must be from 1 to {MAX_SCHEDULE_NAME_LENGTH} characters.",
            )
        workouts = plan.get("workouts")
        if workouts is None:
            continue
        _bounded_list(workouts, "workouts", MAX_SCHEDULE_WORKOUTS_PER_PLAN)
        for workout in workouts:
            if not isinstance(workout, dict):
                raise ScheduleError("scheduled_plan_invalid", "Each workout occurrence must be an object.")
            _reject_unknown(workout, {"workout_id", "source_workout_id", "exercises"}, "workout")
            exercises = workout.get("exercises")
            if exercises is None:
                continue
            _bounded_list(exercises, "exercises", MAX_SCHEDULE_EXERCISES_PER_WORKOUT)
            exercise_total += len(exercises)
            if exercise_total > MAX_SCHEDULE_EXERCISES_TOTAL:
                raise ScheduleError(
                    "scheduled_plan_invalid",
                    f"Schedule may contain at most {MAX_SCHEDULE_EXERCISES_TOTAL} exercises.",
                )
            for exercise in exercises:
                if not isinstance(exercise, dict):
                    raise ScheduleError("scheduled_plan_invalid", "Each exercise occurrence must be an object.")
                _reject_unknown(exercise, {
                    "workout_exercise_id", "source_exercise_id", "sets", "reps", "weight_lbs",
                    "velocity_min", "velocity_max",
                }, "exercise")
                for field, maximum in (("sets", MAX_SCHEDULE_SETS), ("reps", MAX_SCHEDULE_REPS)):
                    if field in exercise:
                        value = exercise[field]
                        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                            raise ScheduleError(
                                "scheduled_plan_invalid", f"{field} must be from 1 to {maximum}.",
                            )
                if "weight_lbs" in exercise:
                    value = exercise["weight_lbs"]
                    if (
                        isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or not 0 <= value <= MAX_SCHEDULE_LOAD_LBS
                    ):
                        raise ScheduleError(
                            "scheduled_plan_invalid",
                            f"weight_lbs must be from 0 to {MAX_SCHEDULE_LOAD_LBS}.",
                        )
                for field in ("velocity_min", "velocity_max"):
                    if field in exercise and exercise[field] is not None:
                        value = exercise[field]
                        if (
                            isinstance(value, bool) or not isinstance(value, (int, float))
                            or not math.isfinite(value) or not 0 <= value <= 10
                        ):
                            raise ScheduleError("scheduled_plan_invalid", f"{field} must be from 0 to 10 or null.")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ScheduleError("scheduled_plan_invalid", "Each schedule entry must be an object.")
        _reject_unknown(entry, {
            "date", "weekday", "is_rest", "rest", "plan_client_id", "plan_key", "plan_index",
        }, "entry")
        plan_key = entry.get("plan_client_id", entry.get("plan_key", entry.get("plan_index")))
        if plan_key is not None and (
            isinstance(plan_key, bool) or not isinstance(plan_key, (str, int))
            or len(str(plan_key)) > MAX_SCHEDULE_CLIENT_ID_LENGTH
        ):
            raise ScheduleError(
                "scheduled_plan_invalid",
                f"Entry plan client ID must be at most {MAX_SCHEDULE_CLIENT_ID_LENGTH} characters.",
            )
        exact_date = entry.get("date")
        if exact_date is not None and (
            not isinstance(exact_date, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", exact_date) is None
        ):
            raise ScheduleError("scheduled_plan_invalid", "date must use YYYY-MM-DD.")
        if exact_date is not None:
            try:
                date.fromisoformat(exact_date)
            except ValueError:
                raise ScheduleError("scheduled_plan_invalid", "date must use YYYY-MM-DD.")


def _positive(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ScheduleError("scheduled_plan_invalid", f"{field} must be a positive integer.")
    return value


def _target(value, field, *, integer=False, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScheduleError("scheduled_plan_invalid", f"{field} is invalid.")
    if integer:
        maximum = MAX_SCHEDULE_SETS if field == "sets" else MAX_SCHEDULE_REPS
        if not isinstance(value, int) or not 1 <= value <= maximum:
            raise ScheduleError("scheduled_plan_invalid", f"{field} must be from 1 to {maximum}.")
        return value
    maximum = 10 if field.startswith("velocity_") else MAX_SCHEDULE_LOAD_LBS
    if not math.isfinite(value) or not 0 <= value <= maximum:
        raise ScheduleError("scheduled_plan_invalid", f"{field} must be from 0 to {maximum}.")
    return float(value)


def _exercise_values(source, submitted=None):
    submitted = submitted or {}
    if submitted.get("workout_exercise_id", submitted.get("source_exercise_id", source.id)) != source.id:
        raise ScheduleError("scheduled_plan_invalid", "Exercise does not belong to its workout occurrence.")
    minimum = submitted.get("velocity_min", source.velocity_min)
    maximum = submitted.get("velocity_max", source.velocity_max)
    minimum = _target(minimum, "velocity_min", nullable=True)
    maximum = _target(maximum, "velocity_max", nullable=True)
    if (minimum is None) != (maximum is None) or (minimum is not None and (minimum > maximum or maximum > 10)):
        raise ScheduleError("scheduled_plan_invalid", "Velocity targets must be blank together or ordered from 0 to 10.")
    return {
        "source_exercise": source,
        "exercise": source.exercise,
        "sets": _target(submitted.get("sets", source.sets), "sets", integer=True),
        "reps": _target(submitted.get("reps", source.reps), "reps", integer=True),
        "weight_lbs": _target(submitted.get("weight_lbs", source.default_weight_lbs), "weight_lbs"),
        "velocity_min": minimum,
        "velocity_max": maximum,
    }


def _validated_plans(athlete, payload):
    plans = payload.get("plans")
    if not isinstance(plans, list) or not plans:
        raise ScheduleError("scheduled_plan_invalid", "plans must be a nonempty list.")
    result = []
    keys = set()
    exercise_total = 0
    for plan_position, body in enumerate(plans, start=1):
        if not isinstance(body, dict):
            raise ScheduleError("scheduled_plan_invalid", "Each plan must be an object.")
        key = body.get("client_id", body.get("key", str(plan_position)))
        if not isinstance(key, (str, int)) or str(key) in keys:
            raise ScheduleError("scheduled_plan_invalid", "Plan client_id values must be unique.")
        key = str(key)
        keys.add(key)
        program_id = body.get("workout_program_id", body.get("source_program_id"))
        source_program = None
        if program_id is not None:
            source_program = WorkoutProgram.objects.prefetch_related("items__workout__exercises").filter(
                id=_positive(program_id, "workout_program_id")
            ).first()
            if source_program is None:
                raise ScheduleError("scheduled_plan_invalid", "Workout program was not found.")
        workouts = body.get("workouts")
        if workouts is None and source_program:
            workouts = [{"workout_id": item.workout_id} for item in source_program.items.all()]
        if not isinstance(workouts, list) or not workouts:
            raise ScheduleError("scheduled_plan_invalid", "Each plan must contain at least one workout.")
        if len(workouts) > MAX_SCHEDULE_WORKOUTS_PER_PLAN:
            raise ScheduleError(
                "scheduled_plan_invalid",
                f"Each plan may contain at most {MAX_SCHEDULE_WORKOUTS_PER_PLAN} workouts.",
            )
        workout_rows = []
        for workout_position, workout_body in enumerate(workouts, start=1):
            if not isinstance(workout_body, dict):
                raise ScheduleError("scheduled_plan_invalid", "Each workout occurrence must be an object.")
            workout_id = workout_body.get("workout_id", workout_body.get("source_workout_id"))
            workout = Workout.objects.prefetch_related("exercises").filter(
                id=_positive(workout_id, "workout_id")
            ).first()
            if workout is None:
                raise ScheduleError("scheduled_plan_invalid", "Workout was not found.")
            source_exercises = list(workout.exercises.all())
            submitted_exercises = workout_body.get("exercises")
            if submitted_exercises is None:
                overrides = {
                    row.workout_exercise_id: row
                    for row in AthleteWorkoutExerciseOverride.objects.filter(
                        athlete=athlete, workout_exercise__workout=workout,
                    )
                }
                submitted_exercises = []
                for source in source_exercises:
                    override = overrides.get(source.id)
                    submitted_exercises.append({
                        "workout_exercise_id": source.id,
                        "sets": override.sets if override and override.sets is not None else source.sets,
                        "reps": override.reps if override and override.reps is not None else source.reps,
                        "weight_lbs": override.weight_lbs if override and override.weight_lbs is not None else source.default_weight_lbs,
                    })
            if not isinstance(submitted_exercises, list) or not submitted_exercises:
                raise ScheduleError("scheduled_plan_invalid", "Each workout must contain exercises.")
            if len(submitted_exercises) > MAX_SCHEDULE_EXERCISES_PER_WORKOUT:
                raise ScheduleError(
                    "scheduled_plan_invalid",
                    f"Each workout may contain at most {MAX_SCHEDULE_EXERCISES_PER_WORKOUT} exercises.",
                )
            exercise_total += len(submitted_exercises)
            if exercise_total > MAX_SCHEDULE_EXERCISES_TOTAL:
                raise ScheduleError(
                    "scheduled_plan_invalid",
                    f"Schedule may contain at most {MAX_SCHEDULE_EXERCISES_TOTAL} exercises.",
                )
            source_by_id = {row.id: row for row in source_exercises}
            exercise_rows = []
            seen = set()
            for exercise_position, exercise_body in enumerate(submitted_exercises, start=1):
                if not isinstance(exercise_body, dict):
                    raise ScheduleError("scheduled_plan_invalid", "Each exercise occurrence must be an object.")
                exercise_id = exercise_body.get("workout_exercise_id", exercise_body.get("source_exercise_id"))
                exercise_id = _positive(exercise_id, "workout_exercise_id")
                if exercise_id in seen or exercise_id not in source_by_id:
                    raise ScheduleError("scheduled_plan_invalid", "Exercises must be unique and belong to the workout.")
                seen.add(exercise_id)
                exercise_rows.append(_exercise_values(source_by_id[exercise_id], exercise_body))
            workout_rows.append({"source_workout": workout, "exercises": exercise_rows})
        name = body.get("name") or (source_program.name if source_program else f"Athlete plan {plan_position}")
        if not isinstance(name, str) or not name.strip():
            raise ScheduleError("scheduled_plan_invalid", "Plan name is required.")
        result.append({"key": key, "name": name.strip(), "source_program": source_program, "workouts": workout_rows})
    return result


def _validated_entries(payload, plan_keys):
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ScheduleError("scheduled_plan_invalid", "entries must be a nonempty list.")
    seen_dates = set()
    seen_weekdays = set()
    result = []
    for body in entries:
        if not isinstance(body, dict):
            raise ScheduleError("scheduled_plan_invalid", "Each schedule entry must be an object.")
        exact_date = body.get("date")
        weekday = body.get("weekday")
        if (exact_date is None) == (weekday is None):
            raise ScheduleError("schedule_conflict", "Each entry requires exactly one date or weekday.")
        if exact_date is not None:
            try:
                exact_date = date.fromisoformat(exact_date)
            except (TypeError, ValueError):
                raise ScheduleError("scheduled_plan_invalid", "date must use YYYY-MM-DD.")
            if exact_date in seen_dates:
                raise ScheduleError("schedule_conflict", "Duplicate exact-date entry.")
            seen_dates.add(exact_date)
        else:
            if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
                raise ScheduleError("scheduled_plan_invalid", "weekday must be from 0 (Monday) through 6 (Sunday).")
            if weekday in seen_weekdays:
                raise ScheduleError("schedule_conflict", "Duplicate weekday entry.")
            seen_weekdays.add(weekday)
        is_rest = body.get("is_rest", body.get("rest", False))
        if not isinstance(is_rest, bool):
            raise ScheduleError("scheduled_plan_invalid", "is_rest must be boolean.")
        plan_key = body.get("plan_client_id", body.get("plan_key", body.get("plan_index")))
        if is_rest:
            if plan_key is not None:
                raise ScheduleError("scheduled_plan_invalid", "Rest entries cannot reference a plan.")
            plan_key = None
        else:
            if plan_key is None:
                raise ScheduleError("scheduled_plan_invalid", "Plan entries require plan_client_id.")
            plan_key = str(plan_key)
            if plan_key not in plan_keys and plan_key.isdigit() and str(int(plan_key) + 1) in plan_keys:
                plan_key = str(int(plan_key) + 1)
            if plan_key not in plan_keys:
                raise ScheduleError("scheduled_plan_invalid", "Entry references an unknown plan.")
        result.append({"date": exact_date, "weekday": weekday, "is_rest": is_rest, "plan_key": plan_key})
    return result


@transaction.atomic
def replace_schedule(athlete_id, payload):
    prevalidate_schedule_payload(payload)
    lock_training_day()
    athlete = Athlete.objects.select_for_update().filter(id=athlete_id).first()
    if athlete is None:
        raise ScheduleError("athlete_not_found", "Athlete not found.")
    expected = payload.get("expected_version")
    existing = AthleteSchedule.objects.select_for_update().filter(athlete=athlete).first()
    current = existing.version if existing else 0
    if expected != current:
        raise ScheduleError("schedule_version_conflict", "Schedule changed; reload before saving.")
    plans = _validated_plans(athlete, payload)
    entries = _validated_entries(payload, {plan["key"] for plan in plans})
    if existing:
        existing.entries.all().delete()
        existing.plans.all().delete()
        schedule = existing
        schedule.version = current + 1
        schedule.active = True
        schedule.save(update_fields=["version", "active", "updated_at"])
    else:
        schedule = AthleteSchedule.objects.create(athlete=athlete, version=1)
    created = {}
    for position, plan_body in enumerate(plans, start=1):
        plan = AthleteSchedulePlan.objects.create(
            schedule=schedule, source_program=plan_body["source_program"],
            name=plan_body["name"], position=position,
        )
        created[plan_body["key"]] = plan
        for workout_position, workout_body in enumerate(plan_body["workouts"], start=1):
            source_workout = workout_body["source_workout"]
            workout = AthleteSchedulePlanWorkout.objects.create(
                plan=plan, source_workout=source_workout, name=source_workout.name,
                position=workout_position,
            )
            for exercise_position, exercise_body in enumerate(workout_body["exercises"], start=1):
                AthleteSchedulePlanExercise.objects.create(
                    workout=workout, position=exercise_position, **exercise_body,
                )
    AthleteScheduleEntry.objects.bulk_create([
        AthleteScheduleEntry(
            schedule=schedule, plan=created.get(row["plan_key"]), date=row["date"],
            weekday=row["weekday"], is_rest=row["is_rest"],
        ) for row in entries
    ])
    return schedule


@transaction.atomic
def delete_schedule(athlete_id, expected_version):
    lock_training_day()
    if not Athlete.objects.select_for_update().filter(id=athlete_id).exists():
        raise ScheduleError("athlete_not_found", "Athlete not found.")
    schedule = AthleteSchedule.objects.select_for_update().filter(athlete_id=athlete_id).first()
    if schedule is None or not schedule.active:
        return False
    if expected_version != schedule.version:
        raise ScheduleError("schedule_version_conflict", "Schedule changed; reload before deleting.")
    schedule.entries.all().delete()
    schedule.plans.all().delete()
    schedule.version += 1
    schedule.active = False
    schedule.save(update_fields=["version", "active", "updated_at"])
    return schedule.version


def _exercise_body(exercise):
    return {
        "id": exercise.id,
        "workout_exercise_id": exercise.source_exercise_id,
        "position": exercise.position,
        "exercise": exercise.exercise,
        "sets": exercise.sets,
        "reps": exercise.reps,
        "weight_lbs": exercise.weight_lbs,
        "velocity_min": exercise.velocity_min,
        "velocity_max": exercise.velocity_max,
    }


def serialize_schedule(schedule):
    plans = list(schedule.plans.prefetch_related("workouts__exercises").order_by("position", "id"))
    training_date = timezone.localdate()
    resolved = resolve_athlete(schedule.athlete, training_date)
    return {
        "athlete_id": schedule.athlete_id,
        "version": schedule.version,
        "active": schedule.active,
        "updated_at": schedule.updated_at,
        "training_date": training_date,
        "resolved": _resolved_body(resolved),
        "plans": [{
            "id": plan.id,
            "client_id": str(plan.position),
            "name": plan.name,
            "position": plan.position,
            "workout_program_id": plan.source_program_id,
            "workouts": [{
                "id": workout.id,
                "workout_id": workout.source_workout_id,
                "name": workout.name,
                "position": workout.position,
                "exercises": [_exercise_body(row) for row in workout.exercises.all()],
            } for workout in plan.workouts.all()],
        } for plan in plans],
        "entries": [{
            "id": entry.id,
            "date": entry.date,
            "weekday": entry.weekday,
            "is_rest": entry.is_rest,
            "plan_id": entry.plan_id,
        } for entry in schedule.entries.order_by("date", "weekday", "id")],
    }


def serialize_schedule_state(athlete, schedule=None):
    if schedule is not None:
        return serialize_schedule(schedule)
    training_date = timezone.localdate()
    resolved = resolve_athlete(athlete, training_date)
    effective_plan = _effective_plan(resolved)
    plans = []
    if effective_plan is not None:
        plans.append({
            **effective_plan,
            "client_id": "1",
            "position": 1,
            "workout_program_id": effective_plan["id"] if resolved["source"] == "fallback" else None,
            "workouts": [{
                **workout,
                "workout_id": workout.get("workout_id", workout.get("id")),
            } for workout in effective_plan["workouts"]],
        })
    return {
        "athlete_id": athlete.id,
        "version": 0,
        "active": False,
        "updated_at": None,
        "training_date": training_date,
        "resolved": _resolved_body(resolved),
        "plans": plans,
        "entries": [],
    }


def resolve_athlete(athlete, training_date):
    schedule = AthleteSchedule.objects.filter(athlete=athlete, active=True).first()
    if schedule:
        entries = schedule.entries.select_related("plan").all()
        entry = next((row for row in entries if row.date == training_date), None)
        source = "date"
        if entry is None:
            entry = next((row for row in entries if row.date is None and row.weekday == training_date.weekday()), None)
            source = "weekday"
        if entry is None:
            return {"athlete": athlete, "source": "missing", "schedule": schedule, "plan": None, "eligible": False}
        return {
            "athlete": athlete, "source": source, "schedule": schedule,
            "plan": entry.plan, "eligible": not entry.is_rest,
            "rest": entry.is_rest,
        }
    assignment = AthleteWorkoutProgramAssignment.objects.select_related("workout_program").filter(athlete=athlete).first()
    if assignment:
        return {"athlete": athlete, "source": "fallback", "schedule": None, "plan": assignment.workout_program, "eligible": True}
    return {"athlete": athlete, "source": "missing", "schedule": None, "plan": None, "eligible": False}


def _fallback_digest(row):
    if row["source"] != "fallback":
        return None
    program = row["plan"]
    overrides = {
        override.workout_exercise_id: override
        for override in AthleteWorkoutExerciseOverride.objects.filter(
            athlete=row["athlete"], workout_exercise__workout__workout_program_items__workout_program=program,
        )
    }
    return [{
        "item_id": item.id,
        "position": item.position,
        "workout_id": item.workout_id,
        "exercises": [{
            "id": exercise.id,
            "position": exercise.position,
            "sets": overrides[exercise.id].sets if exercise.id in overrides and overrides[exercise.id].sets is not None else exercise.sets,
            "reps": overrides[exercise.id].reps if exercise.id in overrides and overrides[exercise.id].reps is not None else exercise.reps,
            "weight_lbs": overrides[exercise.id].weight_lbs if exercise.id in overrides and overrides[exercise.id].weight_lbs is not None else exercise.default_weight_lbs,
            "velocity_min": exercise.velocity_min,
            "velocity_max": exercise.velocity_max,
        } for exercise in item.workout.exercises.all()],
    } for item in program.items.select_related("workout").prefetch_related("workout__exercises").order_by("position", "id")]


def _effective_plan(row):
    plan = row["plan"]
    if plan is None:
        return None
    if row["source"] == "fallback":
        return {
            "id": plan.id,
            "name": plan.name,
            "workouts": [{
                "id": item.workout_id,
                "name": item.workout.name,
                "position": item.position,
                "exercises": [{
                    "id": exercise["id"],
                    "workout_exercise_id": exercise["id"],
                    "position": exercise["position"],
                    "exercise": next(
                        source.exercise for source in item.workout.exercises.all() if source.id == exercise["id"]
                    ),
                    "sets": exercise["sets"],
                    "reps": exercise["reps"],
                    "weight_lbs": exercise["weight_lbs"],
                    "velocity_min": exercise["velocity_min"],
                    "velocity_max": exercise["velocity_max"],
                } for exercise in digest["exercises"]],
            } for item, digest in zip(
                plan.items.select_related("workout").prefetch_related("workout__exercises").order_by("position", "id"),
                _fallback_digest(row),
            )],
        }
    return {
        "id": plan.id,
        "name": plan.name,
        "workouts": [{
            "id": workout.id,
            "workout_id": workout.source_workout_id,
            "name": workout.name,
            "position": workout.position,
            "exercises": [_exercise_body(exercise) for exercise in workout.exercises.all()],
        } for workout in plan.workouts.prefetch_related("exercises").order_by("position", "id")],
    }


def _resolved_body(row):
    state = "rest" if row.get("rest") else "scheduled" if row["source"] in {"date", "weekday"} else row["source"]
    return {
        "source": row["source"],
        "state": state,
        "eligible": row["eligible"],
        "is_rest": row.get("rest", False),
        "schedule_version": row["schedule"].version if row["schedule"] else None,
        "effective_plan": _effective_plan(row),
    }


def _eligible_prescribed_set_count(rows):
    total = 0
    for row in rows:
        if not row["eligible"]:
            continue
        remaining = MAX_SESSION_SETS - total
        if remaining < 0:
            return MAX_SESSION_SETS + 1
        if row["source"] != "fallback":
            total += sum(AthleteSchedulePlanExercise.objects.filter(
                workout__plan=row["plan"],
            ).values_list("sets", flat=True)[:remaining + 1])
            if total > MAX_SESSION_SETS:
                return MAX_SESSION_SETS + 1
            continue
        exercises = list(WorkoutExercise.objects.filter(
            workout__workout_program_items__workout_program=row["plan"],
        ).values_list("id", "sets")[:remaining + 1])
        overrides = {
            exercise_id: sets
            for exercise_id, sets in AthleteWorkoutExerciseOverride.objects.filter(
                athlete=row["athlete"], workout_exercise_id__in={item[0] for item in exercises},
                sets__isnull=False,
            ).values_list("workout_exercise_id", "sets")
        }
        total += sum(overrides.get(exercise_id, sets) for exercise_id, sets in exercises)
        if total > MAX_SESSION_SETS:
            return MAX_SESSION_SETS + 1
    return total


def build_preview(training_date=None):
    training_date = training_date or timezone.localdate()
    rows = [resolve_athlete(athlete, training_date) for athlete in Athlete.objects.filter(is_simulated=False).order_by("name", "id")]
    prescribed_sets = _eligible_prescribed_set_count(rows)
    if prescribed_sets > MAX_SESSION_SETS:
        raise ScheduleError(
            "scheduled_day_too_large",
            "Scheduled day exceeds the prescribed set limit.",
            dimensions={"sets": prescribed_sets, "limits": {"sets": MAX_SESSION_SETS}},
        )
    digest_rows = [{
        "athlete_id": row["athlete"].id,
        "source": row["source"],
        "schedule_version": row["schedule"].version if row["schedule"] else None,
        "plan_id": row["plan"].id if row["plan"] else None,
        "eligible": row["eligible"],
        "fallback_plan": _fallback_digest(row),
    } for row in rows]
    preview_version = hashlib.sha256(json.dumps(
        {"training_date": training_date.isoformat(), "rows": digest_rows},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return {
        "training_date": training_date,
        "weekday": training_date.weekday(),
        "preview_version": preview_version,
        "athletes": [{
            "athlete": {"id": row["athlete"].id, "name": row["athlete"].name},
            "source": row["source"],
            "eligible": row["eligible"],
            "is_rest": row.get("rest", False),
            "schedule_version": row["schedule"].version if row["schedule"] else None,
            "plan": ({"id": row["plan"].id, "name": row["plan"].name} if row["plan"] else None),
            "state": _resolved_body(row)["state"],
            "effective_plan": _effective_plan(row),
        } for row in rows],
        "_resolved": rows,
    }


def freeze_resolved_plan(session, resolved):
    athlete = resolved["athlete"]
    source = resolved["source"]
    source_plan = resolved["plan"]
    if source == "fallback":
        program = source_plan
        name = program.name
        workout_sources = []
        overrides = {
            row.workout_exercise_id: row
            for row in AthleteWorkoutExerciseOverride.objects.filter(athlete=athlete)
        }
        for item in program.items.select_related("workout").prefetch_related("workout__exercises").order_by("position", "id"):
            exercises = []
            for exercise in item.workout.exercises.all():
                override = overrides.get(exercise.id)
                exercises.append({
                    "source_exercise": exercise, "exercise": exercise.exercise,
                    "sets": override.sets if override and override.sets is not None else exercise.sets,
                    "reps": override.reps if override and override.reps is not None else exercise.reps,
                    "weight_lbs": override.weight_lbs if override and override.weight_lbs is not None else exercise.default_weight_lbs,
                    "velocity_min": exercise.velocity_min, "velocity_max": exercise.velocity_max,
                })
            workout_sources.append((item.workout, exercises))
        source_program = program
        schedule_version = None
    else:
        name = source_plan.name
        source_program = source_plan.source_program
        schedule_version = resolved["schedule"].version
        workout_sources = [(workout.source_workout, [{
            "source_exercise": exercise.source_exercise, "exercise": exercise.exercise,
            "sets": exercise.sets, "reps": exercise.reps, "weight_lbs": exercise.weight_lbs,
            "velocity_min": exercise.velocity_min, "velocity_max": exercise.velocity_max,
        } for exercise in workout.exercises.all()]) for workout in source_plan.workouts.prefetch_related("exercises").all()]
    if not workout_sources or any(not exercises for _workout, exercises in workout_sources):
        raise ScheduleError("scheduled_plan_invalid", "Resolved plan contains an empty workout.")
    day_plan = AthleteDayPlan.objects.create(
        session=session, athlete=athlete, schedule_source=source,
        schedule_version=schedule_version, source_program=source_program, name=name,
    )
    first_workout = first_exercise = None
    for workout_position, (source_workout, exercises) in enumerate(workout_sources, start=1):
        frozen_workout = AthleteDayPlanWorkout.objects.create(
            day_plan=day_plan, source_workout=source_workout,
            name=source_workout.name, position=workout_position,
        )
        if first_workout is None:
            first_workout = frozen_workout
        for exercise_position, values in enumerate(exercises, start=1):
            frozen_exercise = AthleteDayPlanExercise.objects.create(
                workout=frozen_workout, position=exercise_position, **values,
            )
            if first_exercise is None:
                first_exercise = frozen_exercise
    AthleteDayProgress.objects.create(
        session=session, athlete=athlete, day_plan=day_plan,
        current_day_plan_workout=first_workout,
        current_day_plan_exercise=first_exercise,
        expected_set_number=1,
    )
    return day_plan
