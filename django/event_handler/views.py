



"""
views.py — the base station's HTTP endpoints (the handlers screens talk to).

Grouped by who uses them:

  TABLET (open — no login):
    - rack_register / rack_racknumber: a tablet says "here I am" and asks
      "which rack am I?"
    - prescriptions_view (GET): look up an athlete's resolved targets for today
      (weights + the speed zone used to color reps).
    - set_create: start a set (make an empty record).
    - set_complete: finish a set — save all its reps + totals in one
      all-or-nothing step. The ONLY place rep records are created.

  READS (open):
    - nodes_list / athletes_view (GET): list the sensors / the lifters.

  COACH-ONLY (needs a coach login):
    - manage athletes, programs, sessions, and nodes; assign racks; and pull
      the analytics summaries.

Open vs coach-only follows docs/reference/spec.md; shapes live in docs/reference/message-contract.md.
"""
import json
import base64
import hashlib
import hmac
import math
import re
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils.dateparse import parse_date
from django.db import IntegrityError, models, transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import (Node, RackScreen, Athlete, TrainingSession, Set, Rep, AthleteReferenceMax,
                     Exercise, RackCheckIn, DailyReport, TrainingGroup, TrainingBlock,
                     TrainingBlockWorkout, TrainingBlockExercise, TrainingProgram,
                     TrainingProgramWorkout, TrainingProgramExercise, SessionParticipation,
                     AthleteWorkoutExerciseOverride, BlockCategory, TrainingGroupCoach,
                     ScheduledSession, MonitoringEvent, RackRuntime, RackCommandReceipt)

# Coaches are Django users; there is no separate coach table. See docs/reference/spec.md.
User = get_user_model()
from .permissions import IsActiveStaff, IsCoach
from .serializers import (SetSerializer, SetCompleteSerializer, RackScreenSerializer,
                          AthleteSerializer, TrainingSessionSerializer,
                          NodeSerializer, ExerciseSerializer, TrainingGroupSerializer,
                          TrainingBlockSerializer, TrainingBlockWorkoutSerializer,
                          TrainingBlockExerciseSerializer, TrainingProgramSerializer,
                          BlockCategorySerializer, TrainingGroupCoachSerializer,
                          ScheduledSessionSerializer)
from .realtime.broadcast.publisher import publish_rack_state, publish_dashboard_state
from .services.active_session import active_session, open_sessions
from .services.athlete_analytics import athlete_analytics
from .services.room_state import room_state_snapshot
from .services.session_completion import end_session
from .services.reports import (AthleteNotInReport, reports_for_athlete, report_list_item,
                               report_detail, athlete_report_detail)
from .services.report_pdf import render_report_pdf, PdfTooLarge
from .services.plan_resolution import (movements_for_athlete as plan_movements_for_athlete,
                                       plans_by_athlete, resolve_target_weight)
from .services.planning import apply_order, instantiate_block, promote_program_to_block, touch_block
from .services.csv_import import SHEET_PLAN, commit_upload, validate_upload
from .services.tuning import RESTING_WINDOW
from .services.node_health import node_is_usable
from .services import ble_agent, nfc_agent

CONTROLLER_LEASE = timedelta(seconds=20)
CONTROLLER_COMMANDS_PER_SECOND = 10
COMMAND_RECEIPT_RETRY_WINDOW = timedelta(hours=1)
CONTROLLER_HEADERS = {
    "device_id": "X-Rack-Device-ID",
    "client_instance_id": "X-Client-Instance-ID",
    "controller_token": "X-Controller-Token",
    "controller_epoch": "X-Controller-Epoch",
}


