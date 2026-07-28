# tests.py — automated checks for the base-station endpoints.
#
# Covers GET /api/sessions/active/ (the rack screen's one startup fetch) and the
# GET /api/exercises/ catalog list. Each test pins one promise the rack screen
# relies on: which session counts as active, who reads as already having data,
# that an athlete's CURRENT reference max (and only that) comes back, and that
# every exercise now resolves through the shared catalog.
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import (Athlete, Program, Session, Set, Rep, AthleteReferenceMax, Exercise,
                     RackCheckIn, DailyReport, Node, TrainingGroup, TrainingProgram,
                     TrainingProgramWorkout, TrainingProgramExercise, SessionParticipation,
                     AthleteWorkoutExerciseOverride, TrainingBlock, TrainingBlockWorkout,
                     TrainingBlockExercise)
from .services.plan_resolution import movements_for_athlete


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


class PlanResolutionTests(APITestCase):
    """Working out what an athlete does today and what weight goes on the bar.

    These pin the two worked examples written into the merge canon, so if the
    arithmetic or the merge rules ever drift, a test says so rather than an
    athlete quietly lifting the wrong weight.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.session = Session.objects.create(label="Thursday")
        self.athlete = Athlete.objects.create(name="Jordan Lee")
        self.session.athletes.add(self.athlete)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        self.bench = Exercise.objects.get_or_create(name="Bench Press")[0]

    def _max(self, exercise, weight, rep_basis=1):
        return AthleteReferenceMax.objects.create(
            athlete=self.athlete, exercise=exercise,
            reference_weight_lbs=weight, rep_basis=rep_basis)

    def _group(self, name, extra_members=0):
        group = TrainingGroup.objects.create(coach=self.coach, name=name)
        self.athlete.training_groups.add(group)
        for n in range(extra_members):
            Athlete.objects.create(name=f"{name} member {n}").training_groups.add(group)
        return group

    def _program(self, group, rows, name="Plan"):
        program = TrainingProgram.objects.create(
            training_group=group, name=name, start_date=timezone.now().date())
        workout = TrainingProgramWorkout.objects.create(
            training_program=program, name="Day 1", position=1)
        for position, (exercise, sets, reps, percent) in enumerate(rows, start=1):
            TrainingProgramExercise.objects.create(
                training_program_workout=workout, exercise=exercise, position=position,
                sets=sets, reps=reps, target_percent=percent,
                velocity_zone_min=0.5, velocity_zone_max=0.8)
        SessionParticipation.objects.create(
            session=self.session, training_program=program, training_program_workout=workout)
        return program

    def test_target_is_a_percentage_of_the_athletes_own_max(self):
        """The canon's worked example: a 225x3 reference, prescribed at 80%,
        must land on 200 lb — converted to a single, then rounded to the bar."""
        self._max(self.squat, 225, rep_basis=3)
        self._program(self._group("Squad"), [(self.squat, 5, 3, 80)])
        movements = movements_for_athlete(self.athlete, self.session)
        self.assertEqual(movements[0]["target_weight_lbs"], 200.0)

    def test_no_max_on_file_gives_no_target_rather_than_a_guess(self):
        """An athlete nobody has tested yet still gets their workout — the weight
        is simply blank, and they key in what they're using. Never guess."""
        self._program(self._group("Squad"), [(self.squat, 5, 3, 80)])
        movements = movements_for_athlete(self.athlete, self.session)
        self.assertEqual(len(movements), 1)
        self.assertIsNone(movements[0]["target_weight_lbs"])

    def test_two_squads_combine_and_the_lighter_prescription_wins(self):
        """The canon's second worked example. Someone in the team squad AND a
        position squad trains BOTH lists, the shared movement appears once at the
        lighter load, and the bigger squad's work comes first."""
        clean = Exercise.objects.get_or_create(name="Power Clean")[0]
        sled = Exercise.objects.get_or_create(name="Deadlift")[0]
        for exercise in (self.squat, self.bench, clean, sled):
            self._max(exercise, 200)

        team = self._group("Varsity Football", extra_members=6)
        position = self._group("Receivers", extra_members=1)
        self._program(team, [(self.squat, 5, 3, 80), (self.bench, 3, 5, 75), (clean, 4, 2, 70)])
        self._program(position, [(self.squat, 3, 5, 70), (sled, 3, 1, 60)])

        movements = movements_for_athlete(self.athlete, self.session)
        names = [m["name"] for m in movements]

        self.assertEqual(len(movements), 4)                 # 5 rows, one shared
        self.assertEqual(names.count("Back Squat"), 1)      # never duplicated
        self.assertEqual(names[0], "Back Squat")            # bigger squad leads
        squat_row = movements[0]
        self.assertEqual((squat_row["planned_sets"], squat_row["target_reps"]), (3, 5))
        self.assertEqual(squat_row["target_weight_lbs"], 140.0)   # 200 x 70%, not 80%

    def test_an_athlete_in_no_squad_simply_has_nothing_planned(self):
        self.assertEqual(movements_for_athlete(self.athlete, self.session), [])

    def test_a_squad_not_training_today_contributes_nothing(self):
        """Belonging to a squad isn't enough — that squad has to actually be in
        this session, which is what lets one athlete carry several plans."""
        group = TrainingGroup.objects.create(coach=self.coach, name="Off today")
        self.athlete.training_groups.add(group)
        TrainingProgram.objects.create(training_group=group, name="Other",
                                       start_date=timezone.now().date())
        self.assertEqual(movements_for_athlete(self.athlete, self.session), [])

    def test_a_coach_override_replaces_only_what_it_sets(self):
        """The exception for an athlete the percentage doesn't suit. It overrides
        the PERCENTAGE, so their number still tracks their max."""
        self._max(self.squat, 200)
        program = self._program(self._group("Squad"), [(self.squat, 5, 3, 80)])
        row = TrainingProgramExercise.objects.get()
        AthleteWorkoutExerciseOverride.objects.create(
            athlete=self.athlete, training_program_exercise=row, target_percent=60)

        movement = movements_for_athlete(self.athlete, self.session)[0]
        self.assertEqual(movement["target_weight_lbs"], 120.0)   # 60%, not 80%
        self.assertEqual(movement["planned_sets"], 5)            # untouched
        self.assertEqual(movement["target_reps"], 3)

    def test_a_rack_only_offers_what_its_equipment_supports(self):
        """A station told what it has won't offer a movement it can't run."""
        for exercise in (self.squat, self.bench):
            self._max(exercise, 200)
        self._program(self._group("Squad"), [(self.squat, 5, 3, 80), (self.bench, 3, 5, 75)])

        node = Node.objects.create(node_id="rack_1", rack_number=1)
        node.allowed_exercises.add(self.squat)          # this rack squats only
        RackCheckIn.objects.create(session=self.session, athlete=self.athlete, rack_number=1)

        names = [m["name"] for m in movements_for_athlete(self.athlete, self.session)]
        self.assertEqual(names, ["Back Squat"])

    def test_unknown_rack_shows_everything_rather_than_blocking(self):
        """Fails open on purpose: if we can't tell where they are yet, they see
        their whole workout instead of being stopped by a timing gap."""
        for exercise in (self.squat, self.bench):
            self._max(exercise, 200)
        self._program(self._group("Squad"), [(self.squat, 5, 3, 80), (self.bench, 3, 5, 75)])
        self.assertEqual(len(movements_for_athlete(self.athlete, self.session)), 2)


