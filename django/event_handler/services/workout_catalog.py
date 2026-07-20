from collections import Counter, OrderedDict
from collections.abc import Mapping
import csv
import io
import math
import re

from django.db import transaction

from ..models import POSITIVE_INTEGER_MAX, Workout, WorkoutExercise


MAX_CSV_BYTES = 1024 * 1024
MAX_CSV_ROWS = 1000
CSV_HEADERS = (
    "workout_name",
    "exercise",
    "position",
    "sets",
    "reps",
    "default_weight_lbs",
    "velocity_min",
    "velocity_max",
)
_POSITIVE_INTEGER = re.compile(r"^[0-9]+$")


def validation_error(row, field, code, detail):
    return {"row": row, "field": field, "code": code, "detail": detail}


def normalize_workout_name(value):
    return value.strip().casefold() if isinstance(value, str) else ""


def _required_text(value, row, field, errors):
    if not isinstance(value, str) or not value.strip():
        errors.append(validation_error(row, field, "required", f"{field} is required."))
        return None
    value = value.strip()
    if len(value) > 255:
        errors.append(validation_error(row, field, "too_long", f"{field} must be at most 255 characters."))
        return None
    return value


def _positive_integer(value, row, field, errors):
    digits = None
    if isinstance(value, bool):
        parsed = None
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        digits = value.strip()
        parsed = None
        if _POSITIVE_INTEGER.fullmatch(digits):
            normalized_digits = digits.lstrip("0") or "0"
            maximum = str(POSITIVE_INTEGER_MAX)
            if len(normalized_digits) < len(maximum) or (
                len(normalized_digits) == len(maximum) and normalized_digits <= maximum
            ):
                parsed = int(normalized_digits)
    else:
        parsed = None
    if (isinstance(value, int) and value > POSITIVE_INTEGER_MAX) or (
        digits is not None and _POSITIVE_INTEGER.fullmatch(digits) and parsed is None
    ):
        errors.append(validation_error(
            row,
            field,
            "out_of_range",
            f"{field} must be at most {POSITIVE_INTEGER_MAX}.",
        ))
        return None
    if parsed is None or parsed < 1:
        errors.append(validation_error(row, field, "invalid_integer", f"{field} must be a positive integer."))
        return None
    return parsed


def _finite_number(value, row, field, errors, *, minimum=None):
    if isinstance(value, bool) or value is None or (isinstance(value, str) and not value.strip()):
        parsed = None
    else:
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            parsed = None
    if parsed is None or not math.isfinite(parsed):
        errors.append(validation_error(row, field, "invalid_number", f"{field} must be a finite number."))
        return None
    if minimum is not None and parsed < minimum:
        errors.append(validation_error(row, field, "out_of_range", f"{field} must be at least {minimum}."))
        return None
    return parsed


def _optional_velocity(value, row, field, errors):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _finite_number(value, row, field, errors)


def validate_workout_rows(rows, *, check_existing=True):
    errors = []
    grouped = OrderedDict()
    for row_number, raw in rows:
        if not isinstance(raw, Mapping):
            errors.append(validation_error(row_number, None, "invalid_row", "Each exercise must be an object."))
            continue
        name = _required_text(raw.get("workout_name"), row_number, "workout_name", errors)
        exercise = _required_text(raw.get("exercise"), row_number, "exercise", errors)
        position = _positive_integer(raw.get("position"), row_number, "position", errors)
        sets = _positive_integer(raw.get("sets"), row_number, "sets", errors)
        reps = _positive_integer(raw.get("reps"), row_number, "reps", errors)
        weight = _finite_number(
            raw.get("default_weight_lbs"), row_number, "default_weight_lbs", errors, minimum=0,
        )
        velocity_min = _optional_velocity(raw.get("velocity_min"), row_number, "velocity_min", errors)
        velocity_max = _optional_velocity(raw.get("velocity_max"), row_number, "velocity_max", errors)
        if (velocity_min is None) != (velocity_max is None):
            errors.append(validation_error(
                row_number,
                "velocity_min",
                "velocity_pair_required",
                "velocity_min and velocity_max must both be blank or both be set.",
            ))
        elif velocity_min is not None and (
            velocity_min < 0 or velocity_max > 10 or velocity_max < velocity_min
        ):
            errors.append(validation_error(
                row_number,
                "velocity_max",
                "invalid_velocity_range",
                "Velocity bounds must be ordered and between 0 and 10 m/s.",
            ))

        if name is None:
            continue
        normalized_name = normalize_workout_name(name)
        workout = grouped.setdefault(normalized_name, {
            "name": name,
            "normalized_name": normalized_name,
            "exercises": [],
        })
        if all(value is not None for value in (exercise, position, sets, reps, weight)) and (
            (velocity_min is None and velocity_max is None)
            or (
                velocity_min is not None
                and velocity_max is not None
                and 0 <= velocity_min <= velocity_max <= 10
            )
        ):
            workout["exercises"].append({
                "_row": row_number,
                "exercise": exercise,
                "position": position,
                "sets": sets,
                "reps": reps,
                "default_weight_lbs": weight,
                "velocity_min": velocity_min,
                "velocity_max": velocity_max,
            })

    for workout in grouped.values():
        positions = [exercise["position"] for exercise in workout["exercises"]]
        duplicates = sorted(position for position, count in Counter(positions).items() if count > 1)
        if duplicates:
            for exercise in workout["exercises"]:
                if exercise["position"] in duplicates:
                    errors.append(validation_error(
                        exercise["_row"],
                        "position",
                        "duplicate_position",
                        f"Workout '{workout['name']}' has duplicate position {exercise['position']}.",
                    ))
        if positions and sorted(set(positions)) != list(range(1, len(positions) + 1)):
            errors.append(validation_error(
                workout["exercises"][0]["_row"],
                "position",
                "non_contiguous_positions",
                f"Workout '{workout['name']}' positions must start at 1 and be contiguous.",
            ))
        workout["exercises"].sort(key=lambda exercise: exercise["position"])
        for exercise in workout["exercises"]:
            exercise.pop("_row")

    if check_existing and grouped:
        existing = set(
            Workout.objects.filter(normalized_name__in=grouped).values_list("normalized_name", flat=True)
        )
        for normalized_name in grouped:
            if normalized_name in existing:
                errors.append(validation_error(
                    None,
                    "workout_name",
                    "workout_name_conflict",
                    f"Workout '{grouped[normalized_name]['name']}' already exists.",
                ))
    return list(grouped.values()), errors