def _canonical_controller_token(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{43}", value) is None:
        return False
    try:
        decoded = base64.urlsafe_b64decode(value + "=")
    except ValueError:
        return False
    return len(decoded) == 32 and base64.urlsafe_b64encode(decoded).decode().rstrip("=") == value


def _token_digest(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _runtime_has_open_set(runtime):
    return bool(runtime.current_set_id and runtime.current_set.ended_at is None)


def _runtime_snapshot(runtime, now=None, *, recovery_required=False):
    now = now or timezone.now()
    lease_active = bool(runtime.lease_expires_at and runtime.lease_expires_at > now)
    phase = RackRuntime.PHASE_RECOVERY_REQUIRED if recovery_required else runtime.phase
    return {
        "rack_number": runtime.rack_number,
        "controller_active": lease_active,
        "controller_epoch": runtime.controller_epoch,
        "lease_expires_at": runtime.lease_expires_at.isoformat() if runtime.lease_expires_at else None,
        "state_version": runtime.state_version,
        "phase": phase,
        "selected_athlete": (
            {"id": runtime.selected_athlete_id, "name": runtime.selected_athlete.name}
            if runtime.selected_athlete_id else None
        ),
        "selected_exercise": (
            {"id": runtime.selected_exercise_id, "name": runtime.selected_exercise.name}
            if runtime.selected_exercise_id else None
        ),
        "current_set": runtime.current_set_id,
        "rep_count": runtime.rep_count,
        "latest_mean_velocity": runtime.latest_mean_velocity,
        "latest_peak_velocity": runtime.latest_peak_velocity,
        "latest_color": runtime.latest_color or None,
        "phase_started_at": runtime.phase_started_at.isoformat() if runtime.phase_started_at else None,
        "updated_at": runtime.updated_at.isoformat() if runtime.updated_at else None,
        "server_time": now.isoformat(),
    }


def _controller_conflict(code, detail, runtime, now=None, *, recovery_required=False):
    return Response({
        "code": code,
        "detail": detail,
        "snapshot": _runtime_snapshot(runtime, now, recovery_required=recovery_required),
    }, status=409)


def _controller_identity(request):
    values = {key: request.headers.get(header) for key, header in CONTROLLER_HEADERS.items()}
    if not all(values.values()) or not _canonical_controller_token(values["controller_token"]):
        return None
    try:
        values["controller_epoch"] = int(values["controller_epoch"])
    except (TypeError, ValueError):
        return None
    return values


def _require_controller(request, runtime, now=None):
    now = now or timezone.now()
    identity = _controller_identity(request)
    if identity is None:
        return _controller_conflict(
            "rack_controller_required", "a valid rack controller capability is required", runtime, now,
        )
    token_matches = hmac.compare_digest(
        runtime.controller_token_digest, _token_digest(identity["controller_token"]),
    )
    holder_matches = bool(
        runtime.controller_screen_id
        and runtime.controller_screen.device_id == identity["device_id"]
        and runtime.controller_screen.rack_number == runtime.rack_number
        and runtime.client_instance_id == identity["client_instance_id"]
        and runtime.controller_epoch == identity["controller_epoch"]
        and token_matches
    )
    if not holder_matches:
        return _controller_conflict(
            "rack_controller_stale", "the controller capability is stale", runtime, now,
        )
    if not runtime.lease_expires_at or runtime.lease_expires_at <= now:
        recovery = _runtime_has_open_set(runtime)
        return _controller_conflict(
            "rack_recovery_required" if recovery else "rack_controller_stale",
            "the controller lease expired during an open set" if recovery else "the controller lease expired",
            runtime, now, recovery_required=recovery,
        )
    return None


def _command_identity(request):
    command_id = request.data.get("command_id")
    expected = request.data.get("expected_state_version")
    try:
        command_id = uuid.UUID(str(command_id))
        expected = int(expected)
    except (TypeError, ValueError, AttributeError):
        return None
    if isinstance(request.data.get("expected_state_version"), bool) or expected < 0:
        return None
    return command_id, expected


def _existing_receipt(request, runtime, command_id):
    receipt = RackCommandReceipt.objects.filter(runtime=runtime, command_id=command_id).first()
    if receipt is None:
        return None
    identity = _controller_identity(request)
    if (
        identity is None
        or identity["controller_epoch"] != receipt.controller_epoch
        or identity["device_id"] != receipt.controller_device_id
        or identity["client_instance_id"] != receipt.client_instance_id
        or not hmac.compare_digest(
            _token_digest(identity["controller_token"]), receipt.controller_token_digest,
        )
    ):
        return _controller_conflict(
            "rack_controller_stale", "the controller capability is stale", runtime,
        )
    if receipt.created_at <= timezone.now() - COMMAND_RECEIPT_RETRY_WINDOW:
        receipt.delete()
        return None
    return Response(receipt.response_body, status=receipt.response_status)


def _state_version_conflict(runtime, expected, now=None):
    if runtime.state_version == expected:
        return None
    return _controller_conflict(
        "rack_state_changed", "rack state changed; reconcile and retry", runtime, now,
    )


def _command_rate_limit(runtime, now=None):
    now = now or timezone.now()
    receipts = RackCommandReceipt.objects.filter(runtime=runtime)
    receipts.filter(created_at__lt=now - COMMAND_RECEIPT_RETRY_WINDOW).delete()
    if receipts.filter(created_at__gte=now - timedelta(seconds=1)).count() < CONTROLLER_COMMANDS_PER_SECOND:
        return None
    return Response({
        "code": "rack_command_rate_limited",
        "detail": "rack controller command rate exceeded",
        "retry_after_seconds": 1,
    }, status=429)


def _save_receipt(request, runtime, command_id, response_body, response_status):
    identity = _controller_identity(request)
    RackCommandReceipt.objects.create(
        runtime=runtime,
        command_id=command_id,
        controller_epoch=identity["controller_epoch"],
        controller_device_id=identity["device_id"],
        client_instance_id=identity["client_instance_id"],
        controller_token_digest=_token_digest(identity["controller_token"]),
        response_status=response_status,
        response_body=response_body,
    )

def _require_coach(request):
    """Small helper for endpoints that are open to read but coach-only to write:
    returns True if the caller is a logged-in coach."""
    return bool(request.user and request.user.is_authenticated)


# ─────────────────────────── tablet: racks ───────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
def rack_register(request):
    """A rack tablet announces itself. Make (or find) its RackScreen row by
    device_id; rack_number stays empty until a coach assigns it. Body: { device_id }."""
    device_id = request.data.get("device_id")
    if not device_id:
        return Response({"error": "device_id is required"}, status=400)
    screen, _ = RackScreen.objects.get_or_create(device_id=device_id)
    return Response({"device_id": screen.device_id, "rack_number": screen.rack_number})


@api_view(["POST"])
@permission_classes([AllowAny])
def node_register(request):
    """A sensor announces itself. Body: { node_id }.

    THE HOLE THIS FILLS. Until now nothing could create an MQTT sensor row. The
    seeder made exactly one, BLE sensors got theirs through verified enrollment, and
    a pulse from anything else was rejected with "node is not registered" — so a
    second simulated rack published into the void, and eight real ESP32s would have
    had to be typed into the database by hand.

    IT DELIBERATELY MIRRORS rack_register, a few lines above. A rack tablet already
    announces itself and waits for a coach to give it a rack number; sensors were the
    one device type without that story, and there was no reason for the asymmetry.

    Registering does NOT give a sensor a rack. It creates a row with rack_number
    empty, which shows up in the coach's list and does nothing until a coach links
    it. That is what keeps this safe to leave open: an unknown device on the gym
    network can make a row nobody has claimed, exactly as it can already make an
    unclaimed rack screen.

    Idempotent, because firmware will call it on every boot.
    """
    node_id = request.data.get("node_id")
    # Same shape the assignment endpoint enforces, so a node_id that registers is
    # always one that can later be assigned.
    if not isinstance(node_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", node_id) is None:
        return Response({
            "code": "invalid_node_id",
            "detail": "node_id may contain only letters, numbers, underscores, and hyphens",
        }, status=400)

    node, created = Node.objects.get_or_create(node_id=node_id)
    # Registering must never change an EXISTING sensor. A BLE node that was enrolled
    # by standing at the rack must not be able to re-register itself as something
    # else by sending one POST.
    return Response({
        "node_id": node.node_id,
        "rack_number": node.rack_number,
        "acquisition_kind": node.acquisition_kind,
        "created": created,
    }, status=201 if created else 200)


@api_view(["GET"])
@permission_classes([AllowAny])
def rack_racknumber(request):
    """A waiting tablet asks "which rack am I?" Returns its rack_number (empty
    until a coach assigns it). Query: ?device_id=..."""
    device_id = request.query_params.get("device_id")
    if not device_id:
        return Response({"error": "device_id is required"}, status=400)
    screen = RackScreen.objects.filter(device_id=device_id).first()
    return Response({"rack_number": screen.rack_number if screen else None})


@api_view(["GET"])
@permission_classes([IsCoach])
def racks_unassigned(request):
    """Coach-only: list every tablet still waiting for a rack (rack_number empty)."""
    waiting = RackScreen.objects.filter(rack_number__isnull=True)
    return Response(RackScreenSerializer(waiting, many=True).data)


@api_view(["PATCH"])
@permission_classes([IsActiveStaff])
def rack_assign(request, device_id):
    """Coach-only: give a waiting tablet its rack number, or release it.

    Body: { rack_number: 3 } to assign, { rack_number: null } to release.

    RELEASING IS THE FIX FOR A REAL DEADLOCK. Nothing used to clear this field, and
    the coach's "waiting tablets" list only shows screens whose rack is empty. So a
    tablet sent back to setup kept its old rack number, never reappeared in that
    list, and could not be reassigned — from the coach's side it had vanished.

    Clearing the browser's site data appeared to fix it, which sent people down the
    wrong path entirely: that works only because it throws away the tablet's stored
    identity, so it comes back as a device the server has never seen. You were not
    repairing the tablet, you were replacing it — and silently orphaning the old row.
    """
    # `in` rather than `.get()`, because null is now a MEANINGFUL value and .get()
    # cannot tell "release this tablet" from "you forgot the field".
    if "rack_number" not in request.data:
        return Response({"error": "rack_number is required"}, status=400)
    rack_number = request.data["rack_number"]
    if rack_number is not None:
        try:
            rack_number = int(rack_number)
        except (TypeError, ValueError):
            return Response({"error": "rack_number must be an integer or null"}, status=400)
    with transaction.atomic():
        screen = RackScreen.objects.select_for_update().filter(device_id=device_id).first()
        if screen is None:
            return Response({"error": "rack screen not found"}, status=404)
        affected_racks = {number for number in (screen.rack_number, rack_number) if number is not None}
        affected_nodes = Node.objects.select_for_update().filter(rack_number__in=affected_racks)
        if Set.objects.select_for_update().filter(node__in=affected_nodes, ended_at=None).exists():
            return Response({
                "code": "rack_assignment_has_open_set",
                "detail": "finish the open set before moving this rack screen",
            }, status=409)
        screen.rack_number = rack_number
        screen.save(update_fields=["rack_number"])
        # Tell the room. Screens refetch when told something changed, and moving a
        # tablet between racks is about as room-visible as a change gets — this was
        # missing, the same way starting a session was.
        MonitoringEvent.objects.create(reason="rack_state_changed")
    return Response(RackScreenSerializer(screen).data)


@api_view(["DELETE"])
@permission_classes([IsActiveStaff])
def rack_remove(request, rack_number):
    """Coach-only: FORCE-CLEAR a rack so a fresh screen can take it over.

    This is the escape hatch for a rack that is wedged — an open set nobody can
    finish because the screen that started it is gone, a controller lease stuck
    in recovery_required, a tablet that was reassigned while it still held the
    rack. The normal release (PATCH /api/racks/{device_id}/ with null) refuses
    while a set is open; this is the deliberate "kill the rack state" lever a
    coach pulls when the screen is physically unreachable.

    WHAT IT CLEARS, AND WHAT IT DOES NOT:
    - Ends any open set on the rack as a FALSE set (is_false_set, ended now).
      A set nobody finished is exactly a false set — it never happened.
    - Releases the rack's controller lease and resets the runtime to idle.
    - Releases any RackScreen from this rack back to the waiting list.
    - Does NOT unassign the node/sensor: the sensor is still bolted to this
      rack, so a new screen on this rack should keep using it.
    - Does NOT touch check-in history or completed sets.
    """
    with transaction.atomic():
        runtime = RackRuntime.objects.select_for_update().filter(rack_number=rack_number).first()
        # End open sets as false sets. PROTECT on Set.session means we never
        # delete; ending is the only legal way to close work, and false is the
        # honest label for work that was started and abandoned. A set is "on this
        # rack" when its node is assigned here — that's the physical truth, and
        # the sensor is what ties a set to a rack.
        open_sets = Set.objects.select_for_update().filter(
            ended_at=None,
            node__rack_number=rack_number,
        )
        for s in open_sets:
            s.ended_at = timezone.now()
            s.is_false_set = True
            s.reps_completed = 0
            s.avg_velocity = None
            s.peak_velocity = None
            s.save(update_fields=[
                "ended_at", "is_false_set", "reps_completed",
                "avg_velocity", "peak_velocity",
            ])
        if runtime is not None:
            runtime.controller_screen = None
            runtime.client_instance_id = ""
            runtime.controller_token_digest = ""
            runtime.controller_epoch += 1
            runtime.lease_expires_at = None
            runtime.phase = RackRuntime.PHASE_IDLE
            runtime.selected_athlete = None
            runtime.selected_exercise = None
            runtime.current_set = None
            runtime.rep_count = 0
            runtime.latest_mean_velocity = None
            runtime.latest_peak_velocity = None
            runtime.latest_color = ""
            runtime.phase_started_at = None
            runtime.state_version += 1
            runtime.save()
            # Stale command receipts for the old controller are dead weight now.
            runtime.command_receipts.all().delete()
        RackScreen.objects.filter(rack_number=rack_number).update(rack_number=None)
        MonitoringEvent.objects.create(reason="rack_state_changed")
    return Response({"rack_number": rack_number, "cleared": True})


@api_view(["PUT"])
@permission_classes([IsActiveStaff])
def rack_node_assignment(request):
    """Select this physical rack's registered node. Body: {device_id, node_id}."""
    allowed_fields = {"device_id", "node_id"}
    if set(request.data) != allowed_fields:
        return Response({
            "code": "invalid_assignment_request",
            "detail": "exactly device_id and node_id are required",
        }, status=400)

    device_id = request.data.get("device_id")
    node_id = request.data.get("node_id")
    if not isinstance(device_id, str) or not device_id.strip():
        return Response({"code": "invalid_device_id", "detail": "device_id must be a non-empty string"}, status=400)
    if not isinstance(node_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", node_id) is None:
        return Response({
            "code": "invalid_node_id",
            "detail": "node_id may contain only letters, numbers, underscores, and hyphens",
        }, status=400)

    try:
        return _assign_node_to_rack(device_id, node_id)
    except IntegrityError:
        return Response({
            "code": "node_assignment_conflict",
            "detail": "another sensor assignment changed this rack; refresh and try again",
        }, status=409)


@transaction.atomic
def _assign_node_to_rack(device_id, node_id):
    screen = RackScreen.objects.select_for_update().filter(device_id=device_id).first()
    if screen is None:
        return Response({"code": "rack_screen_not_found", "detail": "rack screen not found"}, status=404)
    if screen.rack_number is None:
        return Response({"code": "rack_screen_unassigned", "detail": "rack screen has no rack number"}, status=409)

    assigned_nodes = list(
        Node.objects.select_for_update()
        .filter(models.Q(node_id=node_id) | models.Q(rack_number=screen.rack_number))
        .order_by("id")
    )
    selected = next((node for node in assigned_nodes if node.node_id == node_id), None)
    if selected is None:
        return Response({"code": "node_not_found", "detail": "node not found"}, status=404)
    if not selected.is_active:
        return Response({"code": "node_inactive", "detail": "inactive nodes cannot be assigned"}, status=409)
    if selected.is_simulated:
        return Response({"code": "simulated_node", "detail": "simulated nodes cannot be assigned to a physical rack"}, status=409)
    if selected.acquisition_kind == Node.ACQUISITION_WT901_BLE and selected.rack_number is None:
        return Response({
            "code": "wt901_verification_required",
            "detail": "unassigned WT901 nodes must be selected through verified BLE enrollment",
        }, status=409)
    if not node_is_usable(selected):
        return Response({
            "code": "wt901_node_stale",
            "detail": "WT901 BLE nodes require a pulse within the last 2 seconds",
        }, status=409)
    if selected.rack_number not in (None, screen.rack_number):
        return Response({
            "code": "node_assigned_elsewhere",
            "detail": f"node is already assigned to rack {selected.rack_number}",
        }, status=409)

    replaced = next(
        (node for node in assigned_nodes if node.rack_number == screen.rack_number and node.pk != selected.pk),
        None,
    )
    affected_nodes = [node for node in (selected, replaced) if node is not None]
    if Set.objects.select_for_update().filter(node__in=affected_nodes, ended_at=None).exists():
        return Response({
            "code": "node_assignment_has_open_set",
            "detail": "finish the open set before changing this sensor assignment",
        }, status=409)

    if selected.rack_number == screen.rack_number:
        return Response({"rack_number": screen.rack_number, "node": NodeSerializer(selected).data})

    if replaced is not None:
        replaced.rack_number = None
        replaced.save(update_fields=["rack_number"])
    selected.rack_number = screen.rack_number
    selected.save(update_fields=["rack_number"])
    MonitoringEvent.objects.create(reason="node_assignment_changed")

    return Response({"rack_number": screen.rack_number, "node": NodeSerializer(selected).data})


def _ble_error_response(exc):
    if isinstance(exc, ble_agent.BLEAgentConflict):
        return Response({"code": exc.code, "detail": exc.detail}, status=409)
    return Response({
        "code": "ble_agent_unavailable", "detail": "BLE Agent is unavailable",
    }, status=503)


def _nonempty_bounded_string(value, maximum=255):
    return isinstance(value, str) and 0 < len(value) <= maximum and value == value.strip()


@api_view(["POST"])
@permission_classes([IsActiveStaff])
def ble_scans(request):
    if request.data not in ({}, None):
        return Response({
            "code": "invalid_ble_scan_request", "detail": "request body must be empty",
        }, status=400)
    try:
        result = ble_agent.scan()
    except (ble_agent.BLEAgentConflict, ble_agent.BLEAgentUnavailable) as exc:
        return _ble_error_response(exc)
    devices = result.get("devices") if isinstance(result, dict) else None
    if not isinstance(devices, list) or len(devices) > 100:
        return _ble_error_response(ble_agent.BLEAgentUnavailable())
    safe_devices = []
    for device in devices:
        if (
            not isinstance(device, dict)
            or not _nonempty_bounded_string(device.get("handle"))
            or not _nonempty_bounded_string(device.get("label"))
        ):
            return _ble_error_response(ble_agent.BLEAgentUnavailable())
        safe_devices.append({
            "device_handle": device["handle"], "label": device["label"],
        })
    return Response({"devices": safe_devices})


@api_view(["POST"])
@permission_classes([IsActiveStaff])
def ble_verifications(request):
    if set(request.data) != {"device_handle"} or not _nonempty_bounded_string(
        request.data.get("device_handle"),
    ):
        return Response({
            "code": "invalid_ble_verification_request",
            "detail": "exactly one non-empty device_handle is required",
        }, status=400)
    try:
        result = ble_agent.verify(request.data["device_handle"])
    except (ble_agent.BLEAgentConflict, ble_agent.BLEAgentUnavailable) as exc:
        return _ble_error_response(exc)
    required = {"label", "verification_token", "movement_g"}
    if (
        not isinstance(result, dict)
        or not required.issubset(result)
        or not _nonempty_bounded_string(result.get("label"))
        or not _nonempty_bounded_string(result.get("verification_token"), 512)
        or not isinstance(result.get("movement_g"), (int, float))
        or isinstance(result.get("movement_g"), bool)
        or not math.isfinite(result["movement_g"])
        or not 0 <= result["movement_g"] <= 16
    ):
        return _ble_error_response(ble_agent.BLEAgentUnavailable())
    return Response({key: result[key] for key in required} | {"verified": True})


@api_view(["PUT"])
@permission_classes([IsActiveStaff])
def rack_ble_selection(request, rack_number):
    if set(request.data) != {"device_id", "verification_token"} or not all((
        _nonempty_bounded_string(request.data.get("device_id")),
        _nonempty_bounded_string(request.data.get("verification_token"), 512),
    )):
        return Response({
            "code": "invalid_ble_selection_request",
            "detail": "exactly device_id and verification_token are required",
        }, status=400)
    preflight = _preflight_ble_binding(
        rack_number, request.data["device_id"],
    )
    if isinstance(preflight, Response):
        return preflight
    expected_node_id, expected_agent_node_id = preflight

    try:
        binding = ble_agent.bind(
            request.data["verification_token"], rack_number, expected_agent_node_id,
        )
    except (ble_agent.BLEAgentConflict, ble_agent.BLEAgentUnavailable) as exc:
        return _ble_error_response(exc)

    if (
        not isinstance(binding, dict)
        or not _nonempty_bounded_string(binding.get("node_id"), 64)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", binding["node_id"]) is None
        or not _nonempty_bounded_string(binding.get("label"))
        or not _nonempty_bounded_string(binding.get("binding_token"), 512)
    ):
        return _ble_error_response(ble_agent.BLEAgentUnavailable())

    binding_token = binding["binding_token"]
    try:
        response = _apply_ble_binding(
            rack_number, request.data["device_id"], binding["node_id"], expected_node_id,
        )
    except IntegrityError:
        rollback_error = _rollback_ble_binding(binding_token)
        if rollback_error:
            return rollback_error
        return Response({
            "code": "node_assignment_conflict",
            "detail": "another sensor assignment changed this rack; refresh and try again",
        }, status=409)
    except Exception:
        rollback_error = _rollback_ble_binding(binding_token)
        if rollback_error:
            return rollback_error
        raise
    if response.status_code >= 400:
        rollback_error = _rollback_ble_binding(binding_token)
        if rollback_error:
            return rollback_error
        return response
    response.data["label"] = binding["label"]
    return response


@transaction.atomic
def _preflight_ble_binding(rack_number, device_id):
    screen = RackScreen.objects.select_for_update().filter(
        device_id=device_id, rack_number=rack_number,
    ).first()
    if screen is None:
        return Response({
            "code": "rack_screen_not_found", "detail": "assigned rack screen not found",
        }, status=404)
    current = Node.objects.select_for_update().filter(rack_number=rack_number).first()
    if current is not None and Set.objects.select_for_update().filter(
        node=current, ended_at=None,
    ).exists():
        return Response({
            "code": "node_assignment_has_open_set",
            "detail": "finish the open set before changing this sensor assignment",
        }, status=409)
    expected_node_id = current.node_id if current is not None else None
    expected_agent_node_id = (
        current.node_id
        if current is not None and current.acquisition_kind == Node.ACQUISITION_WT901_BLE
        else None
    )
    return expected_node_id, expected_agent_node_id


def _rollback_ble_binding(binding_token):
    try:
        ble_agent.rollback(binding_token)
    except (ble_agent.BLEAgentConflict, ble_agent.BLEAgentUnavailable):
        MonitoringEvent.objects.create(reason="ble_reconciliation_required")
        return Response({
            "code": "ble_reconciliation_required",
            "detail": "BLE binding rollback failed; reconcile this rack before retrying",
        }, status=503)
    return None


@transaction.atomic
def _apply_ble_binding(rack_number, device_id, node_id, expected_node_id):
    screen = RackScreen.objects.select_for_update().filter(
        device_id=device_id, rack_number=rack_number,
    ).first()
    if screen is None:
        return Response({"code": "rack_screen_not_found", "detail": "assigned rack screen not found"}, status=404)
    nodes = list(
        Node.objects.select_for_update()
        .filter(models.Q(node_id=node_id) | models.Q(rack_number=rack_number))
        .order_by("id")
    )
    selected = next((node for node in nodes if node.node_id == node_id), None)
    current = next((node for node in nodes if node.rack_number == rack_number), None)
    if (current.node_id if current is not None else None) != expected_node_id:
        return Response({
            "code": "binding_reconciliation_required",
            "detail": "rack sensor assignment changed during BLE binding",
        }, status=409)
    if selected is not None and selected.acquisition_kind != Node.ACQUISITION_WT901_BLE:
        return Response({
            "code": "node_identity_conflict", "detail": "logical node identity is already in use",
        }, status=409)
    if selected is not None and (not selected.is_active or selected.is_simulated):
        return Response({"code": "node_unavailable", "detail": "sensor node is unavailable"}, status=409)
    if selected is not None and selected.rack_number not in (None, rack_number):
        return Response({
            "code": "node_assigned_elsewhere", "detail": "sensor is already assigned to another rack",
        }, status=409)
    replaced = next(
        (
            node for node in nodes
            if node.rack_number == rack_number and (selected is None or node.pk != selected.pk)
        ),
        None,
    )
    affected = [node for node in (selected, replaced) if node is not None]
    if Set.objects.select_for_update().filter(node__in=affected, ended_at=None).exists():
        return Response({
            "code": "node_assignment_has_open_set",
            "detail": "finish the open set before changing this sensor assignment",
        }, status=409)
    if selected is None:
        selected = Node.objects.create(
            node_id=node_id, acquisition_kind=Node.ACQUISITION_WT901_BLE,
        )
    if selected.rack_number == rack_number:
        return Response({"rack_number": rack_number, "node": NodeSerializer(selected).data})
    if replaced is not None:
        replaced.rack_number = None
        replaced.save(update_fields=["rack_number"])
    selected.rack_number = rack_number
    selected.save(update_fields=["rack_number"])
    MonitoringEvent.objects.create(reason="node_assignment_changed")
    return Response({"rack_number": rack_number, "node": NodeSerializer(selected).data})


@api_view(["GET"])
@permission_classes([AllowAny])
def rack_sensor_health(request, rack_number):
    device_id = request.headers.get("X-Rack-Device-ID")
    if request.query_params or not _nonempty_bounded_string(device_id):
        return Response({
            "code": "invalid_sensor_health_request",
            "detail": "X-Rack-Device-ID header is required and query parameters are not allowed",
        }, status=400)
    if not RackScreen.objects.filter(
        device_id=device_id, rack_number=rack_number,
    ).exists():
        return Response({
            "code": "rack_screen_not_assigned", "detail": "screen is not assigned to this rack",
        }, status=403)
    node = Node.objects.filter(
        rack_number=rack_number, acquisition_kind=Node.ACQUISITION_WT901_BLE,
    ).first()
    if node is None:
        return Response({"code": "sensor_not_found", "detail": "rack BLE sensor not found"}, status=404)
    try:
        health = ble_agent.health(rack_number)
    except (ble_agent.BLEAgentConflict, ble_agent.BLEAgentUnavailable) as exc:
        return _ble_error_response(exc)
    allowed = {"state", "sample_age_ms", "movement_g", "label"}
    if (
        not isinstance(health, dict)
        or not allowed.issubset(health)
        or health["state"] not in {"bound", "live", "stale", "reconnecting"}
        or (
            health["sample_age_ms"] is not None
            and (
                not isinstance(health["sample_age_ms"], int)
                or isinstance(health["sample_age_ms"], bool)
                or health["sample_age_ms"] < 0
            )
        )
        or (
            health["movement_g"] is not None
            and (
                not isinstance(health["movement_g"], (int, float))
                or isinstance(health["movement_g"], bool)
                or not math.isfinite(health["movement_g"])
                or not 0 <= health["movement_g"] <= 16
            )
        )
        or not _nonempty_bounded_string(health["label"])
        or health.get("node_id") != node.node_id
    ):
        return _ble_error_response(ble_agent.BLEAgentUnavailable())
    if health["state"] == "live":
        observed_at = timezone.now() - timedelta(milliseconds=health["sample_age_ms"] or 0)
        Node.objects.filter(pk=node.pk).update(last_seen=observed_at)
    return Response({"node_id": node.node_id, **{key: health[key] for key in allowed}})


@api_view(["GET", "PATCH"])
@permission_classes([AllowAny])
def rack_state(request, rack_number):
    """Read the authoritative rack mirror or apply one fenced state transition."""
    if request.method == "GET":
        runtime = RackRuntime.objects.select_related(
            "selected_athlete", "selected_exercise", "current_set",
        ).filter(rack_number=rack_number).first()
        if runtime is None:
            known_rack = (
                Node.objects.filter(rack_number=rack_number).exists()
                or RackScreen.objects.filter(rack_number=rack_number).exists()
            )
            if not known_rack:
                return Response({"code": "rack_not_found", "detail": "rack not found"}, status=404)
            runtime = RackRuntime.objects.create(rack_number=rack_number)
        recovery = bool(
            runtime.lease_expires_at
            and runtime.lease_expires_at <= timezone.now()
            and _runtime_has_open_set(runtime)
        )
        return Response(_runtime_snapshot(runtime, recovery_required=recovery))

    allowed = {
        "expected_state_version", "command_id", "phase", "selected_athlete",
        "selected_exercise", "rep_count", "latest_mean_velocity",
        "latest_peak_velocity", "latest_color",
    }
    visible_fields = allowed - {"expected_state_version", "command_id"}
    if not set(request.data).issubset(allowed) or not set(request.data).intersection(visible_fields):
        return Response({
            "code": "invalid_rack_state", "detail": "provide only supported rack state fields",
        }, status=400)
    command = _command_identity(request)
    if command is None:
        return Response({
            "code": "invalid_controller_command",
            "detail": "command_id and expected_state_version are required",
        }, status=400)
    command_id, expected = command

    with transaction.atomic():
        locked_node = Node.objects.select_for_update().filter(rack_number=rack_number).first()
        runtime = RackRuntime.objects.select_for_update().filter(rack_number=rack_number).first()
        if runtime is None:
            return Response({"code": "rack_not_found", "detail": "rack not found"}, status=404)
        conflict = _require_controller(request, runtime)
        if conflict:
            return conflict
        receipt = _existing_receipt(request, runtime, command_id)
        if receipt:
            return receipt
        limited = _command_rate_limit(runtime)
        if limited:
            return limited
        conflict = _state_version_conflict(runtime, expected)
        if conflict:
            return conflict

        phase = request.data.get("phase", runtime.phase)
        transitions = {
            RackRuntime.PHASE_IDLE: {RackRuntime.PHASE_IDLE, RackRuntime.PHASE_COUNTDOWN},
            RackRuntime.PHASE_COUNTDOWN: {
                RackRuntime.PHASE_COUNTDOWN, RackRuntime.PHASE_ACTIVE, RackRuntime.PHASE_IDLE,
            },
            RackRuntime.PHASE_ACTIVE: {
                RackRuntime.PHASE_ACTIVE, RackRuntime.PHASE_SUMMARY,
                RackRuntime.PHASE_RECOVERY_REQUIRED,
            },
            RackRuntime.PHASE_SUMMARY: {
                RackRuntime.PHASE_SUMMARY, RackRuntime.PHASE_REST, RackRuntime.PHASE_IDLE,
            },
            RackRuntime.PHASE_REST: {
                RackRuntime.PHASE_REST, RackRuntime.PHASE_IDLE, RackRuntime.PHASE_COUNTDOWN,
            },
            RackRuntime.PHASE_RECOVERY_REQUIRED: {
                RackRuntime.PHASE_RECOVERY_REQUIRED, RackRuntime.PHASE_IDLE,
            },
        }
        if phase not in transitions.get(runtime.phase, set()):
            return Response({
                "code": "invalid_phase_transition",
                "detail": f"cannot transition from {runtime.phase} to {phase}",
            }, status=409)

        athlete = runtime.selected_athlete
        if "selected_athlete" in request.data:
            athlete_id = request.data["selected_athlete"]
            athlete = None if athlete_id is None else Athlete.objects.filter(id=athlete_id).first()
            if athlete_id is not None and athlete is None:
                return Response({"code": "athlete_not_found", "detail": "athlete not found"}, status=404)
            session = _active_session()
            if athlete is not None and (session is None or not session.athletes.filter(id=athlete.id).exists()):
                return Response({
                    "code": "athlete_not_in_active_session",
                    "detail": "athlete is not in the active session",
                }, status=409)
        exercise = runtime.selected_exercise
        if "selected_exercise" in request.data:
            exercise_id = request.data["selected_exercise"]
            exercise = None if exercise_id is None else Exercise.objects.filter(id=exercise_id).first()
            if exercise_id is not None and exercise is None:
                return Response({"code": "exercise_not_found", "detail": "exercise not found"}, status=404)

        rep_count = request.data.get("rep_count", runtime.rep_count)
        try:
            rep_count = int(rep_count)
        except (TypeError, ValueError):
            rep_count = -1
        if isinstance(request.data.get("rep_count"), bool) or rep_count < 0:
            return Response({"code": "invalid_rep_count", "detail": "rep_count must be non-negative"}, status=400)
        metrics = {}
        for field in ("latest_mean_velocity", "latest_peak_velocity"):
            value = request.data.get(field, getattr(runtime, field))
            if value is not None:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    value = -1
                if not math.isfinite(value) or value < 0:
                    return Response({"code": "invalid_velocity", "detail": f"{field} must be finite and non-negative"}, status=400)
            metrics[field] = value
        color = request.data.get("latest_color", runtime.latest_color)
        if color not in ("", None, "green", "yellow", "red", "neutral"):
            return Response({"code": "invalid_velocity_color", "detail": "latest_color is invalid"}, status=400)

        requires_usable_node = (
            (phase != runtime.phase and phase in {
                RackRuntime.PHASE_COUNTDOWN, RackRuntime.PHASE_ACTIVE,
            })
            or bool(set(request.data).intersection({
                "rep_count", "latest_mean_velocity", "latest_peak_velocity", "latest_color",
            }))
        )
        if requires_usable_node and (locked_node is None or not node_is_usable(locked_node)):
            return _controller_conflict(
                "rack_sensor_required", "rack state update requires a usable assigned sensor", runtime,
            )

        if (
            phase == runtime.phase
            and (athlete.id if athlete else None) == runtime.selected_athlete_id
            and (exercise.id if exercise else None) == runtime.selected_exercise_id
            and rep_count == runtime.rep_count
            and metrics["latest_mean_velocity"] == runtime.latest_mean_velocity
            and metrics["latest_peak_velocity"] == runtime.latest_peak_velocity
            and (color or "") == runtime.latest_color
        ):
            return _controller_conflict(
                "rack_state_unchanged", "rack state command made no visible change", runtime,
            )

        now = timezone.now()
        if phase != runtime.phase:
            runtime.phase_started_at = now
        runtime.phase = phase
        runtime.selected_athlete = athlete
        runtime.selected_exercise = exercise
        runtime.rep_count = rep_count
        runtime.latest_mean_velocity = metrics["latest_mean_velocity"]
        runtime.latest_peak_velocity = metrics["latest_peak_velocity"]
        runtime.latest_color = color or ""
        runtime.state_version += 1
        runtime.save()
        MonitoringEvent.objects.create(reason="rack_state_changed")
        body = _runtime_snapshot(runtime, now)
        _save_receipt(request, runtime, command_id, body, 200)
    return Response(body)


@api_view(["POST"])
@permission_classes([AllowAny])
def rack_controller_acquire(request, rack_number):
    """Claim or renew ownership after validating the physical rack identity."""
    required = {"device_id", "client_instance_id", "controller_token"}
    if set(request.data) != required:
        return Response({
            "code": "invalid_controller_claim",
            "detail": "exactly device_id, client_instance_id, and controller_token are required",
        }, status=400)
    device_id = request.data.get("device_id")
    client_instance_id = request.data.get("client_instance_id")
    token = request.data.get("controller_token")
    if (
        not isinstance(device_id, str) or not device_id or len(device_id) > 255
        or not isinstance(client_instance_id, str) or not client_instance_id or len(client_instance_id) > 255
        or not _canonical_controller_token(token)
    ):
        return Response({
            "code": "invalid_controller_claim", "detail": "controller claim fields are invalid",
        }, status=400)

    with transaction.atomic():
        screen = RackScreen.objects.select_for_update().filter(device_id=device_id).first()
        if screen is None or screen.rack_number != rack_number:
            return Response({
                "code": "rack_screen_not_assigned", "detail": "screen is not assigned to this rack",
            }, status=409)
        node = Node.objects.select_for_update().filter(rack_number=rack_number).first()
        if node is None or not node_is_usable(node):
            return Response({
                "code": "rack_sensor_required", "detail": "rack requires an active physical sensor",
            }, status=409)
        RackRuntime.objects.get_or_create(rack_number=rack_number)
        runtime = RackRuntime.objects.select_for_update().get(rack_number=rack_number)
        now = timezone.now()
        digest = _token_digest(token)
        same_holder = bool(
            runtime.controller_screen_id == screen.id
            and runtime.client_instance_id == client_instance_id
            and hmac.compare_digest(runtime.controller_token_digest, digest)
        )
        lease_active = bool(runtime.lease_expires_at and runtime.lease_expires_at > now)
        if lease_active and same_holder:
            return Response({
                "controller_epoch": runtime.controller_epoch,
                "lease_expires_at": runtime.lease_expires_at,
                "state_version": runtime.state_version,
                "server_time": now,
                "snapshot": _runtime_snapshot(runtime, now),
            })
        if lease_active:
            return _controller_conflict(
                "rack_controller_busy", "another browser controls this rack", runtime, now,
            )
        if _runtime_has_open_set(runtime) and not same_holder:
            return _controller_conflict(
                "rack_recovery_required",
                "the expired open set can only be recovered by its original controller",
                runtime, now, recovery_required=True,
            )

        runtime.controller_screen = screen
        runtime.client_instance_id = client_instance_id
        runtime.controller_token_digest = digest
        runtime.controller_epoch += 1
        runtime.lease_expires_at = now + CONTROLLER_LEASE
        runtime.state_version += 1
        runtime.save()
        MonitoringEvent.objects.create(reason="controller_acquired")
        body = {
            "controller_epoch": runtime.controller_epoch,
            "lease_expires_at": runtime.lease_expires_at,
            "state_version": runtime.state_version,
            "server_time": now,
            "snapshot": _runtime_snapshot(runtime, now),
        }
    return Response(body)


@api_view(["POST"])
@permission_classes([AllowAny])
def rack_controller_heartbeat(request, rack_number):
    """Extend the current lease using server time; heartbeats are not visible events."""
    if request.data:
        return Response({"code": "invalid_heartbeat", "detail": "heartbeat body must be empty"}, status=400)
    with transaction.atomic():
        runtime = RackRuntime.objects.select_for_update().filter(rack_number=rack_number).first()
        if runtime is None:
            return Response({"code": "rack_not_found", "detail": "rack not found"}, status=404)
        now = timezone.now()
        conflict = _require_controller(request, runtime, now)
        if conflict:
            return conflict
        runtime.lease_expires_at = now + CONTROLLER_LEASE
        runtime.save(update_fields=["lease_expires_at", "updated_at"])
        body = {
            "controller_epoch": runtime.controller_epoch,
            "lease_expires_at": runtime.lease_expires_at,
            "state_version": runtime.state_version,
            "server_time": now,
        }
    return Response(body)


@api_view(["POST"])
@permission_classes([AllowAny])
def rack_controller_release(request, rack_number):
    """Release a quiet rack without allowing an open set to lose its owner."""
    if set(request.data) != {"expected_state_version", "command_id"}:
        return Response({
            "code": "invalid_controller_command",
            "detail": "exactly command_id and expected_state_version are required",
        }, status=400)
    command = _command_identity(request)
    if command is None:
        return Response({"code": "invalid_controller_command", "detail": "controller command is invalid"}, status=400)
    command_id, expected = command
    with transaction.atomic():
        runtime = RackRuntime.objects.select_for_update().filter(rack_number=rack_number).first()
        if runtime is None:
            return Response({"code": "rack_not_found", "detail": "rack not found"}, status=404)
        receipt = _existing_receipt(request, runtime, command_id)
        if receipt:
            return receipt
        conflict = _require_controller(request, runtime)
        if conflict:
            return conflict
        limited = _command_rate_limit(runtime)
        if limited:
            return limited
        conflict = _state_version_conflict(runtime, expected)
        if conflict:
            return conflict
        if _runtime_has_open_set(runtime):
            return _controller_conflict(
                "rack_recovery_required", "an open set must be completed before release",
                runtime, recovery_required=True,
            )
        runtime.controller_screen = None
        runtime.client_instance_id = ""
        runtime.controller_token_digest = ""
        runtime.lease_expires_at = None
        runtime.state_version += 1
        runtime.save()
        MonitoringEvent.objects.create(reason="controller_released")
        body = _runtime_snapshot(runtime)
        _save_receipt(request, runtime, command_id, body, 200)
    return Response(body)


# "Which training day is live?" lives in services/active_session.py, NOT here —
# the rack endpoints, the wall display's room_state, and this module all have to
# give the same answer, and they used to each carry their own copy of the query.
# See that file for why, and for what P14 changes.
_open_sessions = open_sessions
_active_session = active_session


@api_view(["POST"])
@permission_classes([AllowAny])
def rack_checkin(request, rack_number):
    """Record that an athlete signed in at this rack (Phase 11 Step 2). Append-only:
    writes a new RackCheckIn, which makes THIS rack the athlete's current one for the
    session (newest wins). This is the one thing that "moves" an athlete to a rack —
    a hand tap on the check-in screen today, an NFC tap later. Body: { athlete }."""
    command = _command_identity(request)
    if command is None:
        return Response({
            "code": "invalid_controller_command",
            "detail": "command_id and expected_state_version are required",
        }, status=400)
    command_id, expected = command
    with transaction.atomic():
        locked_node = Node.objects.select_for_update().filter(rack_number=rack_number).first()
        runtime = RackRuntime.objects.select_for_update().filter(rack_number=rack_number).first()
        if runtime is None:
            return Response({"code": "rack_controller_required", "detail": "rack has no controller"}, status=409)
        conflict = _require_controller(request, runtime)
        if conflict:
            return conflict
        receipt = _existing_receipt(request, runtime, command_id)
        if receipt:
            return receipt
        limited = _command_rate_limit(runtime)
        if limited:
            return limited
        conflict = _state_version_conflict(runtime, expected)
        if conflict:
            return conflict
        session = _active_session()
        if session is None:
            return Response({"error": "no active session"}, status=400)
        if locked_node is None or not node_is_usable(locked_node):
            return Response({
                "code": "rack_sensor_required",
                "detail": "select an active physical sensor before athlete check-in",
            }, status=409)
        athlete = Athlete.objects.filter(id=request.data.get("athlete")).first()
        if athlete is None:
            return Response({"error": "athlete not found"}, status=404)
        if not session.athletes.filter(id=athlete.id).exists():
            return Response({"error": "athlete is not in the active session"}, status=404)
        if runtime.selected_athlete_id == athlete.id:
            return _controller_conflict(
                "duplicate_checkin", "athlete is already selected at this rack revision", runtime,
            )
        RackCheckIn.objects.create(session=session, athlete=athlete, rack_number=rack_number)
        runtime.selected_athlete = athlete
        runtime.state_version += 1
        runtime.save(update_fields=["selected_athlete", "state_version", "updated_at"])
        MonitoringEvent.objects.create(
            reason="athlete_checked_in",
            is_simulated=session.is_simulated,
        )
        body = {
            "session_id": session.id,
            "athlete": {"id": athlete.id, "name": athlete.name},
            "rack_number": rack_number,
        }
        _save_receipt(request, runtime, command_id, body, 201)
    return Response(body, status=201)


@api_view(["GET"])
@permission_classes([AllowAny])
def rack_checkins(request, rack_number):
    """The rack's HOT LIST: athletes this rack currently 'owns' — those whose NEWEST
    check-in this session is this rack. Surfaced first on the check-in screen for
    fast re-pick. Derived from RackCheckIn (newest-wins per athlete); nothing new
    stored; session-scoped."""
    session = _active_session()
    if session is None:
        return Response({"session_id": None, "rack_number": rack_number, "athletes": []})

    # newest check-in per athlete this session → their current rack
    current_rack = {}
    for c in RackCheckIn.objects.filter(session=session).select_related("athlete").order_by(
        "athlete_id", "-checked_in_at"
    ):
        if c.athlete_id not in current_rack:  # first seen == newest, thanks to the ordering
            current_rack[c.athlete_id] = (c.rack_number, c.athlete.name)

    athletes = [{"athlete_id": aid, "name": name}
                for aid, (rn, name) in current_rack.items() if rn == rack_number]
    return Response({"session_id": session.id, "rack_number": rack_number, "athletes": athletes})


@api_view(["POST"])
@permission_classes([AllowAny])
def rack_nfc_tap(request, rack_number):
    """Consume one NFC tap and resolve it to an athlete in the active session.

    Two ways in, one resolution path:
    - Empty body {}: the rack's own reader agent (a Unix socket on this host).
    - {tag_id: "..."}: the rack screen read the tap from its LOCAL reader over
      loopback HTTP and forwarded the raw tag here. Resolution stays server-side
      either way — the tag is matched against Athlete.nfc_tag_id and the athlete
      must be in the active session before they're recognized.
    """
    if request.query_params:
        return Response({"code": "invalid_nfc_request", "detail": "query parameters are not allowed"}, status=400)
    tag_id = request.data.get("tag_id") if isinstance(request.data, dict) else None
    if request.data == {}:
        tag_id = None
    elif set(request.data) == {"tag_id"} and isinstance(tag_id, str):
        if nfc_agent.TAG_PATTERN.fullmatch(tag_id) is None:
            return Response({"code": "invalid_nfc_request", "detail": "tag_id must match ^[0-9A-F]{8,32}$"}, status=400)
    else:
        return Response({
            "code": "invalid_nfc_request",
            "detail": "empty body or {tag_id} required",
        }, status=400)
    runtime = RackRuntime.objects.select_related("controller_screen").filter(rack_number=rack_number).first()
    if runtime is None:
        return Response({"code": "rack_controller_required", "detail": "rack has no controller"}, status=409)
    conflict = _require_controller(request, runtime)
    if conflict:
        return conflict
    session = _active_session()
    if session is None:
        return Response({"status": "none"})
    if tag_id is None:
        try:
            tap = nfc_agent.consume(rack_number)
        except nfc_agent.NFCAgentUnavailable:
            response = Response({"status": "unavailable"})
            response["Cache-Control"] = "no-store"
            return response
        if tap["status"] == "none":
            response = Response({"status": "none"})
            response["Cache-Control"] = "no-store"
            return response
        tag_id = tap["tag_id"]
    athlete = Athlete.objects.filter(nfc_tag_id=tag_id).first()
    if athlete is None or not session.athletes.filter(id=athlete.id).exists():
        body = {"status": "unknown"}
    else:
        body = {"status": "recognized", "athlete": {"athlete_id": athlete.id, "name": athlete.name}}
    response = Response(body)
    response["Cache-Control"] = "no-store"
    return response


# ─────────────────────────── nodes ───────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def nodes_list(request):
    """Open: list every sensor node and its latest status."""
    return Response(NodeSerializer(Node.objects.all(), many=True).data)


@api_view(["PUT"])
@permission_classes([IsActiveStaff])
def node_acquisition_kind(request, node_id):
    """Provision the transport trusted to supply one registered node's health."""
    if set(request.data) != {"acquisition_kind"}:
        return Response({
            "code": "invalid_acquisition_request",
            "detail": "exactly acquisition_kind is required",
        }, status=400)
    acquisition_kind = request.data.get("acquisition_kind")
    valid_kinds = {choice[0] for choice in Node.ACQUISITION_CHOICES}
    if acquisition_kind not in valid_kinds:
        return Response({
            "code": "invalid_acquisition_kind",
            "detail": "acquisition_kind must be mqtt or wt901_ble",
        }, status=400)

    with transaction.atomic():
        node = Node.objects.select_for_update().filter(node_id=node_id).first()
        if node is None:
            return Response({"code": "node_not_found", "detail": "node not found"}, status=404)
        if Set.objects.select_for_update().filter(node=node, ended_at=None).exists():
            return Response({
                "code": "node_acquisition_has_open_set",
                "detail": "finish the open set before changing acquisition kind",
            }, status=409)
        if node.acquisition_kind == acquisition_kind:
            return Response(NodeSerializer(node).data)
        node.acquisition_kind = acquisition_kind
        node.save(update_fields=["acquisition_kind"])
        MonitoringEvent.objects.create(reason="node_acquisition_changed")
    return Response(NodeSerializer(node).data)


# ─────────────────────────── athletes ───────────────────────────

@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def athletes_view(request):
    """GET: list all lifters (open). POST: add a lifter (coach only)."""
    if request.method == "GET":
        return Response(AthleteSerializer(Athlete.objects.all(), many=True).data)
    if not _require_coach(request):
        return Response({"detail": "coach login required"}, status=401)
    form = AthleteSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    return Response(AthleteSerializer(form.save()).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsCoach])
def athlete_detail(request, athlete_id):
    """Coach-only: read or update one lifter.

    GET matters more than it looks. `notes` is a plain field on Athlete rather
    than its own resource (merge canon R1), so this is the ONLY way to read a
    coach's notes on someone — there is no notes route to fall back on. A detail
    endpoint that could be written but not read forced the coach screen to pull
    the entire roster just to see one athlete's note.
    """
    athlete = Athlete.objects.filter(id=athlete_id).first()
    if athlete is None:
        return Response({"error": "athlete not found"}, status=404)

    if request.method == "GET":
        return Response(AthleteSerializer(athlete).data)

    form = AthleteSerializer(athlete, data=request.data, partial=True)
    form.is_valid(raise_exception=True)
    return Response(AthleteSerializer(form.save()).data)


# ─────────────────────────── programs (training plans) ───────────────────────────

@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def prescriptions_view(request):
    """GET: an athlete's training plan for today, ?athlete={id} to filter (open).

    SAME ADDRESS, DIFFERENT SOURCE. This used to read a per-athlete table where a
    coach typed one weight per person. That table is gone: a plan now belongs to
    a TrainingGroup and says a PERCENT, and the pounds are worked out per athlete
    from their own reference max. Callers see the same fields either way, which
    is the point — this is a diagnostic read, and it had no business breaking
    over where the numbers come from.

    `id` is null now. There is no longer a single row to point at: what comes
    back is resolved from the athlete's group plan, not stored per athlete.
    """
    if request.method == "GET":
        athlete_id = request.query_params.get("athlete")
        session = _active_session()
        athletes = Athlete.objects.filter(id=athlete_id) if athlete_id else Athlete.objects.all()

        plans = []
        for athlete in athletes:
            for movement in plan_movements_for_athlete(athlete, session):
                plans.append({
                    "id": None,
                    "athlete": athlete.id,
                    "exercise": movement["exercise_id"],
                    "target_sets": movement["planned_sets"],
                    "target_reps": movement["target_reps"],
                    "target_weight_lbs": movement["target_weight_lbs"],
                    "velocity_zone_min": movement["velocity_zone_min"],
                    "velocity_zone_max": movement["velocity_zone_max"],
                })
        return Response(plans)

    # Writing a plan one athlete at a time is the thing this merge removed. A
    # 410 says the address is deliberately dead rather than broken, and points
    # at what replaced it, so anyone still calling it learns why.
    return Response({
        "code": "endpoint_retired",
        "detail": ("Per-athlete plans have been replaced by group plans. Build a "
                   "template at POST /api/workout-programs/, deploy it with "
                   "POST /api/training-programs/, and put athletes in the group "
                   "with POST /api/training-groups/{id}/athletes/."),
    }, status=410)


# ─────────────────────────── exercises (catalog) ───────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def exercises_list(request):
    """Open: list the movement catalog — the official set of exercises the rack
    and coach pickers choose from, so nobody hand-types a name into drift."""
    return Response(ExerciseSerializer(Exercise.objects.all().order_by("name"), many=True).data)


# ─────────────────────────── sessions ───────────────────────────

@api_view(["POST"])
@permission_classes([IsCoach])
def sessions_view(request):
    """Coach-only: start a training session.

    ONE OPEN SESSION AT A TIME (canon D18). A second open session is refused with
    409, naming the one already open.

    Why this matters more than it looks: `_active_session()` is last-one-wins, and
    the rack screens follow it. So a stray second session did not produce an
    error — it silently became the one athletes checked into, their sets attached
    to a session with no participants, and the day's report came out wrong while
    every tablet looked completely normal. It also made "End training day" look
    broken, because ending the top session instantly promoted the next one and
    the panel redrew identically.

    The refusal names the open session so the caller can offer "end that one
    first" instead of a dead end. `force` is deliberately NOT offered: there is no
    honest reason to run two days at once, and an override would just move the
    quiet corruption behind a flag.
    """
    open_session = _active_session()
    if open_session is not None:
        return Response({
            "error": "a training day is already open",
            "open_session": {
                "id": open_session.id,
                "label": open_session.label,
                "started_at": open_session.started_at,
            },
            "detail": f"End '{open_session.label}' before starting another day.",
        }, status=409)

    form = TrainingSessionSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    # `started_at` stopped being auto_now_add in P14 so a session can be created
    # before it runs. THIS route still means "start the day now" — it is the
    # coach panel's button, and a coach pressing it expects the room open. A
    # session created from a calendar slot is the one that starts out unstarted.
    return Response(
        TrainingSessionSerializer(form.save(started_at=timezone.now())).data,
        status=201)


@api_view(["PATCH"])
@permission_classes([IsCoach])
def session_detail(request, session_id):
    """Coach-only: update a session. A PATCH with no ended_at means "end it now".

    ENDING A SESSION IS A BIG DEAL, and it happens right here — there is no
    separate `end/` route, because "end the session" is just "set its end time"
    and this endpoint already did that (merge canon R2). When this PATCH ends a
    day it hands off to the completion service, which atomically freezes the
    immutable DailyReport and recalculates everyone's reference maxes (D10).

    The response gains a `daily_report` block when a report was produced, so a
    coach tablet can jump straight to the finished report without a second call.
    Ending an already-ended session is safe: it returns the existing report
    rather than writing a second one.

    It also gains an `ended` block naming the day that just ended and whether
    another is still open (canon D18). Before P12 the coach panel could redraw
    looking completely unchanged — ending the top of several stacked sessions
    instantly promoted the next one — so the button appeared to do nothing while
    working perfectly every time. Saying what happened is the fix for that; the
    create guard is what stops the stack forming in the first place.
    """
    session = TrainingSession.objects.filter(id=session_id).first()
    if session is None:
        return Response({"error": "session not found"}, status=404)
    form = TrainingSessionSerializer(session, data=request.data, partial=True)
    form.is_valid(raise_exception=True)

    # "Is this PATCH ending the day?" — either the caller omitted ended_at (our
    # long-standing shorthand for "end it now") or passed a real timestamp.
    ends_session = ("ended_at" not in request.data
                    or form.validated_data.get("ended_at") is not None)

    if not ends_session:
        return Response(TrainingSessionSerializer(form.save()).data)

    requested_end = form.validated_data.get("ended_at") if "ended_at" in request.data else None
    report, _created = end_session(session_id, ended_at=requested_end)

    session.refresh_from_db()
    body = TrainingSessionSerializer(session).data
    if report is not None:
        body["daily_report"] = {"id": report.id, "generated_at": report.generated_at}

    # Name the day that ended and say whether anything is still open, so the
    # panel can confirm in words rather than leaving the coach to infer it from a
    # screen that may look identical. `still_open` should be null now that the
    # create guard exists — it stays in the payload because databases that
    # predate the guard can hold a stack, and a silent one is how D18 hid.
    remaining = _active_session()
    body["ended"] = {
        "id": session.id,
        "label": session.label,
        "ended_at": session.ended_at,
        "report_generated": report is not None,
        "still_open": ({"id": remaining.id, "label": remaining.label}
                       if remaining is not None else None),
    }
    return Response(body)


@api_view(["GET"])
@permission_classes([AllowAny])
def sessions_active(request):
    """The rack tablet's ONE startup fetch (open, no login). Returns the current
    session plus everything the rack screen needs to run a whole set-logging
    session without asking again: who's on the roster, each athlete's current
    maxes, and the planned exercises with their targets + velocity zones.

    THE SEAM, AND WHY THIS SHAPE NEVER CHANGED.
    Each roster entry carries a RESOLVED absolute `targets` map
    {exercise_id: target_weight_lbs}. The tablet READS that number; it has never
    computed anything from a percent and a max, and it must not start.

    That was a deliberate bet made while the plan still stored one typed weight
    per athlete: keep the resolved number on the wire, and a future
    percent-of-max system can compute the SAME field server-side without the
    tablet noticing. The bet paid — plans now store `target_percent`, the pounds
    are worked out in services/plan_resolution.py, and this response shape did
    not move by a single field. That is why react/src/rack/ is frozen. See §6.3.

      1. `exercise_id` is the Exercise catalog id — every plan row, Set, and
         reference max links to that one catalog — with the display `name`
         riding alongside it in session_exercises.
      2. `session_exercises[]` carries the velocity zone, which is where the
         tablet reads it from to color reps. It deliberately does NOT carry
         `target_percent`: percentages are resolved here, not on the tablet.

    `maxes` (from AthleteReferenceMax — each athlete's newest row per exercise)
    rides along for coach-side callers. ⚠️ THE RACK SCREEN DOES NOT READ IT and
    never has; it reads `targets`. Do not "fix" a weight bug by reaching for this
    map on the tablet — the fix belongs in plan_resolution.py.

    ⚠️ REFERENCE max, not a lifetime best. It is what the athlete can do NOW, so
    it can go DOWN, and prescribed weights are supposed to follow it down.

    "Active" comes from `_active_session()` — the one definition every endpoint
    shares, so the rack and the coach tablet can never disagree about which
    session is live.
    """
    session = _active_session()
    if session is None:
        # No live session: return the same envelope with nulls/empties so the
        # tablet can render a plain "no active session" screen without having to
        # special-case an HTTP error status.
        return Response({"session_id": None, "label": None, "roster": [], "session_exercises": []})

    athletes = list(session.athletes.order_by("name", "id"))
    athlete_ids = [a.id for a in athletes]

    # Everyone's plan for today, resolved once — the same helper the wall display
    # uses, so the two can't disagree about what somebody is meant to be lifting.
    plans = plans_by_athlete(session, athletes)

    # has_data: this athlete already has a completed set in THIS session. Drives
    # Phase 11's is_makeup (a set logged for someone who missed the original run).
    # Coach weight adjustments excluded: they are finished set rows, so counting
    # them would mark an athlete as "already has data" and their genuine first set
    # of the session would then be flagged as a retroactive makeup.
    athletes_with_data = set(
        Set.objects.filter(session=session, ended_at__isnull=False,
                           is_coach_adjustment=False)
        .values_list("athlete_id", flat=True)
    )

    # Current reference max per (athlete, exercise), in ONE query.
    # AthleteReferenceMax is ordered newest-first, so the first row we see for a
    # pair is the current one.
    maxes_by_athlete = {}
    for m in AthleteReferenceMax.objects.filter(athlete_id__in=athlete_ids).order_by(
        "athlete_id", "exercise_id", "-recorded_at"
    ):
        pairs = maxes_by_athlete.setdefault(m.athlete_id, {})
        if m.exercise_id not in pairs:  # first seen == newest, thanks to the ordering
            pairs[m.exercise_id] = m.reference_weight_lbs

    # Per-athlete resolved target weights, plus the session-level exercise list
    # for the dropdown + velocity zones. Both now come from each athlete's GROUP
    # plan (percent x their own reference max) instead of a per-athlete row, and
    # the response shape is byte-for-byte what it was — the rack must not be able
    # to tell that the source changed.
    #
    # session_exercises takes the first athlete seen to prescribe a movement as
    # the representative zone/target-reps. Same assumption as before the swap:
    # a movement's zone is shared across the room.
    targets_by_athlete = {}
    session_exercises = {}
    for athlete in athletes:
        for movement in plans[athlete.id]:
            targets_by_athlete.setdefault(athlete.id, {})[movement["exercise_id"]] = \
                movement["target_weight_lbs"]
            if movement["exercise_id"] not in session_exercises:
                session_exercises[movement["exercise_id"]] = {
                    "exercise_id": movement["exercise_id"],
                    "name": movement["name"],
                    "target_sets": movement["planned_sets"],
                    "target_reps": movement["target_reps"],
                    "velocity_zone_min": movement["velocity_zone_min"],
                    "velocity_zone_max": movement["velocity_zone_max"],
                }

    roster = [{
        "athlete_id": a.id,
        "name": a.name,
        "has_data": a.id in athletes_with_data,
        "maxes": maxes_by_athlete.get(a.id, {}),
        "targets": targets_by_athlete.get(a.id, {}),
    } for a in athletes]

    return Response({
        "session_id": session.id,
        "label": session.label,
        "roster": roster,
        "session_exercises": list(session_exercises.values()),
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def athlete_progress(request, athlete_id):
    """The rack's athlete DAY-VIEW (open, no login). For one athlete in the active
    session, returns their planned movements (from Program) with live progress
    (derived from their completed Set rows THIS session) — so any rack shows the
    same, up-to-date view. Everything is DERIVED per request; no new tables.

    Fetched when an athlete checks in at a rack, and again after each of their sets
    completes (Phase 11 Step 2). "Active" session is resolved exactly like
    sessions_active (most recent with ended_at null).

    Progress rules:
      - A set counts as COMPLETED once it has an ended_at (set-complete stamps it).
      - False sets are counted separately and NEVER advance the set number.
      - next_set_number = completed (non-false) sets + 1 — the authoritative
        set_number to send at set-create (a client counter can't stay correct
        across rack moves + supersets, so the server owns it).
      - Movements are ordered by Program.id (the athlete's program-creation order,
        which is the intended workout order).
      - last_weight_lbs = the actual load of this athlete's NEWEST non-false
        completed set of that movement THIS session (null if none yet). It lets the
        tablet default the next set to what they last actually lifted — carrying an
        on-the-fly weight change forward across reloads/rack moves WITHIN the
        session, while never touching the prescribed target. TrainingSession-scoped only:
        a prior session's loads are never read, so each session starts at target.
    """
    session = _active_session()
    athlete = Athlete.objects.filter(id=athlete_id).first()
    if athlete is None:
        return Response({"error": "athlete not found"}, status=404)

    if session is None:
        # Same empty-envelope convention as sessions_active: no HTTP error, just
        # nulls/empties so the tablet renders a plain "no active session" screen.
        return Response({
            "session_id": None,
            "athlete": {"id": athlete.id, "name": athlete.name},
            "current_exercise_id": None,
            "movements": [],
        })

    if not session.athletes.filter(id=athlete_id).exists():
        return Response({"error": "athlete is not in the active session"}, status=404)

    # Tally this athlete's finished sets in THIS session, per exercise — real
    # (non-false) and false counted separately, plus the actual load of the newest
    # non-false set (for the next-set default). Ordered oldest→newest so the last
    # write per exercise IS the newest.
    completed_by_exercise = {}
    false_by_exercise = {}
    last_weight_by_exercise = {}
    for s in Set.objects.filter(
        session=session, athlete_id=athlete_id, ended_at__isnull=False
    ).order_by("started_at", "id"):
        if s.is_coach_adjustment:
            # A coach changing the weight an athlete is working with. It has to be
            # a finished set row to move the carried-forward load at all, but it
            # is NOT a lift: counting it would advance their set number and could
            # mark a movement finished that they never actually did. So it moves
            # the weight and nothing else.
            if s.weight_lbs is not None:
                last_weight_by_exercise[s.exercise_id] = s.weight_lbs
        elif s.is_false_set:
            false_by_exercise[s.exercise_id] = false_by_exercise.get(s.exercise_id, 0) + 1
        else:
            completed_by_exercise[s.exercise_id] = completed_by_exercise.get(s.exercise_id, 0) + 1
            if s.weight_lbs is not None:
                last_weight_by_exercise[s.exercise_id] = s.weight_lbs

    # WHERE THE PLAN COMES FROM (mid-merge, two sources on purpose).
    #
    # The new way: the athlete's TrainingGroup is training in this session, and the TrainingGroup's
    # plan says "5 sets of 3 at 80%" — their weight is worked out from their own
    # current max. One plan, everyone gets their own numbers.
    #
    # The old way: a plan row per athlete with a weight typed into it.
    #
    # We try the new way first and fall back to the old one, because both kinds of
    # data exist right now. The fallback disappears when the old table retires in
    # the rename phase — at which point this becomes a single call.
    # One source now. The per-athlete fallback that sat here through the merge
    # existed only so the rack kept working while both plan systems were alive;
    # with the old table gone it had nothing left to read. An empty list is a
    # legitimate answer (no group, group not training today, coach hasn't picked
    # the workout) and the rack already handles it.
    planned = plan_movements_for_athlete(athlete, session)

    # Live progress is layered on identically regardless of which source the plan
    # came from — the tablet cannot tell the difference, and must not be able to.
    movements = []
    current_exercise_id = None  # suggested current = first movement not yet complete
    for item in planned:
        exercise_id = item["exercise_id"]
        completed = completed_by_exercise.get(exercise_id, 0)
        false_count = false_by_exercise.get(exercise_id, 0)
        planned_sets = item["planned_sets"]
        if planned_sets is not None and completed >= planned_sets:
            status = "complete"
        elif completed > 0:
            status = "in_progress"
        else:
            status = "not_started"
        if current_exercise_id is None and status != "complete":
            current_exercise_id = exercise_id
        movements.append({
            **item,
            "last_weight_lbs": last_weight_by_exercise.get(exercise_id),
            "completed_sets": completed,
            "false_sets": false_count,
            "next_set_number": completed + 1,
            "status": status,
        })

    return Response({
        "session_id": session.id,
        "athlete": {"id": athlete.id, "name": athlete.name},
        "current_exercise_id": current_exercise_id,
        "movements": movements,
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def session_status(request):
    """Room state for the active session: each athlete's live status + since-when.
    The rack's rest/check-in cards turn this into a ticking timer + status label,
    and a coach tablet can reuse the exact same data. Derived per request from
    `Set` + `RackCheckIn` — no new tables.

    Status per athlete (first match wins):
      lifting     — a set is in progress right now  → `since` = when it started
      resting     — their most recent set has ended → `since` = when it ended
      ready       — checked in at a rack, no set yet → `since` = check-in time
      not_started — no activity this session         → `since` = null
    """
    session = _active_session()
    if session is None:
        return Response({"session_id": None, "athletes": []})

    athletes = list(session.athletes.order_by("name", "id"))
    ids = [a.id for a in athletes]

    # in-progress set (lifting) per athlete
    lifting = {}
    for s in Set.objects.filter(session=session, athlete_id__in=ids, ended_at__isnull=True):
        lifting.setdefault(s.athlete_id, s.started_at)

    # most recent finished set (resting) per athlete.
    # Coach weight adjustments are excluded: they're written as finished sets so
    # they can move the working weight, but nobody lifted anything — counting one
    # here would show the athlete resting, with a ticking rest timer, off a set
    # that never happened.
    last_done = {}
    for s in Set.objects.filter(session=session, athlete_id__in=ids,
                                ended_at__isnull=False, is_coach_adjustment=False
                                ).order_by("athlete_id", "-ended_at"):
        last_done.setdefault(s.athlete_id, s.ended_at)  # first == newest, thanks to ordering

    # newest check-in (which rack + when) per athlete
    checkin = {}
    for c in RackCheckIn.objects.filter(session=session, athlete_id__in=ids).order_by(
        "athlete_id", "-checked_in_at"
    ):
        checkin.setdefault(c.athlete_id, (c.rack_number, c.checked_in_at))

    # "resting" only counts as ACTIVELY between sets — a set that ended long ago
    # means they've moved on, not that they're resting for hours. Past this window
    # they fall through to "ready" (if still checked in) or "not_started".
    # The window itself is a tunable: services/tuning.py.
    now = timezone.now()

    out = []
    for a in athletes:
        if a.id in lifting:
            status, since = "lifting", lifting[a.id]
        elif a.id in last_done and (now - last_done[a.id]) <= RESTING_WINDOW:
            status, since = "resting", last_done[a.id]
        elif a.id in checkin:
            status, since = "ready", checkin[a.id][1]
        else:
            status, since = "not_started", None
        out.append({
            "athlete_id": a.id,
            "name": a.name,
            "status": status,
            "since": since,  # DRF serializes to ISO 8601; the tablet ticks a timer from it
            "rack_number": checkin.get(a.id, (None, None))[0],
        })
    return Response({"session_id": session.id, "athletes": out})


# ─────────────────────────── sets ───────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
def set_create(request):
    """Start a set: create the empty set record when an athlete begins, so the
    finish endpoint has something to fill in. Body: session, athlete, exercise,
    set_number, and optionally node + weight_lbs."""
    expected_rack = request.data.get("rack_number")
    control_fields = {"rack_number", "command_id", "expected_state_version"}
    form = SetSerializer(data={key: value for key, value in request.data.items() if key not in control_fields})
    form.is_valid(raise_exception=True)
    with transaction.atomic():
        selected_node = form.validated_data.get("node")
        runtime = None
        command_id = None
        if selected_node is not None:
            if expected_rack is None:
                return Response({
                    "code": "rack_number_required",
                    "detail": "rack_number is required when starting a sensor-backed set",
                }, status=400)
            selected_node = Node.objects.select_for_update().get(pk=selected_node.pk)
            try:
                rack_number = int(expected_rack)
            except (TypeError, ValueError):
                return Response({"code": "invalid_rack_number", "detail": "rack_number must be an integer"}, status=400)
            if selected_node.rack_number != rack_number:
                return Response({
                    "code": "node_assignment_changed",
                    "detail": "the selected node is no longer assigned to this rack",
                }, status=409)
            if not node_is_usable(selected_node):
                return Response({
                    "code": "rack_sensor_required",
                    "detail": "sensor-backed set start requires a usable assigned sensor",
                }, status=409)
            runtime = RackRuntime.objects.select_for_update().filter(rack_number=rack_number).first()
            if runtime is None:
                return Response({"code": "rack_controller_required", "detail": "rack has no controller"}, status=409)
            conflict = _require_controller(request, runtime)
            if conflict:
                return conflict
            command = _command_identity(request)
            if command is None:
                return Response({
                    "code": "invalid_controller_command",
                    "detail": "command_id and expected_state_version are required",
                }, status=400)
            command_id, expected = command
            receipt = _existing_receipt(request, runtime, command_id)
            if receipt:
                return receipt
            limited = _command_rate_limit(runtime)
            if limited:
                return limited
            conflict = _state_version_conflict(runtime, expected)
            if conflict:
                return conflict
            athlete = Athlete.objects.select_for_update().get(pk=form.validated_data["athlete"].pk)
            if Set.objects.filter(
                models.Q(node__rack_number=rack_number) | models.Q(athlete=athlete),
                ended_at=None,
                is_coach_adjustment=False,
            ).exists():
                return _controller_conflict(
                    "open_set_exists", "rack or athlete already has an open set", runtime,
                )
        new_set = form.save(node=selected_node) if selected_node is not None else form.save()
        new_set.is_simulated = new_set.session.is_simulated or bool(
            new_set.node and new_set.node.is_simulated
        )
        if new_set.is_simulated:
            new_set.save(update_fields=["is_simulated"])
        MonitoringEvent.objects.create(
            reason="set_started",
            is_simulated=new_set.is_simulated,
        )
        if runtime is not None:
            now = timezone.now()
            runtime.current_set = new_set
            runtime.selected_athlete = new_set.athlete
            runtime.selected_exercise = new_set.exercise
            runtime.phase = RackRuntime.PHASE_ACTIVE
            runtime.phase_started_at = now
            runtime.rep_count = 0
            runtime.latest_mean_velocity = None
            runtime.latest_peak_velocity = None
            runtime.latest_color = ""
            runtime.state_version += 1
            runtime.save()
            body = dict(SetSerializer(new_set).data)
            _save_receipt(request, runtime, command_id, body, 201)
    
    rack_number = new_set.node.rack_number if new_set.node else None 
    if rack_number is not None: 
        publish_rack_state(rack_number, {
            "type": "athlete_checkin",
            "athlete": {"id" : new_set.athlete.id, "name": new_set.athlete.name},
            "rack_number": rack_number, 
        })
    
    return Response(SetSerializer(new_set).data, status=201)


@api_view(["POST"])
@permission_classes([AllowAny])
def set_complete(request, set_id):
    """Save a finished set. Take all its reps + totals and write them to the
    database in ONE all-or-nothing step (if anything fails, nothing saves). This
    is the only code path that creates Rep rows. A false set saves zero reps.
    We also flag whether it was the athlete's best-ever velocity or weight."""
    form = SetCompleteSerializer(data={
        key: value for key, value in request.data.items()
        if key not in {"command_id", "expected_state_version"}
    })
    form.is_valid(raise_exception=True)
    data = form.validated_data

    node_id = Set.objects.filter(id=set_id).values_list("node_id", flat=True).first()

    # Assignment takes the node lock before the set lock. Completion uses the same
    # order and captures the rack before commit so a later move cannot reroute it.
    with transaction.atomic():
        locked_node = Node.objects.select_for_update().filter(id=node_id).first() if node_id else None
        runtime = None
        command_id = None
        if locked_node and locked_node.rack_number is not None:
            runtime = RackRuntime.objects.select_for_update().filter(
                rack_number=locked_node.rack_number,
            ).first()
            if runtime is None:
                return Response({"code": "rack_controller_required", "detail": "rack has no controller"}, status=409)
            conflict = _require_controller(request, runtime)
            if conflict:
                return conflict
            command = _command_identity(request)
            if command is None:
                return Response({
                    "code": "invalid_controller_command",
                    "detail": "command_id and expected_state_version are required",
                }, status=400)
            command_id, expected = command
            receipt = _existing_receipt(request, runtime, command_id)
            if receipt:
                return receipt
            limited = _command_rate_limit(runtime)
            if limited:
                return limited
            conflict = _state_version_conflict(runtime, expected)
            if conflict:
                return conflict
        target_set = Set.objects.select_for_update().filter(id=set_id).first()
        if target_set is None:
            return Response({"error": "set not found"}, status=404)
        if target_set.ended_at is not None:
            return Response({
                "code": "set_already_completed",
                "detail": "set has already been completed",
            }, status=409)
        if runtime is not None and runtime.current_set_id != target_set.id:
            return _controller_conflict(
                "rack_state_changed", "set is not the rack runtime's current set", runtime,
            )
        if data["is_false_set"]:
            # false start — record it as false, save no reps
            target_set.is_false_set = True
            target_set.reps_completed = 0
            target_set.avg_velocity = None
            target_set.peak_velocity = None
            target_set.ended_at = timezone.now()
            target_set.save()
            is_velocity_pr = is_weight_pr = False
        else:
            # save every rep in one batch, all tied to this set
            Rep.objects.bulk_create([
                Rep(set=target_set, **rep) for rep in data["reps"]
            ])
            target_set.reps_completed = data["reps_completed"]
            target_set.avg_velocity = data.get("avg_velocity")
            target_set.peak_velocity = data.get("peak_velocity")
            target_set.is_false_set = False
            target_set.ended_at = timezone.now()
            target_set.save()
            is_velocity_pr, is_weight_pr = _personal_records(target_set)

        MonitoringEvent.objects.create(
            reason="set_completed",
            is_simulated=target_set.is_simulated,
        )
        completion_rack_number = locked_node.rack_number if locked_node else None

        if runtime is not None:
            now = timezone.now()
            runtime.current_set = None
            runtime.phase = (
                RackRuntime.PHASE_IDLE if target_set.is_false_set else RackRuntime.PHASE_SUMMARY
            )
            runtime.phase_started_at = now
            runtime.rep_count = target_set.reps_completed
            runtime.latest_mean_velocity = target_set.avg_velocity
            runtime.latest_peak_velocity = target_set.peak_velocity
            runtime.latest_color = (
                data["reps"][-1]["velocity_color"] if data["reps"] else ""
            )
            runtime.state_version += 1
            runtime.save()

        body = dict(SetSerializer(target_set).data)
        body["is_velocity_pr"] = is_velocity_pr
        body["is_weight_pr"] = is_weight_pr
        if runtime is not None:
            _save_receipt(request, runtime, command_id, body, 200)

    rack_number = completion_rack_number
    athlete_summary = {"id": target_set.athlete.id, "name": target_set.athlete.name}

    if rack_number is not None:
        publish_rack_state(rack_number, {
            "type": "set_complete",
            "set_id": target_set.id,
            "athlete": athlete_summary,
            "reps_completed": target_set.reps_completed,
            "avg_velocity": target_set.avg_velocity,
            "peak_velocity": target_set.peak_velocity,
            "is_false_set": target_set.is_false_set,
        })

    publish_dashboard_state({
        "type": "leaderboard_update",
        "athlete": athlete_summary,
        "rack_number": rack_number,
        "avg_velocity": target_set.avg_velocity,
        "peak_velocity": target_set.peak_velocity,
        "reps_completed": target_set.reps_completed,
        "is_false_set": target_set.is_false_set,
        "is_velocity_pr": is_velocity_pr,
        "is_weight_pr": is_weight_pr,
    })

    return Response(body)


def _personal_records(finished_set):
    """Was this set the athlete's best-ever for this exercise? Compare it to their
    earlier real (non-false) sets of the same exercise. "Best" means fastest peak
    velocity, or heaviest weight. A first-ever set has nothing to beat, so it is
    not flagged as a new record."""
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


# ─────────────────────────── analytics (coach) ───────────────────────────

@api_view(["GET"])
@permission_classes([IsCoach])
def analytics_session(request, session_id):
    """Coach-only: a quick summary of one session — how many sets and reps total,
    and each athlete's average velocity."""
    # Coach weight adjustments excluded everywhere in analytics: they are not
    # performances, and averaging them in would drag every number sideways.
    sets = Set.objects.filter(session_id=session_id, is_false_set=False,
                              is_coach_adjustment=False).select_related("athlete")
    per_athlete = {}
    total_reps = 0
    for s in sets:
        total_reps += s.reps_completed
        row = per_athlete.setdefault(s.athlete_id, {
            "athlete": {"id": s.athlete_id, "name": s.athlete.name}, "sets": 0, "_vs": []})
        row["sets"] += 1
        if s.avg_velocity is not None:
            row["_vs"].append(s.avg_velocity)
    athletes_out = [{
        "athlete": r["athlete"], "sets": r["sets"],
        "avg_velocity": round(sum(r["_vs"]) / len(r["_vs"]), 3) if r["_vs"] else None,
    } for r in per_athlete.values()]
    return Response({
        "session_id": int(session_id),
        "total_sets": sets.count(),
        "total_reps": total_reps,
        "athletes": athletes_out,
    })


@api_view(["GET"])
@permission_classes([IsCoach])
def analytics_athlete(request, athlete_id):
    """Coach-only: everything the athlete and history tabs need (P13).

    One call answers both of a coach's questions about a person: how are they
    doing overall (`summary` and `exercise_summaries`), and what did they
    actually do (`sets`, each with its reps). One request rather than three,
    because these tabs sit side by side and a coach flips between them.

    ⚠️ `summary` is aggregated across ALL history while `sets` is capped at the
    50 most recent — the UI tells the coach exactly that, so totals computed from
    the truncated list would make the screen lie. See services/athlete_analytics.py.

    This WIDENED an older response that returned only `{athlete_id, sets:[...]}`
    with a flat velocity trend. `athlete_id` is kept for anything still reading
    it; the per-set key was `set_id` and is now `id`, matching every other set
    payload we serve.
    """
    context = athlete_analytics(athlete_id)
    if context is None:
        return Response({"error": "athlete not found"}, status=404)
    # Retained alongside the new `athlete` block so an older caller does not
    # break on the widening.
    return Response({"athlete_id": int(athlete_id), **context})


# ─────────────────────────── room state (derived) ───────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def room_state(request):
    """The live picture of the room, for the wall display and the coach tablet.

    ONE endpoint serves both audiences, chosen by `?details=true` (merge canon
    R3 — his branch had this split across `wall-state/` and `room-state/`, two
    routes backed by the identical function one boolean apart; folding them
    leaves a single thing to document and maintain):

      GET /api/room-state/               -> WALL view. Open, because the wall
                                            screen is a shared display nobody
                                            logs into. Names and numbers only:
                                            no database ids, no roster.
      GET /api/room-state/?details=true  -> COACH view. Requires a coach login
                                            and adds ids, the participant
                                            roster, and node health so the UI
                                            can link through to records.

    Everything is DERIVED per request from check-ins and set/rep rows — there is
    no room-state table (canon D2/D3/D8). See services/room_state.py for how.
    """
    include_details = request.query_params.get("details", "").lower() in {"1", "true", "yes"}

    # The detail level IS the privilege boundary: ids and the roster are coach
    # data, so asking for them requires actually being a coach. Refusing here
    # rather than silently downgrading means a coach UI with an expired token
    # gets a clear 401 instead of mysteriously missing fields.
    if include_details and not (request.user and request.user.is_authenticated):
        return Response({"error": "coach login required for ?details=true"}, status=401)

    response = Response(room_state_snapshot(include_details=include_details))
    # Never cache: a stale room picture is worse than a slow one, and this is
    # per-viewer data on a shared network.
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    return response


# ─────────────────────────── reports (immutable history) ───────────────────────────

@api_view(["GET"])
@permission_classes([IsCoach])
def reports_view(request):
    """Coach-only: browse finished training days, newest first.

    ONE family of report routes serves both "all reports" and "this athlete's
    reports" — the athlete view is just a filter, so it is a query parameter
    rather than a parallel set of `athletes/{id}/reports/...` endpoints (merge
    canon R6). Query: ?athlete={id}
    """
    athlete_id = request.query_params.get("athlete")
    if athlete_id:
        reports = reports_for_athlete(athlete_id)
    else:
        reports = DailyReport.objects.all()
    reports = reports.order_by("-generated_at", "-id")[:200]
    return Response([report_list_item(r) for r in reports])


@api_view(["GET"])
@permission_classes([IsCoach])
def report_detail_view(request, report_id):
    """Coach-only: one finished day in full.

    With ?athlete={id} the report is narrowed to that athlete's own work — the
    same stored snapshot, read through a single-athlete lens, so an athlete's
    record and the team record can never disagree.
    """
    report = DailyReport.objects.filter(id=report_id).first()
    if report is None:
        return Response({"error": "report not found"}, status=404)
    athlete_id = request.query_params.get("athlete")
    if athlete_id:
        try:
            return Response(athlete_report_detail(report, athlete_id))
        except AthleteNotInReport:
            # A fair question with the answer "no" — they did not train that
            # day. Never a 500.
            return Response({"code": "athlete_not_in_report",
                             "detail": "That athlete has no record in this report."},
                            status=404)
    return Response(report_detail(report))


# ─────────────────────────── reference maxes ───────────────────────────

@api_view(["POST"])
@permission_classes([IsCoach])
def reference_maxes_view(request):
    """Coach-only: record what athletes can currently lift.

    THIS IS THE PRESCRIPTION LEVER. Every target weight is a percentage of these
    numbers, so this is how a coach moves what the whole gym is prescribed. It is
    a different thing from adjusting the load on a bar today — that rides on the
    set itself and changes nothing about the plan.

    Takes a LIST so a coach can enter a whole TrainingGroup's testing day in one go
    rather than one athlete at a time:

        { "exercise": 1, "rep_basis": 1,
          "entries": [ {"athlete": 3, "reference_weight_lbs": 315},
                       {"athlete": 4, "reference_weight_lbs": 275} ] }

    Every entry writes a NEW row; nothing is overwritten. An athlete's current
    reference is simply their newest row, so re-entering a number supersedes the
    old one while the history stays intact and graphable. Applies forward only —
    targets an athlete already trained against are never rewritten.
    """
    exercise_id = request.data.get("exercise")
    if not Exercise.objects.filter(id=exercise_id).exists():
        return Response({"error": "exercise not found"}, status=404)

    entries = request.data.get("entries")
    if not isinstance(entries, list) or not entries:
        return Response({"error": "entries must be a non-empty list"}, status=400)

    rep_basis = request.data.get("rep_basis", 1)
    created = []
    for entry in entries:
        athlete_id = entry.get("athlete")
        weight = entry.get("reference_weight_lbs")
        if not Athlete.objects.filter(id=athlete_id).exists():
            return Response({"error": f"athlete {athlete_id} not found"}, status=404)
        if weight is None:
            return Response({"error": f"reference_weight_lbs is required for athlete {athlete_id}"},
                            status=400)
        created.append(AthleteReferenceMax(
            athlete_id=athlete_id, exercise_id=exercise_id,
            reference_weight_lbs=weight, rep_basis=entry.get("rep_basis", rep_basis),
            source=AthleteReferenceMax.SOURCE_MANUAL,
        ))
    AthleteReferenceMax.objects.bulk_create(created)

    return Response({
        "exercise_id": exercise_id,
        "recorded": [{"athlete_id": m.athlete_id,
                      "reference_weight_lbs": m.reference_weight_lbs,
                      "rep_basis": m.rep_basis} for m in created],
    }, status=201)


@api_view(["GET"])
@permission_classes([IsCoach])
def report_pdf_view(request, report_id):
    """Coach-only: the same finished day, as a printable PDF.

    Coaches hand these to athletes and staff who are nowhere near a tablet, so
    the PDF renders from the SAME frozen snapshot the JSON detail view reads —
    a printout and the screen can never disagree. ?athlete={id} narrows it to
    one athlete's copy.
    """
    report = DailyReport.objects.filter(id=report_id).first()
    if report is None:
        return Response({"error": "report not found"}, status=404)

    athlete_id = request.query_params.get("athlete")
    try:
        detail = athlete_report_detail(report, athlete_id) if athlete_id else report_detail(report)
    except AthleteNotInReport:
        return Response({"code": "athlete_not_in_report",
                         "detail": "That athlete has no record in this report."}, status=404)

    try:
        pdf_bytes = render_report_pdf(detail)
    except PdfTooLarge:
        # A day so large it would produce an unusable document. Better a clear
        # refusal than a multi-hundred-page download that times out the tablet.
        return Response({"error": "report is too large to render as a PDF"}, status=413)

    filename = f"report-{report.id}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    return response


# ─────────────────────────── planning: TrainingGroups, templates, plans ───────────────────────────
#
# Route names here match what the coach front end already calls, even where our
# model names differ (its "workout-programs" are our reusable TrainingBlocks).
# Bending the URLs to the existing client is deliberate — canon §3.3.

@api_view(["GET", "POST"])
@permission_classes([IsCoach])
def training_groups_view(request):
    """Coach-only: list or create TrainingGroups.

    A TrainingGroup is a NAMED SUBSET of athletes who train the same plan — not the whole
    roster. A gym runs several at once (a team TrainingGroup, a position TrainingGroup, a
    rehab group), and an athlete can be in more than one.

    Staff are a LIST, not a field: see `training_group_coaches_view`. Whoever
    creates a group becomes its head coach, because a group with no staff at all
    is never what someone meant to make.
    """
    if request.method == "GET":
        return Response(TrainingGroupSerializer(
            TrainingGroup.objects.prefetch_related("coach_links__coach").order_by("name"),
            many=True).data)

    form = TrainingGroupSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    with transaction.atomic():
        group = form.save()
        TrainingGroupCoach.objects.create(
            training_group=group, coach=request.user, role=TrainingGroupCoach.HEAD)
    return Response(TrainingGroupSerializer(group).data, status=201)


@api_view(["GET", "POST", "PATCH", "DELETE"])
@permission_classes([IsCoach])
def training_group_coaches_view(request, group_id):
    """Coach-only: who runs this TrainingGroup.

    This replaced a single `coach` field on the group in P11, because a real
    weight room puts several staff on one group and one field can only name one
    of them.

      GET    -> the staff list
      POST   -> add someone:    { "coach": 4, "role": "assistant" }
      PATCH  -> change a role:  { "coach": 4, "role": "head" }
      DELETE -> remove someone: { "coach": 4 }

    ⚠️ Being on this list is a STATEMENT, not a permission. Nothing here is
    consulted when deciding whether a write is allowed — `IsCoach` still means
    "is authenticated". That is the canon's filter-not-fence decision, and it is
    deliberate: recording who runs what is useful on its own, and enforcement can
    be added later on top of this without undoing any of it.
    """
    group = TrainingGroup.objects.filter(id=group_id).first()
    if group is None:
        return Response({"error": "training group not found"}, status=404)

    if request.method == "GET":
        return Response(TrainingGroupCoachSerializer(
            group.coach_links.select_related("coach").order_by("role", "coach__username"),
            many=True).data)

    coach_id = request.data.get("coach")
    if not User.objects.filter(id=coach_id).exists():
        return Response({"error": "coach not found"}, status=400)

    if request.method == "DELETE":
        removed, _ = group.coach_links.filter(coach_id=coach_id).delete()
        if not removed:
            return Response({"error": "that coach does not run this group"}, status=404)
        # A group with no staff is allowed rather than blocked: the sequence
        # "swap the head coach" is easier to get right if removing the old one
        # first is legal. It shows as head_coach: null until someone is added.
        return Response(TrainingGroupCoachSerializer(
            group.coach_links.select_related("coach"), many=True).data)

    role = request.data.get("role") or TrainingGroupCoach.ASSISTANT
    if role not in dict(TrainingGroupCoach.ROLE_CHOICES):
        return Response({"error": "role must be 'head' or 'assistant'"}, status=400)

    with transaction.atomic():
        if role == TrainingGroupCoach.HEAD:
            # Only one head at a time. Demoting the incumbent rather than
            # refusing means "make Mike the head" is one call, which is how a
            # coach thinks about it — and it cannot leave two heads behind.
            group.coach_links.filter(role=TrainingGroupCoach.HEAD).exclude(
                coach_id=coach_id).update(role=TrainingGroupCoach.ASSISTANT)

        if request.method == "PATCH":
            link = group.coach_links.filter(coach_id=coach_id).first()
            if link is None:
                return Response({"error": "that coach does not run this group"}, status=404)
            link.role = role
            link.save(update_fields=["role"])
        else:
            # update_or_create, not create: adding someone already on the list is
            # a role change in disguise, and the unique constraint would
            # otherwise turn an ordinary click into a 500.
            TrainingGroupCoach.objects.update_or_create(
                training_group=group, coach_id=coach_id, defaults={"role": role})

    return Response(TrainingGroupCoachSerializer(
        group.coach_links.select_related("coach").order_by("role", "coach__username"),
        many=True).data, status=200 if request.method == "PATCH" else 201)


@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsCoach])
def training_group_athletes_view(request, group_id):
    """Coach-only: who is in this TrainingGroup.

    POST adds, DELETE removes; both take {"athletes": [ids]}. Membership is
    current-state only — taking someone out never rewrites what they already
    trained, because history lives on the sets they actually did.
    """
    group = TrainingGroup.objects.filter(id=group_id).first()
    if group is None:
        return Response({"error": "training group not found"}, status=404)

    if request.method == "GET":
        return Response(AthleteSerializer(group.athletes.order_by("name"), many=True).data)

    ids = request.data.get("athletes")
    if not isinstance(ids, list) or not ids:
        return Response({"error": "athletes must be a non-empty list of ids"}, status=400)
    athletes = Athlete.objects.filter(id__in=ids)
    if athletes.count() != len(set(ids)):
        return Response({"error": "one or more athletes not found"}, status=404)

    if request.method == "POST":
        group.athletes.add(*athletes)
    else:
        group.athletes.remove(*athletes)
    return Response(AthleteSerializer(group.athletes.order_by("name"), many=True).data)


@api_view(["GET", "POST"])
@permission_classes([IsCoach])
def training_blocks_view(request):
    """Coach-only: the reusable TEMPLATES a coach designs once and redeploys.

    A TrainingBlock has no TrainingGroup and no dates — it is the recipe, not a
    serving of it.

    Blocks are GLOBAL ON PURPOSE. The whole department can see and reuse every
    one, because a good block getting reused is the point of a shared catalog.
    So `?coach=` is a LENS, NOT A FENCE — it exists so nobody scrolls a
    department-sized list to find their own work, and the full list is always
    one request away. It grants nothing and forbids nothing.

      GET /api/training-blocks/                    -> every block (default)
      GET /api/training-blocks/?coach=me           -> only the caller's
      GET /api/training-blocks/?coach=4            -> only that coach's
      GET /api/training-blocks/?category=2         -> only blocks with that label
      GET /api/training-blocks/?category=2&category=5  -> EITHER label (any-of)
      GET /api/training-blocks/?sort=recent        -> most recently EDITED first

    Several `category` values mean ANY-OF, not all-of, because the labels sit on
    different axes — "Off-season" and "Football" are not competing answers to one
    question, and asking for both meaning "must be both" would usually return
    nothing. Any-of matches how a filter bar with checkboxes reads.

    `sort=recent` orders by `updated_at`, which P10 maintains whenever anyone
    edits a block's days or rows. Default order stays alphabetical, because a
    catalog you are browsing rather than resuming reads better by name.
    """
    if request.method == "GET":
        blocks = TrainingBlock.objects.prefetch_related("workouts__exercises", "categories")

        coach = request.query_params.get("coach")
        if coach == "me":
            blocks = blocks.filter(coach=request.user)
        elif coach:
            if not coach.isdigit():
                return Response({"error": "coach must be a coach id or 'me'"}, status=400)
            blocks = blocks.filter(coach_id=int(coach))

        categories = request.query_params.getlist("category")
        if categories:
            if not all(value.isdigit() for value in categories):
                return Response({"error": "category must be a category id"}, status=400)
            # A join across a many-to-many repeats a row once per match, so a
            # block carrying two of the requested labels would otherwise be
            # listed twice.
            blocks = blocks.filter(categories__id__in=[int(v) for v in categories]).distinct()

        order = "-updated_at" if request.query_params.get("sort") == "recent" else "name"
        return Response(TrainingBlockSerializer(blocks.order_by(order), many=True).data)

    form = TrainingBlockSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    return Response(TrainingBlockSerializer(form.save(coach=request.user)).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsCoach])
def training_block_detail(request, block_id):
    """Coach-only: read or amend one block's own fields.

    This exists because categories would otherwise be write-once. Every block
    that already existed before P11 has no labels, and with create-only routes
    there would be no way to give it any — the feature would only ever apply to
    blocks made after it shipped.

    PATCH covers the block's OWN fields (name, categories, duration, cadence).
    The days and rows inside it have their own routes from P10.

    ⚠️ There is deliberately NO DELETE here. Nothing in the product deletes a
    whole block, and the canon's reasoning for `?coach=` being a filter rather
    than a permission fence rests partly on that. Adding one is a real decision,
    not a convenience — make it on purpose.
    """
    block = TrainingBlock.objects.filter(id=block_id).first()
    if block is None:
        return Response({"error": "training block not found"}, status=404)

    if request.method == "GET":
        return Response(TrainingBlockSerializer(block).data)

    form = TrainingBlockSerializer(block, data=request.data, partial=True)
    form.is_valid(raise_exception=True)
    # auto_now on `updated_at` fires here, so amending a block's own fields
    # counts as editing it — same as editing a day inside it.
    return Response(TrainingBlockSerializer(form.save()).data)


@api_view(["GET", "POST"])
@permission_classes([IsCoach])
def block_categories_view(request):
    """Coach-only: the catalog's label vocabulary — "Off-season", "Football".

    Shared by the whole department on purpose: the labels are only useful if
    everyone files things under the same words. Names are unique, so a second
    attempt at one that exists comes back 400 rather than quietly creating a
    near-duplicate.
    """
    if request.method == "GET":
        return Response(BlockCategorySerializer(
            BlockCategory.objects.order_by("name"), many=True).data)

    form = BlockCategorySerializer(data=request.data)
    form.is_valid(raise_exception=True)
    return Response(BlockCategorySerializer(form.save()).data, status=201)


@api_view(["GET", "POST"])
@permission_classes([IsCoach])
def training_block_workouts_view(request, block_id):
    """Coach-only: the individual days inside a template, and their movements.

    The block is in the URL rather than the body, because a day cannot exist
    without one — nesting says that in the address instead of leaving it as a
    field a caller could forget.

    POST accepts a whole day at once — its name, its position in the block, and
    the movements in order — because a coach thinks in days, not in rows:

        POST /api/training-blocks/1/workouts/
        { "name": "Day 1 — Lower", "position": 1,
          "exercises": [ {"exercise": 3, "sets": 5, "reps": 3, "target_percent": 80} ] }

    Writing the day in one call also means a half-entered workout can't exist.
    """
    block = TrainingBlock.objects.filter(id=block_id).first()
    if block is None:
        return Response({"error": "training block not found"}, status=404)

    if request.method == "GET":
        workouts = block.workouts.prefetch_related("exercises").order_by("position")
        return Response(TrainingBlockWorkoutSerializer(workouts, many=True).data)

    rows = request.data.get("exercises") or []
    with transaction.atomic():
        workout = TrainingBlockWorkout.objects.create(
            training_block=block,
            name=request.data.get("name") or "Workout",
            position=request.data.get("position") or (block.workouts.count() + 1),
        )
        for position, row in enumerate(rows, start=1):
            if not Exercise.objects.filter(id=row.get("exercise")).exists():
                raise ValueError(f"exercise {row.get('exercise')} not found")
            TrainingBlockExercise.objects.create(
                training_block_workout=workout,
                exercise_id=row["exercise"],
                position=row.get("position") or position,
                sets=row.get("sets") or 1,
                reps=row.get("reps") or 1,
                target_percent=row.get("target_percent"),
                velocity_zone_min=row.get("velocity_zone_min"),
                velocity_zone_max=row.get("velocity_zone_max"),
            )
    touch_block(block.id)
    return Response(TrainingBlockWorkoutSerializer(workout).data, status=201)


# ─────────────────── editing a template (P10) ───────────────────
#
# A template you can write but never change is a template you rewrite from
# scratch over one typo. Everything below edits the BLOCK side only.
#
# ⚠️ None of it can reach a deployed TrainingProgram. Program rows carry no
# foreign key back to block rows — they were copied down at deploy time — so
# deleting a day from a template cannot remove it from a group that is
# currently training it. That independence is deliberate and load-bearing.

def _block_workout(block_id, workout_id):
    """One day, confirmed to be inside the block named in the URL.

    Checking the parent matters: without it, /training-blocks/1/workouts/99/
    would happily edit a day belonging to block 2.
    """
    return TrainingBlockWorkout.objects.filter(
        id=workout_id, training_block_id=block_id).first()


@api_view(["PATCH", "DELETE"])
@permission_classes([IsCoach])
def training_block_workout_detail(request, block_id, workout_id):
    """Coach-only: rename or remove one day in a template.

    Deleting takes its prescription rows with it (they cannot outlive the day
    they belong to) but leaves every deployed program untouched.
    """
    workout = _block_workout(block_id, workout_id)
    if workout is None:
        return Response({"error": "workout not found in this block"}, status=404)

    if request.method == "DELETE":
        workout.delete()
        touch_block(block_id)
        return Response(status=204)

    name = request.data.get("name")
    if name is not None:
        if not str(name).strip():
            return Response({"code": "invalid_name",
                             "detail": "A day needs a name."}, status=400)
        workout.name = str(name).strip()
        workout.save(update_fields=["name"])
        touch_block(block_id)
    return Response(TrainingBlockWorkoutSerializer(workout).data)


@api_view(["PUT"])
@permission_classes([IsCoach])
def training_block_workout_order(request, block_id):
    """Coach-only: set the order of the days in a template.

    Takes the WHOLE list — {"workout_ids": [12, 9, 14]} — not one day at a time.
    See services/planning.apply_order for why that is the only shape that works
    against a non-deferrable position constraint, and why it is the better API
    regardless.
    """
    block = TrainingBlock.objects.filter(id=block_id).first()
    if block is None:
        return Response({"error": "training block not found"}, status=404)

    ids = request.data.get("workout_ids")
    if not isinstance(ids, list):
        return Response({"code": "invalid_order",
                         "detail": "Send workout_ids as a list."}, status=400)
    try:
        apply_order(block.workouts.all(), ids)
    except ValueError as problem:
        # Naming a subset would silently drop days out of the order, so the whole
        # list is required and a mismatch is refused rather than half-applied.
        return Response({"code": "invalid_order", "detail": str(problem)}, status=400)

    touch_block(block_id)
    return Response(TrainingBlockWorkoutSerializer(
        block.workouts.prefetch_related("exercises").order_by("position"), many=True).data)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsCoach])
def training_block_exercise_detail(request, block_id, workout_id, exercise_id):
    """Coach-only: change or remove one prescribed movement in a template day."""
    workout = _block_workout(block_id, workout_id)
    if workout is None:
        return Response({"error": "workout not found in this block"}, status=404)
    row = workout.exercises.filter(id=exercise_id).first()
    if row is None:
        return Response({"error": "exercise row not found in this workout"}, status=404)

    if request.method == "DELETE":
        row.delete()
        touch_block(block_id)
        return Response(status=204)

    # Only the prescription itself is editable here. `position` is deliberately
    # NOT: reordering is a whole-list operation, and letting it in through the
    # back door is exactly what breaks against the unique constraint.
    fields = {}
    for field in ("sets", "reps", "target_percent", "velocity_zone_min", "velocity_zone_max"):
        if field in request.data:
            fields[field] = request.data[field]
    if "exercise" in request.data:
        if not Exercise.objects.filter(id=request.data["exercise"]).exists():
            return Response({"error": "exercise not found"}, status=404)
        fields["exercise_id"] = request.data["exercise"]
    if not fields:
        return Response({"code": "nothing_to_change",
                         "detail": "Send at least one field to change."}, status=400)

    for name, value in fields.items():
        setattr(row, name, value)
    row.save(update_fields=list(fields))
    touch_block(block_id)
    return Response(TrainingBlockExerciseSerializer(row).data)


@api_view(["PUT"])
@permission_classes([IsCoach])
def training_block_exercise_order(request, block_id, workout_id):
    """Coach-only: set the order of the movements inside one template day."""
    workout = _block_workout(block_id, workout_id)
    if workout is None:
        return Response({"error": "workout not found in this block"}, status=404)

    ids = request.data.get("exercise_ids")
    if not isinstance(ids, list):
        return Response({"code": "invalid_order",
                         "detail": "Send exercise_ids as a list."}, status=400)
    try:
        apply_order(workout.exercises.all(), ids)
    except ValueError as problem:
        return Response({"code": "invalid_order", "detail": str(problem)}, status=400)

    touch_block(block_id)
    return Response(TrainingBlockExerciseSerializer(
        workout.exercises.order_by("position"), many=True).data)


@api_view(["GET", "POST"])
@permission_classes([IsCoach])
def training_programs_view(request):
    """Coach-only: a template DEPLOYED for a TrainingGroup, starting on a date.

    Two ways to create one, both first-class:
      with "training_block"    — copy that template down for this TrainingGroup
      without "training_block" — a one-off plan authored directly for the TrainingGroup,
                                 no template involved.

    Turning a program back INTO a reusable template is
    `POST training-programs/{id}/promote/` — and it copies the days and rows up,
    because pointing `training_block` at a new block would only record provenance
    and leave the block empty.
    """
    if request.method == "GET":
        programs = TrainingProgram.objects.select_related("training_group") \
                                          .prefetch_related("workouts__exercises")
        group_id = request.query_params.get("training_group")
        if group_id:
            programs = programs.filter(training_group_id=group_id)
        return Response(TrainingProgramSerializer(programs.order_by("-start_date"), many=True).data)

    group = TrainingGroup.objects.filter(id=request.data.get("training_group")).first()
    if group is None:
        return Response({"error": "training group not found"}, status=404)

    block_id = request.data.get("training_block")
    if block_id:
        block = TrainingBlock.objects.filter(id=block_id).first()
        if block is None:
            return Response({"error": "training block not found"}, status=404)
        # ⚠️ PARSE THE DATES HERE. They arrive as strings, and Django only coerces
        # them on the way into the database — the in-memory instance keeps the
        # string. That was invisible until P14, when the schedule generator
        # started doing arithmetic on `program.start_date` and got
        # "can only concatenate str to str" on every deploy through the API.
        # Every P14 test passed real `date` objects, so none of them caught it.
        dates = {}
        for field in ("start_date", "end_date"):
            raw = request.data.get(field)
            if raw in (None, ""):
                dates[field] = None
                continue
            parsed = parse_date(raw) if isinstance(raw, str) else raw
            if parsed is None:
                return Response({"error": f"{field} must be a date (YYYY-MM-DD)"},
                                status=400)
            dates[field] = parsed

        if dates["start_date"] is None:
            return Response({"error": "start_date is required to deploy a block"},
                            status=400)

        program = instantiate_block(
            block, group,
            name=request.data.get("name"),
            start_date=dates["start_date"],
            end_date=dates["end_date"],
        )
        return Response(TrainingProgramSerializer(program).data, status=201)

    form = TrainingProgramSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    return Response(TrainingProgramSerializer(form.save()).data, status=201)


@api_view(["POST"])
@permission_classes([IsCoach])
def training_program_promote(request, program_id):
    """Coach-only: turn this program into a new reusable TrainingBlock.

    For the plan a coach tuned until it was better than the template it came
    from — or wrote from scratch for one group and now wants to run again.

    Body: `{ "name": "Fall Strength v2" }` — optional, defaults to the program's
    own name.

    ⚠️ This COPIES the days and prescription rows up into the new block. It is not
    a matter of pointing `training_block` at a fresh row: that records provenance
    and copies nothing, so the block would come out empty and deploying it would
    hand a group a plan with no movements in it.

    The program itself is unchanged apart from its `training_block` now naming
    the block it is a deployment of.
    """
    program = (TrainingProgram.objects
               .filter(id=program_id)
               .prefetch_related("workouts__exercises").first())
    if program is None:
        return Response({"error": "training program not found"}, status=404)

    if not program.workouts.exists():
        # A block with no days is the exact failure this endpoint exists to
        # prevent, so refusing here is more honest than creating one.
        return Response({
            "error": "this program has no days to promote",
            "detail": "Add at least one day to the program before making a block from it.",
        }, status=400)

    name = (request.data.get("name") or "").strip() or None
    block = promote_program_to_block(program, coach=request.user, name=name)
    return Response(TrainingBlockSerializer(block).data, status=201)


@api_view(["GET"])
@permission_classes([IsCoach])
def scheduled_sessions_view(request):
    """Coach-only: the calendar — planned training slots.

    A slot says "this program's Day 2, on the 14th". It is a PLAN: `session` is
    null until a coach creates that day (see `scheduled_session_create_session`).

      GET /api/scheduled-sessions/                     -> every slot
      GET /api/scheduled-sessions/?training_program=3  -> one program's calendar
      GET /api/scheduled-sessions/?training_group=2    -> one group's
      GET /api/scheduled-sessions/?from=2026-08-01&to=2026-08-31  -> a date window
      GET /api/scheduled-sessions/?unrun=true          -> only slots with no session

    Slots are generated when a block is deployed and are FROZEN after that (canon
    D20) — there is deliberately no POST here. A calendar you can hand-append to
    would drift from the block that produced it, and "where did this extra
    Tuesday come from" is not a question worth creating.
    """
    slots = ScheduledSession.objects.select_related(
        "training_program__training_group", "training_program_workout", "session")

    program_id = request.query_params.get("training_program")
    if program_id:
        if not program_id.isdigit():
            return Response({"error": "training_program must be an id"}, status=400)
        slots = slots.filter(training_program_id=int(program_id))

    group_id = request.query_params.get("training_group")
    if group_id:
        if not group_id.isdigit():
            return Response({"error": "training_group must be an id"}, status=400)
        slots = slots.filter(training_program__training_group_id=int(group_id))

    # A calendar screen asks for the month it is showing; without a window it
    # would pull every slot of every program ever deployed.
    for param, lookup in (("from", "date__gte"), ("to", "date__lte")):
        raw = request.query_params.get(param)
        if raw:
            parsed = parse_date(raw)
            if parsed is None:
                return Response({"error": f"{param} must be a date (YYYY-MM-DD)"},
                                status=400)
            slots = slots.filter(**{lookup: parsed})

    if request.query_params.get("unrun", "").lower() in {"1", "true", "yes"}:
        slots = slots.filter(session__isnull=True)

    return Response(ScheduledSessionSerializer(slots.order_by("date", "id"), many=True).data)


@api_view(["GET", "PATCH"])
@permission_classes([IsCoach])
def scheduled_session_detail(request, slot_id):
    """Coach-only: read a slot, or MOVE it to another date.

    Moving is a single `date` write and regenerates nothing — that is the whole
    design (canon D20). The rest of a slot is decided when the schedule is
    generated and is read-only here.

    ⚠️ A slot whose session has already been created can still be moved, and that
    is deliberate: the coach is correcting the calendar, and the session keeps its
    own real start time regardless. The plan and the record are separate things.
    """
    slot = ScheduledSession.objects.filter(id=slot_id).select_related(
        "training_program__training_group", "training_program_workout", "session").first()
    if slot is None:
        return Response({"error": "scheduled session not found"}, status=404)

    if request.method == "GET":
        return Response(ScheduledSessionSerializer(slot).data)

    form = ScheduledSessionSerializer(slot, data=request.data, partial=True)
    form.is_valid(raise_exception=True)

    # One slot per program per day is a database constraint, so a clash would
    # otherwise surface as a 500. Saying which date is taken is more useful than
    # "integrity error".
    new_date = form.validated_data.get("date", slot.date)
    clash = (ScheduledSession.objects
             .filter(training_program_id=slot.training_program_id, date=new_date)
             .exclude(id=slot.id).first())
    if clash is not None:
        return Response({
            "error": "that program already trains on that date",
            "detail": f"{clash.training_program_workout.name} is already scheduled "
                      f"for {new_date.isoformat()}.",
        }, status=409)

    return Response(ScheduledSessionSerializer(form.save()).data)


@api_view(["POST"])
@permission_classes([IsCoach])
def scheduled_session_create_session(request, slot_id):
    """Coach-only: turn a planned slot into a real training session.

    ⚠️ CREATE IS NOT START. The session comes back with `started_at: null` — it
    exists, it is linked to the slot, its roster and participation are set up, and
    it holds no racks and captures no check-ins until someone starts it. That is
    the point of P14: a coach can set Thursday up on Tuesday.

    The roster is the group's current members, and a SessionParticipation row
    points the group at the day this slot runs — the two things that were being
    done by hand in the seed command and by no UI at all.

    Idempotent: a slot that already has a session returns it rather than making a
    second one. Two taps on a calendar must not produce two Thursdays.
    """
    slot = ScheduledSession.objects.filter(id=slot_id).select_related(
        "training_program__training_group", "training_program_workout", "session").first()
    if slot is None:
        return Response({"error": "scheduled session not found"}, status=404)

    if slot.session_id is not None:
        return Response(ScheduledSessionSerializer(slot).data, status=200)

    group = slot.training_program.training_group
    athletes = list(group.athletes.all())

    with transaction.atomic():
        session = TrainingSession.objects.create(
            # Named for the day it runs, not for a weekday — a slot can be moved.
            label=request.data.get("label") or f"{slot.training_program_workout.name} · {slot.date.isoformat()}",
            started_at=None,   # created, NOT started — see the docstring
        )
        if athletes:
            session.athletes.set(athletes)
        SessionParticipation.objects.create(
            session=session,
            training_program=slot.training_program,
            training_program_workout=slot.training_program_workout,
        )
        slot.session = session
        slot.save(update_fields=["session"])

    slot.refresh_from_db()
    return Response(ScheduledSessionSerializer(slot).data, status=201)


@api_view(["POST"])
@permission_classes([IsCoach])
def session_start(request, session_id):
    """Coach-only: start a session that was created ahead of time.

    Its own route rather than a PATCH, deliberately. `PATCH /api/sessions/{id}/`
    with an empty body already means "END the day now" (canon R2), so making start
    another PATCH would leave one call's meaning resting on subtle differences in
    the body — for two actions that are opposites. Ending is still the PATCH;
    starting is this.

    Refuses (409) while another day is already running, for exactly the reasons in
    `sessions_view`: the racks follow the active session, so a second one silently
    captures check-ins.
    """
    session = TrainingSession.objects.filter(id=session_id).first()
    if session is None:
        return Response({"error": "session not found"}, status=404)

    if session.ended_at is not None:
        return Response({"error": "that training day has already ended"}, status=409)

    if session.started_at is not None:
        # Idempotent: already running is the state the caller wanted.
        return Response(TrainingSessionSerializer(session).data, status=200)

    running = active_session()
    if running is not None:
        return Response({
            "error": "a training day is already open",
            "open_session": {"id": running.id, "label": running.label,
                             "started_at": running.started_at},
            "detail": f"End '{running.label}' before starting another day.",
        }, status=409)

    session.started_at = timezone.now()
    session.save(update_fields=["started_at"])
    # Tell the room a day has begun.
    #
    # THIS WAS MISSING, and the symptom was completely unlike the cause: the wall
    # display stayed on "no active session" after a coach started one, and only a
    # manual reload fixed it. Ending a day already emitted an event, so ending
    # worked and starting did not — which reads like the display being flaky rather
    # than a mutation that never announced itself.
    #
    # Screens do not poll; they refetch when told something changed (see the
    # invalidation decision in docs/journal/rack-tablet.md). That design is only as
    # complete as its emitters, and it fails silently by showing correct-looking
    # stale data. Any mutation the room can see needs one of these, in the same
    # transaction as the change.
    MonitoringEvent.objects.create(
        reason="session_started",
        is_simulated=session.is_simulated,
    )
    return Response(TrainingSessionSerializer(session).data)


@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsCoach])
def session_participation_view(request, session_id):
    """Coach-only: which TrainingGroups are training in this session, and what they're doing.

    This is what makes one session shared. Several TrainingGroups can be in the gym at
    the same time on different plans, and each athlete gets their own TrainingGroup's
    workout — which is exactly how an athlete in two TrainingGroups ends up doing both.

    POST body: { "training_program": 1, "training_program_workout": 4 }
    The workout is the day being run. Until it is set, that TrainingGroup has nothing
    scheduled and its athletes see an empty list — a planning gap, not an error.
    """
    session = TrainingSession.objects.filter(id=session_id).first()
    if session is None:
        return Response({"error": "session not found"}, status=404)

    def current():
        return [{
            "id": p.id,
            "training_program": p.training_program_id,
            "program_name": p.training_program.name,
            "group_name": p.training_program.training_group.name,
            "training_program_workout": p.training_program_workout_id,
            "workout_name": p.training_program_workout.name if p.training_program_workout else None,
        } for p in SessionParticipation.objects
            .filter(session=session)
            .select_related("training_program__training_group", "training_program_workout")]

    if request.method == "GET":
        return Response(current())

    program = TrainingProgram.objects.filter(id=request.data.get("training_program")).first()
    if program is None:
        return Response({"error": "training program not found"}, status=404)

    if request.method == "DELETE":
        SessionParticipation.objects.filter(session=session, training_program=program).delete()
        return Response(current())

    workout_id = request.data.get("training_program_workout")
    if workout_id and not TrainingProgramWorkout.objects.filter(
            id=workout_id, training_program=program).exists():
        return Response({"error": "workout does not belong to that program"}, status=400)

    SessionParticipation.objects.update_or_create(
        session=session, training_program=program,
        defaults={"training_program_workout_id": workout_id},
    )
    return Response(current(), status=201)


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsCoach])
def athlete_exercise_override_view(request, athlete_id, exercise_id):
    """Coach-only: an exception for one athlete on one prescribed movement.

    For the outlier the TrainingGroup percentage doesn't suit — someone coming back from
    injury, or a lifter whose bench is far behind their squat. It overrides the
    PERCENTAGE, never a fixed weight, so their number still tracks their own max
    instead of freezing in place.

    `exercise_id` here is the program-exercise row being overridden (the specific
    line in that TrainingGroup's plan), not the catalog movement.

    Most athletes never need one of these. It is an escape hatch, not the path.
    """
    athlete = Athlete.objects.filter(id=athlete_id).first()
    if athlete is None:
        return Response({"error": "athlete not found"}, status=404)
    row = TrainingProgramExercise.objects.filter(id=exercise_id).first()
    if row is None:
        return Response({"error": "program exercise not found"}, status=404)

    if request.method == "DELETE":
        AthleteWorkoutExerciseOverride.objects.filter(
            athlete=athlete, training_program_exercise=row).delete()
        return Response(status=204)

    existing = AthleteWorkoutExerciseOverride.objects.filter(
        athlete=athlete, training_program_exercise=row).first()

    if request.method == "GET":
        if existing is None:
            return Response({"athlete": athlete_id, "training_program_exercise": exercise_id,
                             "target_percent": None, "sets": None, "reps": None})
        return Response({"athlete": athlete_id, "training_program_exercise": exercise_id,
                         "target_percent": existing.target_percent,
                         "sets": existing.sets, "reps": existing.reps})

    fields = {k: request.data.get(k) for k in ("target_percent", "sets", "reps")}
    if all(v is None for v in fields.values()):
        return Response({"error": "set at least one of target_percent, sets, reps"}, status=400)

    override, _ = AthleteWorkoutExerciseOverride.objects.update_or_create(
        athlete=athlete, training_program_exercise=row, defaults=fields)
    return Response({"athlete": athlete_id, "training_program_exercise": exercise_id,
                     "target_percent": override.target_percent,
                     "sets": override.sets, "reps": override.reps})


