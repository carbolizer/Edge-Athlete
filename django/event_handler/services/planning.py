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

from ..models import (ScheduledSession, TrainingBlock, TrainingBlockExercise, TrainingBlockWorkout,
                      TrainingProgram, TrainingProgramExercise, TrainingProgramWorkout)
from .cadence import training_dates


# ─────────────────────── editing a template ───────────────────────


class UnknownOrderObject(Exception):
    pass


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
    if len(ordered_ids) != len(set(ordered_ids)):
        raise ValueError("the id list must name every row in this parent, exactly once")
    rows = {row.pk: row for row in queryset}
    if not set(ordered_ids).issubset(rows):
        raise UnknownOrderObject
    if len(ordered_ids) != len(rows):
        raise ValueError("the id list must name every row in this parent, exactly once")

    highest = max((getattr(row, position_field) for row in rows.values()), default=0)
    offset = highest + len(rows) + 1
    if offset + len(rows) > 2_147_483_647:
        raise ValueError("positions are too large to reorder")
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
    group = group.__class__.objects.select_for_update().get(pk=group.pk)
    block = TrainingBlock.objects.select_for_update().get(pk=block.pk)
    if block.organization_id != group.organization_id:
        raise ValueError("the training block and group must belong to the same organization")

    source_workouts = list(
        TrainingBlockWorkout.objects.select_for_update()
        .filter(training_block=block).order_by("position")
    )

    program = TrainingProgram.objects.create(
        training_group=group,
        training_block=block,          # remembered so we know where it came from
        name=name or block.name,
        start_date=start_date,
        end_date=end_date,
    )

    for source_workout in source_workouts:
        source_exercises = list(source_workout.exercises.select_for_update().order_by("position"))
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
            ) for row in source_exercises
        ])

    generate_schedule(program, block)
    return program


@transaction.atomic
def promote_program_to_block(program, coach, name=None):
    """Turn a program into a NEW reusable TrainingBlock. Returns the block.

    WHAT THIS IS FOR: a coach writes a one-off plan for a group, or deploys a
    block and then edits the deployment until it is genuinely better than the
    template it came from. Either way they now have a good week of training
    trapped inside a single group's program. This lifts it back out so it can be
    run again next season, for anyone.

    ⚠️ THIS IS NOT "POINT THE FK AT A NEW BLOCK". That claim lived in this
    codebase and in the canon for weeks and was simply wrong: `training_block`
    records where a program came FROM and copies nothing, so pointing it at a
    fresh block yields a block with zero days. Deploying it would hand a group an
    empty plan — and it would look like a data-loss bug rather than a
    misunderstanding. The rows have to be copied UP first, which is what this
    does.

    It is `instantiate_block()` in reverse and deliberately mirrors it, so the
    two stay readable side by side. Same all-or-nothing rule: a block that got
    only half its days would look complete in the catalog and short-change
    whoever deployed it next.

    Works on ANY program, hand-written or edited-after-deploy, because the source
    rows are the same shape either way.
    """
    program = (TrainingProgram.objects.select_for_update()
               .select_related("training_group").get(pk=program.pk))
    source_block = None
    organization = program.training_group.organization
    if organization is None:
        raise ValueError("the program's training group has no organization")
    if program.training_block_id is not None:
        source_block = TrainingBlock.objects.select_for_update().get(pk=program.training_block_id)
        if source_block.organization_id != organization.id:
            raise ValueError("the program's training block belongs to another organization")

    source_workouts = list(program.workouts.select_for_update().order_by("position"))

    block = TrainingBlock.objects.create(
        name=name or program.name,
        coach=coach,
        organization=organization,
        # Carried across when the program came from a block: cadence and duration
        # are what make a block SCHEDULABLE, and the program was actually built on
        # them. A promoted block without them would generate an empty calendar.
        # Categories are deliberately NOT copied — filing is a decision the coach
        # makes about the new block, not a property of the training.
        cadence_days_of_week=source_block.cadence_days_of_week if source_block else "",
        duration_weeks=source_block.duration_weeks if source_block else None,
    )

    for source_workout in source_workouts:
        source_exercises = list(source_workout.exercises.select_for_update().order_by("position"))
        copied = TrainingBlockWorkout.objects.create(
            training_block=block,
            name=source_workout.name,
            position=source_workout.position,
        )
        TrainingBlockExercise.objects.bulk_create([
            TrainingBlockExercise(
                training_block_workout=copied,
                exercise_id=row.exercise_id,
                position=row.position,
                sets=row.sets,
                reps=row.reps,
                target_percent=row.target_percent,
                velocity_zone_min=row.velocity_zone_min,
                velocity_zone_max=row.velocity_zone_max,
            ) for row in source_exercises
        ])

    # Point the program at what it is now a deployment of.
    #
    # ⚠️ ACCEPTED LOSS, stated so it stays a choice: if this program came from
    # another block, that link is overwritten and "originally deployed from Fall
    # Strength" is no longer recorded anywhere. The alternative is a program
    # whose training_block names a template its contents no longer match, which
    # is worse — the FK's whole job is to answer "what is this a copy of", and
    # after promotion the honest answer is the new block.
    program.training_block = block
    program.save(update_fields=["training_block"])

    return block


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
