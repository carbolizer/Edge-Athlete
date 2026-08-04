"""Create or remove the development-only wristband demo roster."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.db.models import Q

from event_handler.models import (
    Athlete,
    AthleteDayPlan,
    AthleteDayProgress,
    AthleteRackParticipation,
    AthleteSchedule,
    AthleteWorkoutAssignment,
    AthleteWorkoutExerciseOverride,
    AthleteWorkoutProgramAssignment,
    DailyReport,
    DemoAthleteSeed,
    Program,
    RackIdentityEvent,
    RackWorkoutState,
    Rep,
    Session,
    Set,
    Workout,
    WorkoutExercise,
    WorkoutProgram,
    WorkoutProgramItem,
)
from event_handler.services.training_days import lock_training_day
from event_handler.services.training_limits import MAX_SESSION_ATHLETES


DEMO_SEED_KEY = "wristband-v1"
DEMO_ATHLETES = (
    ("[DEMO] Avery", "edgeathlete-demo-wristband-avery"),
    ("[DEMO] Jordan", "edgeathlete-demo-wristband-jordan"),
    ("[DEMO] Morgan", "edgeathlete-demo-wristband-morgan"),
    ("[DEMO] Riley", "edgeathlete-demo-wristband-riley"),
)
DEMO_WORKOUT_NAME = "[DEMO] Wristband Workout"
DEMO_PROGRAM_NAME = "[DEMO] Wristband Program"
DEMO_EXERCISE = {
    "exercise": "Back squat",
    "position": 1,
    "sets": 3,
    "reps": 5,
    "default_weight_lbs": 0,
    "velocity_min": 0.5,
    "velocity_max": 0.8,
}


class Command(BaseCommand):
    help = "Seed or remove the four reserved wristband demo athletes for one legacy session."

    def add_arguments(self, parser):
        parser.add_argument("--session-id", type=int, required=True)
        parser.add_argument("--remove", action="store_true")
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["remove"]:
            raise CommandError("Demo athlete seeding requires settings.DEBUG=True.")
        session_id = options["session_id"]
        if session_id < 1:
            raise CommandError("--session-id must be a positive integer.")
        if options["remove"] and not options["confirm"]:
            raise CommandError("Pass --confirm with --remove; no records were changed.")

        try:
            with transaction.atomic():
                lock_training_day()
                session = Session.objects.select_for_update().filter(id=session_id).first()
                if session is None:
                    raise CommandError("Target session does not exist.")
                self._validate_session(session)
                seed = (
                    DemoAthleteSeed.objects.select_for_update()
                    .filter(key=DEMO_SEED_KEY)
                    .first()
                )
                counts = self._remove(session, seed) if options["remove"] else self._seed(session, seed)
        except IntegrityError as error:
            raise CommandError("Demo ownership changed concurrently; retry the command.") from error

        if options["remove"]:
            self.stdout.write(self.style.SUCCESS(
                f"Removed {counts['athletes']} demo athlete(s), {counts['sets']} Set(s), "
                f"{counts['reps']} Rep(s), and {counts['catalog']} reserved catalog graph(s)."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Demo wristband roster ready: {counts['athletes']} athletes in session {session.id}."
            ))

    def _validate_session(self, session):
        if session.ended_at is not None:
            raise CommandError("Target session has ended.")
        if session.is_simulated:
            raise CommandError("Target session is simulated.")
        if session.athlete_day_plans.exists() or session.athlete_progress.filter(day_plan__isnull=False).exists():
            raise CommandError("Target session uses a frozen schema 3 plan.")

    def _reserved_rows(self):
        names = [name for name, _nfc in DEMO_ATHLETES]
        nfc_ids = [nfc for _name, nfc in DEMO_ATHLETES]
        athletes = list(
            Athlete.objects.select_for_update()
            .filter(Q(name__in=names) | Q(nfc_tag_id__in=nfc_ids))
            .order_by("id")
        )
        workout = (
            Workout.objects.select_for_update()
            .filter(normalized_name=DEMO_WORKOUT_NAME.casefold())
            .first()
        )
        program = (
            WorkoutProgram.objects.select_for_update()
            .filter(normalized_name=DEMO_PROGRAM_NAME.casefold())
            .first()
        )
        return athletes, workout, program

    def _seed(self, session, seed):
        if seed is not None:
            self._lock_seed_assets(seed)
            self._validate_owned_graph(session, seed)
            return {"athletes": 4}

        athletes, workout, program = self._reserved_rows()
        if athletes or workout or program:
            raise CommandError("Reserved demo data exists without its ownership record; seeding aborted.")
        if session.athletes.count() + 4 > MAX_SESSION_ATHLETES:
            raise CommandError(f"Seeding would exceed the {MAX_SESSION_ATHLETES}-athlete session limit.")

        workout = Workout.objects.create(name=DEMO_WORKOUT_NAME)
        WorkoutExercise.objects.create(workout=workout, **DEMO_EXERCISE)
        program = WorkoutProgram.objects.create(name=DEMO_PROGRAM_NAME)
        WorkoutProgramItem.objects.create(workout_program=program, workout=workout, position=1)
        athletes = [
            Athlete.objects.create(name=name, nfc_tag_id=nfc_tag_id)
            for name, nfc_tag_id in DEMO_ATHLETES
        ]
        session.athletes.add(*athletes)
        AthleteWorkoutProgramAssignment.objects.bulk_create([
            AthleteWorkoutProgramAssignment(athlete=athlete, workout_program=program)
            for athlete in athletes
        ])
        DemoAthleteSeed.objects.create(
            key=DEMO_SEED_KEY,
            session=session,
            workout=workout,
            workout_program=program,
            athlete_1=athletes[0],
            athlete_2=athletes[1],
            athlete_3=athletes[2],
            athlete_4=athletes[3],
        )
        return {"athletes": 4}

    def _lock_seed_assets(self, seed):
        athlete_ids = self._athlete_ids(seed)
        list(Athlete.objects.select_for_update().filter(id__in=athlete_ids).order_by("id"))
        Workout.objects.select_for_update().get(id=seed.workout_id)
        WorkoutProgram.objects.select_for_update().get(id=seed.workout_program_id)
        list(WorkoutExercise.objects.select_for_update().filter(workout_id=seed.workout_id).order_by("id"))
        list(WorkoutProgramItem.objects.select_for_update().filter(workout_program_id=seed.workout_program_id).order_by("id"))
        list(AthleteWorkoutProgramAssignment.objects.select_for_update().filter(athlete_id__in=athlete_ids).order_by("athlete_id"))

    @staticmethod
    def _athlete_ids(seed):
        return [seed.athlete_1_id, seed.athlete_2_id, seed.athlete_3_id, seed.athlete_4_id]

    def _validate_owned_graph(self, session, seed):
        if seed.session_id != session.id:
            raise CommandError("The demo ownership record belongs to another session.")
        athletes = [seed.athlete_1, seed.athlete_2, seed.athlete_3, seed.athlete_4]
        if len({athlete.id for athlete in athletes}) != 4:
            raise CommandError("The demo ownership record has duplicate athlete slots.")
        for athlete, expected in zip(athletes, DEMO_ATHLETES):
            if (
                (athlete.name, athlete.nfc_tag_id) != expected
                or athlete.notes != ""
                or athlete.is_simulated
                or set(athlete.sessions.values_list("id", flat=True)) != {session.id}
            ):
                raise CommandError("A reserved demo athlete no longer matches its owned identity.")
            assignment = AthleteWorkoutProgramAssignment.objects.filter(athlete=athlete).first()
            if assignment is None or assignment.workout_program_id != seed.workout_program_id:
                raise CommandError("A reserved demo athlete has an invalid program binding.")

        workout = seed.workout
        program = seed.workout_program
        exercises = list(workout.exercises.all())
        items = list(program.items.all())
        if workout.name != DEMO_WORKOUT_NAME or program.name != DEMO_PROGRAM_NAME:
            raise CommandError("The reserved demo catalog names no longer match ownership.")
        if len(exercises) != 1 or any(
            getattr(exercises[0], field) != value for field, value in DEMO_EXERCISE.items()
        ):
            raise CommandError("The reserved demo workout does not match the expected prescription.")
        if len(items) != 1 or items[0].workout_id != workout.id or items[0].position != 1:
            raise CommandError("The reserved demo program does not match the expected workout graph.")
        self._assert_catalog_isolated(seed, athletes, exercises[0], items[0])

    def _assert_catalog_isolated(self, seed, athletes, exercise, item):
        athlete_ids = [athlete.id for athlete in athletes]
        workout = seed.workout
        program = seed.workout_program
        unsafe = (
            program.athlete_program_assignments.exclude(athlete_id__in=athlete_ids).exists()
            or program.athlete_schedule_plans.exists()
            or program.frozen_athlete_day_plans.exists()
            or program.athlete_progress.exclude(athlete_id__in=athlete_ids).exists()
            or workout.athlete_assignments.exists()
            or workout.athlete_schedule_occurrences.exists()
            or workout.frozen_day_occurrences.exists()
            or workout.rack_assignments.exists()
            or workout.workout_program_items.exclude(id=item.id).exists()
            or exercise.athlete_overrides.exists()
            or exercise.athlete_schedule_occurrences.exists()
            or exercise.frozen_day_occurrences.exists()
            or exercise.current_athlete_progress.exclude(athlete_id__in=athlete_ids).exists()
            or exercise.performed_sets.exclude(athlete_id__in=athlete_ids).exists()
            or item.athlete_assignments.exists()
            or item.rack_assignments.exists()
            or item.current_athlete_progress.exclude(athlete_id__in=athlete_ids).exists()
            or item.sets.exclude(athlete_id__in=athlete_ids).exists()
        )
        if unsafe:
            raise CommandError("Reserved demo catalog data has non-demo or unsafe references; operation aborted.")

    def _remove(self, session, seed):
        if seed is None:
            athletes, workout, program = self._reserved_rows()
            if athletes or workout or program:
                raise CommandError("Reserved demo data exists without its ownership record; cleanup aborted.")
            return {"athletes": 0, "sets": 0, "reps": 0, "catalog": 0}

        self._lock_seed_assets(seed)
        self._validate_owned_graph(session, seed)
        athletes = [seed.athlete_1, seed.athlete_2, seed.athlete_3, seed.athlete_4]
        athlete_ids = self._athlete_ids(seed)
        exercise = seed.workout.exercises.get()
        item = seed.workout_program.items.get()

        if RackWorkoutState.objects.filter(selected_athlete_id__in=athlete_ids).exists():
            raise CommandError("A demo athlete is selected on a rack; sign out before cleanup.")
        if AthleteSchedule.objects.filter(athlete_id__in=athlete_ids).exists():
            raise CommandError("A demo athlete has a schedule or schedule tombstone; cleanup aborted.")
        if AthleteDayPlan.objects.filter(athlete_id__in=athlete_ids).exists():
            raise CommandError("A demo athlete has a frozen day plan; cleanup aborted.")
        if AthleteWorkoutExerciseOverride.objects.filter(athlete_id__in=athlete_ids).exists():
            raise CommandError("A demo athlete has an exercise override; cleanup aborted.")
        if Program.objects.filter(athlete_id__in=athlete_ids).exists():
            raise CommandError("A demo athlete has a legacy Program; cleanup aborted.")
        if AthleteWorkoutAssignment.objects.filter(athlete_id__in=athlete_ids).exists():
            raise CommandError("A demo athlete has a direct workout assignment; cleanup aborted.")
        if DailyReport.objects.filter(session=session).exists():
            raise CommandError("The demo session has a daily report; cleanup aborted.")

        progress_rows = list(AthleteDayProgress.objects.filter(athlete_id__in=athlete_ids))
        if any(not self._valid_progress(row, session, seed.workout_program_id, item.id, exercise.id) for row in progress_rows):
            raise CommandError("Demo progress is malformed or references another session; cleanup aborted.")
        progress_by_id = {row.id: row for row in progress_rows}
        set_rows = list(Set.objects.filter(athlete_id__in=athlete_ids).prefetch_related("reps"))
        if any(not self._valid_set(row, session, progress_by_id, item.id, exercise.id) for row in set_rows):
            raise CommandError("A demo Set is malformed or references another session; cleanup aborted.")
        progress_ids = set(progress_by_id)
        set_ids = {row.id for row in set_rows}
        events = list(RackIdentityEvent.objects.filter(athlete_id__in=athlete_ids))
        if any(
            row.session_id != session.id
            or (row.resulting_set_id is not None and row.resulting_set_id not in set_ids)
            or (row.result == RackIdentityEvent.RESULT_CONFIRMED) != (row.resulting_set_id is None)
            or (
                row.resulting_set_id is not None
                and (
                    next(workout_set for workout_set in set_rows if workout_set.id == row.resulting_set_id).athlete_id != row.athlete_id
                    or next(workout_set for workout_set in set_rows if workout_set.id == row.resulting_set_id).rack_number != row.rack_number
                )
            )
            for row in events
        ):
            raise CommandError("A demo identity event is malformed or references another session; cleanup aborted.")
        if AthleteRackParticipation.objects.filter(athlete_id__in=athlete_ids).exclude(session=session).exists():
            raise CommandError("Demo rack participation references another session; cleanup aborted.")

        counts = {
            "athletes": 4,
            "sets": len(set_rows),
            "reps": Rep.objects.filter(set_id__in=set_ids).count(),
            "catalog": 1,
        }
        RackIdentityEvent.objects.filter(id__in=[row.id for row in events]).delete()
        AthleteRackParticipation.objects.filter(athlete_id__in=athlete_ids, session=session).delete()
        Set.objects.filter(id__in=set_ids).delete()
        AthleteDayProgress.objects.filter(id__in=progress_ids).delete()
        AthleteWorkoutProgramAssignment.objects.filter(athlete_id__in=athlete_ids).delete()
        session.athletes.remove(*athletes)
        seed.delete()
        Athlete.objects.filter(id__in=athlete_ids).delete()
        seed.workout_program.delete()
        seed.workout.delete()
        return counts

    @staticmethod
    def _valid_progress(row, session, program_id, item_id, exercise_id):
        if row.session_id != session.id or row.workout_program_id != program_id or row.day_plan_id is not None:
            return False
        if row.status == AthleteDayProgress.COMPLETE:
            return (
                row.current_program_item_id is None
                and row.current_workout_exercise_id is None
                and row.expected_set_number is None
            )
        return (
            row.status in {AthleteDayProgress.READY, AthleteDayProgress.IN_SET}
            and row.current_program_item_id == item_id
            and row.current_workout_exercise_id == exercise_id
            and row.current_day_plan_workout_id is None
            and row.current_day_plan_exercise_id is None
            and row.expected_set_number in {1, 2, 3}
        )

    @staticmethod
    def _valid_set(row, session, progress_by_id, item_id, exercise_id):
        progress = progress_by_id.get(row.athlete_day_progress_id)
        reps = list(row.reps.all())
        if progress is None or progress.athlete_id != row.athlete_id:
            return False
        if row.ended_at is None:
            valid_result = (
                row.reps_completed == 0 and not reps and row.avg_velocity is None
                and row.peak_velocity is None and not row.is_false_set
            )
        elif row.is_false_set:
            valid_result = (
                row.reps_completed == 0 and not reps and row.avg_velocity is None
                and row.peak_velocity is None
            )
        else:
            valid_result = (
                row.reps_completed == len(reps)
                and [rep.rep_number for rep in reps] == list(range(1, len(reps) + 1))
            )
        return (
            row.session_id == session.id
            and row.workout_program_item_id == item_id
            and row.workout_exercise_id == exercise_id
            and row.day_plan_workout_id is None
            and row.day_plan_exercise_id is None
            and row.exercise == DEMO_EXERCISE["exercise"]
            and row.set_number in {1, 2, 3}
            and row.weight_lbs == DEMO_EXERCISE["default_weight_lbs"]
            and not row.is_simulated
            and valid_result
        )
