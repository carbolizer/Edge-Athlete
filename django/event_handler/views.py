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
    - nodes_list / athletes_view (GET): list the sensors / the lifters.

  COACH-ONLY (needs a coach login):
    - manage athletes, programs, sessions, and nodes; assign racks; and pull
      the analytics summaries.

Open vs coach-only follows SPEC.md; shapes live in MESSAGE_CONTRACT.md.
"""
from datetime import timedelta
import hashlib

from django.db import transaction
from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from .models import Node, RackScreen, Athlete, Program, Session, Set, Rep, MonitoringEvent
from .permissions import IsCoach
from .services.set_completion import complete_set, SetAlreadyComplete, SetNotFound
from .serializers import (SetSerializer, SetCompleteSerializer, RackScreenSerializer,
                          ProgramSerializer, PublicProgramSerializer, AthleteSerializer, PublicAthleteSerializer, SessionSerializer,
                          NodeSerializer)


def _require_coach(request):
    """Small helper for endpoints that are open to read but coach-only to write:
    returns True if the caller is a logged-in coach."""
    return bool(request.user and request.user.is_authenticated and request.user.is_active and request.user.is_staff)


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
@permission_classes([IsCoach])
def rack_assign(request, device_id):
    """Coach-only: give a waiting tablet its rack number. Body: { rack_number }."""
    screen = RackScreen.objects.filter(device_id=device_id).first()
    if screen is None:
        return Response({"error": "rack screen not found"}, status=404)
    rack_number = request.data.get("rack_number")
    if rack_number is None:
        return Response({"error": "rack_number is required"}, status=400)
    screen.rack_number = rack_number
    screen.save()
    return Response(RackScreenSerializer(screen).data)


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


def _room_state_snapshot(include_details):
    """Build a bounded persisted snapshot for a wall or authenticated coach."""
    # Read the revision first. A later commit can make snapshot data newer than
    # this cursor, but its retained event will then force another reconciliation.
    revision = MonitoringEvent.objects.order_by("-id").values_list("id", flat=True).first() or 0
    active_sessions = Session.objects.filter(ended_at__isnull=True).order_by("-started_at", "-id")
    active_session = active_sessions.first()

    node_racks = Node.objects.exclude(rack_number=None).values_list("rack_number", flat=True).distinct()[:MAX_DASHBOARD_RACKS]
    screen_racks = RackScreen.objects.exclude(rack_number=None).values_list("rack_number", flat=True).distinct()[:MAX_DASHBOARD_RACKS]
    session_racks = Set.objects.none().values_list("rack_number", flat=True)
    if active_session:
        session_racks = Set.objects.filter(session=active_session).exclude(rack_number=None).values_list("rack_number", flat=True).distinct()[:MAX_DASHBOARD_RACKS]
    all_rack_numbers = sorted(set(node_racks) | set(screen_racks) | set(session_racks))
    rack_numbers = all_rack_numbers[:MAX_DASHBOARD_RACKS]
    nodes = list(Node.objects.filter(rack_number__in=rack_numbers).order_by("rack_number", "node_id"))
    screen_counts = dict(
        RackScreen.objects.filter(rack_number__in=rack_numbers)
        .values_list("rack_number")
        .annotate(count=Count("id"))
    )

    latest_sets_by_rack = {}
    active_sets_by_rack = {}
    unassigned_session_sets = 0
    session_sets = Set.objects.none()
    if active_session:
        session_sets = Set.objects.filter(session=active_session)
        latest_sets = (
            session_sets.filter(rack_number__in=rack_numbers, ended_at__isnull=False)
            .select_related("athlete", "node")
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
                program = Program.objects.filter(
                    athlete=latest_set.athlete,
                    exercise=latest_set.exercise,
                ).order_by("-id").first()
                latest_set_body.update({
                    "id": latest_set.id,
                    "athlete": {"id": latest_set.athlete_id, "name": latest_set.athlete.name},
                    "weight_lbs": latest_set.weight_lbs,
                    "started_at": latest_set.started_at,
                    "ended_at": latest_set.ended_at,
                    "is_false_set": latest_set.is_false_set,
                    "target_zone": {
                        "min": program.velocity_zone_min,
                        "max": program.velocity_zone_max,
                    } if program else None,
                    "reps": [{
                        "rep_number": rep.rep_number,
                        "timestamp": rep.timestamp,
                        "mean_velocity": rep.mean_velocity,
                        "peak_velocity": rep.peak_velocity,
                        "duration_ms": rep.duration_ms,
                        "velocity_color": rep.velocity_color if rep.velocity_color in {"green", "yellow", "red"} else "neutral",
                    } for rep in reps],
                    "reps_truncated": latest_set.reps.count() > MAX_DASHBOARD_REPS,
                    "measured_insights": _measured_set_insights(latest_set, reps, program),
                })

        rack_body = {
            "rack_number": rack_number,
            "status": status,
            "status_color": status_color,
            "latest_set": latest_set_body,
        }
        if include_details:
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
            })
        racks.append(rack_body)

    leaders = list(
        valid_sets.exclude(avg_velocity=None)
        .values("athlete_id", "athlete__name")
        .annotate(best_avg_velocity=Max("avg_velocity"))
        .order_by("-best_avg_velocity", "athlete__name", "athlete_id")[:MAX_DASHBOARD_LEADERS]
    )
    leaderboard = [{
        "rank": index,
        "athlete": {
            **({"id": leader["athlete_id"]} if include_details else {}),
            "name": leader["athlete__name"],
        },
        "best_avg_velocity": leader["best_avg_velocity"],
    } for index, leader in enumerate(leaders, start=1)]

    room_insights = _room_insights(valid_sets)
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
            "active_racks": len(latest_sets_by_rack),
        },
        "racks": racks,
        "leaderboard": leaderboard,
        "insights": room_insights,
        "truncated": {
            "racks": len(all_rack_numbers) > MAX_DASHBOARD_RACKS,
            "leaderboard": valid_sets.values("athlete_id").distinct().count() > MAX_DASHBOARD_LEADERS,
        },
    }
    if include_details:
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


def _measured_set_insights(workout_set, reps, program):
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
    if program:
        below = sum(value < program.velocity_zone_min for value in velocities)
        inside = sum(program.velocity_zone_min <= value <= program.velocity_zone_max for value in velocities)
        above = sum(value > program.velocity_zone_max for value in velocities)

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
    return Response(_room_state_snapshot(include_details=False))


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
    return Response(NodeSerializer(form.save()).data)


# ─────────────────────────── athletes ───────────────────────────

@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def athletes_view(request):
    """GET: list all lifters (open). POST: add a lifter (coach only)."""
    if request.method == "GET":
        return Response(PublicAthleteSerializer(Athlete.objects.all()[:500], many=True).data)
    if not _require_coach(request):
        return Response({"detail": "coach login required"}, status=401)
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


# ─────────────────────────── sessions ───────────────────────────

@api_view(["POST"])
@permission_classes([IsCoach])
def sessions_view(request):
    """Coach-only: start a training session."""
    form = SessionSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    return Response(SessionSerializer(form.save()).data, status=201)


@api_view(["PATCH"])
@permission_classes([IsCoach])
def session_detail(request, session_id):
    """Coach-only: update a session. A PATCH with no ended_at means "end it now"."""
    session = Session.objects.filter(id=session_id).first()
    if session is None:
        return Response({"error": "session not found"}, status=404)
    form = SessionSerializer(session, data=request.data, partial=True)
    form.is_valid(raise_exception=True)
    session = form.save()
    if "ended_at" not in request.data:
        session.ended_at = timezone.now()
        session.save()
    return Response(SessionSerializer(session).data)


# ─────────────────────────── sets ───────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
def set_create(request):
    """Start a set: create the empty set record when an athlete begins, so the
    finish endpoint has something to fill in. Body: session, athlete, exercise,
    set_number, and optionally node + weight_lbs."""
    form = SetSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    new_set = form.save()
    return Response(SetSerializer(new_set).data, status=201)


@api_view(["POST"])
@permission_classes([AllowAny])
def set_complete(request, set_id):
    """Save a finished set. Take all its reps + totals and write them to the
    database in ONE all-or-nothing step (if anything fails, nothing saves). This
    is the only code path that creates Rep rows. A false set saves zero reps.
    We also flag whether it was the athlete's best-ever velocity or weight."""
    form = SetCompleteSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    data = form.validated_data

    try:
        target_set, is_velocity_pr, is_weight_pr = complete_set(set_id, data)
    except SetNotFound:
        return Response({"error": "set not found"}, status=404)
    except SetAlreadyComplete:
        return Response({"error": "set is already complete"}, status=409)

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
