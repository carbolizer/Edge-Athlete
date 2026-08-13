"""Works out what an athlete is doing today, and what weight goes on the bar.

THE ONE IDEA BEHIND ALL OF THIS
A coach writes a plan once, for a TrainingGroup, in percentages — "back squat, 5 sets of
3, at 80%". Every athlete in that TrainingGroup gets a different weight out of the same
line, because 80% is taken against THEIR current max. Nobody types a weight per
athlete, and as people get stronger their numbers follow automatically.

So nothing here stores a target weight. It is worked out fresh every time it is
asked for, which is why an athlete who tests heavier on Monday is lifting heavier
on Tuesday with no one editing anything.

TWO QUESTIONS, ANSWERED IN ORDER
  1. What is this athlete doing today?  -> movements_for_athlete()
  2. What weight is that, for them?     -> resolve_target_weight()

⚠️ THE OUTPUT OF THIS FILE FEEDS A FROZEN CONTRACT.
The rack screen reads these numbers through an endpoint whose response shape must
not change by a single field. Change what the numbers ARE here as much as you
like; never change what the response LOOKS like. See the merge canon §6.3.
"""

from ..models import (AthleteReferenceMax, AthleteWorkoutExerciseOverride, Node,
                      RackCheckIn, SessionParticipation)
from .lifting_math import normalize_to_single, round_to_loadable


def current_reference_max(athlete_id, exercise_id):
    """This athlete's current working max for one movement, on a 1-rep basis.

    The reference table is append-only and newest-wins: recording a new number
    doesn't edit the old row, it supersedes it. So "current" is simply their most
    recent row, and the history stays intact and graphable.

    Returns None when they have never had a max recorded for this movement.
    """
    row = (AthleteReferenceMax.objects
           .filter(athlete_id=athlete_id, exercise_id=exercise_id)
           .order_by("-recorded_at", "-id")
           .first())
    if row is None:
        return None
    return normalize_to_single(row.reference_weight_lbs, row.rep_basis)


def resolve_target_weight(athlete_id, exercise_id, target_percent):
    """Turn "80%" into an actual number of pounds for this athlete.

    Returns None if they have no max on file for the movement — deliberately, and
    it is NOT an error. The rack screen already renders a blank target and lets
    the athlete key in what they're using, so a missing max degrades to "ask the
    human" rather than blocking them from lifting. Never guess a weight.
    """
    if target_percent is None:
        return None
    reference = current_reference_max(athlete_id, exercise_id)
    if reference is None:
        return None
    return round_to_loadable(reference * (target_percent / 100.0))


def _overrides_for(athlete_id, program_exercise_ids):
    """Per-athlete exceptions, keyed by the plan row they override.

    Most athletes have none of these. It exists for the outlier the percentage
    doesn't suit — and it overrides the PERCENT, never a fixed weight, so an
    overridden athlete's number still tracks their max instead of freezing.
    """
    if not program_exercise_ids:
        return {}
    return {o.training_program_exercise_id: o for o in
            AthleteWorkoutExerciseOverride.objects.filter(
                athlete_id=athlete_id,
                training_program_exercise_id__in=program_exercise_ids)}


def _programs_for_athlete_today(athlete, session):
    """Which plans apply to this athlete in this session.

    This is an INTERSECTION: the TrainingGroups the athlete belongs to, AND the TrainingGroups
    that are actually training in this session. That is what lets one person sit
    in both "Varsity Football" and "Receivers" without ever choosing between
    them — they get the football plan at a football session and the receiver plan
    at a receiver session, with nothing to configure.

    Ordered biggest TrainingGroup first, so the whole-team lift comes before position
    work. Ties break on start date, then creation, then id — never on database
    ordering, so the same inputs always give the same answer.
    """
    group_ids = set(athlete.training_groups.values_list("id", flat=True))
    if not group_ids:
        return []

    participations = (SessionParticipation.objects
                      .filter(session=session,
                              training_program__training_group_id__in=group_ids)
                      .select_related("training_program",
                                      "training_program__training_group",
                                      "training_program_workout"))

    def sort_key(p):
        group = p.training_program.training_group
        return (-group.athletes.count(),
                -(p.training_program.start_date.toordinal() if p.training_program.start_date else 0),
                -p.training_program.created_at.timestamp(),
                p.training_program_id)

    return sorted(participations, key=sort_key)


