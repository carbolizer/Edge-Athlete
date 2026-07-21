# tests.py — automated checks for the base-station endpoints.
#
# Covers GET /api/sessions/active/ (the rack screen's one startup fetch) and the
# GET /api/exercises/ catalog list. Each test pins one promise the rack screen
# relies on: which session counts as active, who reads as already having data,
# that an athlete's CURRENT reference max (and only that) comes back, and that
# every exercise now resolves through the shared catalog.
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from .models import Athlete, Program, Session, Set, AthleteReferenceMax, Exercise, RackCheckIn


class ActiveSessionEndpointTests(APITestCase):
    URL = "/api/sessions/active/"

    def _exercise(self, name):
        exercise, _ = Exercise.objects.get_or_create(name=name)
        return exercise

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
        squat = self._exercise("Back Squat")
        lifted = Athlete.objects.create(name="Lifted")
        idle = Athlete.objects.create(name="Idle")
        session.athletes.add(lifted, idle)
        Set.objects.create(session=session, athlete=lifted, exercise=squat,
                           set_number=1, ended_at=timezone.now())
        # idle has only an unfinished set → still counts as no data
        Set.objects.create(session=session, athlete=idle, exercise=squat, set_number=1)

        res = self.client.get(self.URL)
        by_name = {r["name"]: r for r in res.data["roster"]}
        self.assertTrue(by_name["Lifted"]["has_data"])
        self.assertFalse(by_name["Idle"]["has_data"])

    def test_returns_current_max_and_omits_missing_ones(self):
        session = Session.objects.create(label="Live")
        squat = self._exercise("Back Squat")
        bench = self._exercise("Bench Press")  # in the catalog, but no max for this athlete
        athlete = Athlete.objects.create(name="Max Tester")
        session.athletes.add(athlete)
        self._program(athlete, squat, 225.0)
        self._dated_max(athlete, squat, 300.0, days_ago=40)   # old
        self._dated_max(athlete, squat, 315.0, days_ago=2)    # current

        res = self.client.get(self.URL)
        entry = res.data["roster"][0]
        self.assertEqual(entry["maxes"][squat.id], 315.0)   # newest wins
        self.assertNotIn(bench.id, entry["maxes"])           # gap → no key

    def test_reference_max_can_go_down(self):
        # A reference max is "what they can do now", not a lifetime best: a newer,
        # LOWER row must supersede an older, higher one.
        session = Session.objects.create(label="Live")
        squat = self._exercise("Back Squat")
        athlete = Athlete.objects.create(name="Bad Week")
        session.athletes.add(athlete)
        self._dated_max(athlete, squat, 315.0, days_ago=30)  # was strong
        self._dated_max(athlete, squat, 285.0, days_ago=1)   # rough patch

        res = self.client.get(self.URL)
        self.assertEqual(res.data["roster"][0]["maxes"][squat.id], 285.0)

    def test_targets_and_exercises_come_from_programs(self):
        session = Session.objects.create(label="Live")
        squat = self._exercise("Back Squat")
        athlete = Athlete.objects.create(name="Planned")
        session.athletes.add(athlete)
        self._program(athlete, squat, 205.0)

        res = self.client.get(self.URL)
        self.assertEqual(res.data["roster"][0]["targets"][squat.id], 205.0)
        ex = res.data["session_exercises"][0]
        self.assertEqual(ex["exercise_id"], squat.id)       # real catalog id now
        self.assertEqual(ex["name"], "Back Squat")
        self.assertEqual(ex["velocity_zone_min"], 0.5)
        self.assertEqual(ex["velocity_zone_max"], 0.8)


