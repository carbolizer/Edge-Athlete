# tests.py — automated checks for the base-station endpoints.
#
# Covers GET /api/sessions/active/ (the rack screen's one startup fetch) and the
# GET /api/exercises/ catalog list. Each test pins one promise the rack screen
# relies on: which session counts as active, who reads as already having data,
# that an athlete's CURRENT reference max (and only that) comes back, and that
# every exercise now resolves through the shared catalog.
from datetime import timedelta

from django.utils import timezone
from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import (Athlete, Program, Session, Set, Rep, AthleteReferenceMax, Exercise,
                     RackCheckIn, DailyReport)


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
        # Migration 0009_seed_exercise_catalog already seeds the canonical movements,
        # so this test can no longer assume an empty table (its original assumption).
        # Add two rows whose names bracket the alphabet — chosen NOT to collide with
        # the seeded set — then assert the endpoint returns the whole catalog sorted
        # by name and includes them. This checks the real invariant (name-sorted
        # ordering) robustly, instead of hard-coding the exact catalog contents.
        Exercise.objects.create(name="Aardvark Raise")
        Exercise.objects.create(name="Zercher Carry")
        res = self.client.get("/api/exercises/")
        self.assertEqual(res.status_code, 200)
        names = [e["name"] for e in res.data]
        self.assertIn("Aardvark Raise", names)
        self.assertIn("Zercher Carry", names)
        self.assertEqual(names, sorted(names))


class RoomStateEndpointTests(APITestCase):
    """GET /api/room-state/ — the derived live room picture (merge canon D8).

    These pin the thing the merge actually changed: the room view is rebuilt
    from RackCheckIn + Set/Rep instead of the dropped RackWorkoutState /
    AthleteDayProgress tables. They also pin the wall-vs-coach privilege
    boundary, since `?details=true` is what folds his old `wall-state/` and
    `room-state/` into one route (R3).
    """

    def _room(self):
        session = Session.objects.create(label="Live")
        athlete = Athlete.objects.create(name="Jordan Lee")
        session.athletes.add(athlete)
        squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        return session, athlete, squat

    def test_rack_occupancy_comes_from_the_checkin_log(self):
        """The core D8 rebuild: nobody assigns a rack, so an athlete appears at
        one purely because their newest check-in names it."""
        session, athlete, _ = self._room()

        # Before check-in the room knows of no occupied rack.
        res = self.client.get("/api/room-state/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"]["active_racks"], 0)

        RackCheckIn.objects.create(session=session, athlete=athlete, rack_number=3)

        res = self.client.get("/api/room-state/")
        rack = next(r for r in res.data["racks"] if r["rack_number"] == 3)
        self.assertEqual(rack["athlete"]["name"], "Jordan Lee")
        self.assertEqual(res.data["summary"]["active_racks"], 1)

    def test_newest_checkin_moves_the_athlete(self):
        """Check-ins are append-only and newest-wins, so moving racks is just a
        newer row — the athlete must not appear at both."""
        session, athlete, _ = self._room()
        RackCheckIn.objects.create(session=session, athlete=athlete, rack_number=1)
        RackCheckIn.objects.create(session=session, athlete=athlete, rack_number=2)

        res = self.client.get("/api/room-state/")
        occupied = {r["rack_number"] for r in res.data["racks"] if r["athlete"] is not None}
        self.assertEqual(occupied, {2})

    def test_status_and_color_derive_from_the_latest_set(self):
        """Per-rack `status` is set lifecycle; `status_color` is the velocity zone
        of the last rep. Two different concepts that share a palette (canon §5.6)."""
        session, athlete, squat = self._room()
        RackCheckIn.objects.create(session=session, athlete=athlete, rack_number=1)

        # An in-progress set reads as active, with no colour yet.
        live_set = Set.objects.create(session=session, athlete=athlete, exercise=squat, set_number=1)
        res = self.client.get("/api/room-state/")
        rack = next(r for r in res.data["racks"] if r["rack_number"] == 1)
        self.assertEqual(rack["status"], "active")
        self.assertEqual(rack["status_color"], "neutral")

        # Finishing it flips to complete, and the last rep supplies the colour.
        live_set.ended_at = timezone.now()
        live_set.reps_completed = 1
        live_set.save()
        Rep.objects.create(set=live_set, rep_number=1, timestamp=timezone.now(),
                           mean_velocity=0.7, peak_velocity=0.9, duration_ms=800,
                           velocity_color="green")
        res = self.client.get("/api/room-state/")
        rack = next(r for r in res.data["racks"] if r["rack_number"] == 1)
        self.assertEqual(rack["status"], "complete")
        self.assertEqual(rack["status_color"], "green")

    def test_wall_view_is_open_but_hides_ids_and_roster(self):
        """The wall screen hangs in the gym with nobody logged in, so it gets
        names and numbers only — no database ids, no participant roster."""
        self._room()
        res = self.client.get("/api/room-state/")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("id", res.data["session"])
        self.assertNotIn("participants", res.data)

    def test_details_requires_a_coach_login(self):
        """Asking for the detail level IS asking for coach data, so it must 401
        rather than silently downgrading to the wall view."""
        self._room()
        self.assertEqual(self.client.get("/api/room-state/?details=true").status_code, 401)

    def test_details_adds_ids_and_roster_for_a_coach(self):
        session, athlete, _ = self._room()
        coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=coach)

        res = self.client.get("/api/room-state/?details=true")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["session"]["id"], session.id)
        self.assertEqual([p["name"] for p in res.data["participants"]], ["Jordan Lee"])

    def test_empty_room_still_answers(self):
        """No session at all is a normal state (before the first session of the
        day), not an error — the wall must render something."""
        res = self.client.get("/api/room-state/")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["session"])
        self.assertEqual(res.data["summary"]["completed_sets"], 0)
        self.assertEqual(res.data["leaderboard"], [])


