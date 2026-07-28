"""Builds the live room snapshot the coach dashboard and the wall display read.

WHAT THIS IS FOR
The coach tablet and the gym wall screen both need one picture of "what is
happening in the room right now": which racks have someone at them, what they
just lifted, how the whole room is doing. This module derives that picture on
every request. There is no room-state table and there must never be one.

WHY IT IS DERIVED, NOT STORED (merge canon D2/D3/D8)
Braydon's original version read two stored tables — RackWorkoutState (which rack
a coach had PRE-ASSIGNED an athlete and workout to) and AthleteDayProgress (a
stored per-athlete progress row). Both are dropped in the merge, because this
system's rack is ATHLETE-CENTRIC and GROUP-BLIND: nobody assigns an athlete to a
rack in advance. An athlete walks up to whatever rack is free, checks in, and
carries their own plan with them. So "who is at rack 3" is not a scheduling fact
to store — it is simply their newest RackCheckIn row, and everything else falls
out of the Set/Rep rows they produce. Deriving it per request also means the
answer can never go stale or disagree with the underlying data.

THE SHAPE IS NOT OURS TO CHOOSE
The response keys below are dictated by the existing consumer (his Dashboard.jsx
+ dashboardView.js). We bend to it rather than reshaping his front end, so the
key names, nesting, and the two detail levels are all deliberate. Do not "tidy"
them.

TWO DETAIL LEVELS, ONE FUNCTION
  include_details=False -> the WALL display. Publicly visible on a gym screen, so
                           it deliberately omits database ids and the participant
                           roster: names and numbers only.
  include_details=True  -> the COACH view (authenticated). Adds ids and the
                           roster so the coach UI can link through to records.
"""

from datetime import timedelta

from django.db.models import Count, Max, Sum
from django.db.models.functions import Lower
from django.utils import timezone

from event_handler.models import (MonitoringEvent, Node, Program, RackCheckIn,
                                  RackScreen, Rep, Session, Set)

# Hard ceilings so one absurd gym (or a bad import) can never make this endpoint
# return an unbounded payload to a tablet on a slow local network.
MAX_DASHBOARD_RACKS = 32
MAX_DASHBOARD_LEADERS = 20

# A node that has not sent a pulse within this window reads as stale hardware.
NODE_STALE_AFTER = timedelta(seconds=15)

_REAL_COLORS = {"green", "yellow", "red"}


def _active_session():
    """The one live session — newest session that has not been ended."""
    return Session.objects.filter(ended_at__isnull=True).order_by("-started_at", "-id").first()


def _current_athlete_by_rack(session):
    """Who is standing at each rack RIGHT NOW, from the check-in log (D2).

    RackCheckIn is append-only and newest-wins: checking in somewhere new simply
    supersedes the older row, because an athlete cannot lift at two racks at
    once. So the current occupant of a rack is just the newest check-in naming
    it — no stored "current rack" field to keep in sync.
    """
    if session is None:
        return {}
    current = {}
    # Newest first, so the FIRST row we see for an athlete is their current rack.
    for checkin in (RackCheckIn.objects
                    .filter(session=session)
                    .select_related("athlete")
                    .order_by("-checked_in_at", "-id")):
        if checkin.athlete_id in current:
            continue  # already saw this athlete's newest check-in
        current[checkin.athlete_id] = (checkin.rack_number, checkin.athlete)
    # Flip to rack -> athlete. If two athletes somehow name the same rack, the
    # newest check-in wins (we walked newest-first, so the first one sticks).
    by_rack = {}
    for rack_number, athlete in current.values():
        by_rack.setdefault(rack_number, athlete)
    return by_rack