class AthleteProgressEndpointTests(APITestCase):
    """GET /api/sessions/active/athlete/{id}/progress/ — the rack day-view. Pins:
    which sets count as completed, that false sets don't advance the number, the
    Program.id movement order, the status/current-movement logic, and the guards."""

    def _exercise(self, name):
        exercise, _ = Exercise.objects.get_or_create(name=name)
        return exercise

    def _program(self, athlete, exercise, weight, sets=5):
        return Program.objects.create(
            athlete=athlete, exercise=exercise, target_sets=sets, target_reps=3,
            target_weight_lbs=weight, velocity_zone_min=0.5, velocity_zone_max=0.8)

    def _finished_set(self, session, athlete, exercise, n, false=False):
        return Set.objects.create(
            session=session, athlete=athlete, exercise=exercise, set_number=n,
            is_false_set=false, ended_at=timezone.now())

    def _url(self, athlete_id):
        return f"/api/sessions/active/athlete/{athlete_id}/progress/"

    def test_no_active_session_returns_empty(self):
        athlete = Athlete.objects.create(name="Nobody")
        res = self.client.get(self._url(athlete.id))
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["session_id"])
        self.assertEqual(res.data["movements"], [])

    def test_unknown_athlete_is_404(self):
        Session.objects.create(label="Live")
        res = self.client.get(self._url(999999))
        self.assertEqual(res.status_code, 404)

    def test_athlete_not_on_roster_is_404(self):
        Session.objects.create(label="Live")
        outsider = Athlete.objects.create(name="Outsider")
        res = self.client.get(self._url(outsider.id))
        self.assertEqual(res.status_code, 404)

    def test_derives_progress_in_program_order(self):
        session = Session.objects.create(label="Live")
        squat = self._exercise("Back Squat")
        bench = self._exercise("Bench Press")
        athlete = Athlete.objects.create(name="Lifter")
        session.athletes.add(athlete)
        self._program(athlete, squat, 225.0)   # created first  → movement 1
        self._program(athlete, bench, 135.0)    # created second → movement 2
        self._finished_set(session, athlete, squat, 1)
        self._finished_set(session, athlete, squat, 2)
        self._finished_set(session, athlete, squat, 3, false=True)  # doesn't advance

        res = self.client.get(self._url(athlete.id))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["session_id"], session.id)
        self.assertEqual(res.data["current_exercise_id"], squat.id)
        moves = res.data["movements"]
        self.assertEqual([m["exercise_id"] for m in moves], [squat.id, bench.id])
        sq = moves[0]
        self.assertEqual(sq["completed_sets"], 2)
        self.assertEqual(sq["false_sets"], 1)
        self.assertEqual(sq["next_set_number"], 3)   # false set didn't count
        self.assertEqual(sq["status"], "in_progress")
        self.assertEqual(sq["target_weight_lbs"], 225.0)
        bn = moves[1]
        self.assertEqual(bn["completed_sets"], 0)
        self.assertEqual(bn["next_set_number"], 1)
        self.assertEqual(bn["status"], "not_started")

    def test_completed_movement_advances_current(self):
        session = Session.objects.create(label="Live")
        squat = self._exercise("Back Squat")
        bench = self._exercise("Bench Press")
        athlete = Athlete.objects.create(name="Lifter")
        session.athletes.add(athlete)
        self._program(athlete, squat, 225.0, sets=2)
        self._program(athlete, bench, 135.0, sets=3)
        self._finished_set(session, athlete, squat, 1)
        self._finished_set(session, athlete, squat, 2)   # squat now 2/2 → complete

        res = self.client.get(self._url(athlete.id))
        moves = {m["exercise_id"]: m for m in res.data["movements"]}
        self.assertEqual(moves[squat.id]["status"], "complete")
        self.assertEqual(res.data["current_exercise_id"], bench.id)

    def test_last_weight_is_newest_non_false_lift(self):
        # The day-view default for the next set follows what the athlete LAST
        # actually lifted this session (so an on-the-fly weight change carries
        # forward), never the prescribed target, and a false attempt doesn't count.
        session = Session.objects.create(label="Live")
        squat = self._exercise("Back Squat")
        bench = self._exercise("Bench Press")
        athlete = Athlete.objects.create(name="Lifter")
        session.athletes.add(athlete)
        self._program(athlete, squat, 225.0)
        self._program(athlete, bench, 135.0)
        Set.objects.create(session=session, athlete=athlete, exercise=squat,
                           set_number=1, weight_lbs=225.0, ended_at=timezone.now())
        Set.objects.create(session=session, athlete=athlete, exercise=squat,
                           set_number=2, weight_lbs=230.0, ended_at=timezone.now())
        Set.objects.create(session=session, athlete=athlete, exercise=squat,   # botched, heavier
                           set_number=3, weight_lbs=240.0, is_false_set=True, ended_at=timezone.now())

        res = self.client.get(self._url(athlete.id))
        moves = {m["exercise_id"]: m for m in res.data["movements"]}
        self.assertEqual(moves[squat.id]["target_weight_lbs"], 225.0)  # prescription untouched
        self.assertEqual(moves[squat.id]["last_weight_lbs"], 230.0)    # newest non-false lift
        self.assertIsNone(moves[bench.id]["last_weight_lbs"])          # not yet lifted → null