class CoachWeightAdjustmentTests(APITestCase):
    """A coach changing the weight an athlete is working with (canon D15).

    The subtle part: it has to be a finished set row to move the carried-forward
    load, but it must not count as a lift. These pin that it moves the weight and
    NOTHING else.
    """

    def setUp(self):
        self.session = Session.objects.create(label="Thursday")
        self.athlete = Athlete.objects.create(name="Jordan Lee")
        self.session.athletes.add(self.athlete)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        Program.objects.create(athlete=self.athlete, exercise=self.squat, target_sets=5,
                               target_reps=3, target_weight_lbs=225,
                               velocity_zone_min=0.5, velocity_zone_max=0.8)

    def _set(self, weight, **kwargs):
        return Set.objects.create(session=self.session, athlete=self.athlete,
                                  exercise=self.squat, weight_lbs=weight,
                                  ended_at=timezone.now(),
                                  set_number=kwargs.pop("set_number", 1), **kwargs)

    def test_adjustment_moves_the_working_weight_but_counts_as_no_sets(self):
        self._set(225, reps_completed=3)                       # a real lift
        self._set(185, set_number=2, is_coach_adjustment=True)  # coach drops the load

        res = self.client.get(f"/api/sessions/active/athlete/{self.athlete.id}/progress/")
        movement = res.data["movements"][0]
        self.assertEqual(movement["last_weight_lbs"], 185.0)   # the weight moved
        self.assertEqual(movement["completed_sets"], 1)        # still one real set
        self.assertEqual(movement["false_sets"], 0)
        self.assertEqual(movement["next_set_number"], 2)       # counter unaffected
        self.assertEqual(movement["status"], "in_progress")

    def test_adjustment_before_any_lifting_does_not_start_the_workout(self):
        """Setting someone's weight before they begin must leave them looking
        untouched, not half-finished."""
        self._set(185, is_coach_adjustment=True)
        res = self.client.get(f"/api/sessions/active/athlete/{self.athlete.id}/progress/")
        movement = res.data["movements"][0]
        self.assertEqual(movement["last_weight_lbs"], 185.0)
        self.assertEqual(movement["completed_sets"], 0)
        self.assertEqual(movement["status"], "not_started")
        self.assertEqual(movement["next_set_number"], 1)

    def test_an_adjusted_athlete_is_not_shown_as_resting(self):
        """Otherwise the room shows them resting with a ticking timer having
        lifted nothing."""
        self._set(185, is_coach_adjustment=True)
        res = self.client.get("/api/sessions/active/status/")
        me = next(a for a in res.data["athletes"] if a["athlete_id"] == self.athlete.id)
        self.assertNotEqual(me["status"], "resting")


