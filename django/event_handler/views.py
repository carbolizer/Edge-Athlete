



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
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Node, RackScreen, Athlete, Program, Session, Set, Rep, AthleteReferenceMax, Exercise
from .permissions import IsCoach
from .serializers import (SetSerializer, SetCompleteSerializer, RackScreenSerializer,
                          ProgramSerializer, AthleteSerializer, SessionSerializer,
                          NodeSerializer, ExerciseSerializer)
from .notification_flow.broadcast.publisher import publish_rack_state, publish_dashboard_state

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
    return Response(NodeSerializer(Node.objects.all(), many=True).data)


@api_view(["PATCH"])
@permission_classes([IsCoach])
def node_detail(request, node_id):
    """Coach-only: reassign a node to a different rack (or update its fields)."""
    node = Node.objects.filter(node_id=node_id).first()
    if node is None:
        return Response({"error": "node not found"}, status=404)
    form = NodeSerializer(node, data=request.data, partial=True)
    form.is_valid(raise_exception=True)
    saved_node = form.save()

    if saved_node.rack_number is not None: 
        publish_rack_state(saved_node.rack_number, {
            "type": "node_reassigned", 
            "node_id": saved_node.node_id,
        })
    
    return Response(NodeSerializer(saved_node).data)


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


@api_view(["PATCH"])
@permission_classes([IsCoach])
def athlete_detail(request, athlete_id):
    """Coach-only: update a lifter's details."""
    athlete = Athlete.objects.filter(id=athlete_id).first()
    if athlete is None:
        return Response({"error": "athlete not found"}, status=404)
    form = AthleteSerializer(athlete, data=request.data, partial=True)
    form.is_valid(raise_exception=True)
    return Response(AthleteSerializer(form.save()).data)


# ─────────────────────────── programs (training plans) ───────────────────────────

@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def programs_view(request):
    """GET: an athlete's training plans, ?athlete={id} to filter (open). POST:
    create a plan (coach only)."""
    if request.method == "GET":
        plans = Program.objects.all()
        athlete_id = request.query_params.get("athlete")
        if athlete_id is not None:
            plans = plans.filter(athlete_id=athlete_id)
        return Response(ProgramSerializer(plans, many=True).data)
    if not _require_coach(request):
        return Response({"detail": "coach login required"}, status=401)
    form = ProgramSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    return Response(ProgramSerializer(form.save()).data, status=201)


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