def validate_manual_workout(payload):
    if not isinstance(payload, Mapping):
        return [], [validation_error(None, None, "invalid_request", "Request body must be an object.")]
    name = payload.get("name")
    exercises = payload.get("exercises")
    if not isinstance(exercises, list) or not exercises:
        return [], [validation_error(None, "exercises", "required", "At least one exercise is required.")]
    if len(exercises) > MAX_CSV_ROWS:
        return [], [validation_error(
            None,
            "exercises",
            "row_limit_exceeded",
            "A workout must contain at most 1000 exercises.",
        )]
    rows = []
    for index, exercise in enumerate(exercises, start=1):
        row = dict(exercise) if isinstance(exercise, Mapping) else exercise
        if isinstance(row, dict):
            row["workout_name"] = name
        rows.append((index, row))
    return validate_workout_rows(rows)


def parse_workout_csv(uploaded_file):
    if uploaded_file is None:
        return [], [validation_error(None, "file", "file_required", "A CSV file is required.")]
    uploaded_file.seek(0)
    body = uploaded_file.read(MAX_CSV_BYTES + 1)
    if len(body) > MAX_CSV_BYTES:
        return [], [validation_error(None, "file", "file_too_large", "CSV file must not exceed 1 MiB.")]
    if not body:
        return [], [validation_error(None, "file", "empty_file", "CSV file is empty.")]
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], [validation_error(None, "file", "invalid_encoding", "CSV file must use UTF-8 encoding.")]
    if "\x00" in text:
        return [], [validation_error(None, "file", "malformed_csv", "CSV file is malformed.")]

    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        headers = next(reader, None)
        if headers is None:
            return [], [validation_error(None, "file", "empty_file", "CSV file is empty.")]
        duplicate_headers = sorted(header for header, count in Counter(headers).items() if count > 1)
        missing_headers = sorted(set(CSV_HEADERS) - set(headers))
        unknown_headers = sorted(set(headers) - set(CSV_HEADERS))
        header_errors = []
        if duplicate_headers:
            header_errors.append(validation_error(None, "headers", "duplicate_headers", f"Duplicate header(s): {', '.join(duplicate_headers)}."))
        if missing_headers:
            header_errors.append(validation_error(None, "headers", "missing_headers", f"Missing header(s): {', '.join(missing_headers)}."))
        if unknown_headers:
            header_errors.append(validation_error(None, "headers", "unknown_headers", f"Unknown header(s): {', '.join(unknown_headers)}."))
        if header_errors:
            return [], header_errors

        rows = []
        for csv_row in reader:
            if not csv_row:
                continue
            if len(rows) >= MAX_CSV_ROWS:
                return [], [validation_error(None, "file", "row_limit_exceeded", "CSV file must contain at most 1000 exercise rows.")]
            row_number = reader.line_num
            if len(csv_row) != len(headers):
                return [], [validation_error(row_number, None, "malformed_csv", "CSV row has an incorrect number of columns.")]
            rows.append((row_number, dict(zip(headers, csv_row))))
    except (csv.Error, UnicodeError):
        return [], [validation_error(None, "file", "malformed_csv", "CSV file is malformed.")]

    if not rows:
        return [], [validation_error(None, "file", "empty_csv", "CSV file must contain at least one exercise row.")]
    return validate_workout_rows(rows)


@transaction.atomic
def create_workouts(validated_workouts):
    created = []
    for workout_data in validated_workouts:
        workout = Workout.objects.create(
            name=workout_data["name"],
            normalized_name=workout_data["normalized_name"],
        )
        WorkoutExercise.objects.bulk_create([
            WorkoutExercise(workout=workout, **exercise)
            for exercise in workout_data["exercises"]
        ])
        created.append(workout)
    return created


def serialize_workout(workout):
    return {
        "id": workout.id,
        "name": workout.name,
        "created_at": workout.created_at,
        "exercises": [{
            "id": exercise.id,
            "exercise": exercise.exercise,
            "position": exercise.position,
            "sets": exercise.sets,
            "reps": exercise.reps,
            "default_weight_lbs": exercise.default_weight_lbs,
            "velocity_min": exercise.velocity_min,
            "velocity_max": exercise.velocity_max,
        } for exercise in workout.exercises.all()],
    }


def preview_workout(workout):
    return {
        "name": workout["name"],
        "exercises": workout["exercises"],
    }
