import json

from django.db import connection, transaction
from django.db.models import Count, Q
from django.utils import timezone

from ..models import (
    Athlete,
    AthleteDayProgress,
    AthleteRackParticipation,
    AthleteWorkoutAssignment,
    AthleteWorkoutExerciseOverride,
    AthleteWorkoutProgramAssignment,
    DailyReport,
    MonitoringEvent,
    Program,
    RackScreen,
    RackWorkoutState,
    Rep,
    Session,
    Set,
    WorkoutExercise,
    WorkoutProgramItem,
)
from .athlete_workouts import assignment_workout, effective_workout
from .training_limits import (
    MAX_REPORT_SNAPSHOT_BYTES,
    MAX_SESSION_ATHLETES,
    MAX_SESSION_REPS,
    MAX_SESSION_SETS,
)


TRAINING_DAY_ADVISORY_LOCK = 2026071601
REPORT_SCHEMA_VERSION = 2


class ActiveTrainingDayConflict(Exception):
    pass


class SessionNotFound(Exception):
    pass


class SessionAlreadyEnded(Exception):
    pass


class SimulationEndRejected(Exception):
    pass


class UnfinishedSetsConflict(Exception):
    def __init__(self, rack_numbers, unassigned_set_count):
        self.rack_numbers = rack_numbers
        self.unassigned_set_count = unassigned_set_count
        super().__init__("Training day has unfinished sets.")


class TrainingDayRaceConflict(Exception):
    pass


class SessionAthleteLimitExceeded(Exception):
    pass


class ReportTooLarge(Exception):
    def __init__(self, dimensions):
        self.dimensions = dimensions
        super().__init__("Daily report exceeds Pi-safe limits.")


def lock_training_day():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [TRAINING_DAY_ADVISORY_LOCK])


def lock_rack_number(rack_number):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [rack_number])


@transaction.atomic
def start_training_day(validated_data, *, is_simulated=False):
    lock_training_day()
    if Session.objects.select_for_update().filter(ended_at=None).exists():
        raise ActiveTrainingDayConflict
    athletes = validated_data.pop("athletes", [])
    if len(athletes) > MAX_SESSION_ATHLETES:
        raise SessionAthleteLimitExceeded
    session = Session.objects.create(**validated_data, is_simulated=is_simulated)
    session.athletes.set(athletes)
    rack_numbers = list(
        RackScreen.objects.exclude(rack_number=None)
        .values("rack_number")
        .annotate(screen_count=Count("device_id"))
        .filter(screen_count=1)
        .order_by("rack_number")
        .values_list("rack_number", flat=True)
    )
    for rack_number in rack_numbers:
        lock_rack_number(rack_number)
        state, _created = RackWorkoutState.objects.select_for_update().get_or_create(
            rack_number=rack_number,
        )
        state.active_session = session
        state.active_program = None
        state.assigned_workout = None
        state.assigned_program_item = None
        state.selected_athlete = None
        state.save(update_fields=[
            "active_session",
            "active_program",
            "assigned_workout",
            "assigned_program_item",
            "selected_athlete",
            "updated_at",
        ])
    MonitoringEvent.objects.create(reason="session_started", is_simulated=is_simulated)
    return session


def _iso(value):
    return value.isoformat() if value is not None else None


def _rack_workout(state):
    if state.assigned_program_item_id:
        return state.assigned_program_item.workout
    return state.assigned_workout


def _prescription_for_athlete(athlete, assignment, selected_state, legacy_programs):
    workout = assignment_workout(assignment)
    source = "athlete" if workout else None
    program_identity = None
    rack_number = None
    if assignment and assignment.assigned_program_item_id:
        item = assignment.assigned_program_item
        program_identity = {"id": item.workout_program_id, "name": item.workout_program.name}
    if workout is None and selected_state:
        workout = _rack_workout(selected_state)
        source = "rack" if workout else None
        rack_number = selected_state.rack_number
        if selected_state.assigned_program_item_id:
            item = selected_state.assigned_program_item
            program_identity = {"id": item.workout_program_id, "name": item.workout_program.name}
    if workout:
        body = effective_workout(workout, athlete)
        return {
            "source": source,
            "rack_number": rack_number,
            "program": program_identity,
            "workout": {"id": body["id"], "name": body["name"]},
            "exercises": body["exercises"],
        }
    legacy = legacy_programs.get(athlete.id, [])
    if legacy:
        return {
            "source": "legacy",
            "rack_number": selected_state.rack_number if selected_state else None,
            "program": None,
            "workout": None,
            "exercises": [{
                "id": program.id,
                "exercise": program.exercise,
                "position": position,
                "sets": program.target_sets,
                "reps": program.target_reps,
                "default_weight_lbs": program.target_weight_lbs,
                "velocity_min": program.velocity_zone_min,
                "velocity_max": program.velocity_zone_max,
            } for position, program in enumerate(legacy, start=1)],
        }
    return None


