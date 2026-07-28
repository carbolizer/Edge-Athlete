"""Ending a training day: freeze the report, then update everyone's maxes.

WHAT HAPPENS WHEN A COACH ENDS A SESSION
Three things, in this order, all-or-nothing inside one transaction:

  1. Build an immutable SNAPSHOT of everything that happened and store it as a
     DailyReport. After this the day can be read back forever without depending
     on live tables that will keep changing.
  2. Recalculate each athlete's REFERENCE MAX from what they actually lifted, so
     tomorrow's percentages track today's real capability (merge canon D10).
  3. Stamp the session ended and announce the change.

WHY IT IS ONE TRANSACTION
A half-ended day is the worst outcome: a session marked finished with no report,
or a report with no maxes updated. Either would need manual repair. Wrapping the
whole thing means a failure anywhere leaves the day simply *not ended*, which the
coach can retry safely.

WHY THERE IS NO `sessions/{id}/end/` ROUTE
Ending a session is just "set its end time", and `PATCH /api/sessions/{id}/`
already did exactly that before this merge. A second route would be two ways to
do one thing (canon R2), so the finalization hooks into that existing PATCH
instead.
"""

from django.db import transaction
from django.utils import timezone

from ..models import (AthleteReferenceMax, DailyReport, MonitoringEvent,
                      RackCheckIn, Rep, Session, Set)
from .lifting_math import one_rep_max

REPORT_SCHEMA_VERSION = 1


def estimated_one_rep_max(weight_lbs, reps):
    """Kept as a named step for readability; the formula itself lives in
    lifting_math so this and the target-weight calculation can never drift
    apart (canon D11)."""
    return one_rep_max(weight_lbs, reps)


def _snapshot(session):
    """Freeze the whole day into plain JSON.

    Shape note: this deliberately fills the fields that exist in THIS system and
    leaves the rest null. `assigned_program` and `final_progress` stay null until
    the planning phase gives athletes real programs to be measured against — the
    report reader treats missing pieces as absent rather than erroring, so the
    report simply grows richer later without a schema change.
    """
    athletes = list(session.athletes.order_by("name", "id"))

    # Which racks each athlete used today — derived from the check-in log rather
    # than a stored participation row (canon D2).
    racks_by_athlete = {}
    for checkin in RackCheckIn.objects.filter(session=session):
        racks_by_athlete.setdefault(checkin.athlete_id, set()).add(checkin.rack_number)

    sets_by_athlete = {}
    # Coach weight adjustments are left out of the permanent record: they are a
    # dial being turned, not work anybody did.
    all_sets = list(Set.objects.filter(session=session, is_coach_adjustment=False)
                    .select_related("exercise").order_by("started_at", "id"))
    reps_by_set = {}
    for rep in Rep.objects.filter(set__session=session).order_by("rep_number"):
        reps_by_set.setdefault(rep.set_id, []).append(rep)

    for a_set in all_sets:
        sets_by_athlete.setdefault(a_set.athlete_id, []).append({
            "id": a_set.id,
            "set_number": a_set.set_number,
            "exercise": {"id": a_set.exercise_id, "name": a_set.exercise.name},
            "weight_lbs": a_set.weight_lbs,
            "reps_completed": a_set.reps_completed,
            "avg_velocity": a_set.avg_velocity,
            "peak_velocity": a_set.peak_velocity,
            "is_false_set": a_set.is_false_set,
            "is_makeup": a_set.is_makeup,
            "started_at": a_set.started_at.isoformat() if a_set.started_at else None,
            "ended_at": a_set.ended_at.isoformat() if a_set.ended_at else None,
            "reps": [{
                "rep_number": r.rep_number,
                "mean_velocity": r.mean_velocity,
                "peak_velocity": r.peak_velocity,
                "duration_ms": r.duration_ms,
                "velocity_color": r.velocity_color,
            } for r in reps_by_set.get(a_set.id, [])],
        })

    athlete_blocks = [{
        "athlete": {"id": a.id, "name": a.name},
        "assigned_program": None,   # filled once group programs exist (planning phase)
        "final_progress": None,     # ditto
        "rack_participation": sorted(racks_by_athlete.get(a.id, [])),
        "sets": sets_by_athlete.get(a.id, []),
    } for a in athletes]

    real_sets = [s for block in athlete_blocks for s in block["sets"] if not s["is_false_set"]]
    velocities = [s["avg_velocity"] for s in real_sets if s["avg_velocity"] is not None]

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "session": {
            "id": session.id,
            "label": session.label,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "ended_at": None,  # set by the caller once the end time is decided
        },
        "athletes": athlete_blocks,
        "summary": {
            "athlete_count": len(athlete_blocks),
            "completed_sets": len(real_sets),
            "completed_reps": sum(s["reps_completed"] or 0 for s in real_sets),
            "average_velocity": (sum(velocities) / len(velocities)) if velocities else None,
        },
    }