def _allowed_exercise_ids_at_athletes_rack(athlete_id, session):
    """What the athlete's current rack can physically do, if it says.

    A rack can be told what equipment it has, so a station that isn't set up for
    cleans doesn't offer cleans. This is a fact about the hardware, not a
    schedule — and it is only ever a filter on what gets shown, never a rejection
    when someone tries to lift.

    Returns None meaning "no restriction", which is the normal case. FAILS OPEN
    on purpose: if we can't tell which rack they're at yet, they see everything
    rather than being blocked mid-session by a timing gap.
    """
    checkin = (RackCheckIn.objects
               .filter(session=session, athlete_id=athlete_id)
               .order_by("-checked_in_at", "-id")
               .first())
    if checkin is None:
        return None

    node = Node.objects.filter(rack_number=checkin.rack_number).first()
    if node is None:
        return None

    allowed = set(node.allowed_exercises.values_list("id", flat=True))
    return allowed or None   # empty list means "unrestricted", not "nothing allowed"


def movements_for_athlete(athlete, session):
    """The athlete's movements for today, in the order they should do them.

    Returns a list of plain dicts — deliberately not model objects — so the
    endpoint that renders the frozen rack contract can map them straight across
    without reaching back into the database.

    An empty list is a legitimate answer at several points (no TrainingGroup, TrainingGroup not
    training today, coach hasn't picked the workout yet). None of those are
    errors: the rack simply shows nothing to do.
    """
    if session is None:
        return []

    participations = _programs_for_athlete_today(athlete, session)
    if not participations:
        return []

    allowed_ids = _allowed_exercise_ids_at_athletes_rack(athlete.id, session)

    # UNION the plans, keeping ONE entry per movement.
    #
    # Someone in two TrainingGroups trains the team lift AND their position work — the
    # lists combine rather than one replacing the other. But a movement must
    # appear only once: progress is counted per movement, so a duplicate would
    # make the same completed sets show up twice and corrupt the set counter
    # the rack relies on.
    #
    # When both plans prescribe the same movement, the LIGHTER percentage wins.
    # Coaches adjust a group down to take load off, so the lower number is the
    # deliberate one. The winning row is taken whole — its sets and reps travel
    # with its percentage, because mixing one plan's load with another's rep
    # scheme is a prescription nobody wrote.
    by_exercise = {}
    order = []
    for participation in participations:
        workout = participation.training_program_workout
        if workout is None:
            continue  # coach hasn't chosen this TrainingGroup's workout for the day yet
        for row in workout.exercises.select_related("exercise").order_by("position"):
            if allowed_ids is not None and row.exercise_id not in allowed_ids:
                continue  # this rack can't do it, so don't offer it
            existing = by_exercise.get(row.exercise_id)
            if existing is None:
                by_exercise[row.exercise_id] = row
                order.append(row.exercise_id)
            elif row.target_percent is not None and existing.target_percent is not None \
                    and row.target_percent < existing.target_percent:
                by_exercise[row.exercise_id] = row   # lighter wins, whole row

    overrides = _overrides_for(athlete.id, [r.id for r in by_exercise.values()])

    movements = []
    for exercise_id in order:
        row = by_exercise[exercise_id]
        override = overrides.get(row.id)

        percent = row.target_percent
        sets = row.sets
        reps = row.reps
        if override is not None:
            # Only the fields the coach actually set are overridden; the rest of
            # the plan still applies.
            if override.target_percent is not None:
                percent = override.target_percent
            if override.sets is not None:
                sets = override.sets
            if override.reps is not None:
                reps = override.reps

        movements.append({
            "exercise_id": exercise_id,
            "name": row.exercise.name,
            "planned_sets": sets,
            "target_reps": reps,
            "target_weight_lbs": resolve_target_weight(athlete.id, exercise_id, percent),
            "velocity_zone_min": row.velocity_zone_min,
            "velocity_zone_max": row.velocity_zone_max,
        })

    return movements


def plans_by_athlete(session, athletes):
    """Everyone's movements for the day, keyed by athlete id.

    One place so the wall display, the coach tablet, and the rack can never
    disagree about what somebody is supposed to be doing — before this existed
    each read reached for the plan tables itself, and the room view was still
    reading a table the rack had already stopped using.
    """
    return {athlete.id: movements_for_athlete(athlete, session) for athlete in athletes}


def velocity_zones_by_athlete(session, athletes):
    """{athlete_id: {exercise_id: {velocity_min, velocity_max}}}.

    The dashboard colours a rep against the zone the athlete's own plan
    prescribes, so this is that plan narrowed to just the two numbers.
    """
    return {
        athlete_id: {
            movement["exercise_id"]: {
                "velocity_min": movement["velocity_zone_min"],
                "velocity_max": movement["velocity_zone_max"],
            } for movement in movements
        } for athlete_id, movements in plans_by_athlete(session, athletes).items()
    }