# ─────────────────────────── CSV import (D16/D17) ───────────────────────────


def _import_target(request):
    """Work out where an upload is going, from the form fields sent with it.

    Returns (target, kind, scope_group, error_response). A max sheet or roster
    may name a TrainingGroup so duplicate names can be told apart by who is actually in
    it; a plan MUST name a template or a TrainingGroup, because there is nowhere else to
    put workouts.
    """
    block_id = request.data.get("training_block")
    program_id = request.data.get("training_program")
    group_id = request.data.get("training_group")

    if block_id and program_id:
        return None, None, None, Response(
            {"code": "ambiguous_target",
             "detail": "Send training_block or training_program, not both."}, status=400)

    if block_id:
        block = TrainingBlock.objects.filter(id=block_id).first()
        if block is None:
            return None, None, None, Response({"error": "training block not found"}, status=404)
        return block, "block", None, None

    if program_id:
        program = TrainingProgram.objects.filter(id=program_id).select_related("training_group").first()
        if program is None:
            return None, None, None, Response({"error": "training program not found"}, status=404)
        return program, "program", program.training_group, None

    group = None
    if group_id:
        group = TrainingGroup.objects.filter(id=group_id).first()
        if group is None:
            return None, None, None, Response({"error": "training group not found"}, status=404)
    return None, None, group, None


