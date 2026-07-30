"""
athlete_analytics.py — everything the coach's athlete and history tabs read.

WHAT THIS IS FOR, in plain terms: a coach picks an athlete and wants two things.
"How are they doing overall?" (totals and bests, per movement) and "show me what
they actually did, set by set, rep by rep." Both answers already exist in the
Set and Rep rows — nobody had written the read.

Derived per request, no new tables (canon: derived-first).

⚠️ TWO RULES THAT ARE EASY TO GET WRONG, both load-bearing:

1. THE SUMMARY COVERS ALL HISTORY; ONLY THE SET LIST IS TRUNCATED. A busy
   athlete has thousands of sets, and mounting them all locks up a tablet. So we
   return the most recent SET_LIMIT of them — but the totals and bests are
   aggregated in the database across everything. The UI says as much ("summaries
   include all history"), so computing the totals from the truncated list would
   make the screen quietly lie.

2. EVERY SET CARRIES A `measured` BLOCK, ALWAYS. The coach UI reads
   `workoutSet.measured.first_to_last_change_percent` with no optional chaining,
   so a missing block is not a blank field — it is a thrown TypeError, and React
   unmounts the whole coach view on an uncaught render error. A black screen.
   Return the block with null inside it rather than omitting it.

WHICH SETS COUNT (canon §6.5): false sets and coach adjustments are excluded from
analytics — a false set is a mis-record and an adjustment moves the working load
without anyone lifting. Unfinished sets are excluded too: they have no `ended_at`,
and the history view groups by day, so one would render as an "Invalid Date" day.
"""

from django.db.models import Count, Max, Sum

from ..models import Athlete, Rep, Set

# A tablet can render this much without stalling. The UI states both limits to
# the coach rather than silently dropping data, and nothing here shrinks what is
# stored — these are display budgets, not retention rules.
SET_LIMIT = 50
REP_LIMIT = 100


def _real_sets(athlete_id):
    """The sets that count as work this athlete actually did."""
    return Set.objects.filter(
        athlete_id=athlete_id,
        is_false_set=False,
        is_coach_adjustment=False,
        ended_at__isnull=False,
    )


def _measured(reps):
    """The one derived number the set cards show: how much this athlete's
    velocity moved from their first rep to their last.

    Signed, and negative means they slowed down over the set — the ordinary
    sign of fatigue. Kept as a change rather than a "loss" so a set someone
    finished FASTER than they started reads as positive instead of as a negative
    loss, which is a double negative nobody parses at a glance.

    Needs two reps to mean anything, and a non-zero first rep to divide by.
    """
    speeds = [rep.mean_velocity for rep in reps if rep.mean_velocity is not None]
    if len(speeds) < 2 or not speeds[0]:
        return {"first_to_last_change_percent": None}
    return {"first_to_last_change_percent": (speeds[-1] - speeds[0]) / speeds[0] * 100}


def _reps_by_set(set_ids):
    """Every set's reps in one query, capped per set.

    One query rather than one per set: a coach opening an athlete with fifty
    sets should not cost fifty round trips. The cap is applied in Python because
    "first N per group" is not a thing a portable ORM query does cheaply, and
    the rows are already in memory.
    """
    grouped = {}
    truncated = set()
    for rep in Rep.objects.filter(set_id__in=set_ids).order_by("set_id", "rep_number"):
        bucket = grouped.setdefault(rep.set_id, [])
        if len(bucket) < REP_LIMIT:
            bucket.append(rep)
        else:
            truncated.add(rep.set_id)
    return grouped, truncated


def athlete_analytics(athlete_id):
    """The athlete's performance context, or None if there is no such athlete.

    Returning None rather than raising lets the view answer 404 — an unknown id
    is a normal thing for a URL to contain, not an exception.
    """
    athlete = Athlete.objects.filter(id=athlete_id).first()
    if athlete is None:
        return None

    real = _real_sets(athlete_id)

    # Aggregated across ALL history, not the truncated list — see rule 1 above.
    totals = real.aggregate(
        completed_sets=Count("id"),
        completed_reps=Sum("reps_completed"),
        best_average=Max("avg_velocity"),
        highest_peak=Max("peak_velocity"),
        heaviest_weight=Max("weight_lbs"),
    )
    summary = {
        "completed_sets": totals["completed_sets"] or 0,
        # Sum() is null over an empty set, and "0 reps" is the truthful answer
        # for someone who has not lifted yet.
        "completed_reps": totals["completed_reps"] or 0,
        # These stay null rather than becoming 0: an athlete with no sets has no
        # best velocity, and 0.00 m/s would read as a measurement.
        "best_average": totals["best_average"],
        "highest_peak": totals["highest_peak"],
        "heaviest_weight": totals["heaviest_weight"],
    }

    # Most-trained movement first: the question behind this panel is usually
    # "how is their squat going", and the movements they train most are the ones
    # they are being programmed on. Name breaks ties so the order is stable
    # between requests rather than shifting under the coach's eye.
    exercise_summaries = [{
        "exercise": row["exercise__name"],
        "completed_sets": row["completed_sets"],
        "completed_reps": row["completed_reps"] or 0,
        "best_average": row["best_average"],
        "heaviest_weight": row["heaviest_weight"],
    } for row in real.values("exercise__name").annotate(
        completed_sets=Count("id"),
        completed_reps=Sum("reps_completed"),
        best_average=Max("avg_velocity"),
        heaviest_weight=Max("weight_lbs"),
    ).order_by("-completed_sets", "exercise__name")]

    # Newest first, so a truncated list keeps the most recent work — that is
    # what a coach standing in the room is asking about.
    recent = list(real.select_related("exercise", "session", "node")
                      .order_by("-ended_at", "-id")[:SET_LIMIT])
    reps_by_set, reps_truncated = _reps_by_set([s.id for s in recent])

    sets = []
    for workout_set in recent:
        reps = reps_by_set.get(workout_set.id, [])
        sets.append({
            "id": workout_set.id,
            "set_number": workout_set.set_number,
            "exercise": workout_set.exercise.name,
            "weight_lbs": workout_set.weight_lbs,
            "reps_completed": workout_set.reps_completed,
            "avg_velocity": workout_set.avg_velocity,
            "peak_velocity": workout_set.peak_velocity,
            "ended_at": workout_set.ended_at.isoformat() if workout_set.ended_at else None,
            # `Set` has no rack column — D11 dropped it, because where a set was
            # recorded is a property of the NODE that recorded it, and a node
            # gets reassigned between racks. Null when the node is gone.
            "rack_number": workout_set.node.rack_number if workout_set.node else None,
            # The history view groups sets into days and then into workouts, and
            # the session is what names each workout. Without it every day
            # renders as "Unlabeled workout".
            "session": {"id": workout_set.session_id, "label": workout_set.session.label},
            "reps": [{
                "rep_number": rep.rep_number,
                "mean_velocity": rep.mean_velocity,
                "peak_velocity": rep.peak_velocity,
                "duration_ms": rep.duration_ms,
            } for rep in reps],
            "reps_truncated": workout_set.id in reps_truncated,
            # ALWAYS present — see rule 2 at the top of this file.
            "measured": _measured(reps),
        })

    return {
        "athlete": {
            "id": athlete.id,
            "name": athlete.name,
            "created_at": athlete.created_at.isoformat() if athlete.created_at else None,
        },
        "summary": summary,
        "exercise_summaries": exercise_summaries,
        "sets": sets,
        # True when older sets exist beyond the ones returned, so the UI can say
        # so instead of implying this is the athlete's whole history.
        "truncated": summary["completed_sets"] > len(sets),
    }