def _program_snapshot(program, athlete):
    if program is None:
        return None
    return {
        "id": program.id,
        "name": program.name,
        "items": [{
            "id": item.id,
            "position": item.position,
            "workout": effective_workout(item.workout, athlete),
        } for item in program.items.select_related("workout").prefetch_related(
            "workout__exercises",
        ).order_by("position", "id")],
    }


def _progress_snapshot(progress):
    if progress is None:
        return None
    current_item = progress.current_program_item
    current_exercise = progress.current_workout_exercise
    return {
        "id": progress.id,
        "status": progress.status,
        "workout_program_id": progress.workout_program_id,
        "current_program_item": ({
            "id": current_item.id,
            "position": current_item.position,
            "workout_id": current_item.workout_id,
        } if current_item else None),
        "current_workout_exercise": ({
            "id": current_exercise.id,
            "position": current_exercise.position,
        } if current_exercise else None),
        "expected_set_number": progress.expected_set_number,
    }


def _build_schema_one_snapshot(session, end_time, states, session_sets, reps):
    included_sets = [
        workout_set for workout_set in session_sets
        if workout_set.ended_at is not None
        and not workout_set.is_false_set
        and not workout_set.is_simulated
    ]
    athlete_ids = set(session.athletes.values_list("id", flat=True))
    athlete_ids.update(workout_set.athlete_id for workout_set in included_sets)
    athletes = list(Athlete.objects.filter(id__in=athlete_ids).order_by("name", "id"))
    assignments = {
        assignment.athlete_id: assignment
        for assignment in AthleteWorkoutAssignment.objects.select_related(
            "assigned_workout",
            "assigned_program_item__workout",
            "assigned_program_item__workout_program",
        ).filter(athlete_id__in=athlete_ids)
    }
    selected_states = {}
    for state in states:
        if state.selected_athlete_id and state.selected_athlete_id not in selected_states:
            selected_states[state.selected_athlete_id] = state
    legacy_programs = {}
    for program in Program.objects.filter(
        athlete_id__in=athlete_ids, is_simulated=False,
    ).order_by("athlete_id", "id"):
        legacy_programs.setdefault(program.athlete_id, []).append(program)
    reps_by_set = {}
    for rep in reps:
        reps_by_set.setdefault(rep.set_id, []).append(rep)
    sets_by_athlete = {}
    for workout_set in included_sets:
        sets_by_athlete.setdefault(workout_set.athlete_id, []).append(workout_set)

    return {
        "schema_version": 1,
        "generated_at": _iso(end_time),
        "session": {
            "id": session.id,
            "label": session.label,
            "started_at": _iso(session.started_at),
            "ended_at": _iso(end_time),
        },
        "athletes": [{
            "athlete": {"id": athlete.id, "name": athlete.name},
            "prescription": _prescription_for_athlete(
                athlete,
                assignments.get(athlete.id),
                selected_states.get(athlete.id),
                legacy_programs,
            ),
            "sets": [{
                "id": workout_set.id,
                "rack_number": workout_set.rack_number,
                "exercise": workout_set.exercise,
                "set_number": workout_set.set_number,
                "weight_lbs": workout_set.weight_lbs,
                "started_at": _iso(workout_set.started_at),
                "ended_at": _iso(workout_set.ended_at),
                "reps_completed": workout_set.reps_completed,
                "avg_velocity": workout_set.avg_velocity,
                "peak_velocity": workout_set.peak_velocity,
                "reps": [{
                    "id": rep.id,
                    "rep_number": rep.rep_number,
                    "timestamp": _iso(rep.timestamp),
                    "mean_velocity": rep.mean_velocity,
                    "peak_velocity": rep.peak_velocity,
                    "duration_ms": rep.duration_ms,
                    "velocity_color": rep.velocity_color,
                } for rep in reps_by_set.get(workout_set.id, [])],
            } for workout_set in sets_by_athlete.get(athlete.id, [])],
        } for athlete in athletes],
        "exclusions": {
            "false_sets": sum(workout_set.is_false_set for workout_set in session_sets),
            "simulated_sets": sum(workout_set.is_simulated for workout_set in session_sets),
            "unsaved_live_reps": "not_persisted",
        },
    }


