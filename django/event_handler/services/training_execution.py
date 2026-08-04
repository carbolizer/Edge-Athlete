from django.db import IntegrityError, transaction

from ..models import (
    AthleteDayProgress,
    AthleteWorkoutExerciseOverride,
    MonitoringEvent,
    Node,
    Set,
)
from .training_limits import MAX_SESSION_SETS


class ExecutionError(Exception):
    def __init__(self, code, detail, status=409):
        self.code = code
        self.detail = detail
        self.status = status
        super().__init__(detail)


@transaction.atomic
def start_expected_set(session, athlete, progress, rack_number):
    """Create or return the sole server-derived set for the current progress step."""
    existing = Set.objects.select_for_update().filter(
        athlete_day_progress=progress, ended_at=None,
    ).first()
    if existing:
        if existing.rack_number != rack_number:
            raise ExecutionError("unfinished_set", "Athlete has an unfinished set on another rack.")
        return existing, False
    if progress.status == AthleteDayProgress.COMPLETE:
        return None, False
    if progress.status != AthleteDayProgress.READY:
        raise ExecutionError("unfinished_set", "Athlete has an unfinished set.")

    nodes = list(Node.objects.select_for_update().filter(rack_number=rack_number).order_by("node_id")[:2])
    if len(nodes) != 1 or not nodes[0].is_active:
        raise ExecutionError("rack_node_unavailable", "Rack requires exactly one active sensor node.")
    node = nodes[0]
    if node.is_simulated != session.is_simulated or athlete.is_simulated != session.is_simulated:
        raise ExecutionError("simulation_ownership_mismatch", "Rack execution ownership does not match the active session.")
    if Set.objects.filter(session=session).count() >= MAX_SESSION_SETS:
        raise ExecutionError("session_set_limit", f"Session may contain at most {MAX_SESSION_SETS} persisted sets.")

    values = {
        "session": session,
        "athlete": athlete,
        "node": node,
        "rack_number": rack_number,
        "set_number": progress.expected_set_number,
        "is_simulated": session.is_simulated,
        "athlete_day_progress": progress,
    }
    if progress.day_plan_id:
        workout = progress.current_day_plan_workout
        exercise = progress.current_day_plan_exercise
        if (
            workout is None or exercise is None
            or workout.day_plan_id != progress.day_plan_id
            or exercise.workout_id != workout.id
        ):
            raise ExecutionError("unexpected_workout_step", "Frozen athlete progress is inconsistent.")
        values.update({
            "exercise": exercise.exercise,
            "weight_lbs": exercise.weight_lbs,
            "day_plan_workout": workout,
            "day_plan_exercise": exercise,
        })
    else:
        item = progress.current_program_item
        exercise = progress.current_workout_exercise
        if (
            item is None or exercise is None
            or item.workout_program_id != progress.workout_program_id
            or exercise.workout_id != item.workout_id
        ):
            raise ExecutionError("unexpected_workout_step", "Athlete progress does not match the assigned program.")
        override = AthleteWorkoutExerciseOverride.objects.filter(
            athlete=athlete, workout_exercise=exercise,
        ).first()
        values.update({
            "exercise": exercise.exercise,
            "weight_lbs": override.weight_lbs if override and override.weight_lbs is not None else exercise.default_weight_lbs,
            "workout_program_item": item,
            "workout_exercise": exercise,
        })
    try:
        workout_set = Set.objects.create(**values)
    except IntegrityError as error:
        raise ExecutionError("unfinished_set", "Athlete has an unfinished set.") from error
    progress.status = AthleteDayProgress.IN_SET
    progress.save(update_fields=["status", "updated_at"])
    MonitoringEvent.objects.create(reason="set_started", is_simulated=session.is_simulated)
    return workout_set, True
