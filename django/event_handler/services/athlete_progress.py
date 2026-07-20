from django.db import IntegrityError

from ..models import AthleteDayProgress


class AthleteProgramIncomplete(Exception):
    pass


def first_program_step(workout_program):
    item = (
        workout_program.items.select_related("workout")
        .prefetch_related("workout__exercises")
        .order_by("position", "id")
        .first()
    )
    exercise = item.workout.exercises.order_by("position", "id").first() if item else None
    if item is None or exercise is None:
        raise AthleteProgramIncomplete
    return item, exercise


def get_or_create_progress(session, athlete, assignment):
    progress = (
        AthleteDayProgress.objects.select_for_update(of=("self",))
        .select_related(
            "athlete",
            "workout_program",
            "current_program_item__workout",
            "current_workout_exercise",
        )
        .filter(session=session, athlete=athlete)
        .first()
    )
    if progress:
        return progress
    item, exercise = first_program_step(assignment.workout_program)
    try:
        return AthleteDayProgress.objects.create(
            session=session,
            athlete=athlete,
            workout_program=assignment.workout_program,
            current_program_item=item,
            current_workout_exercise=exercise,
            expected_set_number=1,
            status=AthleteDayProgress.READY,
        )
    except IntegrityError:
        return (
            AthleteDayProgress.objects.select_for_update(of=("self",))
            .select_related(
                "athlete",
                "workout_program",
                "current_program_item__workout",
                "current_workout_exercise",
            )
            .get(session=session, athlete=athlete)
        )