def _rack_numbers(session, athlete_by_rack):
    """Every rack the room knows about — hardware, tablets, and occupied racks.

    A rack is worth showing if a sensor is assigned to it, a tablet is standing
    at it, or somebody is checked in there. (His version also unioned in
    Set.rack_number; that column is dropped in this merge — D11 — because rack
    identity now comes from the check-in log alone.)
    """
    numbers = set(athlete_by_rack)
    numbers.update(Node.objects.exclude(rack_number=None)
                   .values_list("rack_number", flat=True).distinct())
    numbers.update(RackScreen.objects.exclude(rack_number=None)
                   .values_list("rack_number", flat=True).distinct())
    return sorted(numbers)


def _latest_sets_by_athlete(session, athlete_ids):
    """Each athlete's most recent set this session (started last, not ended last).

    "Most recent" is by start time on purpose: a set that is still in progress
    has no end time, and it is exactly the one the room should be showing.
    """
    if session is None or not athlete_ids:
        return {}
    latest = {}
    for s in (Set.objects
              .filter(session=session, athlete_id__in=athlete_ids,
                      is_coach_adjustment=False)
              .select_related("exercise", "athlete")
              .order_by("-started_at", "-id")):
        latest.setdefault(s.athlete_id, s)
    return latest


def _set_status(a_set):
    """Live execution state of one set — NOT a velocity judgement (canon §5.6).

    idle / active / complete / false set is "where is this set in its lifecycle",
    a completely separate concept from the green/yellow/red velocity colour.
    """
    if a_set is None:
        return "idle"
    if a_set.ended_at is None:
        return "active"
    if a_set.is_false_set:
        return "false set"
    return "complete"


def _status_color(reps):
    """The velocity zone of the LAST rep — the "how did that move" colour.

    Falls back to neutral when there are no reps yet or the stored colour is not
    one of the three real zones, so the wall never renders a mystery colour.
    """
    if not reps:
        return "neutral"
    last = reps[-1].velocity_color
    return last if last in _REAL_COLORS else "neutral"


def _target_zone_for(athlete_id, exercise_id):
    """The athlete's velocity target for this movement.

    NOTE (merge phase): this still reads the legacy per-athlete Program table,
    which is what the rack itself resolves targets from today. When P5 re-points
    target resolution at TrainingProgramExercise (% x reference max), this
    lookup moves with it — see canon §6.1. Kept deliberately in one small
    function so that swap is a one-place change.
    """
    program = Program.objects.filter(athlete_id=athlete_id, exercise_id=exercise_id).first()
    if program is None:
        return None
    return {"velocity_min": program.velocity_zone_min, "velocity_max": program.velocity_zone_max}


def _rack_body(rack_number, athlete, latest_set, reps, include_details, nodes_by_rack):
    """One rack's tile on the dashboard."""
    status = _set_status(latest_set)
    body = {
        "rack_number": rack_number,
        "status": status,
        "status_color": _status_color(reps),
        "latest_set": None,
    }

    if athlete is not None:
        body["athlete"] = {
            **({"id": athlete.id} if include_details else {}),
            "name": athlete.name,
        }
    else:
        body["athlete"] = None

    if latest_set is not None:
        zone = _target_zone_for(latest_set.athlete_id, latest_set.exercise_id)
        body["latest_set"] = {
            **({"id": latest_set.id} if include_details else {}),
            "exercise": latest_set.exercise.name,
            "set_number": latest_set.set_number,
            "weight_lbs": latest_set.weight_lbs,
            "reps_completed": latest_set.reps_completed,
            "avg_velocity": latest_set.avg_velocity,
            "peak_velocity": latest_set.peak_velocity,
            "is_false_set": latest_set.is_false_set,
            "target_zone": zone,
            "reps": [{
                "rep_number": rep.rep_number,
                "mean_velocity": rep.mean_velocity,
                "peak_velocity": rep.peak_velocity,
                "velocity_color": rep.velocity_color if rep.velocity_color in _REAL_COLORS else "neutral",
            } for rep in reps],
        }

    if include_details:
        node = nodes_by_rack.get(rack_number)
        body["node"] = None if node is None else {
            "node_id": node.node_id,
            "battery_level": node.battery_level,
            "signal_strength": node.signal_strength,
            "is_stale": node.last_seen is None or node.last_seen < timezone.now() - NODE_STALE_AFTER,
        }

    return body


