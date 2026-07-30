# seed_active_session.py — fill an empty dev database with one realistic, live
# training session so the rack screen has real data to fetch on day one.
#
# It builds exactly what GET /api/sessions/active/ is meant to return: a session
# that hasn't ended, a roster of athletes, a plan they train, a few already-
# finished sets so some athletes read as "has data" (and some don't), and real
# recorded maxes — on purpose leaving one gap and one older-then-newer pair so
# you can see the endpoint pick the current max and expose the "no max yet" case
# the rack screen prompts for.
#
# The plan is built the way a coach builds one: a TrainingBlock (the reusable
# template) is deployed as a TrainingProgram for a TrainingGroup, and that group
# is scheduled into the session. Prescriptions are PERCENTAGES, so the pounds
# each athlete sees come from their own reference max — which is why Taylor Fox's
# missing bench max shows up as a real "no target" case rather than a made-up
# number.
#
# Re-runnable: pass --reset to wipe just the rows this command creates (matched
# by the fixed names below) and rebuild them cleanly.
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from django.contrib.auth.models import User

from event_handler.models import (Athlete, AthleteReferenceMax, DailyReport, Exercise,
                                  Node, Rep, TrainingSession, SessionParticipation, Set,
                                  TrainingBlock, TrainingBlockExercise, TrainingBlockWorkout,
                                  TrainingGroup, TrainingGroupCoach, TrainingProgram)
from event_handler.services.planning import instantiate_block

SESSION_LABEL = "Thursday — Lower + Push"
NODE_ID = "rack_1"
GROUP_NAME = "Varsity"
BLOCK_NAME = "Base Strength"
WORKOUT_NAME = "Thursday — Lower + Push"

ATHLETES = ["Jordan Lee", "Sam Rivera", "Alex Kim", "Taylor Fox"]

# The prescription, written once for the whole group. 72% of a 315 squat is 227,
# which rounds to 225 — the same bar the old per-athlete seed put in front of
# Jordan, now arrived at the way the system actually works.
PRESCRIPTION = [
    {"exercise": "Back Squat",  "sets": 5, "reps": 3, "percent": 72.0,
     "zone_min": 0.5, "zone_max": 0.8},
    {"exercise": "Bench Press", "sets": 4, "reps": 5, "percent": 75.0,
     "zone_min": 0.4, "zone_max": 0.7},
]

SQUAT = "Back Squat"
BENCH = "Bench Press"