def _import_corrections(request):
    """The coach's answers to "who did you mean?", sent back with the file.

    Returns (corrections, error_response). Arrives as a JSON string because the
    upload is multipart form data, not a JSON body. A malformed value is
    reported rather than ignored — silently dropping corrections would re-raise
    the errors the coach just fixed, and look like their fix didn't take.
    """
    raw = request.data.get("corrections")
    if not raw:
        return None, None
    if isinstance(raw, dict):
        return raw, None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None, Response({"code": "invalid_corrections",
                               "detail": "Corrections must be valid JSON."}, status=400)
    if not isinstance(parsed, dict):
        return None, Response({"code": "invalid_corrections",
                               "detail": "Corrections must be an object keyed by kind."}, status=400)
    return parsed, None


def _import_response(sheet_type, payload, errors, skipped, *, created=None):
    """One response shape for both preview and import.

    `rows` is always present, even alongside errors — that is what lets the coach
    screen show their own spreadsheet back with the bad cells marked instead of
    just refusing the file (canon D17c).
    """
    body = {
        "sheet_type": sheet_type,
        "rows": payload,
        "errors": errors,
        "skipped": skipped,
        "counts": {
            "ready": len(payload) if sheet_type != "plan" else sum(
                len(w["exercises"]) for w in payload),
            "errors": len(errors),
            "skipped": len(skipped),
        },
    }
    if created is not None:
        body["created"] = created
    return Response(body, status=400 if errors else 200)