def _build_schema_two_snapshot(session, end_time, states, session_sets, reps):
    included_sets = [
        workout_set for workout_set in session_sets
        if workout_set.ended_at is not None
        and not workout_set.is_simulated
    ]
    athlete_ids = set(session.athletes.values_list("id", flat=True))
    athlete_ids.update(workout_set.athlete_id for workout_set in included_sets)
    athlete_ids.update(
        AthleteDayProgress.objects.filter(session=session).values_list("athlete_id", flat=True)
    )
    athlete_ids.update(
        AthleteRackParticipation.objects.filter(session=session).values_list("athlete_id", flat=True)
    )
    athletes = list(Athlete.objects.filter(id__in=athlete_ids).order_by("name", "id"))
    program_assignments = {
        assignment.athlete_id: assignment
        for assignment in AthleteWorkoutProgramAssignment.objects.select_related(
            "workout_program",
        ).filter(athlete_id__in=athlete_ids)
    }
    progress_by_athlete = {
        progress.athlete_id: progress
        for progress in AthleteDayProgress.objects.select_related(
            "workout_program",
            "current_program_item",
            "current_workout_exercise",
        ).filter(session=session, athlete_id__in=athlete_ids)
    }
    rack_participation = {}
    for athlete_id, rack_number in AthleteRackParticipation.objects.filter(
        session=session,
    ).values_list("athlete_id", "rack_number"):
        rack_participation.setdefault(athlete_id, set()).add(rack_number)
    reps_by_set = {}
    for rep in reps:
        reps_by_set.setdefault(rep.set_id, []).append(rep)
    sets_by_athlete = {}
    for workout_set in included_sets:
        sets_by_athlete.setdefault(workout_set.athlete_id, []).append(workout_set)

    athlete_rows = []
    for athlete in athletes:
        progress = progress_by_athlete.get(athlete.id)
        assignment = program_assignments.get(athlete.id)
        program = progress.workout_program if progress else (
            assignment.workout_program if assignment else None
        )
        athlete_rows.append({
            "athlete": {"id": athlete.id, "name": athlete.name},
            "assigned_program": _program_snapshot(program, athlete),
            "final_progress": _progress_snapshot(progress),
            "rack_participation": sorted(rack_participation.get(athlete.id, set())),
            "sets": [{
                "id": workout_set.id,
                "athlete_day_progress_id": workout_set.athlete_day_progress_id,
                "workout_program_item_id": workout_set.workout_program_item_id,
                "workout_exercise_id": workout_set.workout_exercise_id,
                "rack_number": workout_set.rack_number,
                "exercise": workout_set.exercise,
                "set_number": workout_set.set_number,
                "weight_lbs": workout_set.weight_lbs,
                "started_at": _iso(workout_set.started_at),
                "ended_at": _iso(workout_set.ended_at),
                "reps_completed": workout_set.reps_completed,
                "avg_velocity": workout_set.avg_velocity,
                "peak_velocity": workout_set.peak_velocity,
                "is_false_set": workout_set.is_false_set,
                "reps": [{
                    "id": rep.id,
                    "rep_number": rep.rep_number,
                    "timestamp": _iso(rep.timestamp),
                    "mean_velocity": rep.mean_velocity,
                    "peak_velocity": rep.peak_velocity,
                    "duration_ms": rep.duration_ms,
                    "velocity_color": rep.velocity_color,
                } for rep in reps_by_set.get(workout_set.id, [])],
            } for workout_set in sets_by_athlete.get(athlete.id, [])],
        })
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": _iso(end_time),
        "session": {
            "id": session.id,
            "label": session.label,
            "started_at": _iso(session.started_at),
            "ended_at": _iso(end_time),
        },
        "athletes": athlete_rows,
        "exclusions": {
            "false_sets": sum(workout_set.is_false_set for workout_set in session_sets),
            "simulated_sets": sum(workout_set.is_simulated for workout_set in session_sets),
            "unsaved_live_reps": "not_persisted",
        },
    }


def _build_snapshot(session, end_time, states, session_sets, reps):
    athlete_ids = session.athletes.values_list("id", flat=True)
    athlete_driven = (
        AthleteDayProgress.objects.filter(session=session).exists()
        or AthleteWorkoutProgramAssignment.objects.filter(athlete_id__in=athlete_ids).exists()
    )
    builder = _build_schema_two_snapshot if athlete_driven else _build_schema_one_snapshot
    return builder(session, end_time, states, session_sets, reps)