class Command(BaseCommand):
    help = "Seed one active (not-yet-ended) session with roster, programs, sets, and maxes."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Delete this command's previously seeded rows first, then reseed.")

    @transaction.atomic
    def handle(self, *args, **options):
        names = list(ATHLETES)

        if options["reset"]:
            # We clear by the fixed names/ids this seed owns, so real data is
            # left alone.
            #
            # Order matters, and BOTH of these are PROTECT on purpose: a Set is
            # the only permanent record that an athlete actually lifted, and a
            # DailyReport is the frozen history of a finished day. Neither may
            # be taken out silently by deleting a session. So the seeder — which
            # is allowed to destroy its own demo data — has to say plainly that
            # it is removing them.
            #
            # The report side only bites once a day has actually been ENDED, so
            # it went unnoticed until someone ended one in the browser.
            Set.objects.filter(session__label=SESSION_LABEL).delete()
            DailyReport.objects.filter(session__label=SESSION_LABEL).delete()
            TrainingSession.objects.filter(label=SESSION_LABEL).delete()
            AthleteReferenceMax.objects.filter(athlete__name__in=names).delete()
            TrainingProgram.objects.filter(training_group__name=GROUP_NAME).delete()
            TrainingBlock.objects.filter(name=BLOCK_NAME).delete()
            TrainingGroup.objects.filter(name=GROUP_NAME).delete()
            Athlete.objects.filter(name__in=names).delete()
            Node.objects.filter(node_id=NODE_ID).delete()
            self.stdout.write("Reset: cleared previously seeded rows.")

        # A sensor node linked to rack 1, so the simulator + broadcasts have a
        # rack to talk about later in Phase 10/11.
        node, _ = Node.objects.get_or_create(
            node_id=NODE_ID, defaults={"rack_number": 1, "mount_type": Node.MOUNT_BAR})

        # The two movements, in the catalog. Everything below links to these.
        squat, _ = Exercise.objects.get_or_create(name=SQUAT)
        bench, _ = Exercise.objects.get_or_create(name=BENCH)

        # A coach to own the group and the template.
        coach = User.objects.filter(is_staff=True).first() or User.objects.first()
        if coach is None:
            coach = User.objects.create_user(username="coach", password="coach")

        # Athletes, and the group they all train with.
        athletes = {name: Athlete.objects.get_or_create(name=name)[0] for name in ATHLETES}
        group, _ = TrainingGroup.objects.get_or_create(name=GROUP_NAME)
        # Staff are a join table now, not a field — a group can have several.
        TrainingGroupCoach.objects.get_or_create(
            training_group=group, coach=coach,
            defaults={"role": TrainingGroupCoach.HEAD})
        for athlete in athletes.values():
            athlete.training_groups.add(group)

        # The template, written once — then deployed for the group. Deploying
        # copies the rows down, which is why editing the template later can't
        # rewrite what this group already trained.
        # Cadence and duration are set so the demo block actually SCHEDULES.
        # They were both blank before P14, which was harmless while nothing read
        # them — now it would mean a deployed program with an empty calendar and
        # no obvious reason why.
        block, _ = TrainingBlock.objects.get_or_create(name=BLOCK_NAME, coach=coach)
        # Set rather than passed as `defaults`: defaults only apply when the row
        # is CREATED, so on any database that already held this block from before
        # P14 the cadence would have stayed blank and the demo would show a
        # deployed program with an empty calendar and no obvious reason why. A
        # seeder should converge on the state it promises, not depend on running
        # first.
        if not block.cadence_days_of_week or not block.duration_weeks:
            block.cadence_days_of_week = "Mon,Wed,Fri"
            block.duration_weeks = 4
            block.save(update_fields=["cadence_days_of_week", "duration_weeks"])
        if not block.workouts.exists():
            workout = TrainingBlockWorkout.objects.create(
                training_block=block, name=WORKOUT_NAME, position=1)
            for position, row in enumerate(PRESCRIPTION, start=1):
                TrainingBlockExercise.objects.create(
                    training_block_workout=workout,
                    exercise=Exercise.objects.get(name=row["exercise"]),
                    position=position, sets=row["sets"], reps=row["reps"],
                    target_percent=row["percent"],
                    velocity_zone_min=row["zone_min"], velocity_zone_max=row["zone_max"])

        # localdate(), not now().date(): a calendar date should be the date in the
        # gym, not in UTC. Identical while TIME_ZONE is UTC, and wrong by a day
        # every evening the moment anyone sets a real one. room_state.py already
        # uses localdate() for the same reason.
        program = instantiate_block(block, group, start_date=timezone.localdate())

        # Close anything still open before opening a new day. Re-running the
        # seeder used to stack another open session every time, which is exactly
        # how the demo database ended up with four of them and made "End training
        # day" look broken (canon D18) — ending the top one just promoted the
        # next. The API now refuses a second open session; the seeder writes rows
        # directly, so it has to hold the same rule itself.
        closed = TrainingSession.objects.filter(ended_at__isnull=True).update(
            ended_at=timezone.now())
        if closed:
            self.stdout.write(f"  closed {closed} session(s) that were still open")

        # The live session, roster = all four athletes.
        # started_at is explicit since P14 — a session can now exist unstarted,
        # and the whole point of this seeder is a day that is actually running.
        session = TrainingSession.objects.create(label=SESSION_LABEL,
                                                 started_at=timezone.now())
        session.athletes.set(athletes.values())

        # Put the group ON the session, pointed at the day's workout. Without
        # this the session has a roster but nobody has anything to lift — the
        # session is where the plan and the people actually meet.
        SessionParticipation.objects.create(
            session=session, training_program=program,
            training_program_workout=program.workouts.order_by("position").first())

        # Give TWO of the four a finished set already, so has_data is non-trivial
        # (Jordan + Sam read as has_data=true; Alex + Taylor as false → their next
        # set would NOT be a makeup, the first two's WOULD).
        self._finish_a_set(session, node, athletes["Jordan Lee"], squat, 1, 205.0)
        self._finish_a_set(session, node, athletes["Sam Rivera"], squat, 1, 255.0)

        # Recorded reference maxes (AthleteReferenceMax). Deliberately shaped to
        # exercise the endpoint:
        #  - Jordan gets an OLD squat ref then a NEWER one → endpoint must return 315.
        #  - Most athletes have both lifts; Taylor has NO bench ref → the rack
        #    screen's inline "set your max" prompt has a real gap to fill.
        self._record_max(athletes["Jordan Lee"], squat, 300.0, days_ago=40)
        self._record_max(athletes["Jordan Lee"], squat, 315.0, days_ago=3)
        self._record_max(athletes["Jordan Lee"], bench, 205.0, days_ago=5)
        self._record_max(athletes["Sam Rivera"], squat, 365.0, days_ago=7)
        self._record_max(athletes["Sam Rivera"], bench, 245.0, days_ago=7)
        self._record_max(athletes["Alex Kim"],   squat, 245.0, days_ago=10)
        self._record_max(athletes["Alex Kim"],   bench, 175.0, days_ago=10)
        self._record_max(athletes["Taylor Fox"], squat, 275.0, days_ago=14)
        # Taylor Fox — Bench Press: intentionally left with no max on file.

        self.stdout.write(self.style.SUCCESS(
            f"Seeded active session '{session.label}' (id={session.id}) with "
            f"{len(athletes)} athletes in '{GROUP_NAME}' training '{program.name}', "
            f"2 completed sets, and maxes."))

    def _finish_a_set(self, session, node, athlete, exercise, set_number, weight_lbs):
        """Create one already-completed set with a couple of reps, so the athlete
        reads as has_data=true for this session."""
        s = Set.objects.create(
            session=session, athlete=athlete, node=node, exercise=exercise,
            set_number=set_number, weight_lbs=weight_lbs, reps_completed=2,
            avg_velocity=0.68, peak_velocity=0.82, is_false_set=False,
            ended_at=timezone.now())
        for n in (1, 2):
            Rep.objects.create(set=s, rep_number=n, timestamp=timezone.now(),
                               mean_velocity=0.68, peak_velocity=0.82,
                               duration_ms=700, velocity_color="green")
        return s

    def _record_max(self, athlete, exercise, weight_lbs, days_ago,
                    source=AthleteReferenceMax.SOURCE_MANUAL):
        """Append one reference-max row, back-dating recorded_at so 'newest wins'
        is testable (auto_now_add is set on create, so we override it with a
        direct update)."""
        m = AthleteReferenceMax.objects.create(
            athlete=athlete, exercise=exercise, reference_weight_lbs=weight_lbs, source=source)
        AthleteReferenceMax.objects.filter(pk=m.pk).update(
            recorded_at=timezone.now() - timedelta(days=days_ago))
        return m