@api_view(["POST"])
@permission_classes([IsCoach])
@parser_classes([MultiPartParser, FormParser])
def import_preview(request):
    """Check an uploaded spreadsheet and write NOTHING.

    Always the first half of the pair: the coach sees what we understood, fixes
    anything marked wrong, and only then imports. See services/csv_import.py.
    """
    target, kind, scope_group, error = _import_target(request)
    if error is not None:
        return error
    corrections, error = _import_corrections(request)
    if error is not None:
        return error

    sheet_type, payload, errors, skipped = validate_upload(
        request.FILES.get("file"), scope_group=scope_group, corrections=corrections)

    if sheet_type == SHEET_PLAN and target is None and not errors:
        errors = [{"row": None, "field": "training_block", "code": "target_required",
                   "detail": "Choose which template or TrainingGroup plan these workouts belong to."}]
    return _import_response(sheet_type, payload, errors, skipped)


@api_view(["POST"])
@permission_classes([IsCoach])
@parser_classes([MultiPartParser, FormParser])
def import_commit(request):
    """Re-check an uploaded spreadsheet and, if it is clean, save it in one step.

    Re-checked rather than trusting the preview because the gym changes between
    the two calls — an athlete could be renamed, or another coach could import
    the same sheet first. Nothing is saved unless every row passes now.
    """
    target, kind, scope_group, error = _import_target(request)
    if error is not None:
        return error
    corrections, error = _import_corrections(request)
    if error is not None:
        return error

    sheet_type, payload, errors, skipped = validate_upload(
        request.FILES.get("file"), scope_group=scope_group, corrections=corrections)

    if sheet_type == SHEET_PLAN and target is None and not errors:
        errors = [{"row": None, "field": "training_block", "code": "target_required",
                   "detail": "Choose which template or TrainingGroup plan these workouts belong to."}]
    if errors:
        return _import_response(sheet_type, payload, errors, skipped)

    created = commit_upload(sheet_type, payload, target=target, kind=kind)
    return _import_response(sheet_type, payload, errors, skipped, created=created)


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsCoach])
def athlete_program_view(request, athlete_id):
    """What this athlete is training, and which TrainingGroup decides it.

    HIS PAGE ASKS A QUESTION OUR MODEL ANSWERS DIFFERENTLY. His planning screen
    was built where a program is pinned onto one athlete. Here a program belongs
    to a GROUP, and an athlete trains it by being in that TrainingGroup (D12) — which is
    what lets one plan serve thirty people and one athlete carry two plans at
    once (D13). So the route keeps its name and its shape, and the meaning
    underneath is TrainingGroup membership:

        GET     -> every program that currently applies to them, and via which TrainingGroup
        PUT     -> put them in the TrainingGroup that runs this program
        DELETE  -> take them out of the TrainingGroups currently prescribing to them

    Writes therefore have a WIDER effect than the wording suggests, and the
    response says so plainly (`groups_changed`) rather than letting a coach
    discover it later. Both directions are reversible, and neither touches
    history — past sessions and sets stay attached to whatever they ran under.
    """
    athlete = Athlete.objects.filter(id=athlete_id).first()
    if athlete is None:
        return Response({"code": "athlete_not_found", "detail": "Athlete not found."}, status=404)

    if request.method == "PUT":
        program_id = request.data.get("workout_program_id") or request.data.get("training_program")
        program = (TrainingProgram.objects.select_related("training_group")
                   .filter(id=program_id).first())
        if program is None:
            return Response({"code": "training_program_not_found",
                             "detail": "Training program not found."}, status=404)
        athlete.training_groups.add(program.training_group)
        return Response(_assignment_body(athlete, groups_changed=[{
            "id": program.training_group_id, "name": program.training_group.name,
            "action": "added"}]))

    if request.method == "DELETE":
        removed = [{"id": group.id, "name": group.name, "action": "removed"}
                   for group in _groups_prescribing_to(athlete)]
        athlete.training_groups.remove(*[g["id"] for g in removed])
        return Response(_assignment_body(athlete, groups_changed=removed))

    return Response(_assignment_body(athlete))