class PlanningEndpointTests(APITestCase):
    """Building a template and deploying it to a squad.

    Walks the path a coach actually takes: make a squad, write a template once,
    deploy it, schedule it — and check an athlete ends up with their own weights.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        self.bench = Exercise.objects.get_or_create(name="Bench Press")[0]

    def _template_with_a_day(self):
        block = self.client.post("/api/workout-programs/", {"name": "Fall Strength"},
                                 format="json").data
        self.client.post("/api/workouts/", {
            "training_block": block["id"], "name": "Day 1", "position": 1,
            "exercises": [
                {"exercise": self.squat.id, "sets": 5, "reps": 3, "target_percent": 80},
                {"exercise": self.bench.id, "sets": 3, "reps": 5, "target_percent": 75},
            ]}, format="json")
        return block

    def test_a_squad_is_a_subset_of_athletes_not_everyone(self):
        alice = Athlete.objects.create(name="Alice")
        Athlete.objects.create(name="Not in the squad")
        squad = self.client.post("/api/training-groups/", {"name": "Varsity"},
                                 format="json").data
        res = self.client.post(f"/api/training-groups/{squad['id']}/athletes/",
                               {"athletes": [alice.id]}, format="json")
        self.assertEqual([a["name"] for a in res.data], ["Alice"])

    def test_deploying_a_template_copies_it_rather_than_pointing_at_it(self):
        """The copy is what lets a coach edit next season's template without
        rewriting what this squad already trained."""
        block = self._template_with_a_day()
        squad = self.client.post("/api/training-groups/", {"name": "Varsity"},
                                 format="json").data
        program = self.client.post("/api/training-programs/", {
            "training_group": squad["id"], "training_block": block["id"],
            "start_date": "2026-07-27"}, format="json").data

        self.assertEqual(len(program["workouts"]), 1)
        self.assertEqual(len(program["workouts"][0]["exercises"]), 2)
        # Editing the template afterwards must NOT reach into the deployed plan.
        TrainingBlockExercise.objects.filter(exercise=self.squat).update(target_percent=99)
        still = TrainingProgramExercise.objects.get(exercise=self.squat)
        self.assertEqual(still.target_percent, 80)

    def test_a_squad_can_have_a_one_off_plan_with_no_template(self):
        """Not every plan is worth templating; a coach can write one directly and
        promote it later."""
        squad = self.client.post("/api/training-groups/", {"name": "Rehab"},
                                 format="json").data
        res = self.client.post("/api/training-programs/", {
            "training_group": squad["id"], "name": "Ad hoc", "start_date": "2026-07-27"},
            format="json")
        self.assertEqual(res.status_code, 201)
        self.assertIsNone(res.data["training_block"])

    def test_scheduling_a_squad_gives_its_athletes_their_own_weights(self):
        """End to end: template -> squad -> today's session -> a real number."""
        athlete = Athlete.objects.create(name="Jordan Lee")
        AthleteReferenceMax.objects.create(athlete=athlete, exercise=self.squat,
                                           reference_weight_lbs=315, rep_basis=1)
        session = Session.objects.create(label="Thursday")
        session.athletes.add(athlete)

        block = self._template_with_a_day()
        squad = self.client.post("/api/training-groups/", {"name": "Varsity"},
                                 format="json").data
        self.client.post(f"/api/training-groups/{squad['id']}/athletes/",
                         {"athletes": [athlete.id]}, format="json")
        program = self.client.post("/api/training-programs/", {
            "training_group": squad["id"], "training_block": block["id"],
            "start_date": "2026-07-27"}, format="json").data

        res = self.client.post(f"/api/sessions/{session.id}/participation/", {
            "training_program": program["id"],
            "training_program_workout": program["workouts"][0]["id"]}, format="json")
        self.assertEqual(res.status_code, 201)

        progress = self.client.get(
            f"/api/sessions/active/athlete/{athlete.id}/progress/").data
        squat_row = next(m for m in progress["movements"] if m["name"] == "Back Squat")
        self.assertEqual(squat_row["target_weight_lbs"], 250.0)   # 315 x 80%, to the bar

    def test_a_workout_cannot_be_scheduled_under_the_wrong_program(self):
        """Guards against a coach's UI sending mismatched ids and silently
        scheduling a squad onto another squad's day."""
        session = Session.objects.create(label="Thursday")
        block = self._template_with_a_day()
        squad_a = self.client.post("/api/training-groups/", {"name": "A"}, format="json").data
        squad_b = self.client.post("/api/training-groups/", {"name": "B"}, format="json").data
        prog_a = self.client.post("/api/training-programs/", {
            "training_group": squad_a["id"], "training_block": block["id"],
            "start_date": "2026-07-27"}, format="json").data
        prog_b = self.client.post("/api/training-programs/", {
            "training_group": squad_b["id"], "training_block": block["id"],
            "start_date": "2026-07-27"}, format="json").data

        res = self.client.post(f"/api/sessions/{session.id}/participation/", {
            "training_program": prog_a["id"],
            "training_program_workout": prog_b["workouts"][0]["id"]}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_override_endpoint_round_trips_and_clears(self):
        athlete = Athlete.objects.create(name="Jordan Lee")
        block = self._template_with_a_day()
        squad = self.client.post("/api/training-groups/", {"name": "Varsity"},
                                 format="json").data
        program = self.client.post("/api/training-programs/", {
            "training_group": squad["id"], "training_block": block["id"],
            "start_date": "2026-07-27"}, format="json").data
        row_id = program["workouts"][0]["exercises"][0]["id"]
        url = f"/api/athletes/{athlete.id}/workout-exercises/{row_id}/override/"

        self.assertIsNone(self.client.get(url).data["target_percent"])
        self.assertEqual(self.client.put(url, {"target_percent": 60},
                                         format="json").data["target_percent"], 60)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertIsNone(self.client.get(url).data["target_percent"])

    def test_an_override_that_sets_nothing_is_rejected(self):
        athlete = Athlete.objects.create(name="Jordan Lee")
        block = self._template_with_a_day()
        squad = self.client.post("/api/training-groups/", {"name": "Varsity"},
                                 format="json").data
        program = self.client.post("/api/training-programs/", {
            "training_group": squad["id"], "training_block": block["id"],
            "start_date": "2026-07-27"}, format="json").data
        row_id = program["workouts"][0]["exercises"][0]["id"]
        res = self.client.put(f"/api/athletes/{athlete.id}/workout-exercises/{row_id}/override/",
                              {}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_planning_requires_a_coach(self):
        self.client.force_authenticate(user=None)
        for url in ("/api/training-groups/", "/api/workout-programs/",
                    "/api/workouts/", "/api/training-programs/"):
            self.assertEqual(self.client.get(url).status_code, 401, url)


class CsvImportTests(APITestCase):
    """Importing a coach's spreadsheets (canon D16/D17).

    These pin the behaviour that is easy to "helpfully" break later: that we
    never invent a weight whose meaning the sheet didn't state, that one typo
    doesn't throw away the whole file, and that nobody gets created silently.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        self.bench = Exercise.objects.get_or_create(name="Bench Press")[0]

    def _upload(self, text, url="/api/workouts/imports/preview/", **extra):
        upload = SimpleUploadedFile("sheet.csv", text.encode("utf-8"), content_type="text/csv")
        return self.client.post(url, {"file": upload, **extra}, format="multipart")

    # ── which kind of sheet is this ──────────────────────────────────────────

    def test_the_sheet_type_is_worked_out_from_the_column_names(self):
        roster = self._upload("athlete_name\nJordan Lee\n")
        maxes = self._upload("athlete_name,exercise,max_lbs\nJordan Lee,Back Squat,315\n")
        plan = self._upload("workout_name,exercise,position,sets,reps,target_percent\n"
                            "Day 1,Back Squat,1,5,3,80\n")
        self.assertEqual(roster.data["sheet_type"], "roster")
        self.assertEqual(maxes.data["sheet_type"], "reference_max")
        self.assertEqual(plan.data["sheet_type"], "plan")

    def test_an_unrecognisable_sheet_says_what_the_options_are(self):
        res = self._upload("colour,size\nred,large\n")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["errors"][0]["code"], "unrecognized_sheet")

    # ── the max sheet: never invent a number ─────────────────────────────────

    def test_a_bare_max_needs_no_guessing(self):
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,max_lbs\nJordan Lee,Back Squat,315\n",
                           url="/api/workouts/imports/")
        self.assertEqual(res.status_code, 200)
        record = AthleteReferenceMax.objects.get()
        self.assertEqual(record.reference_weight_lbs, 315)
        self.assertEqual(record.rep_basis, 1)

    def test_a_weight_with_reps_is_stored_at_that_rep_basis_not_converted_early(self):
        """225x5 is recorded honestly as 225 at 5 reps; the conversion to a single
        happens in one place later, so the original fact stays visible."""
        Athlete.objects.create(name="Jordan Lee")
        self._upload("athlete_name,exercise,weight_lbs,reps\nJordan Lee,Back Squat,225,5\n",
                     url="/api/workouts/imports/")
        record = AthleteReferenceMax.objects.get()
        self.assertEqual(record.reference_weight_lbs, 225)
        self.assertEqual(record.rep_basis, 5)

    def test_a_stated_percentage_is_back_solved_exactly(self):
        Athlete.objects.create(name="Jordan Lee")
        self._upload("athlete_name,exercise,weight_lbs,target_percent\n"
                     "Jordan Lee,Back Squat,225,75\n", url="/api/workouts/imports/")
        self.assertEqual(AthleteReferenceMax.objects.get().reference_weight_lbs, 300)

    def test_a_weight_that_could_mean_anything_is_SKIPPED_not_guessed(self):
        """The whole point of D16: a made-up max is newest-wins, so it would
        outrank the athlete's real tested number and drag every other target
        down with it. Missing is safe; wrong is not."""
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,weight_lbs\nJordan Lee,Back Squat,225\n",
                           url="/api/workouts/imports/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AthleteReferenceMax.objects.count(), 0)
        self.assertEqual(res.data["skipped"][0]["code"], "weight_meaning_unknown")
        self.assertIn("Jordan Lee", res.data["skipped"][0]["detail"])

    def test_a_skipped_row_does_not_stop_the_good_rows(self):
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,weight_lbs,reps\n"
                           "Jordan Lee,Back Squat,225,5\n"
                           "Jordan Lee,Bench Press,185,\n", url="/api/workouts/imports/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["created"], 1)
        self.assertEqual(res.data["counts"]["skipped"], 1)

    # ── typos are repairable, not fatal ──────────────────────────────────────

    def test_a_misspelled_name_suggests_the_real_one_and_keeps_the_other_rows(self):
        Athlete.objects.create(name="Jordan Lee")
        Athlete.objects.create(name="Sam Rivera")
        res = self._upload("athlete_name,exercise,max_lbs\n"
                           "Jordn Lee,Back Squat,315\n"
                           "Sam Rivera,Back Squat,275\n")
        self.assertEqual(res.status_code, 400)
        problem = res.data["errors"][0]
        self.assertEqual(problem["code"], "unknown_athlete")
        self.assertEqual(problem["row"], 2)
        self.assertIn("Jordan Lee", problem["suggestions"])
        # D17c: the good row still comes back so the screen can render the sheet.
        self.assertEqual([row["athlete_name"] for row in res.data["rows"]], ["Sam Rivera"])

    def test_nothing_is_written_while_any_row_is_still_broken(self):
        Athlete.objects.create(name="Sam Rivera")
        res = self._upload("athlete_name,exercise,max_lbs\n"
                           "Jordn Lee,Back Squat,315\n"
                           "Sam Rivera,Back Squat,275\n", url="/api/workouts/imports/")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(AthleteReferenceMax.objects.count(), 0)

    def test_a_misspelled_movement_suggests_the_catalog_entry(self):
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,max_lbs\nJordan Lee,Bakc Squat,315\n")
        problem = res.data["errors"][0]
        self.assertEqual(problem["code"], "unknown_exercise")
        self.assertIn("Back Squat", problem["suggestions"])

    def test_two_people_with_one_name_are_told_apart_by_the_squad(self):
        """Squad-scoping is what collapses the ambiguity — two Jordan Lees in a
        gym is believable, two in one squad is not."""
        in_squad = Athlete.objects.create(name="Jordan Lee")
        Athlete.objects.create(name="Jordan Lee")   # a different Jordan, elsewhere
        squad = TrainingGroup.objects.create(name="Varsity", coach=self.coach)
        in_squad.training_groups.add(squad)

        res = self._upload("athlete_name,exercise,max_lbs\nJordan Lee,Back Squat,315\n",
                           url="/api/workouts/imports/", training_group=squad.id)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AthleteReferenceMax.objects.get().athlete_id, in_squad.id)

    def test_an_unscoped_duplicate_name_stops_and_asks(self):
        Athlete.objects.create(name="Jordan Lee")
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,max_lbs\nJordan Lee,Back Squat,315\n")
        problem = res.data["errors"][0]
        self.assertEqual(problem["code"], "ambiguous_athlete")
        self.assertEqual(len(problem["candidates"]), 2)

    def test_surname_first_and_stray_spacing_still_match(self):
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,max_lbs\n\"Lee,  Jordan\",back  squat,315\n",
                           url="/api/workouts/imports/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AthleteReferenceMax.objects.count(), 1)

    # ── the roster sheet ─────────────────────────────────────────────────────

    def test_a_roster_creates_people_and_can_drop_them_into_a_squad(self):
        squad = TrainingGroup.objects.create(name="Varsity", coach=self.coach)
        res = self._upload("athlete_name,training_group\nJordan Lee,Varsity\nSam Rivera,Varsity\n",
                           url="/api/workouts/imports/")
        self.assertEqual(res.data["created"], 2)
        self.assertEqual(squad.athletes.count(), 2)

    def test_re_uploading_a_roster_adds_the_new_people_without_duplicating_the_old(self):
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name\nJordan Lee\nSam Rivera\n",
                           url="/api/workouts/imports/")
        self.assertEqual(res.data["created"], 1)
        self.assertEqual(Athlete.objects.filter(name="Jordan Lee").count(), 1)
        self.assertEqual(res.data["skipped"][0]["code"], "already_on_roster")

    def test_a_max_sheet_never_creates_a_missing_athlete(self):
        """A typo turned into a new athlete would shadow the real person forever."""
        res = self._upload("athlete_name,exercise,max_lbs\nNobody At All,Back Squat,315\n",
                           url="/api/workouts/imports/")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Athlete.objects.count(), 0)

    # ── the plan sheet ───────────────────────────────────────────────────────

    def _block(self):
        return TrainingBlock.objects.create(coach=self.coach, name="Fall Strength")

    def test_a_plan_imports_into_a_template_in_spreadsheet_order(self):
        block = self._block()
        res = self._upload(
            "workout_name,exercise,position,sets,reps,target_percent\n"
            "Day 1 - Lower,Back Squat,1,5,3,80\n"
            "Day 2 - Upper,Bench Press,1,3,5,75\n"
            "Day 1 - Lower,Bench Press,2,3,8,65\n",
            url="/api/workouts/imports/", training_block=block.id)
        self.assertEqual(res.status_code, 200)
        days = list(TrainingBlockWorkout.objects.filter(training_block=block).order_by("position"))
        self.assertEqual([d.name for d in days], ["Day 1 - Lower", "Day 2 - Upper"])
        self.assertEqual(days[0].exercises.count(), 2)

    def test_a_plan_imports_into_one_squads_program_too(self):
        """D7: both levels. A one-off for one squad never becomes a template."""
        squad = TrainingGroup.objects.create(name="Varsity", coach=self.coach)
        program = TrainingProgram.objects.create(training_group=squad, name="Spring",
                                                 start_date=timezone.now().date())
        res = self._upload("workout_name,exercise,position,sets,reps,target_percent\n"
                           "Day 1,Back Squat,1,5,3,80\n",
                           url="/api/workouts/imports/", training_program=program.id)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(TrainingProgramWorkout.objects.filter(training_program=program).count(), 1)
        self.assertEqual(TrainingBlockWorkout.objects.count(), 0)

    def test_importing_again_appends_rather_than_colliding(self):
        block = self._block()
        sheet = ("workout_name,exercise,position,sets,reps,target_percent\n"
                 "Day 1,Back Squat,1,5,3,80\n")
        self._upload(sheet, url="/api/workouts/imports/", training_block=block.id)
        res = self._upload(sheet.replace("Day 1", "Day 2"), url="/api/workouts/imports/",
                           training_block=block.id)
        self.assertEqual(res.status_code, 200)
        positions = list(TrainingBlockWorkout.objects.filter(training_block=block)
                         .order_by("position").values_list("position", flat=True))
        self.assertEqual(positions, [1, 2])

    def test_a_plan_with_nowhere_to_go_is_refused(self):
        res = self._upload("workout_name,exercise,position,sets,reps,target_percent\n"
                           "Day 1,Back Squat,1,5,3,80\n")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["errors"][0]["code"], "target_required")

    def test_an_absolute_weight_column_is_not_accepted_on_a_plan(self):
        """D16 rule 1: a pounds column would bypass the reference-max machinery
        every prescribed weight depends on."""
        block = self._block()
        res = self._upload("workout_name,exercise,position,sets,reps,default_weight_lbs\n"
                           "Day 1,Back Squat,1,5,3,225\n",
                           training_block=block.id)
        self.assertEqual(res.status_code, 400)
        codes = {e["code"] for e in res.data["errors"]}
        self.assertIn("missing_headers", codes)
        self.assertIn("unknown_headers", codes)

    def test_a_percent_over_100_is_allowed_but_zero_is_not(self):
        block = self._block()
        ok = self._upload("workout_name,exercise,position,sets,reps,target_percent\n"
                          "Day 1,Back Squat,1,5,3,105\n",
                          training_block=block.id)
        bad = self._upload("workout_name,exercise,position,sets,reps,target_percent\n"
                           "Day 1,Back Squat,1,5,3,0\n",
                           training_block=block.id)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(bad.status_code, 400)

    def test_a_gap_in_the_exercise_order_is_refused(self):
        block = self._block()
        res = self._upload("workout_name,exercise,position,sets,reps,target_percent\n"
                           "Day 1,Back Squat,1,5,3,80\n"
                           "Day 1,Bench Press,3,3,5,75\n",
                           training_block=block.id)
        self.assertEqual(res.status_code, 400)
        self.assertIn("non_contiguous_positions", {e["code"] for e in res.data["errors"]})

    # ── the file itself ──────────────────────────────────────────────────────

    def test_a_spreadsheet_saved_out_of_excel_still_reads(self):
        """Excel writes an invisible marker at the start of the file; without
        handling it the first column name silently stops matching."""
        Athlete.objects.create(name="Jordan Lee")
        upload = SimpleUploadedFile(
            "sheet.csv", "﻿athlete_name,exercise,max_lbs\nJordan Lee,Back Squat,315\n".encode("utf-8"),
            content_type="text/csv")
        res = self.client.post("/api/workouts/imports/", {"file": upload}, format="multipart")
        self.assertEqual(res.status_code, 200)

    def test_preview_writes_nothing(self):
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,max_lbs\nJordan Lee,Back Squat,315\n")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AthleteReferenceMax.objects.count(), 0)
        self.assertEqual(res.data["counts"]["ready"], 1)

    def test_import_requires_a_coach(self):
        self.client.force_authenticate(user=None)
        res = self._upload("athlete_name\nJordan Lee\n", url="/api/workouts/imports/")
        self.assertIn(res.status_code, (401, 403))
        self.assertEqual(Athlete.objects.count(), 0)


class AthleteAssignmentTests(APITestCase):
    """What one athlete is training (`athletes/{id}/workout-assignment/`).

    His page was built where a program pins onto one athlete; here it belongs to
    a squad and the athlete trains it by membership. These pin that the route
    still answers his question, and that a write says what it really did.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        self.athlete = Athlete.objects.create(name="Jordan Lee")
        self.squad = TrainingGroup.objects.create(name="Varsity", coach=self.coach)
        self.program = TrainingProgram.objects.create(
            training_group=self.squad, name="Fall", start_date=timezone.now().date())
        workout = TrainingProgramWorkout.objects.create(
            training_program=self.program, name="Day 1", position=1)
        TrainingProgramExercise.objects.create(
            training_program_workout=workout, exercise=self.squat, position=1,
            sets=5, reps=3, target_percent=80)

    def _url(self):
        return f"/api/athletes/{self.athlete.id}/workout-assignment/"

    def test_an_athlete_in_no_squad_has_no_plan(self):
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["assignment"], [])

    def test_assigning_a_program_puts_them_in_its_squad_and_says_so(self):
        res = self.client.put(self._url(), {"workout_program_id": self.program.id},
                              format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["groups_changed"],
                         [{"id": self.squad.id, "name": "Varsity", "action": "added"}])
        self.assertIn(self.squad, self.athlete.training_groups.all())

    def test_the_plan_comes_back_with_real_pounds_not_just_a_percent(self):
        """A percent on its own tells a coach nothing about what goes on the bar."""
        AthleteReferenceMax.objects.create(athlete=self.athlete, exercise=self.squat,
                                           reference_weight_lbs=315, rep_basis=1)
        self.athlete.training_groups.add(self.squad)
        row = self.client.get(self._url()).data["assignment"][0]["workouts"][0]["exercises"][0]
        self.assertEqual(row["target_percent"], 80)
        self.assertEqual(row["target_weight_lbs"], 250.0)   # 315 x 80% = 252 -> 250

    def test_an_athlete_with_no_max_still_reads_without_error(self):
        self.athlete.training_groups.add(self.squad)
        row = self.client.get(self._url()).data["assignment"][0]["workouts"][0]["exercises"][0]
        self.assertIsNone(row["target_weight_lbs"])

    def test_two_squads_both_show_up_with_the_squad_that_owns_each(self):
        """D13: an athlete can carry more than one plan, and a coach needs to see
        which squad each one comes from."""
        speed = TrainingGroup.objects.create(name="Speed", coach=self.coach)
        TrainingProgram.objects.create(training_group=speed, name="Sprint",
                                       start_date=timezone.now().date())
        self.athlete.training_groups.add(self.squad, speed)
        assignment = self.client.get(self._url()).data["assignment"]
        self.assertEqual({a["training_group"]["name"] for a in assignment},
                         {"Varsity", "Speed"})

    def test_removing_the_assignment_takes_them_out_of_the_prescribing_squads_only(self):
        """A squad with no plan attached is roster information a coach set up on
        purpose — clearing an assignment shouldn't quietly discard it."""
        empty = TrainingGroup.objects.create(name="Freshmen", coach=self.coach)
        self.athlete.training_groups.add(self.squad, empty)
        res = self.client.delete(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual([g["name"] for g in res.data["groups_changed"]], ["Varsity"])
        self.assertEqual([g.name for g in self.athlete.training_groups.all()], ["Freshmen"])

    def test_unknown_athlete_and_unknown_program_are_404(self):
        self.assertEqual(self.client.get("/api/athletes/999999/workout-assignment/").status_code, 404)
        res = self.client.put(self._url(), {"workout_program_id": 999999}, format="json")
        self.assertEqual(res.status_code, 404)

    def test_assignment_requires_a_coach(self):
        self.client.force_authenticate(user=None)
        res = self.client.put(self._url(), {"workout_program_id": self.program.id},
                              format="json")
        self.assertIn(res.status_code, (401, 403))
