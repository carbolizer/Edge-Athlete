from ..models import AthleteWorkoutExerciseOverride


def assignment_workout(assignment):
    if assignment is None:
        return None
    if assignment.assigned_program_item_id:
        return assignment.assigned_program_item.workout
    return assignment.assigned_workout


def serialize_athlete_assignment(assignment):
    if assignment.assigned_program_item_id:
        item = assignment.assigned_program_item
        return {
            "athlete_id": assignment.athlete_id,
            "type": "program",
            "program": {
                "id": item.workout_program_id,
                "name": item.workout_program.name,
            },
            "workout": {"id": item.workout_id, "name": item.workout.name},
            "updated_at": assignment.updated_at,
        }
    return {
        "athlete_id": assignment.athlete_id,
        "type": "workout",
        "workout": {
            "id": assignment.assigned_workout_id,
            "name": assignment.assigned_workout.name,
        },
        "updated_at": assignment.updated_at,
    }


def serialize_override(override):
    return {
        "athlete_id": override.athlete_id,
        "workout_exercise_id": override.workout_exercise_id,
        "sets": override.sets,
        "reps": override.reps,
        "weight_lbs": override.weight_lbs,
        "updated_at": override.updated_at,
    }


def effective_workout(workout, athlete):
    overrides = {
        override.workout_exercise_id: override
        for override in AthleteWorkoutExerciseOverride.objects.filter(
            athlete=athlete,
            workout_exercise__workout=workout,
        )
    }
    return {
        "id": workout.id,
        "name": workout.name,
        "exercises": [{
            "id": exercise.id,
            "exercise": exercise.exercise,
            "position": exercise.position,
            "sets": overrides[exercise.id].sets
            if exercise.id in overrides and overrides[exercise.id].sets is not None
            else exercise.sets,
            "reps": overrides[exercise.id].reps
            if exercise.id in overrides and overrides[exercise.id].reps is not None
            else exercise.reps,
            "default_weight_lbs": overrides[exercise.id].weight_lbs
            if exercise.id in overrides and overrides[exercise.id].weight_lbs is not None
            else exercise.default_weight_lbs,
            "velocity_min": exercise.velocity_min,
            "velocity_max": exercise.velocity_max,
        } for exercise in workout.exercises.all()],
    }


def serialize_program_assignment(assignment):
    program = assignment.workout_program
    return {
        "athlete_id": assignment.athlete_id,
        "type": "workout_program",
        "workout_program": {
            "id": program.id,
            "name": program.name,
            "items": [{
                "id": item.id,
                "position": item.position,
                "workout": effective_workout(item.workout, assignment.athlete),
            } for item in program.items.all()],
        },
        "updated_at": assignment.updated_at,
    }


def serialize_day_progress(progress, *, include_active_set=False):
    item = progress.current_program_item
    exercise = progress.current_workout_exercise
    current_workout = effective_workout(item.workout, progress.athlete) if item else None
    effective_exercise = None
    if exercise and current_workout:
        effective_exercise = next(
            row for row in current_workout["exercises"] if row["id"] == exercise.id
        )
    persisted_sets = [{
        "id": workout_set.id,
        "workout_program_item_id": workout_set.workout_program_item_id,
        "workout_exercise_id": workout_set.workout_exercise_id,
        "set_number": workout_set.set_number,
        "rack_number": workout_set.rack_number,
        "weight_lbs": workout_set.weight_lbs,
        "ended_at": workout_set.ended_at,
        "reps_completed": workout_set.reps_completed,
        "avg_velocity": workout_set.avg_velocity,
        "peak_velocity": workout_set.peak_velocity,
        "is_false_set": workout_set.is_false_set,
    } for workout_set in progress.sets.filter(ended_at__isnull=False).order_by("started_at", "id")]
    current_sets = [
        workout_set for workout_set in persisted_sets
        if exercise and workout_set["workout_exercise_id"] == exercise.id
    ]
    active_set = progress.sets.filter(ended_at__isnull=True).order_by("started_at", "id").first()
    return {
        "id": progress.id,
        "status": progress.status,
        "program": {
            "id": progress.workout_program_id,
            "name": progress.workout_program.name,
        },
        "current_workout": ({
            "id": item.workout_id,
            "name": item.workout.name,
            "position": item.position,
        } if item else None),
        "current_exercise": ({
            **effective_exercise,
            "position": exercise.position,
        } if effective_exercise else None),
        "expected_set_number": progress.expected_set_number,
        "active_set": ({
            "id": active_set.id,
            "set_number": active_set.set_number,
            "started_at": active_set.started_at,
        } if active_set and include_active_set else None),
        "current_exercise_completion": ({
            "completed_sets": sum(not workout_set["is_false_set"] for workout_set in current_sets),
            "false_sets": sum(workout_set["is_false_set"] for workout_set in current_sets),
            "sets": current_sets,
        } if exercise else None),
        "persisted_sets": persisted_sets,
    }
