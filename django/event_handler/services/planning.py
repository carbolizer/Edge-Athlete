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

from ..models import (TrainingBlock, TrainingBlockWorkout, TrainingProgram,
                      TrainingProgramExercise, TrainingProgramWorkout)


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

    return program