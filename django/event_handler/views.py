



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

Open vs coach-only follows SPEC.md; shapes live in MESSAGE_CONTRACT.md.
"""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils.dateparse import parse_date
from django.db import transaction
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
                     ScheduledSession)

# Coaches are Django users; there is no separate coach table. See SPEC.md.
User = get_user_model()
from .permissions import IsCoach
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
    session = _active_session()
    if session is None:
        return Response({"error": "no active session"}, status=400)
    athlete = Athlete.objects.filter(id=request.data.get("athlete")).first()
    if athlete is None:
        return Response({"error": "athlete not found"}, status=404)
    if not session.athletes.filter(id=athlete.id).exists():
        return Response({"error": "athlete is not in the active session"}, status=404)
    RackCheckIn.objects.create(session=session, athlete=athlete, rack_number=rack_number)
    return Response({
        "session_id": session.id,
        "athlete": {"id": athlete.id, "name": athlete.name},
        "rack_number": rack_number,
    }, status=201)


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
