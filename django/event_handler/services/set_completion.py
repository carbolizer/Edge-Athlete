"""Atomically persist a validated set completion from a rack or simulator."""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from event_handler.models import (
    Athlete,
    AthleteDayProgress,
    AthleteWorkoutExerciseOverride,
    AthleteWorkoutProgramAssignment,
    MonitoringEvent,
    RackScreen,
    RackWorkoutState,
    Rep,
    Session,
    Set,
)
from event_handler.services.training_days import lock_rack_number
from event_handler.services.training_limits import MAX_SESSION_REPS


class SetNotFound(Exception):
    pass


class SetAlreadyComplete(Exception):
    pass


class SetSessionEnded(Exception):
    pass


class SessionRepLimitExceeded(Exception):
    def __init__(self, current_reps, submitted_reps):
        self.current_reps = current_reps
        self.submitted_reps = submitted_reps
        super().__init__("Session persisted rep limit exceeded.")


class UnexpectedWorkoutStep(Exception):
    def __init__(self, progress):
        self.progress = progress
        super().__init__("Set does not match the athlete's current workout step.")


class RackCompletionRejected(Exception):
    def __init__(self, code, detail, status):
        self.code = code
        self.detail = detail
        self.status = status
        super().__init__(detail)


def _effective_set_count(progress):
    override = AthleteWorkoutExerciseOverride.objects.filter(
        athlete_id=progress.athlete_id,
        workout_exercise_id=progress.current_workout_exercise_id,
    ).first()
    return override.sets if override and override.sets is not None else progress.current_workout_exercise.sets


def _advance_progress(progress, is_false_set):
    if is_false_set:
        progress.status = AthleteDayProgress.READY
        progress.save(update_fields=["status", "updated_at"])
        return

    if progress.expected_set_number < _effective_set_count(progress):
        progress.expected_set_number += 1
        progress.status = AthleteDayProgress.READY
        progress.save(update_fields=["expected_set_number", "status", "updated_at"])
        return

    next_exercise = (
        progress.current_program_item.workout.exercises
        .filter(
            Q(position__gt=progress.current_workout_exercise.position)
            | Q(position=progress.current_workout_exercise.position, id__gt=progress.current_workout_exercise_id)
        )
        .order_by("position", "id")
        .first()
    )
    if next_exercise:
        progress.current_workout_exercise = next_exercise
        progress.expected_set_number = 1
        progress.status = AthleteDayProgress.READY
        progress.save(update_fields=["current_workout_exercise", "expected_set_number", "status", "updated_at"])
        return


    next_item = (
        progress.workout_program.items
        .filter(
            Q(position__gt=progress.current_program_item.position)
            | Q(position=progress.current_program_item.position, id__gt=progress.current_program_item_id)
        )
        .select_related("workout")
        .order_by("position", "id")
        .first()
    )
    if next_item:
        next_exercise = next_item.workout.exercises.order_by("position", "id").first()
        if next_exercise is None:
            raise UnexpectedWorkoutStep(progress)
        progress.current_program_item = next_item
        progress.current_workout_exercise = next_exercise
        progress.expected_set_number = 1
        progress.status = AthleteDayProgress.READY
        progress.save(update_fields=[
            "current_program_item", "current_workout_exercise", "expected_set_number",
            "status", "updated_at",
        ])
        return


    progress.current_program_item = None
    progress.current_workout_exercise = None
    progress.expected_set_number = None
    progress.status = AthleteDayProgress.COMPLETE
    progress.save(update_fields=[
        "current_program_item", "current_workout_exercise", "expected_set_number",
        "status", "updated_at",
    ])