def end_training_day(session_id):
    for _attempt in range(3):
        observed_racks = tuple(
            RackWorkoutState.objects.filter(active_session_id=session_id)
            .order_by("rack_number")
            .values_list("rack_number", flat=True)
        )
        retry = False
        with transaction.atomic():
            lock_training_day()
            for rack_number in observed_racks:
                lock_rack_number(rack_number)
            session = Session.objects.select_for_update().filter(id=session_id).first()
            if session is None:
                raise SessionNotFound
            if session.is_simulated:
                raise SimulationEndRejected
            report = DailyReport.objects.filter(session=session).first()
            if report:
                return report, False
            if session.ended_at is not None:
                raise SessionAlreadyEnded
            locked_states = list(
                RackWorkoutState.objects.select_for_update()
                .filter(active_session=session)
                .order_by("rack_number")
            )
            locked_racks = tuple(state.rack_number for state in locked_states)
            if locked_racks != observed_racks:
                retry = True
            else:
                states = list(
                    RackWorkoutState.objects.select_related(
                        "assigned_workout",
                        "assigned_program_item__workout",
                        "assigned_program_item__workout_program",
                    ).filter(rack_number__in=locked_racks).order_by("rack_number")
                )
                dimensions = {
                    "athletes": Athlete.objects.filter(
                        Q(sessions=session) | Q(sets__session=session),
                    ).distinct().count(),
                    "sets": Set.objects.filter(session=session).count(),
                    "reps": Rep.objects.filter(set__session=session).count(),
                    "snapshot_bytes": None,
                    "limits": {
                        "athletes": MAX_SESSION_ATHLETES,
                        "sets": MAX_SESSION_SETS,
                        "reps": MAX_SESSION_REPS,
                        "snapshot_bytes": MAX_REPORT_SNAPSHOT_BYTES,
                    },
                }
                if (
                    dimensions["athletes"] > MAX_SESSION_ATHLETES
                    or dimensions["sets"] > MAX_SESSION_SETS
                    or dimensions["reps"] > MAX_SESSION_REPS
                ):
                    raise ReportTooLarge(dimensions)
                unfinished = Set.objects.filter(ended_at=None).filter(
                    Q(session=session) | Q(rack_number__in=locked_racks)
                )
                unfinished_racks = list(
                    unfinished.exclude(rack_number=None)
                    .order_by("rack_number")
                    .values_list("rack_number", flat=True)
                    .distinct()
                )
                unassigned_set_count = unfinished.filter(rack_number=None).count()
                if unfinished_racks or unassigned_set_count:
                    raise UnfinishedSetsConflict(
                        unfinished_racks,
                        unassigned_set_count,
                    )
                session_sets = list(
                    Set.objects.select_for_update()
                    .filter(session=session)
                    .select_related("athlete")
                    .order_by("started_at", "id")
                )
                reps = list(
                    Rep.objects.select_for_update()
                    .filter(set__session=session)
                    .order_by("set_id", "rep_number", "id")
                )
                participant_ids = set(session.athletes.values_list("id", flat=True))
                participant_ids.update(workout_set.athlete_id for workout_set in session_sets)
                list(Athlete.objects.select_for_update().filter(id__in=participant_ids).order_by("id"))
                list(AthleteWorkoutAssignment.objects.select_for_update().filter(athlete_id__in=participant_ids))
                program_assignments = list(
                    AthleteWorkoutProgramAssignment.objects.select_for_update()
                    .filter(athlete_id__in=participant_ids)
                    .order_by("athlete_id")
                )
                progress_rows = list(
                    AthleteDayProgress.objects.select_for_update()
                    .filter(session=session)
                    .order_by("athlete_id")
                )
                list(AthleteWorkoutExerciseOverride.objects.select_for_update().filter(athlete_id__in=participant_ids))
                program_ids = {
                    assignment.workout_program_id for assignment in program_assignments
                } | {progress.workout_program_id for progress in progress_rows}
                program_items = list(
                    WorkoutProgramItem.objects.select_for_update()
                    .filter(workout_program_id__in=program_ids)
                    .order_by("workout_program_id", "position", "id")
                )
                list(
                    WorkoutExercise.objects.select_for_update()
                    .filter(workout_id__in={item.workout_id for item in program_items})
                    .order_by("workout_id", "position", "id")
                )
                end_time = timezone.now()
                snapshot = _build_snapshot(session, end_time, states, session_sets, reps)
                dimensions["snapshot_bytes"] = len(
                    json.dumps(
                        snapshot,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                )
                if dimensions["snapshot_bytes"] > MAX_REPORT_SNAPSHOT_BYTES:
                    raise ReportTooLarge(dimensions)
                session.ended_at = end_time
                session.save(update_fields=["ended_at"])
                for state in locked_states:
                    if state.selected_athlete_id is not None:
                        state.selected_athlete = None
                        state.save(update_fields=["selected_athlete", "updated_at"])
                report = DailyReport.objects.create(
                    session=session,
                    schema_version=snapshot.get("schema_version", REPORT_SCHEMA_VERSION),
                    snapshot=snapshot,
                )
                MonitoringEvent.objects.create(reason="session_ended")
                return report, True
        if not retry:
            break
    raise TrainingDayRaceConflict


def serialize_daily_report(report):
    return {
        "id": report.id,
        "session_id": report.session_id,
        "schema_version": report.schema_version,
        "generated_at": report.generated_at,
        "snapshot": report.snapshot,
    }
