from datetime import timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import BooleanField
from django.db.models.expressions import RawSQL
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from ..models import DailyReport


SUPPORTED_REPORT_SCHEMAS = (1, 2)
ATHLETE_IDS_JSON_PATH = "$.athletes[*].athlete.id"


class UnsupportedReportSchema(Exception):
    pass


class AthleteNotInReport(Exception):
    pass


def reports_for_athlete(athlete_id):
    return DailyReport.objects.annotate(
        contains_athlete=RawSQL(
            """
            jsonb_path_query_array(snapshot, '$.athletes[*].athlete.id'::jsonpath)
            @> to_jsonb(ARRAY[%s::bigint])
            """,
            [athlete_id],
            output_field=BooleanField(),
        ),
    ).filter(contains_athlete=True)


def _object(value):
    return value if isinstance(value, dict) else {}


def _items(value):
    return value if isinstance(value, list) else []


def _value(source, key):
    return source[key] if key in source else None


def _identity(source):
    source = _object(source)
    return {"id": _value(source, "id"), "name": _value(source, "name")}


def _exercise(source):
    source = _object(source)
    return {
        "id": _value(source, "id"),
        "exercise": _value(source, "exercise"),
        "position": _value(source, "position"),
        "sets": _value(source, "sets"),
        "reps": _value(source, "reps"),
        "default_weight_lbs": _value(source, "default_weight_lbs"),
        "velocity_min": _value(source, "velocity_min"),
        "velocity_max": _value(source, "velocity_max"),
    }


def _prescription(source):
    if source is None:
        return None
    source = _object(source)
    return {
        "source": _value(source, "source"),
        "rack_number": _value(source, "rack_number"),
        "program": _identity(source["program"]) if source.get("program") is not None else None,
        "workout": _identity(source["workout"]) if source.get("workout") is not None else None,
        "exercises": [_exercise(item) for item in _items(source.get("exercises"))],
    }


def _rep(source):
    source = _object(source)
    return {
        "id": _value(source, "id"),
        "rep_number": _value(source, "rep_number"),
        "timestamp": _value(source, "timestamp"),
        "mean_velocity": _value(source, "mean_velocity"),
        "peak_velocity": _value(source, "peak_velocity"),
        "duration_ms": _value(source, "duration_ms"),
        "velocity_color": _value(source, "velocity_color"),
    }


def _workout_set(source, *, include_false_set=False):
    source = _object(source)
    result = {
        "id": _value(source, "id"),
        "athlete_day_progress_id": _value(source, "athlete_day_progress_id"),
        "workout_program_item_id": _value(source, "workout_program_item_id"),
        "workout_exercise_id": _value(source, "workout_exercise_id"),
        "rack_number": _value(source, "rack_number"),
        "exercise": _value(source, "exercise"),
        "set_number": _value(source, "set_number"),
        "weight_lbs": _value(source, "weight_lbs"),
        "started_at": _value(source, "started_at"),
        "ended_at": _value(source, "ended_at"),
        "reps_completed": _value(source, "reps_completed"),
        "avg_velocity": _value(source, "avg_velocity"),
        "peak_velocity": _value(source, "peak_velocity"),
        "reps": [_rep(item) for item in _items(source.get("reps"))],
    }
    if include_false_set:
        result["is_false_set"] = _value(source, "is_false_set") is True
    return result


def _athlete_v1(source):
    source = _object(source)
    return {
        "athlete": _identity(source.get("athlete")),
        "prescription": _prescription(source.get("prescription")),
        "sets": [_workout_set(item) for item in _items(source.get("sets"))],
    }


def _program_item(source, program):
    source = _object(source)
    workout = _object(source.get("workout"))
    return {
        "id": _value(source, "id"),
        "position": _value(source, "position"),
        "source": "program",
        "program": _identity(program),
        "workout": _identity(workout),
        "exercises": [_exercise(item) for item in _items(workout.get("exercises"))],
    }


def _assigned_program(source):
    if source is None:
        return None
    source = _object(source)
    identity = _identity(source)
    return {
        **identity,
        "items": [_program_item(item, identity) for item in _items(source.get("items"))],
    }


