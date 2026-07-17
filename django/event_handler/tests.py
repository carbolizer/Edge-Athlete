# tests.py — automated checks for the base-station endpoints.
#
# Right now this covers GET /api/sessions/active/ — the rack screen's one startup
# fetch — because everything the tablet does hangs off that payload being correct.
# Each test pins one promise the rack screen relies on: which session counts as
# active, who reads as already having data, and that an athlete's CURRENT max
# (and only that) comes back.
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from .models import Athlete, Program, Session, Set, AthleteReferenceMax


class ActiveSessionEndpointTests(APITestCase):
    URL = "/api/sessions/active/"

    def _program(self, athlete, exercise, weight):
        return Program.objects.create(
            athlete=athlete, exercise=exercise, target_sets=5, target_reps=3,
            target_weight_lbs=weight, velocity_zone_min=0.5, velocity_zone_max=0.8)

    def _dated_max(self, athlete, exercise, weight, days_ago):
        m = AthleteReferenceMax.objects.create(
            athlete=athlete, exercise=exercise, reference_weight_lbs=weight)
        AthleteReferenceMax.objects.filter(pk=m.pk).update(
            recorded_at=timezone.now() - timedelta(days=days_ago))
        return m

    def test_no_active_session_returns_empty_envelope(self):
        Session.objects.create(label="Done", ended_at=timezone.now())  # ended → not active
        res = self.client.get(self.URL)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["session_id"], None)
        self.assertEqual(res.data["roster"], [])
        self.assertEqual(res.data["session_exercises"], [])

    def test_picks_most_recent_unended_session(self):
        Session.objects.create(label="Older")
        newer = Session.objects.create(label="Newer")
        res = self.client.get(self.URL)
        self.assertEqual(res.data["session_id"], newer.id)
        self.assertEqual(res.data["label"], "Newer")

    def test_roster_has_data_reflects_completed_sets(self):
        session = Session.objects.create(label="Live")
        lifted = Athlete.objects.create(name="Lifted")
        idle = Athlete.objects.create(name="Idle")
        session.athletes.add(lifted, idle)
        Set.objects.create(session=session, athlete=lifted, exercise="Back Squat",
                           set_number=1, ended_at=timezone.now())
        # idle has only an unfinished set → still counts as no data
        Set.objects.create(session=session, athlete=idle, exercise="Back Squat", set_number=1)

        res = self.client.get(self.URL)
        by_name = {r["name"]: r for r in res.data["roster"]}
        self.assertTrue(by_name["Lifted"]["has_data"])
        self.assertFalse(by_name["Idle"]["has_data"])

    def test_returns_current_max_and_omits_missing_ones(self):
        session = Session.objects.create(label="Live")
        athlete = Athlete.objects.create(name="Max Tester")
        session.athletes.add(athlete)
        self._program(athlete, "Back Squat", 225.0)
        self._dated_max(athlete, "Back Squat", 300.0, days_ago=40)   # old
        self._dated_max(athlete, "Back Squat", 315.0, days_ago=2)    # current
        # no Bench Press max on file at all

        res = self.client.get(self.URL)
        entry = res.data["roster"][0]
        self.assertEqual(entry["maxes"]["Back Squat"], 315.0)   # newest wins
        self.assertNotIn("Bench Press", entry["maxes"])          # gap → no key

    def test_reference_max_can_go_down(self):
        # A reference max is "what they can do now", not a lifetime best: a newer,
        # LOWER row must supersede an older, higher one.
        session = Session.objects.create(label="Live")
        athlete = Athlete.objects.create(name="Bad Week")
        session.athletes.add(athlete)
        self._dated_max(athlete, "Back Squat", 315.0, days_ago=30)  # was strong
        self._dated_max(athlete, "Back Squat", 285.0, days_ago=1)   # rough patch

        res = self.client.get(self.URL)
        self.assertEqual(res.data["roster"][0]["maxes"]["Back Squat"], 285.0)

    def test_targets_and_exercises_come_from_programs(self):
        session = Session.objects.create(label="Live")
        athlete = Athlete.objects.create(name="Planned")
        session.athletes.add(athlete)
        self._program(athlete, "Back Squat", 205.0)

        res = self.client.get(self.URL)
        self.assertEqual(res.data["roster"][0]["targets"]["Back Squat"], 205.0)
        ex = res.data["session_exercises"][0]
        self.assertEqual(ex["exercise_id"], "Back Squat")
        self.assertEqual(ex["velocity_zone_min"], 0.5)
        self.assertEqual(ex["velocity_zone_max"], 0.8)
