"""
views.py — the base station's HTTP endpoints (the handlers screens talk to).

Grouped by who uses them:

  TABLET (open — no login):
    - rack_register / rack_racknumber: a tablet says "here I am" and asks
      "which rack am I?"
    - programs_view (GET): look up an athlete's plan (targets + the speed zone
      used to color reps).
    - set_create: start a set (make an empty record).
    - set_complete: finish a set — save all its reps + totals in one
      all-or-nothing step. The ONLY place rep records are created.

  READS (open):
    - nodes_list (GET): list the sensors.

  COACH-ONLY (needs a coach login):
    - manage athletes, programs, sessions, and nodes; assign racks; and pull
      the analytics summaries.

Open vs coach-only follows SPEC.md; shapes live in MESSAGE_CONTRACT.md.
"""
from collections.abc import Mapping
from datetime import timedelta
from functools import wraps
import hashlib
import math
import uuid

from django.db import IntegrityError, connection, transaction
from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.db.models.functions import Lower
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, parser_classes, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound, ParseError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from .models import Node, RackScreen, RackWorkoutState, Athlete, Program, Session, Set, Rep, MonitoringEvent, Workout, WorkoutExercise, WorkoutProgram, WorkoutProgramItem, AthleteWorkoutAssignment, AthleteWorkoutProgramAssignment, AthleteWorkoutExerciseOverride, AthleteDayProgress, AthleteRackParticipation, DailyReport, POSITIVE_INTEGER_MAX
from .permissions import IsCoach
from .services.set_completion import (
    complete_set,
    RackCompletionRejected,
    SessionRepLimitExceeded,
    SetAlreadyComplete,
    SetNotFound,
    SetSessionEnded,
    UnexpectedWorkoutStep,
)
from .services.workout_catalog import (
    create_workouts,
    parse_workout_csv,
    preview_workout,
    serialize_workout,
    validate_manual_workout,
)
from .services.workout_programs import (
    WorkoutProgramNameConflict,
    WorkoutProgramValidationError,
    create_workout_program,
    serialize_workout_program,
    validate_workout_program,
)
from .services.athlete_workouts import (
    assignment_workout,
    effective_workout as build_effective_workout,
    serialize_athlete_assignment,
    serialize_day_progress,
    serialize_override,
    serialize_program_assignment,
)
from .services.athlete_progress import AthleteProgramIncomplete, get_or_create_progress
from .services.training_days import (
    ActiveTrainingDayConflict,
    SessionAlreadyEnded,
    SessionNotFound as TrainingDaySessionNotFound,
    SimulationEndRejected,
    ReportTooLarge,
    SessionAthleteLimitExceeded,
    TrainingDayRaceConflict,
    UnfinishedSetsConflict,
    end_training_day,
    lock_rack_number as training_day_lock_rack_number,
    serialize_daily_report,
    start_training_day,
)
from .services.training_limits import MAX_SESSION_REPS, MAX_SESSION_SETS
from .services.reports import (
    AthleteNotInReport,
    UnsupportedReportSchema,
    athlete_report_detail as extract_athlete_report_detail,
    athlete_report_list_item,
    report_detail as extract_report_detail,
    report_list_item,
    reports_for_athlete,
)
from .services.report_pdf import PdfTooLarge, render_report_pdf
from .serializers import (SetSerializer, SetCompleteSerializer, RackScreenSerializer,
                          ProgramSerializer, PublicProgramSerializer, AthleteSerializer, PublicAthleteSerializer, SessionSerializer,
                          NodeSerializer)


def _require_coach(request):
    """Small helper for endpoints that are open to read but coach-only to write:
    returns True if the caller is a logged-in coach."""
    return bool(request.user and request.user.is_authenticated and request.user.is_active and request.user.is_staff)


class RackRegistrationThrottle(AnonRateThrottle):
    scope = "rack_registration"
    rate = "30/min"


class RackReadThrottle(AnonRateThrottle):
    scope = "rack_read"
    rate = "120/min"


class RackWriteThrottle(AnonRateThrottle):
    scope = "rack_write"
    rate = "120/min"


# ─────────────────────────── tablet: racks ───────────────────────────


def _canonical_device_id(value):
    if not isinstance(value, str) or len(value) > 36:
        return None
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return None
    canonical = str(parsed)
    return canonical if value.lower() == canonical else None


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([RackRegistrationThrottle])
def rack_register(request):
    """A rack tablet announces itself. Make (or find) its RackScreen row by
    device_id; rack_number stays empty until a coach assigns it. Body: { device_id }."""
    device_id = _canonical_device_id(request.data.get("device_id"))
    if device_id is None:
        return Response({"code": "invalid_device_id", "detail": "device_id must be a canonical UUID."}, status=400)
    screen, created = RackScreen.objects.get_or_create(device_id=device_id)
    if not created:
        screen.save(update_fields=["last_seen"])
    response = Response({"device_id": screen.device_id, "rack_number": screen.rack_number})
    response["Cache-Control"] = "private, no-store"
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([RackReadThrottle])
def rack_racknumber(request):
    """A waiting tablet asks "which rack am I?" Returns its rack_number (empty
    until a coach assigns it). Query: ?device_id=..."""
    device_id = _canonical_device_id(request.data.get("device_id"))
    if device_id is None:
        return Response({"code": "invalid_device_id", "detail": "device_id must be a canonical UUID."}, status=400)
    screen = RackScreen.objects.filter(device_id=device_id).first()
    response = Response({"rack_number": screen.rack_number if screen else None})
    response["Cache-Control"] = "private, no-store"
    return response


@api_view(["GET"])
@permission_classes([IsCoach])
def racks_unassigned(request):
    """Coach-only: list every tablet still waiting for a rack (rack_number empty)."""
    waiting = RackScreen.objects.filter(rack_number__isnull=True)
    return Response(RackScreenSerializer(waiting, many=True).data)


@api_view(["PATCH"])
@permission_classes([IsCoach])
def rack_assign(request, device_id):
    """Assign a screen to a rack, clearing affected identities safely."""
    rack_number = request.data.get("rack_number")
    if (
        isinstance(rack_number, bool)
        or not isinstance(rack_number, int)
        or not 1 <= rack_number <= POSITIVE_INTEGER_MAX
    ):
        return _rack_error("invalid_rack_number", "rack_number must be a positive integer.", 400)
    for _attempt in range(3):
        observed = RackScreen.objects.filter(device_id=device_id).values_list("rack_number", flat=True).first()
        if observed is None and not RackScreen.objects.filter(device_id=device_id).exists():
            return _rack_error("rack_screen_not_found", "Rack screen not found.", 404)
        retry = False
        with transaction.atomic():
            affected_racks = sorted({rack for rack in (observed, rack_number) if rack is not None})
            for affected_rack in affected_racks:
                _lock_rack_number(affected_rack)
            screen = RackScreen.objects.select_for_update().filter(device_id=device_id).first()
            if screen is None:
                return _rack_error("rack_screen_not_found", "Rack screen not found.", 404)
            if screen.rack_number != observed:
                retry = True
            elif observed == rack_number:
                response = Response(RackScreenSerializer(screen).data)
                response["Cache-Control"] = "private, no-store"
                return response
            else:
                if Set.objects.select_for_update().filter(
                    rack_number__in=affected_racks,
                    ended_at=None,
                ).exists():
                    return _rack_error("unfinished_set", "An affected rack has an unfinished set.", 409)
                states = list(
                    RackWorkoutState.objects.select_for_update().filter(rack_number__in=affected_racks)
                )
                for state in states:
                    if state.selected_athlete_id is not None:
                        state.selected_athlete = None
                        state.save(update_fields=["selected_athlete", "updated_at"])
                screen.rack_number = rack_number
                screen.save(update_fields=["rack_number", "last_seen"])
                active_session = Session.objects.filter(ended_at=None).order_by("-started_at", "-id").first()
                MonitoringEvent.objects.create(
                    reason="rack_screen_reassigned",
                    is_simulated=active_session.is_simulated if active_session else False,
                )
                response = Response(RackScreenSerializer(screen).data)
                response["Cache-Control"] = "private, no-store"
                return response
        if not retry:
            break
    return _rack_error(
        "rack_reassignment_conflict",
        "Rack screen assignment changed concurrently; retry the request.",
        409,
    )