def _selected_movement(latest_sets, include_details):
    """What the room as a whole is working on: the most-common current movement.

    His version read this from the dropped AthleteDayProgress table. We derive it
    instead from what people are actually lifting right now — which is both
    simpler and can't disagree with reality. Ties break by name then id so the
    answer is stable across requests instead of depending on dict ordering.
    """
    counts = {}
    exercises = {}
    for a_set in latest_sets:
        counts[a_set.exercise_id] = counts.get(a_set.exercise_id, 0) + 1
        exercises[a_set.exercise_id] = a_set.exercise
    if not counts:
        return None, None

    exercise_id = min(counts, key=lambda eid: (-counts[eid], exercises[eid].name.strip().casefold(), eid))
    exercise = exercises[exercise_id]
    # Any athlete's zone for this movement is representative enough for a room
    # headline; the per-rack tiles carry each athlete's own target.
    zone = None
    for a_set in latest_sets:
        if a_set.exercise_id == exercise_id:
            zone = _target_zone_for(a_set.athlete_id, exercise_id)
            if zone:
                break

    return exercise_id, {
        **({"id": exercise.id} if include_details else {}),
        "name": exercise.name,
        "velocity_min": (zone or {}).get("velocity_min"),
        "velocity_max": (zone or {}).get("velocity_max"),
        "participant_count": counts[exercise_id],
    }


def _leaderboard(session, exercise_id, include_details):
    """Fastest athletes on the room's current movement, best set each.

    Only real, finished, non-simulated work counts — a false set or a set still
    in progress has nothing meaningful to rank yet.
    """
    if session is None or exercise_id is None:
        return [], False
    rows = (Set.objects
            .filter(session=session, exercise_id=exercise_id, ended_at__isnull=False,
                    is_false_set=False, is_simulated=False)
            .exclude(avg_velocity=None)
            .values("athlete_id", "athlete__name")
            .annotate(best_avg_velocity=Max("avg_velocity"), name_sort=Lower("athlete__name"))
            .order_by("-best_avg_velocity", "name_sort", "athlete_id"))
    total = rows.count()
    return [{
        "rank": index,
        "athlete": {
            **({"id": row["athlete_id"]} if include_details else {}),
            "name": row["athlete__name"],
        },
        "best_avg_velocity": row["best_avg_velocity"],
    } for index, row in enumerate(rows[:MAX_DASHBOARD_LEADERS], start=1)], total > MAX_DASHBOARD_LEADERS


def _insights(session):
    """Three headline facts for the wall — the "who's winning" strip.

    Each is None-safe: an empty or brand-new session simply produces fewer
    insights rather than an error.
    """
    if session is None:
        return []
    real = Set.objects.filter(session=session, ended_at__isnull=False,
                              is_false_set=False, is_simulated=False)
    out = []

    fastest = real.exclude(avg_velocity=None).select_related("athlete").order_by("-avg_velocity").first()
    if fastest:
        out.append({"type": "fastest_set_average", "label": "Fastest set average",
                    "athlete_name": fastest.athlete.name, "value": fastest.avg_velocity, "unit": "m/s"})

    peak = real.exclude(peak_velocity=None).select_related("athlete").order_by("-peak_velocity").first()
    if peak:
        out.append({"type": "highest_peak_velocity", "label": "Highest peak velocity",
                    "athlete_name": peak.athlete.name, "value": peak.peak_velocity, "unit": "m/s"})

    most = (real.values("athlete__name").annotate(total_reps=Sum("reps_completed"))
            .order_by("-total_reps", "athlete__name").first())
    if most and most["total_reps"]:
        out.append({"type": "most_completed_reps", "label": "Most completed reps",
                    "athlete_name": most["athlete__name"], "value": most["total_reps"], "unit": "reps"})

    return out