def complete_set(set_id, data, *, rack_number=None, device_id=None):
    observed = Set.objects.filter(id=set_id).values(
        "session_id", "athlete_id", "athlete_day_progress_id", "rack_number",
    ).first()
    if observed is None:
        raise SetNotFound
    with transaction.atomic():
        locked_rack_number = rack_number if rack_number is not None else observed["rack_number"]
        if locked_rack_number is not None:
            lock_rack_number(locked_rack_number)
        if rack_number is not None:
            screens = list(
                RackScreen.objects.select_for_update()
                .filter(rack_number=rack_number)
                .order_by("device_id")[:2]
            )
            if len(screens) != 1:
                raise RackCompletionRejected(
                    "rack_screen_conflict",
                    "Rack must have exactly one assigned screen.",
                    409,
                )
            if screens[0].device_id != device_id:
                raise RackCompletionRejected(
                    "rack_screen_mismatch",
                    "device_id is not assigned to this rack.",
                    403,
                )
        session = Session.objects.select_for_update().filter(id=observed["session_id"]).first()
        Athlete.objects.select_for_update().filter(id=observed["athlete_id"]).first()
        if observed["athlete_day_progress_id"] is not None:
            assignment = AthleteWorkoutProgramAssignment.objects.select_for_update().filter(
                athlete_id=observed["athlete_id"],
            ).first()
            progress = (
                AthleteDayProgress.objects.select_for_update(of=("self",))
                .select_related(
                    "workout_program", "current_program_item__workout", "current_workout_exercise",
                )
                .filter(id=observed["athlete_day_progress_id"])
                .first()
            )
            rack_state = RackWorkoutState.objects.select_for_update().filter(
                rack_number=observed["rack_number"],
            ).first()
        else:
            assignment = None
            progress = None
            rack_state = None
        target_set = Set.objects.select_for_update().filter(id=set_id).first()
        if target_set is None:
            raise SetNotFound
        if rack_number is not None and target_set.rack_number != rack_number:
            raise RackCompletionRejected(
                "rack_set_mismatch",
                "Set is not active on this rack.",
                409,
            )
        if rack_number is not None and progress is None:
            raise UnexpectedWorkoutStep(None)
        if session.ended_at is not None:
            raise SetSessionEnded
        if target_set.ended_at is not None or target_set.reps.exists():
            raise SetAlreadyComplete
        if progress is not None and (
            progress.status != AthleteDayProgress.IN_SET
            or assignment is None
            or assignment.workout_program_id != progress.workout_program_id
            or progress.session_id != target_set.session_id
            or progress.athlete_id != target_set.athlete_id
            or progress.id != target_set.athlete_day_progress_id
            or progress.current_program_item_id != target_set.workout_program_item_id
            or progress.current_workout_exercise_id != target_set.workout_exercise_id
            or progress.expected_set_number != target_set.set_number
            or rack_state is None
            or rack_state.active_session_id != target_set.session_id
            or rack_state.selected_athlete_id != target_set.athlete_id
            or target_set.rack_number != rack_state.rack_number
        ):
            raise UnexpectedWorkoutStep(progress)
        list(Rep.objects.select_for_update().filter(set=target_set).order_by("id"))
        submitted_reps = 0 if data["is_false_set"] else len(data["reps"])
        current_reps = Rep.objects.filter(set__session=session).count()
        if current_reps + submitted_reps > MAX_SESSION_REPS:
            raise SessionRepLimitExceeded(current_reps, submitted_reps)
        if data["is_false_set"]:
            target_set.is_false_set = True
            target_set.reps_completed = 0
            target_set.avg_velocity = None
            target_set.peak_velocity = None
            is_velocity_pr = is_weight_pr = False
        else:
            Rep.objects.bulk_create([Rep(set=target_set, **rep) for rep in data["reps"]])
            target_set.reps_completed = data["reps_completed"]
            target_set.avg_velocity = data.get("avg_velocity")
            target_set.peak_velocity = data.get("peak_velocity")
            target_set.is_false_set = False
            is_velocity_pr, is_weight_pr = _personal_records(target_set)
        target_set.ended_at = timezone.now()
        target_set.save()
        if progress is not None:
            _advance_progress(progress, data["is_false_set"])
        MonitoringEvent.objects.create(reason="set_completed", is_simulated=target_set.is_simulated)
    return target_set, is_velocity_pr, is_weight_pr


def _personal_records(finished_set):
    prior_sets = Set.objects.filter(
        athlete=finished_set.athlete,
        exercise=finished_set.exercise,
        is_false_set=False,
    ).exclude(id=finished_set.id)

    is_velocity_pr = False
    if finished_set.peak_velocity is not None:
        best = prior_sets.exclude(peak_velocity=None).order_by("-peak_velocity").first()
        is_velocity_pr = best is not None and finished_set.peak_velocity > best.peak_velocity

    is_weight_pr = False
    if finished_set.weight_lbs is not None:
        best = prior_sets.exclude(weight_lbs=None).order_by("-weight_lbs").first()
        is_weight_pr = best is not None and finished_set.weight_lbs > best.weight_lbs

    return is_velocity_pr, is_weight_pr