class SessionCompletionTests(APITestCase):
    """Ending a training day (merge canon R2 + D10).

    Pins the two things that must happen exactly once when a coach ends a
    session: an immutable report gets frozen, and everyone's reference maxes
    move forward from what they actually lifted.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.session = Session.objects.create(label="Thursday")
        self.athlete = Athlete.objects.create(name="Jordan Lee")
        self.session.athletes.add(self.athlete)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]

    def _completed_set(self, weight, reps, **kwargs):
        return Set.objects.create(
            session=self.session, athlete=self.athlete, exercise=self.squat,
            set_number=kwargs.pop("set_number", 1), weight_lbs=weight,
            reps_completed=reps, ended_at=timezone.now(), **kwargs)

    def test_patching_a_session_ends_it_and_freezes_a_report(self):
        """There is no `end/` route — ending IS the PATCH (canon R2)."""
        self._completed_set(225, 3)
        res = self.client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(res.data["ended_at"])
        self.assertIn("daily_report", res.data)
        self.assertEqual(DailyReport.objects.filter(session=self.session).count(), 1)

    def test_ending_twice_does_not_write_a_second_report(self):
        """A double-tapped "end session" button must not produce two records of
        one day, so the second call returns the first report unchanged."""
        self._completed_set(225, 3)
        first = self.client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")
        second = self.client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")
        self.assertEqual(first.data["daily_report"]["id"], second.data["daily_report"]["id"])
        self.assertEqual(DailyReport.objects.count(), 1)

    def test_report_snapshot_captures_the_days_work(self):
        self._completed_set(225, 3)
        self.client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")
        snapshot = DailyReport.objects.get().snapshot
        self.assertEqual(snapshot["summary"]["completed_sets"], 1)
        self.assertEqual(snapshot["summary"]["completed_reps"], 3)
        self.assertEqual(snapshot["athletes"][0]["athlete"]["name"], "Jordan Lee")

    def test_rack_participation_comes_from_checkins(self):
        """Which racks an athlete used is derived from the check-in log, not a
        stored participation table (canon D2)."""
        self._completed_set(225, 3)
        RackCheckIn.objects.create(session=self.session, athlete=self.athlete, rack_number=4)
        RackCheckIn.objects.create(session=self.session, athlete=self.athlete, rack_number=2)
        self.client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")
        snapshot = DailyReport.objects.get().snapshot
        self.assertEqual(snapshot["athletes"][0]["rack_participation"], [2, 4])

    def test_ending_writes_a_new_estimated_reference_max(self):
        """D10: today's real work sets tomorrow's targets, append-only."""
        self._completed_set(225, 3)
        self.client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")
        estimated = AthleteReferenceMax.objects.filter(
            athlete=self.athlete, exercise=self.squat,
            source=AthleteReferenceMax.SOURCE_ESTIMATED)
        self.assertEqual(estimated.count(), 1)
        # Epley: 225 x (1 + 3/30) = 247.5
        self.assertAlmostEqual(estimated.first().reference_weight_lbs, 247.5, places=1)
        self.assertEqual(estimated.first().rep_basis, 1)

    def test_reference_max_estimate_ignores_junk_sets(self):
        """A false set, a coach's weight adjustment, and a 30-rep conditioning
        set are all real rows but none of them describe a max."""
        self._completed_set(500, 3, set_number=1, is_false_set=True)
        self._completed_set(500, 3, set_number=2, is_coach_adjustment=True)
        self._completed_set(500, 40, set_number=3)          # outside the rep window
        self._completed_set(225, 3, set_number=4)           # the one honest effort
        self.client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")
        best = AthleteReferenceMax.objects.filter(
            source=AthleteReferenceMax.SOURCE_ESTIMATED).first()
        self.assertAlmostEqual(best.reference_weight_lbs, 247.5, places=1)

    def test_reference_max_can_go_down(self):
        """The reference is "what can they do now", not a trophy — a weaker day
        must be allowed to pull tomorrow's prescribed weights back."""
        AthleteReferenceMax.objects.create(
            athlete=self.athlete, exercise=self.squat, reference_weight_lbs=400,
            source=AthleteReferenceMax.SOURCE_MANUAL)
        self._completed_set(225, 3)
        self.client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")
        newest = AthleteReferenceMax.objects.filter(
            athlete=self.athlete, exercise=self.squat).first()  # ordering is newest-first
        self.assertAlmostEqual(newest.reference_weight_lbs, 247.5, places=1)