def room_state_snapshot(include_details):
    """Assemble the whole room picture. See the module docstring for the why."""
    session = _active_session()

    # The revision the front end compares against MQTT invalidations. It is the
    # newest MonitoringEvent id, so a dashboard can tell "the snapshot I hold is
    # older than the change I was just told about" and refetch exactly once.
    revision = MonitoringEvent.objects.order_by("-id").values_list("id", flat=True).first() or 0

    athlete_by_rack = _current_athlete_by_rack(session)
    all_rack_numbers = _rack_numbers(session, athlete_by_rack)
    rack_numbers = all_rack_numbers[:MAX_DASHBOARD_RACKS]

    latest_by_athlete = _latest_sets_by_athlete(
        session, [a.id for a in athlete_by_rack.values()])

    # Reps for the visible sets, fetched in one query and grouped in memory
    # rather than one query per rack.
    reps_by_set = {}
    set_ids = [s.id for s in latest_by_athlete.values()]
    if set_ids:
        for rep in Rep.objects.filter(set_id__in=set_ids).order_by("rep_number"):
            reps_by_set.setdefault(rep.set_id, []).append(rep)

    nodes_by_rack = {}
    if include_details:
        for node in Node.objects.filter(rack_number__in=rack_numbers).order_by("rack_number", "node_id"):
            nodes_by_rack.setdefault(node.rack_number, node)

    racks = []
    shown_sets = []
    for rack_number in rack_numbers:
        athlete = athlete_by_rack.get(rack_number)
        latest_set = latest_by_athlete.get(athlete.id) if athlete else None
        if latest_set is not None:
            shown_sets.append(latest_set)
        racks.append(_rack_body(rack_number, athlete, latest_set,
                                reps_by_set.get(latest_set.id, []) if latest_set else [],
                                include_details, nodes_by_rack))

    exercise_id, movement = _selected_movement(shown_sets, include_details)
    leaderboard, leaderboard_truncated = _leaderboard(session, exercise_id, include_details)

    # Room totals over real finished work only.
    real = Set.objects.filter(session=session, ended_at__isnull=False,
                              is_false_set=False, is_simulated=False) if session else Set.objects.none()
    totals = real.aggregate(completed_sets=Count("id"), completed_reps=Sum("reps_completed"),
                            room_avg_velocity=Max("avg_velocity"))
    avg = real.exclude(avg_velocity=None).aggregate(v=Sum("avg_velocity"), n=Count("id"))
    room_avg = round(avg["v"] / avg["n"], 3) if avg["n"] else None

    snapshot = {
        "schema_version": 1,
        "revision": revision,
        "generated_at": timezone.now(),
        "session": {
            **({"id": session.id} if include_details else {}),
            "label": session.label,
            "started_at": session.started_at,
        } if session else None,
        "summary": {
            "participant_count": session.athletes.count() if session else 0,
            "athletes_with_sets": real.values("athlete_id").distinct().count(),
            "completed_sets": totals["completed_sets"] or 0,
            "completed_reps": totals["completed_reps"] or 0,
            "room_avg_velocity": room_avg,
            # An "active rack" is one with somebody checked in at it — the
            # athlete-centric replacement for his coach-pre-assigned count.
            "active_racks": sum(1 for r in racks if r["athlete"] is not None),
        },
        "racks": racks,
        "movement": movement,
        "leaderboard": leaderboard,
        "insights": _insights(session),
        "truncated": {
            "racks": len(all_rack_numbers) > MAX_DASHBOARD_RACKS,
            "leaderboard": leaderboard_truncated,
        },
    }

    if include_details:
        snapshot["participants"] = list(
            session.athletes.order_by("name", "id").values("id", "name")[:500]
        ) if session else []

    return snapshot