def _progress(source):
    if source is None:
        return None
    source = _object(source)
    current_item = _object(source.get("current_program_item"))
    current_exercise = _object(source.get("current_workout_exercise"))
    return {
        "id": _value(source, "id"),
        "status": _value(source, "status"),
        "workout_program_id": _value(source, "workout_program_id"),
        "current_program_item": ({
            "id": _value(current_item, "id"),
            "position": _value(current_item, "position"),
            "workout_id": _value(current_item, "workout_id"),
        } if source.get("current_program_item") is not None else None),
        "current_workout_exercise": ({
            "id": _value(current_exercise, "id"),
            "position": _value(current_exercise, "position"),
        } if source.get("current_workout_exercise") is not None else None),
        "expected_set_number": _value(source, "expected_set_number"),
    }


def _athlete_v2(source):
    source = _object(source)
    assigned_program = _assigned_program(source.get("assigned_program"))
    racks = [
        rack for rack in _items(source.get("rack_participation"))
        if isinstance(rack, int) and not isinstance(rack, bool)
    ]
    return {
        "athlete": _identity(source.get("athlete")),
        "assigned_program": assigned_program,
        "prescriptions": assigned_program["items"] if assigned_program else [],
        "final_progress": _progress(source.get("final_progress")),
        "rack_participation": sorted(set(racks)),
        "sets": [_workout_set(item, include_false_set=True) for item in _items(source.get("sets"))],
    }


def _summary(athletes):
    sets = [
        workout_set for athlete in athletes for workout_set in athlete["sets"]
        if workout_set.get("is_false_set") is not True
    ]
    completed_reps = sum(
        value for value in (workout_set["reps_completed"] for workout_set in sets)
        if isinstance(value, int) and not isinstance(value, bool)
    )
    velocities = [
        workout_set["avg_velocity"] for workout_set in sets
        if isinstance(workout_set["avg_velocity"], (int, float))
        and not isinstance(workout_set["avg_velocity"], bool)
    ]
    return {
        "athlete_count": len(athletes),
        "completed_sets": len(sets),
        "completed_reps": completed_reps,
        "average_velocity": sum(velocities) / len(velocities) if velocities else None,
    }


def _local_date(session, generated_at):
    ended_at = session.get("ended_at")
    parsed = parse_datetime(ended_at) if isinstance(ended_at, str) else None
    instant = parsed or generated_at
    if timezone.is_naive(instant):
        instant = timezone.make_aware(instant, datetime_timezone.utc)
    return instant.astimezone(ZoneInfo(settings.TIME_ZONE)).date().isoformat()


def _report_parts(report):
    snapshot = _object(report.snapshot)
    if report.schema_version != snapshot.get("schema_version"):
        raise UnsupportedReportSchema
    athlete_extractor = {
        1: _athlete_v1,
        2: _athlete_v2,
    }.get(report.schema_version)
    if athlete_extractor is None:
        raise UnsupportedReportSchema
    session = _object(snapshot.get("session"))
    safe_session = {
        "id": _value(session, "id"),
        "label": _value(session, "label"),
        "started_at": _value(session, "started_at"),
        "ended_at": _value(session, "ended_at"),
    }
    athletes = [athlete_extractor(item) for item in _items(snapshot.get("athletes"))]
    metadata = {
        "id": report.id,
        "schema_version": report.schema_version,
        "generated_at": report.generated_at,
        "local_date": _local_date(safe_session, report.generated_at),
        "timezone": settings.TIME_ZONE,
        "session": safe_session,
    }
    return metadata, athletes, _object(snapshot.get("exclusions"))


def report_list_item(report):
    metadata, athletes, _exclusions = _report_parts(report)
    return {**metadata, "summary": _summary(athletes)}


def report_detail(report):
    metadata, athletes, exclusions = _report_parts(report)
    return {
        **metadata,
        "summary": _summary(athletes),
        "athletes": athletes,
        "exclusions": {
            "false_sets": _value(exclusions, "false_sets"),
            "simulated_sets": _value(exclusions, "simulated_sets"),
            "unsaved_live_reps": _value(exclusions, "unsaved_live_reps"),
        },
    }


def athlete_report_list_item(report, athlete_id):
    metadata, athletes, _exclusions = _report_parts(report)
    matching = [item for item in athletes if item["athlete"]["id"] == athlete_id]
    if not matching:
        raise AthleteNotInReport
    athlete = matching[0]
    return {
        **metadata,
        "summary": _summary([athlete]),
        "athlete": athlete["athlete"],
    }


def athlete_report_detail(report, athlete_id):
    metadata, athletes, _exclusions = _report_parts(report)
    matching = [item for item in athletes if item["athlete"]["id"] == athlete_id]
    if not matching:
        raise AthleteNotInReport
    athlete = matching[0]
    return {**metadata, "summary": _summary([athlete]), "athlete": athlete}
