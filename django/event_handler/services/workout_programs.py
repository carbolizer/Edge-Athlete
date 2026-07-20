from collections import Counter
from collections.abc import Mapping

from django.db import transaction

from ..models import POSITIVE_INTEGER_MAX, Workout, WorkoutProgram, WorkoutProgramItem
from .workout_catalog import validation_error


MAX_PROGRAM_ITEMS = 1000


class WorkoutProgramValidationError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("Workout program data is invalid.")


class WorkoutProgramNameConflict(Exception):
    pass


def _json_positive_integer(value, row, field, errors):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        errors.append(validation_error(row, field, "invalid_integer", f"{field} must be a positive integer."))
        return None
    if value > POSITIVE_INTEGER_MAX:
        errors.append(validation_error(
            row,
            field,
            "out_of_range",
            f"{field} must be at most {POSITIVE_INTEGER_MAX}.",
        ))
        return None
    return value


def validate_workout_program(payload):
    if not isinstance(payload, Mapping):
        return None, [validation_error(None, None, "invalid_request", "Request body must be an object.")]

    errors = []
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(validation_error(None, "name", "required", "name is required."))
        normalized_name = ""
        name = ""
    else:
        name = name.strip()
        normalized_name = name.casefold()
        if len(name) > 255:
            errors.append(validation_error(None, "name", "too_long", "name must be at most 255 characters."))

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        errors.append(validation_error(None, "items", "required", "At least one workout item is required."))
        return {"name": name, "normalized_name": normalized_name, "items": []}, errors
    if len(items) > MAX_PROGRAM_ITEMS:
        errors.append(validation_error(
            None,
            "items",
            "item_limit_exceeded",
            "A workout program may contain at most 1000 items.",
        ))
        return {"name": name, "normalized_name": normalized_name, "items": []}, errors

    validated_items = []
    for row, item in enumerate(items, start=1):
        if not isinstance(item, Mapping):
            errors.append(validation_error(row, None, "invalid_item", "Each item must be an object."))
            continue
        position = _json_positive_integer(item.get("position"), row, "position", errors)
        workout_id = _json_positive_integer(item.get("workout_id"), row, "workout_id", errors)
        if position is not None and workout_id is not None:
            validated_items.append({"row": row, "position": position, "workout_id": workout_id})

    positions = Counter(item["position"] for item in validated_items)
    workout_ids = Counter(item["workout_id"] for item in validated_items)
    for item in validated_items:
        if positions[item["position"]] > 1:
            errors.append(validation_error(
                item["row"],
                "position",
                "duplicate_position",
                f"Position {item['position']} is duplicated.",
            ))
        if workout_ids[item["workout_id"]] > 1:
            errors.append(validation_error(
                item["row"],
                "workout_id",
                "duplicate_workout",
                f"Workout {item['workout_id']} is included more than once.",
            ))
    if validated_items and sorted(positions) != list(range(1, len(validated_items) + 1)):
        errors.append(validation_error(
            validated_items[0]["row"],
            "position",
            "non_contiguous_positions",
            "Positions must start at 1 and be contiguous.",
        ))
    validated_items.sort(key=lambda item: item["position"])
    return {
        "name": name,
        "normalized_name": normalized_name,
        "items": validated_items,
    }, errors


@transaction.atomic
def create_workout_program(validated_program):
    workout_ids = [item["workout_id"] for item in validated_program["items"]]
    locked_workouts = {
        workout.id: workout
        for workout in Workout.objects.select_for_update().filter(id__in=workout_ids)
    }
    missing_errors = [
        validation_error(item["row"], "workout_id", "workout_not_found", f"Workout {item['workout_id']} does not exist.")
        for item in validated_program["items"]
        if item["workout_id"] not in locked_workouts
    ]
    if missing_errors:
        raise WorkoutProgramValidationError(missing_errors)
    if WorkoutProgram.objects.filter(normalized_name=validated_program["normalized_name"]).exists():
        raise WorkoutProgramNameConflict

    workout_program = WorkoutProgram.objects.create(
        name=validated_program["name"],
        normalized_name=validated_program["normalized_name"],
    )
    WorkoutProgramItem.objects.bulk_create([
        WorkoutProgramItem(
            workout_program=workout_program,
            workout=locked_workouts[item["workout_id"]],
            position=item["position"],
        )
        for item in validated_program["items"]
    ])
    return workout_program


def serialize_workout_program(workout_program):
    return {
        "id": workout_program.id,
        "name": workout_program.name,
        "created_at": workout_program.created_at,
        "items": [{
            "position": item.position,
            "workout": {
                "id": item.workout_id,
                "name": item.workout.name,
            },
        } for item in workout_program.items.all()],
    }