class ReportsEndpointTests(APITestCase):
    """GET /api/reports/ — one family, athlete view is a filter (canon R6)."""

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.session = Session.objects.create(label="Thursday")
        self.athlete = Athlete.objects.create(name="Jordan Lee")
        self.session.athletes.add(self.athlete)
        squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        Set.objects.create(session=self.session, athlete=self.athlete, exercise=squat,
                           set_number=1, weight_lbs=225, reps_completed=3,
                           ended_at=timezone.now())
        self.client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")

    def test_lists_reports(self):
        res = self.client.get("/api/reports/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)

    def test_filters_by_athlete(self):
        self.assertEqual(len(self.client.get(f"/api/reports/?athlete={self.athlete.id}").data), 1)
        self.assertEqual(len(self.client.get("/api/reports/?athlete=9999").data), 0)

    def test_reports_require_a_coach(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get("/api/reports/").status_code, 401)

    def test_missing_report_is_404(self):
        self.assertEqual(self.client.get("/api/reports/9999/").status_code, 404)


class ReferenceMaxWriteTests(APITestCase):
    """POST /api/reference-maxes/ — the prescription lever."""

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        self.a1 = Athlete.objects.create(name="A One")
        self.a2 = Athlete.objects.create(name="A Two")

    def test_records_a_whole_squad_in_one_call(self):
        res = self.client.post("/api/reference-maxes/", {
            "exercise": self.squat.id, "rep_basis": 1,
            "entries": [{"athlete": self.a1.id, "reference_weight_lbs": 315},
                        {"athlete": self.a2.id, "reference_weight_lbs": 275}],
        }, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(AthleteReferenceMax.objects.count(), 2)

    def test_re_entering_supersedes_without_deleting_history(self):
        """Append-only: the newest row wins, the old one stays graphable."""
        for weight in (300, 315):
            self.client.post("/api/reference-maxes/", {
                "exercise": self.squat.id,
                "entries": [{"athlete": self.a1.id, "reference_weight_lbs": weight}],
            }, format="json")
        rows = AthleteReferenceMax.objects.filter(athlete=self.a1)
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.first().reference_weight_lbs, 315)  # newest-first ordering

    def test_rejects_unknown_athlete_and_empty_entries(self):
        self.assertEqual(self.client.post("/api/reference-maxes/", {
            "exercise": self.squat.id,
            "entries": [{"athlete": 9999, "reference_weight_lbs": 315}]}, format="json").status_code, 404)
        self.assertEqual(self.client.post("/api/reference-maxes/", {
            "exercise": self.squat.id, "entries": []}, format="json").status_code, 400)