def _rack_error(code, detail, status):
    response = Response({"code": code, "detail": detail}, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _private_no_store(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response
    return wrapped


def _private_pdf(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    return wrapped


def _lock_rack_number(rack_number):
    """Serialize rack selection and set-start transactions for one rack."""
    training_day_lock_rack_number(rack_number)


def _program_body(program):
    if program is None:
        return None
    return {
        "id": program.id,
        "exercise": program.exercise,
        "target_sets": program.target_sets,
        "target_reps": program.target_reps,
        "target_weight_lbs": program.target_weight_lbs,
        "velocity_zone_min": program.velocity_zone_min,
        "velocity_zone_max": program.velocity_zone_max,
    }


MAX_RACK_ACTIVE_ATHLETES = 100


def _known_rack(rack_number):
    return rack_number > 0 and (
        RackScreen.objects.filter(rack_number=rack_number).exists()
        or Node.objects.filter(rack_number=rack_number).exists()
        or RackWorkoutState.objects.filter(rack_number=rack_number).exists()
    )


def _workout_identity(workout):
    return {"id": workout.id, "name": workout.name}


def _rack_node_body(rack_number):
    nodes = list(Node.objects.filter(rack_number=rack_number).order_by("node_id")[:2])
    if not nodes:
        return {"state": "unassigned", "node_id": None}
    if len(nodes) > 1:
        return {"state": "conflict", "node_id": None}
    if not nodes[0].is_active:
        return {"state": "inactive", "node_id": None}
    return {"state": "ready", "node_id": nodes[0].node_id}


def _rack_state_body(rack_number, *, include_active_set=False):
    revision = MonitoringEvent.objects.order_by("-id").values_list("id", flat=True).first() or 0
    active_session = Session.objects.filter(ended_at=None).order_by("-started_at", "-id").first()
    state = (
        RackWorkoutState.objects.select_related(
            "active_program__athlete",
            "assigned_workout",
            "assigned_program_item__workout",
            "assigned_program_item__workout_program",
            "selected_athlete",
        ).prefetch_related("assigned_workout__exercises", "assigned_program_item__workout__exercises")
        .filter(rack_number=rack_number)
        .first()
    )
    selected_program = None
    if (
        state
        and state.active_program
        and active_session
        and state.active_session_id == active_session.id
        and active_session.athletes.filter(id=state.active_program.athlete_id).exists()
    ):
        selected_program = state.active_program
    athlete = selected_program.athlete if selected_program else None
    programs = Program.objects.none()
    if athlete:
        programs = Program.objects.filter(athlete=athlete).order_by("id")
    assignment = None
    effective_workout = None
    effective_assignment_source = None
    catalog_athlete = None
    rack_workout = None
    active_athlete_rows = []
    active_athletes_truncated = False
    progress = None
    valid_catalog_assignment = bool(
        state
        and active_session
        and state.active_session_id == active_session.id
        and state.active_program_id is None
        and ((state.assigned_workout_id is None) != (state.assigned_program_item_id is None))
    )
    if valid_catalog_assignment:
        rack_workout = state.assigned_workout
        if state.assigned_program_item:
            item = state.assigned_program_item
            rack_workout = item.workout
            assignment = {
                "type": "program",
                "program": {"id": item.workout_program_id, "name": item.workout_program.name},
                "workout": _workout_identity(item.workout),
            }
        elif rack_workout:
            assignment = {
                "type": "workout",
                "workout": _workout_identity(rack_workout),
            }
    valid_catalog_identity = bool(
        state
        and active_session
        and state.active_session_id == active_session.id
        and state.active_program_id is None
        and state.selected_athlete
        and active_session.athletes.filter(id=state.selected_athlete_id).exists()
    )
    if valid_catalog_identity:
        catalog_athlete = state.selected_athlete
        progress = (
            AthleteDayProgress.objects.select_related(
                "athlete",
                "workout_program",
                "current_program_item__workout",
                "current_workout_exercise",
            ).filter(session=active_session, athlete=catalog_athlete).first()
        )
        if progress and progress.current_program_item_id:
            effective_workout = build_effective_workout(
                progress.current_program_item.workout,
                catalog_athlete,
            )
            effective_assignment_source = "athlete_program"

    roster_available = bool(
        active_session
        and AthleteWorkoutProgramAssignment.objects.filter(
            athlete__sessions=active_session,
            workout_program__items__workout__exercises__isnull=False,
        ).exists()
    )
    if roster_available:
        active_athletes = list(
            active_session.athletes.filter(
                workout_program_assignment__workout_program__items__workout__exercises__isnull=False,
            ).distinct().order_by("name", "id")[:MAX_RACK_ACTIVE_ATHLETES + 1]
        )
        active_athletes_truncated = len(active_athletes) > MAX_RACK_ACTIVE_ATHLETES
        active_athlete_rows = [
            {"id": active_athlete.id, "name": active_athlete.name}
            for active_athlete in active_athletes[:MAX_RACK_ACTIVE_ATHLETES]
        ]
    if not athlete:
        athlete = catalog_athlete
    return {
        "revision": revision,
        "rack_number": rack_number,
        "active_session": {
            "id": active_session.id,
            "label": active_session.label,
        } if active_session else None,
        "selected_athlete": {"id": athlete.id, "name": athlete.name} if athlete else None,
        "active_athletes": active_athlete_rows,
        "active_athletes_truncated": active_athletes_truncated,
        "identity_available": roster_available,
        "assignment": assignment,
        "effective_workout": effective_workout,
        "effective_assignment_source": effective_assignment_source,
        "progress": serialize_day_progress(progress, include_active_set=include_active_set) if progress else None,
        "programs": [_program_body(program) for program in programs],
        "active_program": _program_body(selected_program),
        "node": _rack_node_body(rack_number),
    }


@api_view(["GET", "PATCH"])
@permission_classes([AllowAny])
@throttle_classes([RackReadThrottle])
def rack_workout_state(request, rack_number):
    """Read rack-safe workout state or atomically change its coach selection."""
    if not _known_rack(rack_number):
        return _rack_error("rack_not_found", "Rack not found.", 404)
    if request.method == "GET":
        device_id = _canonical_device_id(request.headers.get("X-Rack-Device-Id"))
        screens = list(
            RackScreen.objects.filter(rack_number=rack_number)
            .order_by("device_id")
            .values_list("device_id", flat=True)[:2]
        )
        include_active_set = len(screens) == 1 and screens[0] == device_id
        response = Response(_rack_state_body(rack_number, include_active_set=include_active_set))
        response["Cache-Control"] = "private, no-store"
        return response

    if not request.user or not request.user.is_authenticated:
        return _rack_error("not_authenticated", "Coach login required.", 401)
    if not request.user.is_active or not request.user.is_staff:
        return _rack_error("permission_denied", "Coach access required.", 403)
    try:
        payload = request.data
    except ParseError:
        return _rack_error("malformed_request", "Request body must be valid JSON.", 400)
    if not isinstance(payload, Mapping):
        return _rack_error("malformed_request", "Request body must be an object.", 400)
    athlete_id = payload.get("athlete_id")
    program_id = payload.get("program_id")
    if (
        isinstance(athlete_id, bool) or not isinstance(athlete_id, int) or athlete_id <= 0
        or isinstance(program_id, bool) or not isinstance(program_id, int) or program_id <= 0
    ):
        return _rack_error(
            "malformed_request",
            "athlete_id and program_id must be positive integers.",
            400,
        )

    with transaction.atomic():
        _lock_rack_number(rack_number)
        active_session = (
            Session.objects.select_for_update()
            .filter(ended_at=None)
            .order_by("-started_at", "-id")
            .first()
        )
        if active_session is None:
            return _rack_error("no_active_session", "No active session.", 409)
        athlete = Athlete.objects.select_for_update().filter(id=athlete_id).first()
        if athlete is None:
            return _rack_error("athlete_not_found", "Athlete not found.", 404)
        if not active_session.athletes.filter(id=athlete.id).exists():
            return _rack_error(
                "athlete_not_in_active_session",
                "Athlete is not in the active session.",
                409,
            )
        program = Program.objects.select_related("athlete").filter(id=program_id).first()
        if program is None:
            return _rack_error("program_not_found", "Program not found.", 404)
        if program.athlete_id != athlete.id:
            return _rack_error(
                "program_athlete_mismatch",
                "Program does not belong to the selected athlete.",
                409,
            )
        if Set.objects.filter(rack_number=rack_number, ended_at=None).exists():
            return _rack_error("unfinished_set", "Rack has an unfinished set.", 409)

        RackWorkoutState.objects.get_or_create(rack_number=rack_number)
        state = RackWorkoutState.objects.select_for_update().get(rack_number=rack_number)
        state.active_session = active_session
        state.active_program = program
        state.assigned_workout = None
        state.assigned_program_item = None
        state.selected_athlete = None
        state.save(update_fields=[
            "active_session", "active_program", "assigned_workout",
            "assigned_program_item", "selected_athlete", "updated_at",
        ])
        MonitoringEvent.objects.create(
            reason="rack_selection_changed",
            is_simulated=active_session.is_simulated,
        )
    response = Response(_rack_state_body(rack_number))
    response["Cache-Control"] = "private, no-store"
    return response


def _positive_json_id(value, field):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= POSITIVE_INTEGER_MAX
    ):
        return None, _rack_error(
            "malformed_request",
            f"{field} must be a positive integer.",
            400,
        )
    return value, None


@_private_no_store
@api_view(["PUT"])
@permission_classes([IsCoach])
def rack_catalog_assignment(request, rack_number):
    """Assign one direct workout or one included program workout to a rack."""
    if not _known_rack(rack_number):
        return _rack_error("rack_not_found", "Rack not found.", 404)
    try:
        payload = request.data
    except ParseError:
        return _rack_error("malformed_request", "Request body must be valid JSON.", 400)
    if not isinstance(payload, Mapping):
        return _rack_error("malformed_request", "Request body must be an object.", 400)
    workout_id, error = _positive_json_id(payload.get("workout_id"), "workout_id")
    if error:
        return error
    workout_program_id = payload.get("workout_program_id")
    if workout_program_id is not None:
        workout_program_id, error = _positive_json_id(workout_program_id, "workout_program_id")
        if error:
            return error

    with transaction.atomic():
        _lock_rack_number(rack_number)
        active_session = (
            Session.objects.select_for_update()
            .filter(ended_at=None)
            .order_by("-started_at", "-id")
            .first()
        )
        if active_session is None:
            return _rack_error("no_active_session", "No active session.", 409)

        assigned_workout = None
        assigned_program_item = None
        if workout_program_id is None:
            assigned_workout = Workout.objects.select_for_update().filter(id=workout_id).first()
            if assigned_workout is None:
                return _rack_error("workout_not_found", "Workout not found.", 404)
        else:
            workout_program = WorkoutProgram.objects.select_for_update().filter(id=workout_program_id).first()
            if workout_program is None:
                return _rack_error("workout_program_not_found", "Workout program not found.", 404)
            assigned_program_item = (
                WorkoutProgramItem.objects.select_for_update()
                .select_related("workout", "workout_program")
                .filter(workout_program=workout_program, workout_id=workout_id)
                .first()
            )
            if assigned_program_item is None:
                if not Workout.objects.filter(id=workout_id).exists():
                    return _rack_error("workout_not_found", "Workout not found.", 404)
                return _rack_error(
                    "workout_not_in_program",
                    "Workout is not included in the workout program.",
                    409,
                )

        RackWorkoutState.objects.get_or_create(rack_number=rack_number)
        state = RackWorkoutState.objects.select_for_update().get(rack_number=rack_number)
        unchanged = (
            state.active_session_id == active_session.id
            and state.active_program_id is None
            and state.assigned_workout_id == (assigned_workout.id if assigned_workout else None)
            and state.assigned_program_item_id == (
                assigned_program_item.id if assigned_program_item else None
            )
        )
        if not unchanged:
            if Set.objects.filter(rack_number=rack_number, ended_at=None).exists():
                return _rack_error("unfinished_set", "Rack has an unfinished set.", 409)
            state.selected_athlete = None
            state.active_session = active_session
            state.active_program = None
            state.assigned_workout = assigned_workout
            state.assigned_program_item = assigned_program_item
            state.save(update_fields=[
                "active_session", "active_program", "assigned_workout",
                "assigned_program_item", "selected_athlete", "updated_at",
            ])
            MonitoringEvent.objects.create(
                reason="rack_assignment_changed",
                is_simulated=active_session.is_simulated,
            )
    return _private_response(_rack_state_body(rack_number))


@_private_no_store
@api_view(["PUT", "DELETE"])
@permission_classes([AllowAny])
@throttle_classes([RackReadThrottle])
def rack_athlete_identity(request, rack_number):
    """Atomically sign an eligible athlete into one registered rack or out."""
    if not _known_rack(rack_number):
        return _rack_error("rack_not_found", "Rack not found.", 404)
    try:
        payload = request.data
    except ParseError:
        return _rack_error("malformed_request", "Request body must be valid JSON.", 400)
    if not isinstance(payload, Mapping):
        return _rack_error("malformed_request", "Request body must be an object.", 400)
    device_id = _canonical_device_id(payload.get("device_id"))
    if device_id is None:
        return _rack_error("invalid_device_id", "device_id must be a canonical UUID.", 400)
    athlete_id = None
    if request.method == "PUT":
        athlete_id, error = _positive_json_id(payload.get("athlete_id"), "athlete_id")
        if error:
            return error

    for _attempt in range(3):
        observed_athlete_id = athlete_id
        if request.method == "DELETE":
            observed_athlete_id = (
                RackWorkoutState.objects.filter(rack_number=rack_number)
                .values_list("selected_athlete_id", flat=True)
                .first()
            )
        observed_racks = tuple(
            RackWorkoutState.objects.filter(selected_athlete_id=observed_athlete_id)
            .order_by("rack_number")
            .values_list("rack_number", flat=True)
        ) if observed_athlete_id else ()
        locked_racks = sorted(set(observed_racks) | {rack_number})
        retry = False
        try:
            with transaction.atomic():
                for locked_rack in locked_racks:
                    _lock_rack_number(locked_rack)
                screens = list(
                    RackScreen.objects.select_for_update()
                    .filter(rack_number=rack_number)
                    .order_by("device_id")[:2]
                )
                if len(screens) != 1:
                    return _rack_error("rack_screen_conflict", "Rack must have exactly one assigned screen.", 409)
                if screens[0].device_id != device_id:
                    return _rack_error("rack_screen_mismatch", "device_id is not assigned to this rack.", 403)

                active_session = (
                    Session.objects.select_for_update()
                    .filter(ended_at=None)
                    .order_by("-started_at", "-id")
                    .first()
                )
                states = list(
                    RackWorkoutState.objects.select_for_update()
                    .filter(rack_number__in=locked_racks)
                    .order_by("rack_number")
                )
                destination = next((row for row in states if row.rack_number == rack_number), None)

                if request.method == "DELETE":
                    if destination is None or destination.selected_athlete_id is None:
                        return _private_response(_rack_state_body(rack_number))
                    progress = AthleteDayProgress.objects.select_for_update().filter(
                        session=active_session,
                        athlete_id=destination.selected_athlete_id,
                    ).first() if active_session else None
                    if (
                        (progress and Set.objects.select_for_update().filter(athlete_day_progress=progress, ended_at=None).exists())
                        or Set.objects.select_for_update().filter(rack_number=rack_number, ended_at=None).exists()
                    ):
                        return _rack_error("unfinished_set", "Athlete has an unfinished set.", 409)
                    destination.selected_athlete = None
                    destination.save(update_fields=["selected_athlete", "updated_at"])
                    MonitoringEvent.objects.create(
                        reason="rack_identity_changed",
                        is_simulated=active_session.is_simulated if active_session else False,
                    )
                    return _private_response(_rack_state_body(rack_number))

                if active_session is None:
                    return _rack_error("no_active_session", "No active session.", 409)
                athlete = Athlete.objects.select_for_update().filter(id=athlete_id).first()
                if athlete is None:
                    return _rack_error("athlete_not_found", "Athlete not found.", 404)
                if not active_session.athletes.filter(id=athlete.id).exists():
                    return _rack_error("athlete_not_in_active_session", "Athlete is not in the active session.", 409)
                assignment = (
                    AthleteWorkoutProgramAssignment.objects.select_for_update()
                    .select_related("workout_program")
                    .filter(athlete=athlete)
                    .first()
                )
                if assignment is None:
                    return _rack_error("athlete_program_required", "Athlete requires a complete workout program.", 409)

                current_racks = tuple(
                    row.rack_number for row in states if row.selected_athlete_id == athlete.id
                )
                if current_racks != observed_racks:
                    retry = True
                    continue
                try:
                    progress = get_or_create_progress(active_session, athlete, assignment)
                except AthleteProgramIncomplete:
                    return _rack_error("athlete_program_required", "Athlete requires a complete workout program.", 409)
                if current_racks == (rack_number,) and destination.selected_athlete_id == athlete.id:
                    participation, created = AthleteRackParticipation.objects.get_or_create(
                        session=active_session,
                        athlete=athlete,
                        rack_number=rack_number,
                    )
                    if not created:
                        participation.save(update_fields=["last_seen_at"])
                    return _private_response(_rack_state_body(rack_number))
                if Set.objects.select_for_update().filter(
                    athlete_day_progress=progress,
                    ended_at=None,
                ).exists():
                    return _rack_error("unfinished_set", "Athlete has an unfinished set.", 409)
                if destination and destination.selected_athlete_id not in (None, athlete.id):
                    occupant_progress = AthleteDayProgress.objects.select_for_update().filter(
                        session=active_session,
                        athlete_id=destination.selected_athlete_id,
                    ).first()
                    if (
                        occupant_progress
                        and Set.objects.select_for_update().filter(
                            athlete_day_progress=occupant_progress,
                            ended_at=None,
                        ).exists()
                    ):
                        return _rack_error("unfinished_set", "Rack athlete has an unfinished set.", 409)
                if Set.objects.select_for_update().filter(rack_number__in=locked_racks, ended_at=None).exists():
                    return _rack_error("unfinished_set", "An affected rack has an unfinished set.", 409)
                AthleteRackParticipation.objects.get_or_create(
                    session=active_session,
                    athlete=athlete,
                    rack_number=rack_number,
                )
                if destination is None:
                    destination = RackWorkoutState.objects.create(
                        rack_number=rack_number,
                        active_session=active_session,
                    )
                for state in states:
                    if state.selected_athlete_id == athlete.id or state.rack_number == rack_number:
                        state.selected_athlete = None
                        state.save(update_fields=["selected_athlete", "updated_at"])
                destination.active_session = active_session
                destination.active_program = None
                destination.assigned_workout = None
                destination.assigned_program_item = None
                destination.selected_athlete = athlete
                destination.save(update_fields=[
                    "active_session", "active_program", "assigned_workout",
                    "assigned_program_item", "selected_athlete", "updated_at",
                ])
                MonitoringEvent.objects.create(
                    reason="rack_identity_changed",
                    is_simulated=active_session.is_simulated,
                )
        except IntegrityError:
            retry = True
        if not retry:
            return _private_response(_rack_state_body(rack_number))
    return _rack_error(
        "athlete_sign_in_conflict",
        "Athlete sign-in changed concurrently; retry the request.",
        409,
    )


# ─────────────────────────── nodes ───────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def nodes_list(request):
    """Open: list every sensor node and its latest status."""
    return Response(NodeSerializer(Node.objects.order_by("node_id")[:500], many=True).data)


MAX_DASHBOARD_RACKS = 32
MAX_DASHBOARD_LEADERS = 20
MAX_DASHBOARD_REPS = 100


class WallStateThrottle(AnonRateThrottle):
    rate = "60/min"


class CoachRoomStateThrottle(UserRateThrottle):
    rate = "120/min"


class ReportPdfThrottle(UserRateThrottle):
    scope = "report_pdf"
    rate = "10/min"


def _coach_training_body(progress):
    if progress is None:
        return None
    exercise = progress.current_workout_exercise
    item = progress.current_program_item
    effective_exercise = None
    if exercise and item:
        effective_exercise = next(
            row for row in build_effective_workout(item.workout, progress.athlete)["exercises"]
            if row["id"] == exercise.id
        )
    current_sets = progress.sets.filter(
        workout_exercise=exercise,
        ended_at__isnull=False,
    ) if exercise else Set.objects.none()
    latest_result = (
        progress.sets.filter(ended_at__isnull=False)
        .order_by("-ended_at", "-id")
        .first()
    )
    return {
        "athlete": {"id": progress.athlete_id, "name": progress.athlete.name},
        "program": {"id": progress.workout_program_id, "name": progress.workout_program.name},
        "workout": ({
            "id": item.workout_id,
            "name": item.workout.name,
            "position": item.position,
        } if item else None),
        "exercise": ({
            "id": exercise.id,
            "name": exercise.exercise,
            "position": exercise.position,
            "sets": effective_exercise["sets"],
            "reps": effective_exercise["reps"],
            "velocity_min": exercise.velocity_min,
            "velocity_max": exercise.velocity_max,
        } if exercise else None),
        "status": progress.status,
        "expected_set_number": progress.expected_set_number,
        "progression": ({
            "completed_sets": current_sets.filter(is_false_set=False).count(),
            "false_sets": current_sets.filter(is_false_set=True).count(),
        } if exercise else None),
        "latest_result": ({
            "id": latest_result.id,
            "exercise_id": latest_result.workout_exercise_id,
            "exercise": latest_result.exercise,
            "set_number": latest_result.set_number,
            "reps_completed": latest_result.reps_completed,
            "avg_velocity": latest_result.avg_velocity,
            "peak_velocity": latest_result.peak_velocity,
            "is_false_set": latest_result.is_false_set,
            "ended_at": latest_result.ended_at,
        } if latest_result else None),
    }


def _room_state_snapshot(include_details):
    """Build a bounded persisted snapshot for a wall or authenticated coach."""
    # Read the revision first. A later commit can make snapshot data newer than
    # this cursor, but its retained event will then force another reconciliation.
    revision = MonitoringEvent.objects.order_by("-id").values_list("id", flat=True).first() or 0
    active_sessions = Session.objects.filter(ended_at__isnull=True).order_by("-started_at", "-id")
    active_session = active_sessions.first()

    node_racks = Node.objects.exclude(rack_number=None).values_list("rack_number", flat=True).distinct()[:MAX_DASHBOARD_RACKS]
    screen_racks = RackScreen.objects.exclude(rack_number=None).values_list("rack_number", flat=True).distinct()[:MAX_DASHBOARD_RACKS]
    state_racks = RackWorkoutState.objects.values_list("rack_number", flat=True).distinct()[:MAX_DASHBOARD_RACKS]
    session_racks = Set.objects.none().values_list("rack_number", flat=True)
    if active_session:
        session_racks = Set.objects.filter(session=active_session).exclude(rack_number=None).values_list("rack_number", flat=True).distinct()[:MAX_DASHBOARD_RACKS]
    all_rack_numbers = sorted(set(node_racks) | set(screen_racks) | set(state_racks) | set(session_racks))
    rack_numbers = all_rack_numbers[:MAX_DASHBOARD_RACKS]
    nodes = list(Node.objects.filter(rack_number__in=rack_numbers).order_by("rack_number", "node_id"))
    screen_counts = dict(
        RackScreen.objects.filter(rack_number__in=rack_numbers)
        .values_list("rack_number")
        .annotate(count=Count("id"))
    )
    selections_by_rack = {}
    registration_counts = {}
    progress_by_athlete = {}
    if active_session:
        selected_states = (
            RackWorkoutState.objects.filter(
                active_session=active_session,
            ).filter(
                Q(
                    selected_athlete__isnull=False,
                    selected_athlete__sessions=active_session,
                )
                | Q(
                    active_program__isnull=False,
                    active_program__athlete__sessions=active_session,
                )
            )
            .select_related("active_program__athlete", "selected_athlete")
        )
        selections_by_rack = {state.rack_number: state for state in selected_states}
        registration_counts = dict(
            RackScreen.objects.filter(rack_number__in=selections_by_rack)
            .values_list("rack_number")
            .annotate(count=Count("id"))
        )
        athlete_ids = {state.selected_athlete_id for state in selected_states}
        progress_by_athlete = {
            progress.athlete_id: progress
            for progress in AthleteDayProgress.objects.filter(
                session=active_session,
                athlete_id__in=athlete_ids,
            ).select_related(
                "athlete",
                "workout_program",
                "current_program_item__workout",
                "current_workout_exercise",
            )
        }

    movement_counts = {}
    movement_exercises = {}
    seen_athletes = set()
    for rack_number, state in selections_by_rack.items():
        if registration_counts.get(rack_number, 0) != 1 or state.selected_athlete_id in seen_athletes:
            continue
        progress = progress_by_athlete.get(state.selected_athlete_id)
        exercise = progress.current_workout_exercise if progress else None
        if exercise is None or exercise.velocity_min is None or exercise.velocity_max is None:
            continue
        seen_athletes.add(state.selected_athlete_id)
        movement_exercises[exercise.id] = exercise
        movement_counts[exercise.id] = movement_counts.get(exercise.id, 0) + 1
    selected_exercise = None
    if movement_counts:
        selected_exercise_id = min(
            movement_counts,
            key=lambda exercise_id: (
                -movement_counts[exercise_id],
                movement_exercises[exercise_id].exercise.strip().casefold(),
                exercise_id,
            ),
        )
        selected_exercise = movement_exercises[selected_exercise_id]

    latest_sets_by_rack = {}
    active_sets_by_rack = {}
    unassigned_session_sets = 0
    session_sets = Set.objects.none()
    if active_session:
        session_sets = Set.objects.filter(session=active_session)
        latest_sets = (
            session_sets.filter(rack_number__in=rack_numbers, ended_at__isnull=False)
            .select_related("athlete", "node", "workout_exercise")
            .order_by("rack_number", "-started_at", "-id")
            .distinct("rack_number")
        )
        latest_sets_by_rack = {workout_set.rack_number: workout_set for workout_set in latest_sets}
        active_sets = (
            session_sets.filter(rack_number__in=rack_numbers, ended_at__isnull=True)
            .order_by("rack_number", "-started_at", "-id")
            .distinct("rack_number")
        )
        active_sets_by_rack = {workout_set.rack_number: workout_set for workout_set in active_sets}
        unassigned_session_sets = session_sets.filter(rack_number__isnull=True).count()

    valid_sets = session_sets.filter(ended_at__isnull=False, is_false_set=False)
    totals = valid_sets.aggregate(
        completed_sets=Count("id"),
        completed_reps=Sum("reps_completed"),
        room_avg_velocity=Avg("avg_velocity"),
        athletes_with_sets=Count("athlete_id", distinct=True),
    )

    racks = []
    for rack_number in rack_numbers:
        rack_nodes = [node for node in nodes if node.rack_number == rack_number]
        latest_set = latest_sets_by_rack.get(rack_number)
        latest_set_body = None
        status = "idle"
        status_color = "neutral"

        if rack_number in active_sets_by_rack:
            status = "active"

        if latest_set:
            if latest_set.is_false_set:
                status = "false set"
            elif rack_number not in active_sets_by_rack:
                status = "complete"

            reps = list(latest_set.reps.order_by("rep_number")[:MAX_DASHBOARD_REPS])
            if reps and reps[-1].velocity_color in {"green", "yellow", "red"}:
                status_color = reps[-1].velocity_color
            latest_set_body = {
                "athlete": {"name": latest_set.athlete.name},
                "exercise": latest_set.exercise,
                "set_number": latest_set.set_number,
                "reps_completed": latest_set.reps_completed,
                "avg_velocity": latest_set.avg_velocity,
                "peak_velocity": latest_set.peak_velocity,
            }
            if include_details:
                velocity_min = velocity_max = None
                if latest_set.workout_exercise_id:
                    velocity_min = latest_set.workout_exercise.velocity_min
                    velocity_max = latest_set.workout_exercise.velocity_max
                else:
                    legacy_program = Program.objects.filter(
                        athlete=latest_set.athlete,
                        exercise=latest_set.exercise,
                    ).order_by("-id").first()
                    if legacy_program:
                        velocity_min = legacy_program.velocity_zone_min
                        velocity_max = legacy_program.velocity_zone_max
                latest_set_body.update({
                    "id": latest_set.id,
                    "athlete": {"id": latest_set.athlete_id, "name": latest_set.athlete.name},
                    "weight_lbs": latest_set.weight_lbs,
                    "started_at": latest_set.started_at,
                    "ended_at": latest_set.ended_at,
                    "is_false_set": latest_set.is_false_set,
                    "target_zone": {
                        "min": velocity_min,
                        "max": velocity_max,
                    } if velocity_min is not None and velocity_max is not None else None,
                    "reps": [{
                        "rep_number": rep.rep_number,
                        "timestamp": rep.timestamp,
                        "mean_velocity": rep.mean_velocity,
                        "peak_velocity": rep.peak_velocity,
                        "duration_ms": rep.duration_ms,
                        "velocity_color": rep.velocity_color if rep.velocity_color in {"green", "yellow", "red"} else "neutral",
                    } for rep in reps],
                    "reps_truncated": latest_set.reps.count() > MAX_DASHBOARD_REPS,
                    "measured_insights": _measured_set_insights(latest_set, reps, velocity_min, velocity_max),
                })

        rack_body = {
            "rack_number": rack_number,
            "status": status,
            "status_color": status_color,
            "latest_set": latest_set_body,
        }
        if include_details:
            selected_state = selections_by_rack.get(rack_number)
            selected_program = selected_state.active_program if selected_state else None
            selected_progress = progress_by_athlete.get(selected_state.selected_athlete_id) if selected_state else None
            rack_body.update({
                "screen_count": screen_counts.get(rack_number, 0),
                "nodes": [{
                    "node_id": node.node_id,
                    "mount_type": node.mount_type,
                    "battery_level": node.battery_level,
                    "signal_strength": node.signal_strength,
                    "last_seen": node.last_seen,
                    "is_active": node.is_active,
                    "is_stale": node.last_seen is None or node.last_seen < timezone.now() - timedelta(seconds=15),
                } for node in rack_nodes[:4]],
                "nodes_truncated": len(rack_nodes) > 4,
                "assignment_conflict": len(rack_nodes) > 1 or screen_counts.get(rack_number, 0) > 1,
                "selection": {
                    "athlete": {
                        "id": selected_program.athlete_id,
                        "name": selected_program.athlete.name,
                    },
                    "active_program": _program_body(selected_program),
                } if selected_program else None,
                "training": _coach_training_body(selected_progress),
            })
        racks.append(rack_body)

    leaderboard_sets = session_sets.none()
    if selected_exercise:
        leaderboard_sets = session_sets.filter(
            workout_exercise=selected_exercise,
            athlete_day_progress__isnull=False,
            ended_at__isnull=False,
            is_false_set=False,
            is_simulated=False,
        ).exclude(avg_velocity=None)
    leaders_query = (
        leaderboard_sets.values("athlete_id", "athlete__name")
        .annotate(best_avg_velocity=Max("avg_velocity"), athlete_name_sort=Lower("athlete__name"))
        .order_by("-best_avg_velocity", "athlete_name_sort", "athlete_id")
    )
    leaders = list(leaders_query[:MAX_DASHBOARD_LEADERS])
    leaderboard = [{
        "rank": index,
        "athlete": {
            **({"id": leader["athlete_id"]} if include_details else {}),
            "name": leader["athlete__name"],
        },
        "best_avg_velocity": leader["best_avg_velocity"],
    } for index, leader in enumerate(leaders, start=1)]

    room_insights = _room_insights(leaderboard_sets)
    snapshot = {
        "schema_version": 1,
        "revision": revision,
        "generated_at": timezone.now(),
        "session": {
            **({"id": active_session.id} if include_details else {}),
            "label": active_session.label,
            "started_at": active_session.started_at,
        } if active_session else None,
        "summary": {
            "participant_count": active_session.athletes.count() if active_session else 0,
            "athletes_with_sets": totals["athletes_with_sets"] or 0,
            "completed_sets": totals["completed_sets"] or 0,
            "completed_reps": totals["completed_reps"] or 0,
            "room_avg_velocity": round(totals["room_avg_velocity"], 3) if totals["room_avg_velocity"] is not None else None,
            "active_racks": sum(
                state.selected_athlete_id is not None
                and registration_counts.get(rack_number, 0) == 1
                for rack_number, state in selections_by_rack.items()
            ),
        },
        "racks": racks,
        "movement": ({
            **({"id": selected_exercise.id} if include_details else {}),
            "name": selected_exercise.exercise,
            "velocity_min": selected_exercise.velocity_min,
            "velocity_max": selected_exercise.velocity_max,
            "participant_count": movement_counts[selected_exercise.id],
        } if selected_exercise else None),
        "leaderboard": leaderboard,
        "insights": room_insights,
        "truncated": {
            "racks": len(all_rack_numbers) > MAX_DASHBOARD_RACKS,
            "leaderboard": leaderboard_sets.values("athlete_id").distinct().count() > MAX_DASHBOARD_LEADERS,
        },
    }
    if include_details:
        snapshot["participants"] = list(
            active_session.athletes.order_by("name", "id").values("id", "name")[:500]
        ) if active_session else []
        snapshot["meta"] = {
            "active_session_count": active_sessions.count(),
            "unassigned_session_sets": unassigned_session_sets,
        }
    return snapshot


def _room_insights(valid_sets):
    fastest_average = valid_sets.exclude(avg_velocity=None).select_related("athlete").order_by("-avg_velocity", "id").first()
    highest_peak = valid_sets.exclude(peak_velocity=None).select_related("athlete").order_by("-peak_velocity", "id").first()
    most_reps = (
        valid_sets.values("athlete__name")
        .annotate(total_reps=Sum("reps_completed"))
        .order_by("-total_reps", "athlete__name")
        .first()
    )
    insights = []
    if fastest_average:
        insights.append({
            "type": "fastest_set_average",
            "label": "Fastest set average",
            "athlete_name": fastest_average.athlete.name,
            "value": fastest_average.avg_velocity,
            "unit": "m/s",
        })
    if highest_peak:
        insights.append({
            "type": "highest_peak_velocity",
            "label": "Highest peak velocity",
            "athlete_name": highest_peak.athlete.name,
            "value": highest_peak.peak_velocity,
            "unit": "m/s",
        })
    if most_reps:
        insights.append({
            "type": "most_completed_reps",
            "label": "Most completed reps",
            "athlete_name": most_reps["athlete__name"],
            "value": most_reps["total_reps"],
            "unit": "reps",
        })
    return insights


def _measured_set_insights(workout_set, reps, velocity_min, velocity_max):
    velocities = [rep.mean_velocity for rep in reps]
    durations = [rep.duration_ms for rep in reps]
    first_velocity = velocities[0] if velocities else None
    last_velocity = velocities[-1] if velocities else None
    velocity_loss = first_velocity - last_velocity if velocities else None

    previous = (
        Set.objects.filter(
            athlete=workout_set.athlete,
            exercise=workout_set.exercise,
            ended_at__isnull=False,
            is_false_set=False,
        )
        .exclude(id=workout_set.id)
        .exclude(avg_velocity=None)
        .filter(
            Q(started_at__lt=workout_set.started_at)
            | Q(started_at=workout_set.started_at, id__lt=workout_set.id)
        )
        .order_by("-started_at", "-id")
        .first()
    )
    average_change = None
    average_change_percent = None
    if previous and workout_set.avg_velocity is not None:
        average_change = workout_set.avg_velocity - previous.avg_velocity
        if previous.avg_velocity:
            average_change_percent = average_change / previous.avg_velocity * 100

    below = inside = above = None
    if velocity_min is not None and velocity_max is not None:
        below = sum(value < velocity_min for value in velocities)
        inside = sum(velocity_min <= value <= velocity_max for value in velocities)
        above = sum(value > velocity_max for value in velocities)

    return {
        "first_rep_mean_velocity": first_velocity,
        "last_rep_mean_velocity": last_velocity,
        "velocity_loss": velocity_loss,
        "velocity_loss_percent": velocity_loss / first_velocity * 100 if first_velocity else None,
        "min_rep_velocity": min(velocities) if velocities else None,
        "max_rep_velocity": max(velocities) if velocities else None,
        "rep_velocity_range": max(velocities) - min(velocities) if velocities else None,
        "mean_rep_duration_ms": sum(durations) / len(durations) if durations else None,
        "reps_below_zone": below,
        "reps_in_zone": inside,
        "reps_above_zone": above,
        "previous_comparable_set_avg_velocity": previous.avg_velocity if previous else None,
        "avg_velocity_change": average_change,
        "avg_velocity_change_percent": average_change_percent,
    }


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([WallStateThrottle])
def wall_state(request):
    """Return scoreboard-safe room state for the shared wall display."""
    response = Response(_room_state_snapshot(include_details=False))
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    return response


@api_view(["GET"])
@permission_classes([IsCoach])
@throttle_classes([CoachRoomStateThrottle])
def room_state(request):
    """Return detailed room state for an authenticated coach."""
    response = Response(_room_state_snapshot(include_details=True))
    response["Cache-Control"] = "private, no-store"
    return response


@api_view(["PATCH"])
@permission_classes([IsCoach])
def node_detail(request, node_id):
    """Coach-only: reassign a node to a different rack (or update its fields)."""
    node = Node.objects.filter(node_id=node_id).first()
    if node is None:
        return Response({"error": "node not found"}, status=404)
    form = NodeSerializer(node, data=request.data, partial=True)
    form.is_valid(raise_exception=True)
    requested_rack = form.validated_data.get("rack_number", node.rack_number)
    for _attempt in range(3):
        observed_rack = Node.objects.filter(id=node.id).values_list("rack_number", flat=True).first()
        retry = False
        with transaction.atomic():
            for rack_number in sorted({
                rack for rack in (observed_rack, requested_rack) if rack is not None
            }):
                _lock_rack_number(rack_number)
            locked_node = Node.objects.select_for_update().get(id=node.id)
            if locked_node.rack_number != observed_rack:
                retry = True
            else:
                form = NodeSerializer(locked_node, data=request.data, partial=True)
                form.is_valid(raise_exception=True)
                node = form.save()
                return Response(NodeSerializer(node).data)
        if not retry:
            break
    return _rack_error(
        "node_reassignment_conflict",
        "Node rack assignment changed concurrently; retry the request.",
        409,
    )


# ─────────────────────────── athletes ───────────────────────────

@_private_no_store
@api_view(["GET", "POST"])
@permission_classes([IsCoach])
def athletes_view(request):
    """Coach-only: list all lifters or add a lifter."""
    if request.method == "GET":
        return Response(PublicAthleteSerializer(Athlete.objects.all()[:500], many=True).data)
    form = AthleteSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    return Response(AthleteSerializer(form.save()).data, status=201)


@api_view(["PATCH"])
@permission_classes([IsCoach])
def athlete_detail(request, athlete_id):
    """Coach-only: update a lifter's details."""
    athlete = Athlete.objects.filter(id=athlete_id).first()
    if athlete is None:
        return Response({"error": "athlete not found"}, status=404)
    if "notes" in request.data:
        return Response({"error": "Use the versioned notes endpoint."}, status=400)
    form = AthleteSerializer(athlete, data=request.data, partial=True)
    form.is_valid(raise_exception=True)
    return Response(AthleteSerializer(form.save()).data)


def _note_version(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@api_view(["GET", "PUT"])
@permission_classes([IsCoach])
def athlete_notes(request, athlete_id):
    """Read or safely replace the coach note without losing concurrent edits."""
    with transaction.atomic():
        athlete = Athlete.objects.select_for_update().filter(id=athlete_id).first()
        if athlete is None:
            return Response({"code": "athlete_not_found", "detail": "Athlete not found."}, status=404)
        current_version = _note_version(athlete.notes)
        if request.method == "PUT":
            text = request.data.get("text")
            expected_version = request.data.get("expected_version")
            if not isinstance(text, str) or len(text) > 65536 or not isinstance(expected_version, str):
                return Response({"code": "invalid_note", "detail": "Text and expected_version are required."}, status=400)
            if expected_version != current_version:
                response = Response({
                    "code": "note_conflict",
                    "detail": "The note changed after it was loaded.",
                    "current": {"text": athlete.notes, "version": current_version},
                }, status=409)
                response["Cache-Control"] = "private, no-store"
                return response
            athlete.notes = text
            athlete.save(update_fields=["notes"])
            current_version = _note_version(text)
    response = Response({"athlete_id": athlete.id, "text": athlete.notes, "version": current_version})
    response["Cache-Control"] = "private, no-store"
    return response


def _with_locked_athlete_workout_mutation(athlete_id, mutation):
    if not Athlete.objects.filter(id=athlete_id).exists():
        return _private_response({"code": "athlete_not_found", "detail": "Athlete not found."}, status=404)
    for _attempt in range(3):
        observed_racks = tuple(
            RackWorkoutState.objects.filter(selected_athlete_id=athlete_id)
            .order_by("rack_number")
            .values_list("rack_number", flat=True)
        )
        retry = False
        with transaction.atomic():
            for rack_number in observed_racks:
                _lock_rack_number(rack_number)
            athlete = Athlete.objects.select_for_update().filter(id=athlete_id).first()
            if athlete is None:
                return _private_response({"code": "athlete_not_found", "detail": "Athlete not found."}, status=404)
            states = list(
                RackWorkoutState.objects.select_for_update()
                .filter(selected_athlete_id=athlete_id)
                .order_by("rack_number")
            )
            locked_racks = tuple(state.rack_number for state in states)
            if locked_racks != observed_racks:
                retry = True
            elif AthleteDayProgress.objects.select_for_update().filter(
                athlete=athlete,
                session__ended_at=None,
            ).exists():
                return _private_response({
                    "code": "athlete_progress_active",
                    "detail": "Assignment and target changes are blocked after this athlete starts the active day.",
                }, status=409)
            elif locked_racks and Set.objects.select_for_update().filter(
                rack_number__in=locked_racks,
                ended_at=None,
            ).exists():
                return _private_response({
                    "code": "unfinished_set",
                    "detail": "A selected rack has an unfinished set.",
                }, status=409)
            else:
                return mutation(athlete, states)
        if not retry:
            break
    return _private_response({
        "code": "athlete_assignment_conflict",
        "detail": "Selected racks changed concurrently; retry the request.",
    }, status=409)


def _athlete_assignment_queryset():
    return AthleteWorkoutProgramAssignment.objects.select_related(
        "athlete",
        "workout_program",
    ).prefetch_related("workout_program__items__workout__exercises")


@_private_no_store
@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsCoach])
def athlete_workout_assignment(request, athlete_id):
    """Read, replace, or remove one athlete's complete workout program."""
    if request.method == "GET":
        if not Athlete.objects.filter(id=athlete_id).exists():
            return _private_response({"code": "athlete_not_found", "detail": "Athlete not found."}, status=404)
        assignment = _athlete_assignment_queryset().filter(athlete_id=athlete_id).first()
        if assignment is None:
            return _private_response({
                "code": "athlete_workout_assignment_not_found",
                "detail": "Athlete workout program assignment not found.",
            }, status=404)
        return _private_response(serialize_program_assignment(assignment))

    if request.method == "PUT":
        try:
            payload = request.data
        except ParseError:
            return _private_response({"code": "malformed_request", "detail": "Request body must be valid JSON."}, status=400)
        if not isinstance(payload, Mapping):
            return _private_response({"code": "malformed_request", "detail": "Request body must be an object."}, status=400)
        unknown = sorted(set(payload) - {"workout_program_id"})
        if unknown:
            return _private_response({
                "code": "unknown_fields",
                "detail": f"Unknown field(s): {', '.join(unknown)}.",
            }, status=400)
        workout_program_id, error = _positive_json_id(
            payload.get("workout_program_id"), "workout_program_id"
        )
        if error:
            return error

        def replace_assignment(athlete, _states):
            workout_program = (
                WorkoutProgram.objects.select_for_update()
                .prefetch_related("items__workout__exercises")
                .filter(id=workout_program_id)
                .first()
            )
            if workout_program is None:
                return _private_response({"code": "workout_program_not_found", "detail": "Workout program not found."}, status=404)
            items = list(workout_program.items.all())
            if not items or any(not list(item.workout.exercises.all()) for item in items):
                return _private_response({
                    "code": "workout_program_incomplete",
                    "detail": "Workout program must contain workouts with at least one exercise each.",
                }, status=409)
            assignment = AthleteWorkoutProgramAssignment.objects.select_for_update().filter(athlete=athlete).first()
            unchanged = bool(assignment and assignment.workout_program_id == workout_program.id)
            if assignment is None:
                assignment = AthleteWorkoutProgramAssignment(athlete=athlete)
            if not unchanged:
                assignment.workout_program = workout_program
                assignment.save()
                MonitoringEvent.objects.create(reason="athlete_assignment_changed")
            assignment = _athlete_assignment_queryset().get(id=assignment.id)
            return _private_response(serialize_program_assignment(assignment))

        return _with_locked_athlete_workout_mutation(athlete_id, replace_assignment)

    def remove_assignment(athlete, states):
        assignment = AthleteWorkoutProgramAssignment.objects.select_for_update().filter(athlete=athlete).first()
        if assignment is not None:
            assignment.delete()
            for state in states:
                state.selected_athlete = None
                state.save(update_fields=["selected_athlete", "updated_at"])
            MonitoringEvent.objects.create(reason="athlete_assignment_changed")
        return Response(status=204)

    return _with_locked_athlete_workout_mutation(athlete_id, remove_assignment)


def _validated_override_value(payload, field, errors):
    value = payload[field]
    if value is None:
        return None
    if field in {"sets", "reps"}:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            errors[field] = f"{field} must be a positive integer or null."
            return None
        if value > POSITIVE_INTEGER_MAX:
            errors[field] = f"{field} must be at most {POSITIVE_INTEGER_MAX}."
            return None
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        errors[field] = "weight_lbs must be a finite nonnegative number or null."
        return None
    return float(value)


@_private_no_store
@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsCoach])
def athlete_workout_exercise_override(request, athlete_id, exercise_id):
    """Read, sparsely update, or remove one athlete exercise override."""
    if request.method == "GET":
        override = AthleteWorkoutExerciseOverride.objects.filter(
            athlete_id=athlete_id,
            workout_exercise_id=exercise_id,
        ).first()
        if override is None:
            return _private_response({"code": "override_not_found", "detail": "Override not found."}, status=404)
        return _private_response(serialize_override(override))

    updates = None
    if request.method == "PATCH":
        try:
            payload = request.data
        except ParseError:
            return _private_response({"code": "malformed_request", "detail": "Request body must be valid JSON."}, status=400)
        if not isinstance(payload, Mapping) or not payload:
            return _private_response({"code": "malformed_request", "detail": "Request body must be a nonempty object."}, status=400)
        allowed = {"sets", "reps", "weight_lbs"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            return _private_response({
                "code": "unknown_fields",
                "detail": f"Unknown field(s): {', '.join(unknown)}.",
            }, status=400)
        errors = {}
        updates = {
            field: _validated_override_value(payload, field, errors)
            for field in payload
        }
        if errors:
            return _private_response({
                "code": "override_validation_failed",
                "detail": "Override data is invalid.",
                "errors": errors,
            }, status=400)

    def mutate_override(athlete, _states):
        exercise = (
            WorkoutExercise.objects.select_for_update()
            .select_related("workout")
            .filter(id=exercise_id)
            .first()
        )
        if exercise is None:
            return _private_response({"code": "workout_exercise_not_found", "detail": "Workout exercise not found."}, status=404)
        override = AthleteWorkoutExerciseOverride.objects.select_for_update().filter(
            athlete=athlete,
            workout_exercise=exercise,
        ).first()
        if request.method == "DELETE":
            if override:
                override.delete()
                MonitoringEvent.objects.create(reason="athlete_override_changed")
            return Response(status=204)

        assignment = _athlete_assignment_queryset().filter(athlete=athlete).first()
        if assignment is None:
            return _private_response({
                "code": "athlete_workout_assignment_required",
                "detail": "Athlete requires a workout assignment before overrides can be changed.",
            }, status=409)
        if not assignment.workout_program.items.filter(workout_id=exercise.workout_id).exists():
            return _private_response({
                "code": "exercise_not_in_athlete_workout",
                "detail": "Workout exercise is not in the athlete's assigned program.",
            }, status=409)
        if override is None:
            override = AthleteWorkoutExerciseOverride(
                athlete=athlete,
                workout_exercise=exercise,
            )
        for field, value in updates.items():
            setattr(override, field, value)
        if override.sets is None and override.reps is None and override.weight_lbs is None:
            return _private_response({
                "code": "empty_override",
                "detail": "At least one override value must be non-null.",
            }, status=400)
        override.save()
        MonitoringEvent.objects.create(reason="athlete_override_changed")
        return _private_response(serialize_override(override))

    return _with_locked_athlete_workout_mutation(athlete_id, mutate_override)


# ─────────────────────────── programs (training plans) ───────────────────────────

@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def programs_view(request):
    """GET: an athlete's training plans, ?athlete={id} to filter (open). POST:
    create a plan (coach only)."""
    if request.method == "GET":
        plans = Program.objects.all()
        athlete_id = request.query_params.get("athlete")
        if athlete_id is None and not _require_coach(request):
            return Response({"detail": "athlete query is required"}, status=400)
        if athlete_id is not None:
            plans = plans.filter(athlete_id=athlete_id)
        serializer = ProgramSerializer if _require_coach(request) else PublicProgramSerializer
        return Response(serializer(plans[:500], many=True).data)
    if not _require_coach(request):
        return Response({"detail": "coach login required"}, status=401)
    form = ProgramSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    return Response(ProgramSerializer(form.save()).data, status=201)


# ─────────────────────────── reusable workouts ───────────────────────────


class WorkoutPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


class ReportPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 20


def _private_response(body, status=200):
    response = Response(body, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _report_not_found():
    return _private_response({"code": "report_not_found", "detail": "Report not found."}, status=404)


def _unsupported_report_schema():
    return _private_response({
        "code": "unsupported_report_schema",
        "detail": "Report schema is not supported.",
    }, status=409)


def _pdf_error(code, detail, status):
    response = _private_response({"code": code, "detail": detail}, status=status)
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _pdf_response(detail, filename):
    try:
        content = render_report_pdf(detail)
    except PdfTooLarge:
        return _pdf_error("pdf_too_large", "Report PDF exceeds the output limit.", 409)
    except Exception:
        return _pdf_error("pdf_render_failed", "Report PDF could not be rendered.", 500)
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _paginate_reports(request, queryset, extractor):
    paginator = ReportPagination()
    try:
        page = paginator.paginate_queryset(queryset, request)
    except (NotFound, ValueError):
        return _private_response({"code": "invalid_page", "detail": "Requested page is invalid."}, status=404)
    try:
        results = [extractor(report) for report in page]
    except UnsupportedReportSchema:
        return _unsupported_report_schema()
    except AthleteNotInReport:
        return _report_not_found()
    response = paginator.get_paginated_response(results)
    response["Cache-Control"] = "private, no-store"
    return response


def _workout_validation_response(errors, *, preview=False):
    body = {
        "code": "workout_validation_failed",
        "detail": "Workout data is invalid.",
        "errors": errors,
    }
    if preview:
        body["valid"] = False
        body["workouts"] = []
    conflict_only = bool(errors) and all(error["code"] == "workout_name_conflict" for error in errors)
    return _private_response(body, status=409 if conflict_only else 400)


def _is_workout_name_conflict(error):
    cause = error.__cause__
    diagnostics = getattr(cause, "diag", None)
    return getattr(diagnostics, "constraint_name", None) == "workout_normalized_name_unique"


@_private_no_store
@api_view(["GET", "POST"])
@permission_classes([IsCoach])
def workouts_view(request):
    """List reusable workouts or atomically create one ordered workout."""
    if request.method == "GET":
        workouts = Workout.objects.prefetch_related("exercises").order_by("name", "id")
        paginator = WorkoutPagination()
        try:
            page = paginator.paginate_queryset(workouts, request)
        except (NotFound, ValueError):
            return _private_response({"code": "invalid_page", "detail": "Requested page is invalid."}, status=404)
        response = paginator.get_paginated_response([serialize_workout(workout) for workout in page])
        response["Cache-Control"] = "private, no-store"
        return response

    try:
        payload = request.data
    except ParseError:
        return _private_response({"code": "malformed_request", "detail": "Request body must be valid JSON."}, status=400)
    workouts, errors = validate_manual_workout(payload)
    if errors:
        return _workout_validation_response(errors)
    try:
        created = create_workouts(workouts)
    except IntegrityError as error:
        if not _is_workout_name_conflict(error):
            raise
        return _private_response({
            "code": "workout_name_conflict",
            "detail": "A workout with this normalized name already exists.",
        }, status=409)
    return _private_response(serialize_workout(created[0]), status=201)


def _uploaded_workout_file_response(request, *, create):
    workouts, errors = parse_workout_csv(request.FILES.get("file"))
    if not create:
        file_error_codes = {
            "file_required", "file_too_large", "empty_file", "invalid_encoding",
            "malformed_csv", "duplicate_headers", "missing_headers", "unknown_headers",
            "empty_csv", "row_limit_exceeded",
        }
        status = 400 if any(error["code"] in file_error_codes for error in errors) else 200
        return _private_response({
            "valid": not errors,
            "workouts": [preview_workout(workout) for workout in workouts],
            "errors": errors,
        }, status=status)
    if errors:
        return _workout_validation_response(errors)
    try:
        created = create_workouts(workouts)
    except IntegrityError as error:
        if not _is_workout_name_conflict(error):
            raise
        return _private_response({
            "code": "workout_name_conflict",
            "detail": "One or more workout names already exist.",
        }, status=409)
    return _private_response({
        "created": [serialize_workout(workout) for workout in created],
        "count": len(created),
    }, status=201)


@_private_no_store
@api_view(["POST"])
@permission_classes([IsCoach])
@parser_classes([MultiPartParser, FormParser])
def workout_import_preview(request):
    """Validate and normalize a bounded CSV upload without writing rows."""
    return _uploaded_workout_file_response(request, create=False)


@_private_no_store
@api_view(["POST"])
@permission_classes([IsCoach])
@parser_classes([MultiPartParser, FormParser])
def workout_import(request):
    """Revalidate and atomically create every workout in a bounded CSV upload."""
    return _uploaded_workout_file_response(request, create=True)


# ─────────────────────────── workout programs ───────────────────────────


def _workout_program_validation_response(errors):
    return _private_response({
        "code": "workout_program_validation_failed",
        "detail": "Workout program data is invalid.",
        "errors": errors,
    }, status=400)


def _is_workout_program_name_conflict(error):
    cause = error.__cause__
    diagnostics = getattr(cause, "diag", None)
    return getattr(diagnostics, "constraint_name", None) == "workout_program_normalized_name_unique"


@_private_no_store
@api_view(["GET", "POST"])
@permission_classes([IsCoach])
def workout_programs_view(request):
    """List workout programs or atomically create one ordered program."""
    if request.method == "GET":
        workout_programs = (
            WorkoutProgram.objects.prefetch_related("items__workout")
            .order_by("name", "id")
        )
        paginator = WorkoutPagination()
        try:
            page = paginator.paginate_queryset(workout_programs, request)
        except (NotFound, ValueError):
            return _private_response({"code": "invalid_page", "detail": "Requested page is invalid."}, status=404)
        response = paginator.get_paginated_response([
            serialize_workout_program(workout_program)
            for workout_program in page
        ])
        response["Cache-Control"] = "private, no-store"
        return response

    try:
        payload = request.data
    except ParseError:
        return _private_response({"code": "malformed_request", "detail": "Request body must be valid JSON."}, status=400)
    validated_program, errors = validate_workout_program(payload)
    if errors:
        return _workout_program_validation_response(errors)
    try:
        workout_program = create_workout_program(validated_program)
    except WorkoutProgramValidationError as error:
        return _workout_program_validation_response(error.errors)
    except WorkoutProgramNameConflict:
        return _private_response({
            "code": "workout_program_name_conflict",
            "detail": "A workout program with this normalized name already exists.",
        }, status=409)
    except IntegrityError as error:
        if not _is_workout_program_name_conflict(error):
            raise
        return _private_response({
            "code": "workout_program_name_conflict",
            "detail": "A workout program with this normalized name already exists.",
        }, status=409)
    workout_program = WorkoutProgram.objects.prefetch_related("items__workout").get(id=workout_program.id)
    return _private_response(serialize_workout_program(workout_program), status=201)


# ─────────────────────────── sessions ───────────────────────────

@api_view(["POST"])
@permission_classes([IsCoach])
def sessions_view(request):
    """Coach-only: start a training session."""
    form = SessionSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    try:
        session = start_training_day(dict(form.validated_data))
    except (ActiveTrainingDayConflict, IntegrityError):
        return _private_response({
            "code": "active_training_day_exists",
            "detail": "An active training day already exists.",
        }, status=409)
    except SessionAthleteLimitExceeded:
        return _private_response({
            "code": "session_athlete_limit",
            "detail": "Training day athlete limit exceeded.",
        }, status=400)
    return _private_response(SessionSerializer(session).data, status=201)


def _end_training_day_response(session_id):
    try:
        report, _created = end_training_day(session_id)
    except TrainingDaySessionNotFound:
        return _private_response({"code": "session_not_found", "detail": "Session not found."}, status=404)
    except SimulationEndRejected:
        return _private_response({
            "code": "simulation_end_rejected",
            "detail": "Simulation sessions cannot produce daily reports.",
        }, status=409)
    except SessionAlreadyEnded:
        return _private_response({
            "code": "session_already_ended",
            "detail": "Session already ended without a daily report.",
        }, status=409)
    except UnfinishedSetsConflict as error:
        return _private_response({
            "code": "unfinished_set",
            "detail": "Training day has unfinished sets.",
            "rack_numbers": error.rack_numbers,
            "unassigned_set_count": error.unassigned_set_count,
        }, status=409)
    except TrainingDayRaceConflict:
        return _private_response({
            "code": "session_end_conflict",
            "detail": "Rack associations changed concurrently; retry ending the session.",
        }, status=409)
    except ReportTooLarge as error:
        return _private_response({
            "code": "report_too_large",
            "detail": "Daily report exceeds Pi-safe limits.",
            "dimensions": error.dimensions,
        }, status=409)
    return _private_response(serialize_daily_report(report))


@_private_no_store
@api_view(["POST"])
@permission_classes([IsCoach])
def session_end(request, session_id):
    """Atomically end one real training day and return its immutable report."""
    return _end_training_day_response(session_id)


@api_view(["PATCH"])
@permission_classes([IsCoach])
def session_detail(request, session_id):
    """Coach-only: update a session and clear identities when it ends."""
    existing_session = Session.objects.filter(id=session_id).first()
    if existing_session is None:
        return Response({"error": "session not found"}, status=404)
    preview_form = SessionSerializer(existing_session, data=request.data, partial=True)
    preview_form.is_valid(raise_exception=True)
    requested_end = (
        "ended_at" not in request.data
        or preview_form.validated_data.get("ended_at") is not None
    )
    if requested_end:
        return _end_training_day_response(session_id)
    if not requested_end:
        with transaction.atomic():
            session = Session.objects.select_for_update().get(id=session_id)
            form = SessionSerializer(session, data=request.data, partial=True)
            form.is_valid(raise_exception=True)
            session = form.save()
        response = Response(SessionSerializer(session).data)
        response["Cache-Control"] = "private, no-store"
        return response


# ─────────────────────────── immutable reports ───────────────────────────

@_private_no_store
@api_view(["GET"])
@permission_classes([IsCoach])
def reports_view(request):
    reports = DailyReport.objects.order_by("-generated_at", "-id")
    return _paginate_reports(request, reports, report_list_item)


@_private_no_store
@api_view(["GET"])
@permission_classes([IsCoach])
def report_detail(request, report_id):
    report = DailyReport.objects.filter(id=report_id).first()
    if report is None:
        return _report_not_found()
    try:
        return _private_response(extract_report_detail(report))
    except UnsupportedReportSchema:
        return _unsupported_report_schema()


@_private_pdf
@api_view(["GET"])
@permission_classes([IsCoach])
@throttle_classes([ReportPdfThrottle])
def report_pdf(request, report_id):
    report = DailyReport.objects.filter(id=report_id).first()
    if report is None:
        return _pdf_error("report_not_found", "Report not found.", 404)
    try:
        detail = extract_report_detail(report)
    except UnsupportedReportSchema:
        return _pdf_error(
            "unsupported_report_schema", "Report schema is not supported.", 409,
        )
    return _pdf_response(detail, f"report-{report.id}.pdf")


@_private_no_store
@api_view(["GET"])
@permission_classes([IsCoach])
def athlete_reports(request, athlete_id):
    if not Athlete.objects.filter(id=athlete_id).exists():
        return _report_not_found()
    reports = reports_for_athlete(athlete_id).order_by("-generated_at", "-id")
    return _paginate_reports(
        request,
        reports,
        lambda report: athlete_report_list_item(report, athlete_id),
    )


@_private_no_store
@api_view(["GET"])
@permission_classes([IsCoach])
def athlete_report_detail(request, athlete_id, report_id):
    report = reports_for_athlete(athlete_id).filter(id=report_id).first()
    if report is None:
        return _report_not_found()
    try:
        return _private_response(extract_athlete_report_detail(report, athlete_id))
    except UnsupportedReportSchema:
        return _unsupported_report_schema()
    except AthleteNotInReport:
        return _report_not_found()


@_private_pdf
@api_view(["GET"])
@permission_classes([IsCoach])
@throttle_classes([ReportPdfThrottle])
def athlete_report_pdf(request, athlete_id, report_id):
    report = reports_for_athlete(athlete_id).filter(id=report_id).first()
    if report is None:
        return _pdf_error("report_not_found", "Report not found.", 404)
    try:
        detail = extract_athlete_report_detail(report, athlete_id)
    except UnsupportedReportSchema:
        return _pdf_error(
            "unsupported_report_schema", "Report schema is not supported.", 409,
        )
    except AthleteNotInReport:
        return _pdf_error("report_not_found", "Report not found.", 404)
    return _pdf_response(detail, f"athlete-{athlete_id}-report-{report.id}.pdf")


# ─────────────────────────── sets ───────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([RackWriteThrottle])
def rack_set_create(request, rack_number):
    """Start the signed-in athlete's current server-owned workout step."""
    try:
        payload = request.data
    except ParseError:
        return _rack_error("malformed_request", "Request body must be valid JSON.", 400)
    if not isinstance(payload, Mapping):
        return _rack_error("malformed_request", "Request body must be an object.", 400)
    unknown_fields = sorted(set(payload) - {"device_id"})
    if unknown_fields:
        return _rack_error(
            "unknown_fields",
            "Rack set start accepts only device_id; workout fields are server-owned.",
            400,
        )
    device_id = _canonical_device_id(payload.get("device_id"))
    if device_id is None:
        return _rack_error("invalid_device_id", "device_id must be a canonical UUID.", 400)
    if not _known_rack(rack_number):
        return _rack_error("rack_not_found", "Rack not found.", 404)

    observed_athlete_id = (
        RackWorkoutState.objects.filter(rack_number=rack_number)
        .values_list("selected_athlete_id", flat=True)
        .first()
    )
    try:
        with transaction.atomic():
            _lock_rack_number(rack_number)
            screens = list(
                RackScreen.objects.select_for_update()
                .filter(rack_number=rack_number)
                .order_by("device_id")[:2]
            )
            if len(screens) != 1:
                return _rack_error("rack_screen_conflict", "Rack must have exactly one assigned screen.", 409)
            if screens[0].device_id != device_id:
                return _rack_error("rack_screen_mismatch", "device_id is not assigned to this rack.", 403)

            session = (
                Session.objects.select_for_update()
                .filter(ended_at=None)
                .order_by("-started_at", "-id")
                .first()
            )
            if session is None:
                return _rack_error("no_active_session", "No active session.", 409)
            athlete = Athlete.objects.select_for_update().filter(id=observed_athlete_id).first()
            if athlete is None:
                return _rack_error("athlete_not_selected", "No athlete is signed into this rack.", 409)
            assignment = (
                AthleteWorkoutProgramAssignment.objects.select_for_update()
                .filter(athlete=athlete)
                .first()
            )
            if assignment is None:
                return _rack_error("athlete_program_required", "Athlete requires a complete workout program.", 409)
            progress = (
                AthleteDayProgress.objects.select_for_update(of=("self",))
                .select_related("current_program_item__workout", "current_workout_exercise")
                .filter(session=session, athlete=athlete)
                .first()
            )
            state = RackWorkoutState.objects.select_for_update().filter(rack_number=rack_number).first()
            if (
                state is None
                or state.active_session_id != session.id
                or state.selected_athlete_id != athlete.id
                or state.selected_athlete_id != observed_athlete_id
            ):
                return _rack_error("rack_identity_changed", "Rack identity changed; refresh and retry.", 409)
            if progress is None:
                return _rack_error("unexpected_workout_step", "Athlete progress is unavailable.", 409)
            if progress.status == AthleteDayProgress.COMPLETE:
                return _rack_error("program_complete", "Athlete has completed today's program.", 409)
            if progress.status != AthleteDayProgress.READY:
                return _rack_error("unfinished_set", "Athlete has an unfinished set.", 409)
            if (
                progress.workout_program_id != assignment.workout_program_id
                or progress.current_program_item.workout_program_id != progress.workout_program_id
                or progress.current_workout_exercise.workout_id != progress.current_program_item.workout_id
            ):
                return _rack_error("unexpected_workout_step", "Athlete progress does not match the assigned program.", 409)
            if Set.objects.select_for_update().filter(athlete_day_progress=progress, ended_at=None).exists():
                return _rack_error("unfinished_set", "Athlete has an unfinished set.", 409)

            nodes = list(Node.objects.select_for_update().filter(rack_number=rack_number).order_by("node_id")[:2])
            if len(nodes) != 1 or not nodes[0].is_active:
                return _rack_error("rack_node_unavailable", "Rack requires exactly one active sensor node.", 409)
            node = nodes[0]
            if node.is_simulated != session.is_simulated or athlete.is_simulated != session.is_simulated:
                return _rack_error("simulation_ownership_mismatch", "Rack execution ownership does not match the active session.", 409)
            if Set.objects.filter(session=session).count() >= MAX_SESSION_SETS:
                return _rack_error(
                    "session_set_limit",
                    f"Session may contain at most {MAX_SESSION_SETS} persisted sets.",
                    409,
                )
            override = AthleteWorkoutExerciseOverride.objects.filter(
                athlete=athlete,
                workout_exercise=progress.current_workout_exercise,
            ).first()
            weight_lbs = (
                override.weight_lbs
                if override and override.weight_lbs is not None
                else progress.current_workout_exercise.default_weight_lbs
            )
            new_set = Set.objects.create(
                session=session,
                athlete=athlete,
                node=node,
                rack_number=rack_number,
                exercise=progress.current_workout_exercise.exercise,
                set_number=progress.expected_set_number,
                weight_lbs=weight_lbs,
                is_simulated=session.is_simulated,
                athlete_day_progress=progress,
                workout_program_item=progress.current_program_item,
                workout_exercise=progress.current_workout_exercise,
            )
            progress.status = AthleteDayProgress.IN_SET
            progress.save(update_fields=["status", "updated_at"])
            MonitoringEvent.objects.create(reason="set_started", is_simulated=session.is_simulated)
    except IntegrityError:
        return _rack_error("unfinished_set", "Athlete has an unfinished set.", 409)
    return Response(SetSerializer(new_set).data, status=201)

@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([RackWriteThrottle])
def set_create(request):
    """Start a set: create the empty set record when an athlete begins, so the
    finish endpoint has something to fill in. Body: session, athlete, exercise,
    set_number, and optionally node + weight_lbs."""
    form = SetSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    node = form.validated_data.get("node")
    for _attempt in range(3):
        observed_rack = (
            Node.objects.filter(id=node.id).values_list("rack_number", flat=True).first()
            if node else None
        )
        retry = False
        with transaction.atomic():
            if observed_rack is not None:
                _lock_rack_number(observed_rack)
            locked_node = None
            if node:
                locked_node = Node.objects.select_for_update().filter(id=node.id).first()
                if locked_node is None:
                    return _rack_error("node_not_found", "Node not found.", 404)
                if locked_node.rack_number != observed_rack:
                    retry = True
            if not retry:
                locked_session = (
                    Session.objects.select_for_update()
                    .filter(id=form.validated_data["session"].id)
                    .first()
                )
                if locked_session is None:
                    return _rack_error("session_not_found", "Session not found.", 404)
                if locked_session.ended_at is not None:
                    return _rack_error("session_ended", "Session has already ended.", 409)
                if not locked_session.is_simulated:
                    return _rack_error(
                        "rack_bound_set_required",
                        "Real active sessions require the rack-bound set endpoint.",
                        409,
                    )
                if not locked_session.athletes.filter(
                    id=form.validated_data["athlete"].id,
                ).exists():
                    return _rack_error(
                        "athlete_not_in_session",
                        "Athlete is not in the submitted session.",
                        409,
                    )
                current_set_count = Set.objects.filter(session=locked_session).count()
                if current_set_count >= MAX_SESSION_SETS:
                    return _rack_error(
                        "session_set_limit",
                        f"Session may contain at most {MAX_SESSION_SETS} persisted sets.",
                        409,
                    )
                form.validated_data["session"] = locked_session
                if locked_node:
                    form.validated_data["node"] = locked_node
                new_set = form.save()
                return Response(SetSerializer(new_set).data, status=201)
        if not retry:
            break
    return _rack_error(
        "node_reassignment_conflict",
        "Node rack assignment changed concurrently; retry the request.",
        409,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([RackWriteThrottle])
def set_complete(request, set_id):
    """Save a finished set. Take all its reps + totals and write them to the
    database in ONE all-or-nothing step (if anything fails, nothing saves). This
    is the only code path that creates Rep rows. A false set saves zero reps.
    We also flag whether it was the athlete's best-ever velocity or weight."""
    if Set.objects.filter(id=set_id, athlete_day_progress__isnull=False).exists():
        return _rack_error(
            "rack_bound_set_required",
            "Athlete-driven sets require the rack-bound completion endpoint.",
            409,
        )
    form = SetCompleteSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    data = form.validated_data

    try:
        target_set, is_velocity_pr, is_weight_pr = complete_set(set_id, data)
    except SetNotFound:
        return Response({"error": "set not found"}, status=404)
    except SetAlreadyComplete:
        return Response({"error": "set is already complete"}, status=409)
    except SetSessionEnded:
        return _rack_error("session_ended", "Session has already ended.", 409)
    except UnexpectedWorkoutStep as error:
        return _private_response({
            "code": "unexpected_workout_step",
            "detail": "Set does not match the athlete's current workout step.",
            "progress": serialize_day_progress(error.progress) if error.progress else None,
        }, status=409)
    except SessionRepLimitExceeded as error:
        return _rack_error(
            "session_rep_limit",
            (
                f"Session may contain at most {MAX_SESSION_REPS} persisted reps "
                f"(current {error.current_reps}, submitted {error.submitted_reps})."
            ),
            409,
        )

    body = SetSerializer(target_set).data
    body["is_velocity_pr"] = is_velocity_pr
    body["is_weight_pr"] = is_weight_pr
    return Response(body)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([RackWriteThrottle])
def rack_set_complete(request, rack_number, set_id):
    """Complete an athlete-driven set from the sole screen assigned to its rack."""
    device_id = _canonical_device_id(request.headers.get("X-Rack-Device-Id"))
    if device_id is None:
        return _rack_error(
            "invalid_device_id",
            "X-Rack-Device-Id must be a canonical UUID.",
            400,
        )
    form = SetCompleteSerializer(data=request.data)
    form.is_valid(raise_exception=True)

    try:
        target_set, is_velocity_pr, is_weight_pr = complete_set(
            set_id,
            form.validated_data,
            rack_number=rack_number,
            device_id=device_id,
        )
    except SetNotFound:
        return _rack_error("set_not_found", "Set not found.", 404)
    except SetAlreadyComplete:
        return _rack_error("set_already_complete", "Set is already complete.", 409)
    except SetSessionEnded:
        return _rack_error("session_ended", "Session has already ended.", 409)
    except RackCompletionRejected as error:
        return _rack_error(error.code, error.detail, error.status)
    except UnexpectedWorkoutStep as error:
        return _private_response({
            "code": "unexpected_workout_step",
            "detail": "Set does not match the athlete's current workout step.",
            "progress": serialize_day_progress(error.progress) if error.progress else None,
        }, status=409)
    except SessionRepLimitExceeded as error:
        return _rack_error(
            "session_rep_limit",
            (
                f"Session may contain at most {MAX_SESSION_REPS} persisted reps "
                f"(current {error.current_reps}, submitted {error.submitted_reps})."
            ),
            409,
        )

    body = SetSerializer(target_set).data
    body["is_velocity_pr"] = is_velocity_pr
    body["is_weight_pr"] = is_weight_pr
    return Response(body)


# ─────────────────────────── analytics (coach) ───────────────────────────

@api_view(["GET"])
@permission_classes([IsCoach])
def analytics_session(request, session_id):
    """Coach-only: a quick summary of one session — how many sets and reps total,
    and each athlete's average velocity."""
    sets = Set.objects.filter(session_id=session_id, is_false_set=False, ended_at__isnull=False)
    totals = sets.aggregate(total_sets=Count("id"), total_reps=Sum("reps_completed"))
    rows = list(sets.values("athlete_id", "athlete__name").annotate(sets=Count("id"), avg_velocity=Avg("avg_velocity")).order_by("athlete__name")[:100])
    response = Response({
        "session_id": int(session_id),
        "total_sets": totals["total_sets"] or 0,
        "total_reps": totals["total_reps"] or 0,
        "athletes": [{"athlete":{"id":row["athlete_id"],"name":row["athlete__name"]},"sets":row["sets"],"avg_velocity":row["avg_velocity"]} for row in rows],
        "athletes_truncated": sets.values("athlete_id").distinct().count() > 100,
    })
    response["Cache-Control"] = "private, no-store"
    return response


@api_view(["GET"])
@permission_classes([IsCoach])
def analytics_athlete(request, athlete_id):
    """Return bounded set detail plus all-time measured context for one athlete."""
    athlete = Athlete.objects.filter(id=athlete_id).first()
    if athlete is None:
        return Response({"error": "athlete not found"}, status=404)
    valid_sets = Set.objects.filter(
        athlete=athlete, ended_at__isnull=False, is_false_set=False,
    )
    totals = valid_sets.aggregate(
        completed_sets=Count("id"), completed_reps=Sum("reps_completed"),
        mean_velocity=Avg("avg_velocity"), best_average=Max("avg_velocity"),
        highest_peak=Max("peak_velocity"), heaviest_weight=Max("weight_lbs"),
        first_set=Min("ended_at"), last_set=Max("ended_at"),
    )
    exercise_total = valid_sets.values("exercise").distinct().count()
    exercise_summaries = list(
        valid_sets.values("exercise").annotate(
            completed_sets=Count("id"), completed_reps=Sum("reps_completed"),
            mean_velocity=Avg("avg_velocity"), best_average=Max("avg_velocity"),
            highest_peak=Max("peak_velocity"), heaviest_weight=Max("weight_lbs"),
            last_performed_at=Max("ended_at"),
        ).order_by("exercise")[:50]
    )
    recent_sets = list(
        valid_sets.select_related("session").prefetch_related("reps")
        .order_by("-ended_at", "-id")[:50]
    )
    set_rows = []
    for workout_set in recent_sets:
        reps = list(workout_set.reps.all()[:100])
        velocities = [rep.mean_velocity for rep in reps]
        change = velocities[-1] - velocities[0] if velocities else None
        set_rows.append({
            "id": workout_set.id,
            "session": {"id": workout_set.session_id, "label": workout_set.session.label},
            "rack_number": workout_set.rack_number,
            "exercise": workout_set.exercise,
            "set_number": workout_set.set_number,
            "weight_lbs": workout_set.weight_lbs,
            "started_at": workout_set.started_at,
            "ended_at": workout_set.ended_at,
            "reps_completed": workout_set.reps_completed,
            "avg_velocity": workout_set.avg_velocity,
            "peak_velocity": workout_set.peak_velocity,
            "reps": [{
                "rep_number": rep.rep_number, "mean_velocity": rep.mean_velocity,
                "peak_velocity": rep.peak_velocity, "duration_ms": rep.duration_ms,
            } for rep in reps],
            "measured": {
                "first_to_last_change_mps": change,
                "first_to_last_change_percent": change / velocities[0] * 100 if velocities and velocities[0] else None,
                "min_rep_velocity": min(velocities) if velocities else None,
                "max_rep_velocity": max(velocities) if velocities else None,
                "velocity_range": max(velocities) - min(velocities) if velocities else None,
            },
            "reps_truncated": workout_set.reps.count() > 100,
        })
    response = Response({
        "schema_version": 1,
        "generated_at": timezone.now(),
        "athlete": {"id": athlete.id, "name": athlete.name, "created_at": athlete.created_at},
        "summary": {
            "completed_sets": totals["completed_sets"] or 0,
            "completed_reps": totals["completed_reps"] or 0,
            "mean_velocity": totals["mean_velocity"],
            "best_average": totals["best_average"],
            "highest_peak": totals["highest_peak"],
            "heaviest_weight": totals["heaviest_weight"],
            "first_set_at": totals["first_set"], "last_set_at": totals["last_set"],
        },
        "exercise_summaries": exercise_summaries,
        "sets": set_rows,
        "truncated": valid_sets.count() > 50,
        "exercise_summaries_truncated": exercise_total > 50,
    })
    response["Cache-Control"] = "private, no-store"
    return response
