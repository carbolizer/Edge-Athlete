# seed_active_session.py — fill an empty dev database with one realistic, live
# training session so the rack screen has real data to fetch on day one.
#
# It builds exactly what GET /api/sessions/active/ is meant to return: a session
# that hasn't ended, a roster of athletes, a training plan (Program) per athlete,
# a few already-finished sets so some athletes read as "has data" (and some
# don't), and real recorded maxes (AthleteMax) — on purpose leaving one gap and
# one older-then-newer pair so you can see the endpoint pick the current max and
# expose the "no max yet" case the rack screen prompts for.
#
# Re-runnable: pass --reset to wipe just the rows this command creates (matched
# by the fixed names below) and rebuild them cleanly.
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from event_handler.models import (Athlete, Program, Session, Set, Rep, Node,
                                   AthleteReferenceMax, Exercise)

SESSION_LABEL = "Thursday — Lower + Push"
NODE_ID = "rack_1"

# (name, back-squat target lbs, bench target lbs) — targets live on each
# athlete's Program; the endpoint hands these back as resolved target weights.
ATHLETES = [
    {"name": "Jordan Lee",   "squat_target": 225.0, "bench_target": 155.0},
    {"name": "Sam Rivera",   "squat_target": 275.0, "bench_target": 185.0},
    {"name": "Alex Kim",     "squat_target": 185.0, "bench_target": 135.0},
    {"name": "Taylor Fox",   "squat_target": 205.0, "bench_target": 145.0},
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
        names = [a["name"] for a in ATHLETES]

        if options["reset"]:
            # Deleting the Session cascades its Sets/Reps; the rest we clear by
            # the fixed names/ids this seed owns, so real data is left alone.
            Session.objects.filter(label=SESSION_LABEL).delete()
            AthleteReferenceMax.objects.filter(athlete__name__in=names).delete()
            Program.objects.filter(athlete__name__in=names).delete()
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

        # Athletes + their per-exercise training plans.
        athletes = {}
        for spec in ATHLETES:
            athlete, _ = Athlete.objects.get_or_create(name=spec["name"])
            athletes[spec["name"]] = athlete
            Program.objects.get_or_create(
                athlete=athlete, exercise=squat,
                defaults={"target_sets": 5, "target_reps": 3,
                          "target_weight_lbs": spec["squat_target"],
                          "velocity_zone_min": 0.5, "velocity_zone_max": 0.8})
            Program.objects.get_or_create(
                athlete=athlete, exercise=bench,
                defaults={"target_sets": 4, "target_reps": 5,
                          "target_weight_lbs": spec["bench_target"],
                          "velocity_zone_min": 0.4, "velocity_zone_max": 0.7})

        # The live session, roster = all four athletes.
        session = Session.objects.create(label=SESSION_LABEL)
        session.athletes.set(athletes.values())

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
            f"{len(athletes)} athletes, programs, 2 completed sets, and maxes."))

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
