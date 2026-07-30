"""Turning a reusable template into a TrainingGroup's actual plan.

THE ONE IDEA
A coach writes a training block once — "Day 1: squat 5x3 at 80%, bench 3x5 at
75%" — and redeploys it for years. Deploying it for a TrainingGroup copies those rows
down into a program that belongs to that TrainingGroup and starts on a date.

WHY COPY INSTEAD OF POINTING AT THE TEMPLATE
Because a coach will tweak. If the program just referenced the template, then
editing the template next season would silently rewrite what last season's TrainingGroup
did, and their history would stop matching what they actually lifted. Copying
means: edit the template, future deployments change; edit a deployment, only that
TrainingGroup changes; either way, what already happened stays true.
"""

from django.db import transaction
from django.utils import timezone

from ..models import (ScheduledSession, TrainingBlock, TrainingBlockWorkout,
                      TrainingProgram, TrainingProgramExercise, TrainingProgramWorkout)
from .cadence import training_dates


# ─────────────────────── editing a template ───────────────────────

def touch_block(block_id):
    """Mark a block as edited just now.

    Renaming a day or changing a prescription row IS editing the template, even
    though the row being saved is a child. `auto_now` only fires for the row
    actually saved, so without this the child's timestamp moves and the block's
    goes stale — and a catalog sorted by "recently edited" would be wrong in
    exactly the case a coach cares about.

    ⚠️ ONLY for the block side. Editing a deployed TrainingProgram must NEVER
    call this: a program is a snapshot taken at deploy time and independent from
    that moment on, which is the whole reason a coach can adjust one group
    mid-season without disturbing the template or any other group running it.
    Touching the block from a program edit would report a template as changed
    when nobody changed it.
    """
    TrainingBlock.objects.filter(pk=block_id).update(updated_at=timezone.now())


@transaction.atomic
def apply_order(queryset, ordered_ids, *, position_field="position"):
    """Renumber rows to 1..n in the order given. Returns the number moved.

    Done in TWO PASSES on purpose. Both position columns carry a
    UniqueConstraint(parent, position) that is NOT deferrable, so Postgres checks
    it after every statement — meaning a straight "set this one to 2" collides
    with whichever row is still sitting on 2. Shifting everything far out of the
    way first means no two rows ever share a number mid-flight.

    Whole-list rather than per-item, so this is idempotent, takes one round trip,
    and cannot leave a gap or a duplicate. A sequence of per-item updates leaves
    the block in a broken order if one of them fails.
    """
    rows = {row.pk: row for row in queryset}
    if set(ordered_ids) != set(rows):
        raise ValueError("the id list must name every row in this parent, exactly once")

    offset = 10_000
    for index, row_id in enumerate(ordered_ids, start=1):
        queryset.model.objects.filter(pk=row_id).update(**{position_field: index + offset})
    for index, row_id in enumerate(ordered_ids, start=1):
        queryset.model.objects.filter(pk=row_id).update(**{position_field: index})
    return len(ordered_ids)


@transaction.atomic
def instantiate_block(block, group, name=None, start_date=None, end_date=None):
    """Deploy a template for a TrainingGroup. Returns the new program.

    All-or-nothing: a program that only got half its workouts copied would look
    complete to a coach and short-change the TrainingGroup mid-week, so a failure part
    way through leaves nothing behind rather than something plausible-but-wrong.
    """
    program = TrainingProgram.objects.create(
        training_group=group,
        training_block=block,          # remembered so we know where it came from
        name=name or block.name,
        start_date=start_date,
        end_date=end_date,
    )

    for source_workout in (TrainingBlockWorkout.objects
                           .filter(training_block=block)
                           .prefetch_related("exercises")
                           .order_by("position")):
        copied = TrainingProgramWorkout.objects.create(
            training_program=program,
            name=source_workout.name,
            position=source_workout.position,
        )
        TrainingProgramExercise.objects.bulk_create([
            TrainingProgramExercise(
                training_program_workout=copied,
                exercise_id=row.exercise_id,
                position=row.position,
                sets=row.sets,
                reps=row.reps,
                target_percent=row.target_percent,
                velocity_zone_min=row.velocity_zone_min,
                velocity_zone_max=row.velocity_zone_max,
            ) for row in source_workout.exercises.order_by("position")
        ])

    generate_schedule(program, block)
    return program


def generate_schedule(program, block=None):
    """Lay this program's days onto real dates. Returns the slots created.

    WHAT THIS IS FOR: a coach deploys an 8-week block that trains Mon/Wed/Fri and
    wants to see it on a calendar. This is the first thing that has ever READ
    `cadence_days_of_week` and `duration_weeks` — until P14 both were written by
    the block builder and read by nothing.

    Days are dealt out in the block's own order and then REPEATED. A three-day
    block on a Mon/Wed/Fri cadence gives Day 1 Monday, Day 2 Wednesday, Day 3
    Friday, then Day 1 again the next Monday — which is what a coach means by
    "this block runs for eight weeks". The rotation follows the DAY ORDER, not the
    weekday, so a block with two days on a three-day cadence keeps cycling
    properly instead of leaving Fridays empty.

    ⚠️ Generates NOTHING, silently, when the block has no cadence, no
    duration_weeks, or no days. That is not a failure: it is a template a coach
    has not finished describing, and refusing to deploy it would block a
    perfectly good one-off program. The schedule simply stays empty until they
    fill those in and deploy again.

    ⚠️ SLOTS ARE FROZEN once written. Nothing re-runs this for an existing
    program — editing the block's cadence later moves no existing slot, the same
    independence rule as the prescription rows copied above. `ignore_conflicts`
    covers the one-slot-per-program-per-day constraint so a re-deploy of the same
    program cannot double a calendar.
    """
    block = block or program.training_block
    if block is None:
        return []

    dates = training_dates(program.start_date, block.cadence_days_of_week,
                           block.duration_weeks)
    days = list(program.workouts.order_by("position"))
    if not dates or not days:
        return []

    slots = [
        ScheduledSession(
            training_program=program,
            training_program_workout=days[index % len(days)],
            date=date,
        )
        for index, date in enumerate(dates)
    ]
    ScheduledSession.objects.bulk_create(slots, ignore_conflicts=True)
    return program.scheduled_sessions.order_by("date", "id")