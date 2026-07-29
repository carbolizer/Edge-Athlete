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

from ..models import (TrainingBlockWorkout, TrainingProgram,
                      TrainingProgramExercise, TrainingProgramWorkout)


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