@api_view(["GET"])
@permission_classes([AllowAny])
def sessions_active(request):
    """The rack tablet's ONE startup fetch (open, no login). Returns the current
    session plus everything the rack screen needs to run a whole set-logging
    session without asking again: who's on the roster, each athlete's current
    maxes, and the planned exercises with their targets + velocity zones.

    MINIMAL-PATH SHAPE (documented seam — see the design note in models.py's
    AthleteMax and the sprint brief). This mirror is built on the existing seven
    models, so it differs from the full Phase 10/11 contract in three ways, all
    intentional:
      1. `exercise_id` is the Exercise catalog id (Program, Set, and reference
         maxes all link to that one catalog now), with the display `name`
         riding alongside it in session_exercises.
      2. `session_exercises[]` omits `target_weight_percent` (that lives on the
         not-yet-built SessionExercise model). It still carries the velocity
         zone, which is where the tablet reads it from to color reps.
      3. Each roster entry carries a RESOLVED absolute `targets` map
         {exercise_id: target_weight_lbs}, sourced straight from the athlete's
         Program. This is the minimal stand-in for the full contract's
         "percent x max" math: later, that same number gets computed server-side
         from `session_exercises[].target_weight_percent` x
         `roster[].maxes[exercise_id]`, and the frontend that reads
         `targets[exercise_id]` never changes.

    `maxes` is real (from AthleteReferenceMax — each athlete's newest row per
    exercise); an athlete/exercise with no reference simply has no key, which is
    what triggers the Phase 11 inline "set your max" entry. (Wire key stays
    `maxes` to match the Phase 10/11 contract; it carries reference maxes.)

    "Active" = the most recent Session whose ended_at is null. Tie-break: newest
    started_at, then highest id (covers same-instant creates deterministically).
    """
    session = Session.objects.filter(ended_at__isnull=True).order_by("-started_at", "-id").first()
    if session is None:
        # No live session: return the same envelope with nulls/empties so the
        # tablet can render a plain "no active session" screen without having to
        # special-case an HTTP error status.
        return Response({"session_id": None, "label": None, "roster": [], "session_exercises": []})

    athletes = list(session.athletes.order_by("name", "id"))
    athlete_ids = [a.id for a in athletes]

    # has_data: this athlete already has a completed set in THIS session. Drives
    # Phase 11's is_makeup (a set logged for someone who missed the original run).
    athletes_with_data = set(
        Set.objects.filter(session=session, ended_at__isnull=False)
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
    # for the dropdown + velocity zones. Both come from the roster's Programs,
    # keyed by the exercise's catalog id. session_exercises takes the first
    # Program seen for each exercise as the representative zone/target-reps —
    # minimal-path assumption that a movement's zone is shared across the room
    # (true for our seed data).
    targets_by_athlete = {}
    session_exercises = {}
    for p in Program.objects.filter(athlete_id__in=athlete_ids).select_related("exercise"):
        targets_by_athlete.setdefault(p.athlete_id, {})[p.exercise_id] = p.target_weight_lbs
        if p.exercise_id not in session_exercises:
            session_exercises[p.exercise_id] = {
                "exercise_id": p.exercise_id,
                "name": p.exercise.name,
                "target_sets": p.target_sets,
                "target_reps": p.target_reps,
                "velocity_zone_min": p.velocity_zone_min,
                "velocity_zone_max": p.velocity_zone_max,
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
    """
    session = Session.objects.filter(ended_at__isnull=True).order_by("-started_at", "-id").first()
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
    # (non-false) and false counted separately, in one query.
    completed_by_exercise = {}
    false_by_exercise = {}
    for s in Set.objects.filter(session=session, athlete_id=athlete_id, ended_at__isnull=False):
        bucket = false_by_exercise if s.is_false_set else completed_by_exercise
        bucket[s.exercise_id] = bucket.get(s.exercise_id, 0) + 1

    movements = []
    current_exercise_id = None  # suggested current = first movement not yet complete
    for p in Program.objects.filter(athlete_id=athlete_id).select_related("exercise").order_by("id"):
        completed = completed_by_exercise.get(p.exercise_id, 0)
        false_count = false_by_exercise.get(p.exercise_id, 0)
        if completed >= p.target_sets:
            status = "complete"
        elif completed > 0:
            status = "in_progress"
        else:
            status = "not_started"
        if current_exercise_id is None and status != "complete":
            current_exercise_id = p.exercise_id
        movements.append({
            "exercise_id": p.exercise_id,
            "name": p.exercise.name,
            "planned_sets": p.target_sets,
            "target_reps": p.target_reps,
            "target_weight_lbs": p.target_weight_lbs,
            "velocity_zone_min": p.velocity_zone_min,
            "velocity_zone_max": p.velocity_zone_max,
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
    target_set = Set.objects.filter(id=set_id).first()
    if target_set is None:
        return Response({"error": "set not found"}, status=404)

    form = SetCompleteSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    data = form.validated_data

    # all-or-nothing: either the whole set saves, or none of it does
    with transaction.atomic():
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

    rack_number = target_set.node.rack_number if target_set.node else None
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

    body = SetSerializer(target_set).data
    body["is_velocity_pr"] = is_velocity_pr
    body["is_weight_pr"] = is_weight_pr
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
    sets = Set.objects.filter(session_id=session_id, is_false_set=False).select_related("athlete")
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
    """Coach-only: an athlete's velocity trend across their sets (oldest first)."""
    sets = Set.objects.filter(athlete_id=athlete_id, is_false_set=False).select_related("exercise").order_by("started_at")
    trend = [{
        "set_id": s.id, "exercise": s.exercise.name, "weight_lbs": s.weight_lbs,
        "avg_velocity": s.avg_velocity, "peak_velocity": s.peak_velocity,
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
    } for s in sets]
    return Response({"athlete_id": int(athlete_id), "sets": trend})