class RackCheckInEndpointTests(APITestCase):
    """POST /api/racks/{n}/checkin/ + GET /api/racks/{n}/checkins/ — the hot list.
    Pins: a check-in appears on that rack's list, ownership transfers to the newest
    rack (one athlete = one rack), and the guards."""

    def _session_with(self, *names):
        session = Session.objects.create(label="Live")
        athletes = [Athlete.objects.create(name=n) for n in names]
        session.athletes.add(*athletes)
        return session, athletes

    def _checkin(self, rack, athlete):
        return self.client.post(f"/api/racks/{rack}/checkin/", {"athlete": athlete.id}, format="json")

    def _hot_list(self, rack):
        return self.client.get(f"/api/racks/{rack}/checkins/")

    def test_checkin_appears_on_that_racks_hot_list(self):
        _, (jordan, _sam) = self._session_with("Jordan", "Sam")
        self.assertEqual(self._checkin(3, jordan).status_code, 201)
        self.assertEqual([a["name"] for a in self._hot_list(3).data["athletes"]], ["Jordan"])
        self.assertEqual(self._hot_list(4).data["athletes"], [])   # nobody at rack 4

    def test_ownership_transfers_to_newest_rack(self):
        _, (jordan,) = self._session_with("Jordan")
        self._checkin(1, jordan)
        self._checkin(2, jordan)   # moved to rack 2
        self.assertEqual(self._hot_list(1).data["athletes"], [])   # left rack 1
        self.assertEqual([a["name"] for a in self._hot_list(2).data["athletes"]], ["Jordan"])

    def test_no_active_session_checkin_is_400(self):
        Session.objects.create(label="Done", ended_at=timezone.now())  # ended → not active
        athlete = Athlete.objects.create(name="Nobody")
        self.assertEqual(self._checkin(1, athlete).status_code, 400)

    def test_unknown_and_offroster_athlete_are_404(self):
        self._session_with("Jordan")
        self.assertEqual(
            self.client.post("/api/racks/1/checkin/", {"athlete": 999999}, format="json").status_code, 404)
        outsider = Athlete.objects.create(name="Outsider")   # exists but not on the roster
        self.assertEqual(self._checkin(1, outsider).status_code, 404)

    def test_no_active_session_hot_list_is_empty(self):
        res = self._hot_list(1)
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["session_id"])
        self.assertEqual(res.data["athletes"], [])


class SessionStatusEndpointTests(APITestCase):
    """GET /api/sessions/active/status/ — room state. Pins the status each athlete
    reads as (lifting / resting / ready / not_started) and that a `since` timestamp
    rides along for the lifting/resting/ready cases."""

    def _live(self, *names):
        session = Session.objects.create(label="Live")
        athletes = [Athlete.objects.create(name=n) for n in names]
        session.athletes.add(*athletes)
        return session, athletes

    def test_status_reflects_each_athletes_activity(self):
        session, (lift, rest, ready, idle) = self._live("Lift", "Rest", "Ready", "Idle")
        squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        # lifting: an in-progress set (no ended_at)
        Set.objects.create(session=session, athlete=lift, exercise=squat, set_number=1)
        # resting: a finished set
        Set.objects.create(session=session, athlete=rest, exercise=squat, set_number=1,
                           ended_at=timezone.now())
        # ready: checked in, no set
        RackCheckIn.objects.create(session=session, athlete=ready, rack_number=2)
        # idle: nothing

        res = self.client.get("/api/sessions/active/status/")
        self.assertEqual(res.status_code, 200)
        by_name = {a["name"]: a for a in res.data["athletes"]}
        self.assertEqual(by_name["Lift"]["status"], "lifting")
        self.assertEqual(by_name["Rest"]["status"], "resting")
        self.assertEqual(by_name["Ready"]["status"], "ready")
        self.assertEqual(by_name["Idle"]["status"], "not_started")
        # a since timestamp rides along for everything but not_started
        self.assertIsNotNone(by_name["Lift"]["since"])
        self.assertIsNotNone(by_name["Ready"]["since"])
        self.assertIsNone(by_name["Idle"]["since"])
        self.assertEqual(by_name["Ready"]["rack_number"], 2)

    def test_no_active_session_is_empty(self):
        res = self.client.get("/api/sessions/active/status/")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["session_id"])
        self.assertEqual(res.data["athletes"], [])


class ExerciseCatalogEndpointTests(APITestCase):
    def test_lists_catalog_by_name(self):
        Exercise.objects.create(name="Bench Press")
        Exercise.objects.create(name="Back Squat")
        res = self.client.get("/api/exercises/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([e["name"] for e in res.data], ["Back Squat", "Bench Press"])