def _recalculate_reference_maxes(session):
    """Write each athlete a fresh reference max from today's real work (D10).

    FEEDS FORWARD ONLY. This adds new rows for FUTURE sessions to read; it never
    touches the targets an athlete already trained against today. AthleteReferenceMax
    is append-only and newest-wins by design, so writing a row *is* the update —
    nothing is edited or deleted, and the old value stays visible as history.

    A max can go DOWN. That is intentional: the reference is "what can they do
    about now", not a trophy, so a rough week should pull tomorrow's prescribed
    weights back rather than leave them chasing an old number.

    Best-effort per (athlete, movement): we take their strongest estimate from
    today's real sets. STILL DELIBERATELY OPEN (canon D10): how many sessions to
    blend, and how to reject a fluke. Today one honest set is better than a stale
    hand-entered number; smoothing is a later decision, not an accident of this
    code.
    """
    best = {}
    for a_set in Set.objects.filter(session=session, ended_at__isnull=False,
                                    is_false_set=False, is_simulated=False,
                                    is_coach_adjustment=False):
        estimate = estimated_one_rep_max(a_set.weight_lbs, a_set.reps_completed)
        if estimate is None:
            continue
        key = (a_set.athlete_id, a_set.exercise_id)
        if estimate > best.get(key, 0):
            best[key] = estimate

    return [AthleteReferenceMax.objects.create(
        athlete_id=athlete_id,
        exercise_id=exercise_id,
        reference_weight_lbs=round(estimate, 1),
        rep_basis=1,  # already normalised to a 1-rep basis by the formula above
        source=AthleteReferenceMax.SOURCE_ESTIMATED,
        source_session=session,
    ) for (athlete_id, exercise_id), estimate in best.items()]


def end_session(session_id, ended_at=None):
    """End a session and return (report, created).

    Idempotent on purpose: ending an already-ended day returns its existing
    report instead of writing a second one or erroring. A coach double-tapping
    "end session", or two tablets racing, must not be able to produce two reports
    for one day — so the row lock plus this check make the second call a no-op.
    """
    with transaction.atomic():
        session = Session.objects.select_for_update().filter(id=session_id).first()
        if session is None:
            return None, False

        existing = DailyReport.objects.filter(session=session).first()
        if existing is not None:
            return existing, False

        end_time = ended_at or timezone.now()
        snapshot = _snapshot(session)
        snapshot["session"]["ended_at"] = end_time.isoformat()

        session.ended_at = end_time
        session.save(update_fields=["ended_at"])

        report = DailyReport.objects.create(
            session=session,
            schema_version=REPORT_SCHEMA_VERSION,
            snapshot=snapshot,
        )

        _recalculate_reference_maxes(session)

        # Tell the dashboards the room just changed. Written inside the same
        # transaction so it can't announce a day that failed to end.
        MonitoringEvent.objects.create(reason="session_ended")

        return report, True