def _groups_prescribing_to(athlete):
    """The TrainingGroups this athlete is in that actually have a plan attached.

    A TrainingGroup with no program isn't prescribing anything, so removing someone from
    it would be busywork that also loses roster information the coach set up on
    purpose.
    """
    return list(athlete.training_groups.filter(programs__isnull=False).distinct())


def _assignment_body(athlete, groups_changed=None):
    """One athlete's plans, grouped by the TrainingGroup each comes from."""
    programs = (TrainingProgram.objects
                .filter(training_group__athletes=athlete)
                .select_related("training_group", "training_block")
                .prefetch_related("workouts__exercises__exercise")
                .distinct().order_by("start_date", "id"))

    body = {
        "athlete": {"id": athlete.id, "name": athlete.name},
        "assignment": [{
            "training_program": {"id": program.id, "name": program.name,
                                 "start_date": program.start_date,
                                 "end_date": program.end_date},
            "training_group": {"id": program.training_group_id,
                               "name": program.training_group.name},
            "from_template": ({"id": program.training_block_id,
                               "name": program.training_block.name}
                              if program.training_block_id else None),
            "workouts": [{
                "id": workout.id, "name": workout.name, "position": workout.position,
                "exercises": [{
                    "id": row.id,
                    "exercise": {"id": row.exercise_id, "name": row.exercise.name},
                    "position": row.position, "sets": row.sets, "reps": row.reps,
                    "target_percent": row.target_percent,
                    # The pounds this becomes for THIS athlete, since a percent on
                    # its own tells a coach nothing about what goes on the bar.
                    "target_weight_lbs": resolve_target_weight(
                        athlete.id, row.exercise_id, row.target_percent),
                    "velocity_zone_min": row.velocity_zone_min,
                    "velocity_zone_max": row.velocity_zone_max,
                } for row in workout.exercises.all()],
            } for workout in program.workouts.all()],
        } for program in programs],
    }
    if groups_changed is not None:
        body["groups_changed"] = groups_changed
    return body
