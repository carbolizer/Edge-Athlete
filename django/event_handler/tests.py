# tests.py — automated checks for the base-station endpoints.
#
# Covers GET /api/sessions/active/ (the rack screen's one startup fetch) and the
# GET /api/exercises/ catalog list. Each test pins one promise the rack screen
# relies on: which session counts as active, who reads as already having data,
# that an athlete's CURRENT reference max (and only that) comes back, and that
# every exercise now resolves through the shared catalog.
import json
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.db.models import ProtectedError
from django.utils import timezone
from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import (Athlete, TrainingSession, Set, Rep, AthleteReferenceMax, Exercise,
                     RackCheckIn, DailyReport, Node, TrainingGroup, TrainingProgram,
                     TrainingProgramWorkout, TrainingProgramExercise, SessionParticipation,
                     AthleteWorkoutExerciseOverride, TrainingBlock, TrainingBlockWorkout,
                     TrainingBlockExercise)
from .services.plan_resolution import movements_for_athlete
from .services.planning import instantiate_block


def give_plan(athlete, session, exercise, weight_lbs, sets=5, reps=3,
              zone_min=0.5, zone_max=0.8, record_max=True):
    """Put an athlete on a group plan that resolves to exactly `weight_lbs`.

    Plans prescribe a PERCENTAGE of the athlete's reference max now, so the way
    to pin a known target in a test is to record `weight_lbs` as their max and
    prescribe 100% of it. That keeps the arithmetic out of the way of whatever
    the test is actually about, while still going through the real resolution
    path rather than around it.

    Reuses the athlete's existing group and program when they already have one,
    so calling this twice gives them two movements on one plan rather than two
    competing plans.
    """
    coach = User.objects.filter(username="plan-helper-coach").first() \
        or User.objects.create_user(username="plan-helper-coach", password="pw")

    group = athlete.training_groups.first()
    if group is None:
        group = TrainingGroup.objects.create(name=f"Group for {athlete.name}", coach=coach)
        athlete.training_groups.add(group)

    program = TrainingProgram.objects.filter(training_group=group).first()
    if program is None:
        program = TrainingProgram.objects.create(
            training_group=group, name=f"Plan for {group.name}",
            start_date=timezone.now().date())
    workout = program.workouts.first() or TrainingProgramWorkout.objects.create(
        training_program=program, name="Day 1", position=1)

    # `record_max=False` for tests that manage their own reference maxes — this
    # helper's max is written NOW, so it would supersede a deliberately back-dated
    # one and quietly break the very thing such a test is checking.
    if record_max:
        AthleteReferenceMax.objects.create(
            athlete=athlete, exercise=exercise, reference_weight_lbs=weight_lbs, rep_basis=1)

    row = TrainingProgramExercise.objects.create(
        training_program_workout=workout, exercise=exercise,
        position=workout.exercises.count() + 1, sets=sets, reps=reps,
        target_percent=100.0, velocity_zone_min=zone_min, velocity_zone_max=zone_max)

    SessionParticipation.objects.get_or_create(
        session=session, training_program=program,
        defaults={"training_program_workout": workout})
    return row


class ActiveSessionEndpointTests(APITestCase):
    URL = "/api/sessions/active/"

    def _exercise(self, name):
        exercise, _ = Exercise.objects.get_or_create(name=name)
        return exercise

    def _program(self, athlete, exercise, weight, session=None, record_max=True):
        return give_plan(athlete, session or TrainingSession.objects.filter(
            ended_at__isnull=True).order_by("-started_at", "-id").first(),
            exercise, weight, record_max=record_max)

    def _dated_max(self, athlete, exercise, weight, days_ago):
        m = AthleteReferenceMax.objects.create(
            athlete=athlete, exercise=exercise, reference_weight_lbs=weight)
        AthleteReferenceMax.objects.filter(pk=m.pk).update(
            recorded_at=timezone.now() - timedelta(days=days_ago))
        return m

    def test_no_active_session_returns_empty_envelope(self):
        TrainingSession.objects.create(label="Done", ended_at=timezone.now())  # ended → not active
        res = self.client.get(self.URL)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["session_id"], None)
        self.assertEqual(res.data["roster"], [])
        self.assertEqual(res.data["session_exercises"], [])

    def test_picks_most_recent_unended_session(self):
        TrainingSession.objects.create(label="Older")
        newer = TrainingSession.objects.create(label="Newer")
        res = self.client.get(self.URL)
        self.assertEqual(res.data["session_id"], newer.id)
        self.assertEqual(res.data["label"], "Newer")

    def test_roster_has_data_reflects_completed_sets(self):
        session = TrainingSession.objects.create(label="Live")
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
        session = TrainingSession.objects.create(label="Live")
        squat = self._exercise("Back Squat")
        bench = self._exercise("Bench Press")  # in the catalog, but no max for this athlete
        athlete = Athlete.objects.create(name="Max Tester")
        session.athletes.add(athlete)
        self._program(athlete, squat, 225.0, record_max=False)
        self._dated_max(athlete, squat, 300.0, days_ago=40)   # old
        self._dated_max(athlete, squat, 315.0, days_ago=2)    # current

        res = self.client.get(self.URL)
        entry = res.data["roster"][0]
        self.assertEqual(entry["maxes"][squat.id], 315.0)   # newest wins
        self.assertNotIn(bench.id, entry["maxes"])           # gap → no key

    def test_reference_max_can_go_down(self):
        # A reference max is "what they can do now", not a lifetime best: a newer,
        # LOWER row must supersede an older, higher one.
        session = TrainingSession.objects.create(label="Live")
        squat = self._exercise("Back Squat")
        athlete = Athlete.objects.create(name="Bad Week")
        session.athletes.add(athlete)
        self._dated_max(athlete, squat, 315.0, days_ago=30)  # was strong
        self._dated_max(athlete, squat, 285.0, days_ago=1)   # rough patch

        res = self.client.get(self.URL)
        self.assertEqual(res.data["roster"][0]["maxes"][squat.id], 285.0)

    def test_targets_and_exercises_come_from_programs(self):
        session = TrainingSession.objects.create(label="Live")
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
    plan order, the status/current-movement logic, and the guards."""

    def _exercise(self, name):
        exercise, _ = Exercise.objects.get_or_create(name=name)
        return exercise

    def _program(self, athlete, exercise, weight, sets=5, session=None):
        return give_plan(athlete, session or TrainingSession.objects.filter(
            ended_at__isnull=True).order_by("-started_at", "-id").first(),
            exercise, weight, sets=sets)

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
        TrainingSession.objects.create(label="Live")
        res = self.client.get(self._url(999999))
        self.assertEqual(res.status_code, 404)

    def test_athlete_not_on_roster_is_404(self):
        TrainingSession.objects.create(label="Live")
        outsider = Athlete.objects.create(name="Outsider")
        res = self.client.get(self._url(outsider.id))
        self.assertEqual(res.status_code, 404)

    def test_derives_progress_in_program_order(self):
        session = TrainingSession.objects.create(label="Live")
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
        session = TrainingSession.objects.create(label="Live")
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
        session = TrainingSession.objects.create(label="Live")
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
        session = TrainingSession.objects.create(label="Live")
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
        TrainingSession.objects.create(label="Done", ended_at=timezone.now())  # ended → not active
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
        session = TrainingSession.objects.create(label="Live")
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


class AthleteNotesTests(APITestCase):
    """Coach notes on an athlete (merge canon R1).

    `notes` is a plain field on Athlete rather than its own resource, so this one
    endpoint is the ONLY way to read or write them. That makes GET load-bearing:
    a detail route that could be written but not read left the coach screen with
    no way to show a note it had just saved.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="notescoach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.athlete = Athlete.objects.create(name="Jordan Lee")

    def test_a_note_can_be_written_and_read_back(self):
        res = self.client.patch(f"/api/athletes/{self.athlete.id}/",
                                {"notes": "Left knee — keep depth honest."}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["notes"], "Left knee — keep depth honest.")

        res = self.client.get(f"/api/athletes/{self.athlete.id}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["notes"], "Left knee — keep depth honest.")
        self.assertEqual(res.data["id"], self.athlete.id)

    def test_writing_a_note_leaves_the_rest_of_the_athlete_alone(self):
        """A note is a partial update — it must not blank out their name or tag."""
        self.athlete.nfc_tag_id = "tag-123"
        self.athlete.save()
        self.client.patch(f"/api/athletes/{self.athlete.id}/", {"notes": "back tomorrow"},
                          format="json")
        self.athlete.refresh_from_db()
        self.assertEqual(self.athlete.name, "Jordan Lee")
        self.assertEqual(self.athlete.nfc_tag_id, "tag-123")

    def test_an_athlete_with_no_note_reads_as_empty_not_missing(self):
        res = self.client.get(f"/api/athletes/{self.athlete.id}/")
        self.assertIn("notes", res.data)
        self.assertEqual(res.data["notes"], "")

    def test_reading_an_unknown_athlete_is_404(self):
        self.assertEqual(self.client.get("/api/athletes/999999/").status_code, 404)


class RoomStateEndpointTests(APITestCase):
    """GET /api/room-state/ — the derived live room picture (merge canon D8).

    These pin the thing the merge actually changed: the room view is rebuilt
    from RackCheckIn + Set/Rep instead of the dropped RackWorkoutState /
    AthleteDayProgress tables. They also pin the wall-vs-coach privilege
    boundary, since `?details=true` is what folds his old `wall-state/` and
    `room-state/` into one route (R3).
    """

    def _room(self):
        session = TrainingSession.objects.create(label="Live")
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
        self.session = TrainingSession.objects.create(label="Thursday")
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
        self.session = TrainingSession.objects.create(label="Thursday")
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

    # ── the athlete-scoped lens (R6) ─────────────────────────────────────────
    #
    # These existed as a route and a list filter, but NOTHING ever asked for one
    # athlete's copy of a specific report. It could never have worked: the id
    # arrives from the query string as text and was compared against the numeric
    # id stored in the snapshot, so every athlete looked absent from every day —
    # and "absent" raised an exception nobody caught, so it surfaced as a 500.

    def test_one_athletes_copy_of_a_day_resolves(self):
        report = DailyReport.objects.get()
        res = self.client.get(f"/api/reports/{report.id}/?athlete={self.athlete.id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["athlete"]["athlete"]["id"], self.athlete.id)

    def test_an_athlete_who_did_not_train_that_day_is_404_not_500(self):
        report = DailyReport.objects.get()
        other = Athlete.objects.create(name="Sam Rivera")
        res = self.client.get(f"/api/reports/{report.id}/?athlete={other.id}")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.data["code"], "athlete_not_in_report")

    def test_a_nonsense_athlete_id_is_404_not_500(self):
        report = DailyReport.objects.get()
        self.assertEqual(
            self.client.get(f"/api/reports/{report.id}/?athlete=banana").status_code, 404)

    def test_the_pdf_takes_the_same_lens(self):
        report = DailyReport.objects.get()
        ok = self.client.get(f"/api/reports/{report.id}/pdf/?athlete={self.athlete.id}")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok["Content-Type"], "application/pdf")
        missing = self.client.get(f"/api/reports/{report.id}/pdf/?athlete=9999")
        self.assertEqual(missing.status_code, 404)


class ReferenceMaxWriteTests(APITestCase):
    """POST /api/reference-maxes/ — the prescription lever."""

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        self.a1 = Athlete.objects.create(name="A One")
        self.a2 = Athlete.objects.create(name="A Two")

    def test_records_a_whole_group_in_one_call(self):
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
        self.session = TrainingSession.objects.create(label="Thursday")
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
        self._program(self._group("Varsity"), [(self.squat, 5, 3, 80)])
        movements = movements_for_athlete(self.athlete, self.session)
        self.assertEqual(movements[0]["target_weight_lbs"], 200.0)

    def test_no_max_on_file_gives_no_target_rather_than_a_guess(self):
        """An athlete nobody has tested yet still gets their workout — the weight
        is simply blank, and they key in what they're using. Never guess."""
        self._program(self._group("Varsity"), [(self.squat, 5, 3, 80)])
        movements = movements_for_athlete(self.athlete, self.session)
        self.assertEqual(len(movements), 1)
        self.assertIsNone(movements[0]["target_weight_lbs"])

    def test_two_groups_combine_and_the_lighter_prescription_wins(self):
        """The canon's second worked example. Someone in the team group AND a
        position group trains BOTH lists, the shared movement appears once at the
        lighter load, and the bigger group's work comes first."""
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
        self.assertEqual(names[0], "Back Squat")            # bigger group leads
        squat_row = movements[0]
        self.assertEqual((squat_row["planned_sets"], squat_row["target_reps"]), (3, 5))
        self.assertEqual(squat_row["target_weight_lbs"], 140.0)   # 200 x 70%, not 80%

    def test_an_athlete_in_no_group_simply_has_nothing_planned(self):
        self.assertEqual(movements_for_athlete(self.athlete, self.session), [])

    def test_a_group_not_training_today_contributes_nothing(self):
        """Belonging to a TrainingGroup isn't enough — that group has to actually be in
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
        program = self._program(self._group("Varsity"), [(self.squat, 5, 3, 80)])
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
        self._program(self._group("Varsity"), [(self.squat, 5, 3, 80), (self.bench, 3, 5, 75)])

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
        self._program(self._group("Varsity"), [(self.squat, 5, 3, 80), (self.bench, 3, 5, 75)])
        self.assertEqual(len(movements_for_athlete(self.athlete, self.session)), 2)


class CoachWeightAdjustmentTests(APITestCase):
    """A coach changing the weight an athlete is working with (canon D15).

    The subtle part: it has to be a finished set row to move the carried-forward
    load, but it must not count as a lift. These pin that it moves the weight and
    NOTHING else.
    """

    def setUp(self):
        self.session = TrainingSession.objects.create(label="Thursday")
        self.athlete = Athlete.objects.create(name="Jordan Lee")
        self.session.athletes.add(self.athlete)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        give_plan(self.athlete, self.session, self.squat, 225)

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

    def test_a_coach_can_actually_reach_the_flag_over_http(self):
        """Every other test here sets the flag through the ORM, which hid the
        real gap: it was missing from SetSerializer.fields, so DRF silently
        dropped it and no client could make an adjustment at all. The whole D15
        exclusion list was unreachable from outside Python."""
        coach = User.objects.create_user(username="d15coach", password="pw")
        self.client.force_authenticate(user=coach)
        res = self.client.post("/api/sets/", {
            "session": self.session.id, "athlete": self.athlete.id,
            "exercise": self.squat.id, "set_number": 1,
            "weight_lbs": 185, "is_coach_adjustment": True,
        }, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.data["is_coach_adjustment"])
        self.assertTrue(Set.objects.get(id=res.data["id"]).is_coach_adjustment)

    def test_a_set_is_a_real_lift_unless_it_says_otherwise(self):
        """The flag must default to False, or an ordinary set posted by a tablet
        would stop counting as work."""
        res = self.client.post("/api/sets/", {
            "session": self.session.id, "athlete": self.athlete.id,
            "exercise": self.squat.id, "set_number": 1, "weight_lbs": 225,
        }, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertFalse(res.data["is_coach_adjustment"])


class PlanningEndpointTests(APITestCase):
    """Building a template and deploying it to a TrainingGroup.

    Walks the path a coach actually takes: make a TrainingGroup, write a template once,
    deploy it, schedule it — and check an athlete ends up with their own weights.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        self.bench = Exercise.objects.get_or_create(name="Bench Press")[0]

    def _template_with_a_day(self):
        block = self.client.post("/api/training-blocks/", {"name": "Fall Strength"},
                                 format="json").data
        self.client.post(f"/api/training-blocks/{block['id']}/workouts/", {
            "name": "Day 1", "position": 1,
            "exercises": [
                {"exercise": self.squat.id, "sets": 5, "reps": 3, "target_percent": 80},
                {"exercise": self.bench.id, "sets": 3, "reps": 5, "target_percent": 75},
            ]}, format="json")
        return block

    def test_a_group_is_a_subset_of_athletes_not_everyone(self):
        alice = Athlete.objects.create(name="Alice")
        Athlete.objects.create(name="Not in the group")
        group = self.client.post("/api/training-groups/", {"name": "Varsity"},
                                 format="json").data
        res = self.client.post(f"/api/training-groups/{group['id']}/athletes/",
                               {"athletes": [alice.id]}, format="json")
        self.assertEqual([a["name"] for a in res.data], ["Alice"])

    def test_deploying_a_template_copies_it_rather_than_pointing_at_it(self):
        """The copy is what lets a coach edit next season's template without
        rewriting what this group already trained."""
        block = self._template_with_a_day()
        group = self.client.post("/api/training-groups/", {"name": "Varsity"},
                                 format="json").data
        program = self.client.post("/api/training-programs/", {
            "training_group": group["id"], "training_block": block["id"],
            "start_date": "2026-07-27"}, format="json").data

        self.assertEqual(len(program["workouts"]), 1)
        self.assertEqual(len(program["workouts"][0]["exercises"]), 2)
        # Editing the template afterwards must NOT reach into the deployed plan.
        TrainingBlockExercise.objects.filter(exercise=self.squat).update(target_percent=99)
        still = TrainingProgramExercise.objects.get(exercise=self.squat)
        self.assertEqual(still.target_percent, 80)

    def test_a_group_can_have_a_one_off_plan_with_no_template(self):
        """Not every plan is worth templating; a coach can write one directly and
        promote it later."""
        group = self.client.post("/api/training-groups/", {"name": "Rehab"},
                                 format="json").data
        res = self.client.post("/api/training-programs/", {
            "training_group": group["id"], "name": "Ad hoc", "start_date": "2026-07-27"},
            format="json")
        self.assertEqual(res.status_code, 201)
        self.assertIsNone(res.data["training_block"])

    def test_scheduling_a_group_gives_its_athletes_their_own_weights(self):
        """End to end: template -> TrainingGroup -> today's session -> a real number."""
        athlete = Athlete.objects.create(name="Jordan Lee")
        AthleteReferenceMax.objects.create(athlete=athlete, exercise=self.squat,
                                           reference_weight_lbs=315, rep_basis=1)
        session = TrainingSession.objects.create(label="Thursday")
        session.athletes.add(athlete)

        block = self._template_with_a_day()
        group = self.client.post("/api/training-groups/", {"name": "Varsity"},
                                 format="json").data
        self.client.post(f"/api/training-groups/{group['id']}/athletes/",
                         {"athletes": [athlete.id]}, format="json")
        program = self.client.post("/api/training-programs/", {
            "training_group": group["id"], "training_block": block["id"],
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
        scheduling a TrainingGroup onto another TrainingGroup's day."""
        session = TrainingSession.objects.create(label="Thursday")
        block = self._template_with_a_day()
        group_a = self.client.post("/api/training-groups/", {"name": "A"}, format="json").data
        group_b = self.client.post("/api/training-groups/", {"name": "B"}, format="json").data
        prog_a = self.client.post("/api/training-programs/", {
            "training_group": group_a["id"], "training_block": block["id"],
            "start_date": "2026-07-27"}, format="json").data
        prog_b = self.client.post("/api/training-programs/", {
            "training_group": group_b["id"], "training_block": block["id"],
            "start_date": "2026-07-27"}, format="json").data

        res = self.client.post(f"/api/sessions/{session.id}/participation/", {
            "training_program": prog_a["id"],
            "training_program_workout": prog_b["workouts"][0]["id"]}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_override_endpoint_round_trips_and_clears(self):
        athlete = Athlete.objects.create(name="Jordan Lee")
        block = self._template_with_a_day()
        group = self.client.post("/api/training-groups/", {"name": "Varsity"},
                                 format="json").data
        program = self.client.post("/api/training-programs/", {
            "training_group": group["id"], "training_block": block["id"],
            "start_date": "2026-07-27"}, format="json").data
        row_id = program["workouts"][0]["exercises"][0]["id"]
        url = f"/api/athletes/{athlete.id}/program-exercises/{row_id}/override/"

        self.assertIsNone(self.client.get(url).data["target_percent"])
        self.assertEqual(self.client.put(url, {"target_percent": 60},
                                         format="json").data["target_percent"], 60)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertIsNone(self.client.get(url).data["target_percent"])

    def test_an_override_that_sets_nothing_is_rejected(self):
        athlete = Athlete.objects.create(name="Jordan Lee")
        block = self._template_with_a_day()
        group = self.client.post("/api/training-groups/", {"name": "Varsity"},
                                 format="json").data
        program = self.client.post("/api/training-programs/", {
            "training_group": group["id"], "training_block": block["id"],
            "start_date": "2026-07-27"}, format="json").data
        row_id = program["workouts"][0]["exercises"][0]["id"]
        res = self.client.put(f"/api/athletes/{athlete.id}/program-exercises/{row_id}/override/",
                              {}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_planning_requires_a_coach(self):
        self.client.force_authenticate(user=None)
        for url in ("/api/training-groups/", "/api/training-blocks/",
                    "/api/training-blocks/1/workouts/", "/api/training-programs/"):
            self.assertEqual(self.client.get(url).status_code, 401, url)


class TemplateEditingTests(APITestCase):
    """Changing a template after it is written (P10).

    Two things are being protected here. Order must survive a reload, which is
    harder than it sounds against a non-deferrable unique constraint. And a
    template edit must never reach a group that is already training a copy of it.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        self.bench = Exercise.objects.get_or_create(name="Bench Press")[0]
        self.block = TrainingBlock.objects.create(name="Fall Strength", coach=self.coach)
        self.days = [
            TrainingBlockWorkout.objects.create(training_block=self.block, name=f"Day {n}", position=n)
            for n in (1, 2, 3)
        ]
        self.rows = [
            TrainingBlockExercise.objects.create(
                training_block_workout=self.days[0], exercise=ex, position=p,
                sets=5, reps=3, target_percent=80)
            for p, ex in enumerate((self.squat, self.bench), start=1)
        ]

    def _day_url(self, day):
        return f"/api/training-blocks/{self.block.id}/workouts/{day.id}/"

    # ── renaming and removing ────────────────────────────────────────────────

    def test_a_day_can_be_renamed(self):
        res = self.client.patch(self._day_url(self.days[0]), {"name": "Day 1 — Lower"},
                                format="json")
        self.assertEqual(res.status_code, 200)
        self.days[0].refresh_from_db()
        self.assertEqual(self.days[0].name, "Day 1 — Lower")

    def test_a_day_cannot_be_renamed_to_nothing(self):
        res = self.client.patch(self._day_url(self.days[0]), {"name": "   "}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["code"], "invalid_name")

    def test_deleting_a_day_takes_its_prescription_rows_with_it(self):
        res = self.client.delete(self._day_url(self.days[0]))
        self.assertEqual(res.status_code, 204)
        self.assertFalse(TrainingBlockWorkout.objects.filter(id=self.days[0].id).exists())
        self.assertEqual(TrainingBlockExercise.objects.filter(
            training_block_workout_id=self.days[0].id).count(), 0)

    def test_a_day_in_another_block_cannot_be_edited_through_this_one(self):
        """Without the parent check, /training-blocks/1/workouts/99/ would edit
        a day belonging to block 2."""
        other = TrainingBlock.objects.create(name="Spring", coach=self.coach)
        stranger = TrainingBlockWorkout.objects.create(training_block=other, name="Theirs", position=1)
        res = self.client.patch(
            f"/api/training-blocks/{self.block.id}/workouts/{stranger.id}/",
            {"name": "Hijacked"}, format="json")
        self.assertEqual(res.status_code, 404)
        stranger.refresh_from_db()
        self.assertEqual(stranger.name, "Theirs")

    # ── reordering ───────────────────────────────────────────────────────────

    def test_days_can_be_reordered_and_the_order_survives_a_reload(self):
        """The case a per-item PATCH cannot do: two days swapping numbers."""
        order = [self.days[2].id, self.days[0].id, self.days[1].id]
        res = self.client.put(f"/api/training-blocks/{self.block.id}/workout-order/",
                              {"workout_ids": order}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([d["id"] for d in res.data], order)
        # Read back from the database, not the response — the point is that it stuck.
        self.assertEqual(
            list(self.block.workouts.order_by("position").values_list("id", flat=True)), order)
        self.assertEqual(
            list(self.block.workouts.order_by("position").values_list("position", flat=True)),
            [1, 2, 3])

    def test_reordering_is_idempotent(self):
        order = [self.days[1].id, self.days[2].id, self.days[0].id]
        url = f"/api/training-blocks/{self.block.id}/workout-order/"
        self.client.put(url, {"workout_ids": order}, format="json")
        self.client.put(url, {"workout_ids": order}, format="json")
        self.assertEqual(
            list(self.block.workouts.order_by("position").values_list("id", flat=True)), order)

    def test_a_partial_order_is_refused_rather_than_half_applied(self):
        """Naming a subset would quietly drop the unnamed days out of the order."""
        res = self.client.put(f"/api/training-blocks/{self.block.id}/workout-order/",
                              {"workout_ids": [self.days[0].id]}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["code"], "invalid_order")
        self.assertEqual(
            list(self.block.workouts.order_by("position").values_list("position", flat=True)),
            [1, 2, 3])

    def test_movements_inside_a_day_can_be_reordered(self):
        order = [self.rows[1].id, self.rows[0].id]
        res = self.client.put(
            f"/api/training-blocks/{self.block.id}/workouts/{self.days[0].id}/exercise-order/",
            {"exercise_ids": order}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            list(self.days[0].exercises.order_by("position").values_list("id", flat=True)), order)

    # ── editing a prescription row ───────────────────────────────────────────

    def test_a_prescription_row_can_be_changed(self):
        res = self.client.patch(
            f"{self._day_url(self.days[0])}exercises/{self.rows[0].id}/",
            {"target_percent": 72.5, "reps": 5}, format="json")
        self.assertEqual(res.status_code, 200)
        self.rows[0].refresh_from_db()
        self.assertAlmostEqual(self.rows[0].target_percent, 72.5)
        self.assertEqual(self.rows[0].reps, 5)

    def test_position_cannot_be_changed_through_the_row_endpoint(self):
        """Reordering is a whole-list operation; letting position in here is
        exactly what breaks against the unique constraint."""
        res = self.client.patch(
            f"{self._day_url(self.days[0])}exercises/{self.rows[0].id}/",
            {"position": 2}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["code"], "nothing_to_change")
        self.rows[0].refresh_from_db()
        self.assertEqual(self.rows[0].position, 1)

    # ── "last edited" ────────────────────────────────────────────────────────

    def test_editing_a_day_marks_the_BLOCK_as_edited(self):
        """auto_now fires for the row being saved, so without an explicit touch
        the child moves and the block goes stale — and a catalog sorted by
        "recently edited" lies in exactly the case a coach cares about."""
        before = TrainingBlock.objects.get(id=self.block.id).updated_at
        self.client.patch(self._day_url(self.days[0]), {"name": "Renamed"}, format="json")
        self.assertGreater(TrainingBlock.objects.get(id=self.block.id).updated_at, before)

    def test_editing_a_prescription_row_marks_the_block_as_edited(self):
        before = TrainingBlock.objects.get(id=self.block.id).updated_at
        self.client.patch(f"{self._day_url(self.days[0])}exercises/{self.rows[0].id}/",
                          {"reps": 8}, format="json")
        self.assertGreater(TrainingBlock.objects.get(id=self.block.id).updated_at, before)

    # ── the independence rule ────────────────────────────────────────────────

    def test_deleting_from_a_template_leaves_a_deployed_program_alone(self):
        """The whole reason deploying COPIES rather than references. A group
        mid-season must not lose a day because a coach tidied the template."""
        group = TrainingGroup.objects.create(name="Varsity", coach=self.coach)
        program = instantiate_block(self.block, group, start_date=timezone.now().date())
        days_before = program.workouts.count()
        rows_before = TrainingProgramExercise.objects.filter(
            training_program_workout__training_program=program).count()
        self.assertGreater(days_before, 0)
        self.assertGreater(rows_before, 0)

        self.client.delete(self._day_url(self.days[0]))
        self.client.delete(f"{self._day_url(self.days[1])}")

        self.assertEqual(program.workouts.count(), days_before)
        self.assertEqual(TrainingProgramExercise.objects.filter(
            training_program_workout__training_program=program).count(), rows_before)

    def test_editing_a_deployed_program_does_not_mark_the_template_as_edited(self):
        """A program is a snapshot. Reporting the template as changed when
        nobody changed it would imply a coupling that does not exist."""
        group = TrainingGroup.objects.create(name="Varsity", coach=self.coach)
        program = instantiate_block(self.block, group, start_date=timezone.now().date())
        before = TrainingBlock.objects.get(id=self.block.id).updated_at

        row = TrainingProgramExercise.objects.filter(
            training_program_workout__training_program=program).first()
        row.target_percent = 60
        row.save(update_fields=["target_percent"])

        self.assertEqual(TrainingBlock.objects.get(id=self.block.id).updated_at, before)


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

    def _upload(self, text, url="/api/imports/preview/", **extra):
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
                           url="/api/imports/")
        self.assertEqual(res.status_code, 200)
        record = AthleteReferenceMax.objects.get()
        self.assertEqual(record.reference_weight_lbs, 315)
        self.assertEqual(record.rep_basis, 1)

    def test_a_weight_with_reps_is_stored_at_that_rep_basis_not_converted_early(self):
        """225x5 is recorded honestly as 225 at 5 reps; the conversion to a single
        happens in one place later, so the original fact stays visible."""
        Athlete.objects.create(name="Jordan Lee")
        self._upload("athlete_name,exercise,weight_lbs,reps\nJordan Lee,Back Squat,225,5\n",
                     url="/api/imports/")
        record = AthleteReferenceMax.objects.get()
        self.assertEqual(record.reference_weight_lbs, 225)
        self.assertEqual(record.rep_basis, 5)

    def test_a_stated_percentage_is_back_solved_exactly(self):
        Athlete.objects.create(name="Jordan Lee")
        self._upload("athlete_name,exercise,weight_lbs,target_percent\n"
                     "Jordan Lee,Back Squat,225,75\n", url="/api/imports/")
        self.assertEqual(AthleteReferenceMax.objects.get().reference_weight_lbs, 300)

    def test_a_weight_that_could_mean_anything_is_SKIPPED_not_guessed(self):
        """The whole point of D16: a made-up max is newest-wins, so it would
        outrank the athlete's real tested number and drag every other target
        down with it. Missing is safe; wrong is not."""
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,weight_lbs\nJordan Lee,Back Squat,225\n",
                           url="/api/imports/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AthleteReferenceMax.objects.count(), 0)
        self.assertEqual(res.data["skipped"][0]["code"], "weight_meaning_unknown")
        self.assertIn("Jordan Lee", res.data["skipped"][0]["detail"])

    def test_a_skipped_row_does_not_stop_the_good_rows(self):
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,weight_lbs,reps\n"
                           "Jordan Lee,Back Squat,225,5\n"
                           "Jordan Lee,Bench Press,185,\n", url="/api/imports/")
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
                           "Sam Rivera,Back Squat,275\n", url="/api/imports/")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(AthleteReferenceMax.objects.count(), 0)

    # ── D17(d): the coach's fix survives the round trip ──────────────────────

    def test_a_correction_imports_the_row_without_re_uploading(self):
        """The point of the whole repair loop: answer "who did you mean?" once,
        send the SAME file back, and it goes in."""
        jordan = Athlete.objects.create(name="Jordan Lee")
        sheet = ("athlete_name,exercise,max_lbs\n"
                 "Jordn Lee,Back Squat,315\n")

        self.assertEqual(self._upload(sheet, url="/api/imports/").status_code, 400)
        self.assertEqual(AthleteReferenceMax.objects.count(), 0)

        res = self._upload(sheet, url="/api/imports/",
                           corrections=json.dumps({"athlete": {"Jordn Lee": jordan.id}}))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AthleteReferenceMax.objects.get().athlete_id, jordan.id)

    def test_one_correction_repairs_every_row_with_that_spelling(self):
        """A name misspelled forty times is one fix, not forty — that is what
        makes repairing on screen better than editing the file."""
        jordan = Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,max_lbs\n"
                           "Jordn Lee,Back Squat,315\n"
                           "jordn lee,Bench Press,225\n",
                           url="/api/imports/",
                           corrections=json.dumps({"athlete": {"Jordn Lee": jordan.id}}))
        self.assertEqual(res.status_code, 200)
        # Both rows landed, including the one spelled with different casing.
        self.assertEqual(AthleteReferenceMax.objects.filter(athlete=jordan).count(), 2)

    def test_a_correction_naming_a_record_that_does_not_exist_is_ignored(self):
        """A stale or hand-edited correction must not write to whatever row that
        id happens to be. It falls back to normal matching and re-reports."""
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,max_lbs\nJordn Lee,Back Squat,315\n",
                           url="/api/imports/",
                           corrections=json.dumps({"athlete": {"Jordn Lee": 999999}}))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["errors"][0]["code"], "unknown_athlete")
        self.assertEqual(AthleteReferenceMax.objects.count(), 0)

    def test_corrections_are_scoped_to_what_they_name(self):
        """An athlete correction must not satisfy a movement lookup, even when
        the misspelling is identical."""
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,max_lbs\nJordan Lee,Bakc Squat,315\n",
                           url="/api/imports/",
                           corrections=json.dumps({"athlete": {"Bakc Squat": self.squat.id}}))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["errors"][0]["code"], "unknown_exercise")

    def test_malformed_corrections_are_reported_rather_than_dropped(self):
        """Silently ignoring them would re-raise the errors the coach just fixed
        and look like their fix didn't take."""
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,max_lbs\nJordan Lee,Back Squat,315\n",
                           url="/api/imports/", corrections="{not json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["code"], "invalid_corrections")

    def test_a_correction_also_repairs_a_misspelled_movement(self):
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,max_lbs\nJordan Lee,Bakc Squat,315\n",
                           url="/api/imports/",
                           corrections=json.dumps({"exercise": {"Bakc Squat": self.squat.id}}))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AthleteReferenceMax.objects.get().exercise_id, self.squat.id)

    def test_a_misspelled_movement_suggests_the_catalog_entry(self):
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,max_lbs\nJordan Lee,Bakc Squat,315\n")
        problem = res.data["errors"][0]
        self.assertEqual(problem["code"], "unknown_exercise")
        self.assertIn("Back Squat", problem["suggestions"])

    def test_two_people_with_one_name_are_told_apart_by_the_group(self):
        """TrainingGroup-scoping is what collapses the ambiguity — two Jordan Lees in a
        gym is believable, two in one group is not."""
        in_group = Athlete.objects.create(name="Jordan Lee")
        Athlete.objects.create(name="Jordan Lee")   # a different Jordan, elsewhere
        group = TrainingGroup.objects.create(name="Varsity", coach=self.coach)
        in_group.training_groups.add(group)

        res = self._upload("athlete_name,exercise,max_lbs\nJordan Lee,Back Squat,315\n",
                           url="/api/imports/", training_group=group.id)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AthleteReferenceMax.objects.get().athlete_id, in_group.id)

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
                           url="/api/imports/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AthleteReferenceMax.objects.count(), 1)

    # ── the roster sheet ─────────────────────────────────────────────────────

    def test_a_roster_creates_people_and_can_drop_them_into_a_group(self):
        group = TrainingGroup.objects.create(name="Varsity", coach=self.coach)
        res = self._upload("athlete_name,training_group\nJordan Lee,Varsity\nSam Rivera,Varsity\n",
                           url="/api/imports/")
        self.assertEqual(res.data["created"], 2)
        self.assertEqual(group.athletes.count(), 2)

    def test_re_uploading_a_roster_adds_the_new_people_without_duplicating_the_old(self):
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name\nJordan Lee\nSam Rivera\n",
                           url="/api/imports/")
        self.assertEqual(res.data["created"], 1)
        self.assertEqual(Athlete.objects.filter(name="Jordan Lee").count(), 1)
        self.assertEqual(res.data["skipped"][0]["code"], "already_on_roster")

    def test_a_max_sheet_never_creates_a_missing_athlete(self):
        """A typo turned into a new athlete would shadow the real person forever."""
        res = self._upload("athlete_name,exercise,max_lbs\nNobody At All,Back Squat,315\n",
                           url="/api/imports/")
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
            url="/api/imports/", training_block=block.id)
        self.assertEqual(res.status_code, 200)
        days = list(TrainingBlockWorkout.objects.filter(training_block=block).order_by("position"))
        self.assertEqual([d.name for d in days], ["Day 1 - Lower", "Day 2 - Upper"])
        self.assertEqual(days[0].exercises.count(), 2)

    def test_a_plan_imports_into_one_groups_program_too(self):
        """D7: both levels. A one-off for one TrainingGroup never becomes a template."""
        group = TrainingGroup.objects.create(name="Varsity", coach=self.coach)
        program = TrainingProgram.objects.create(training_group=group, name="Spring",
                                                 start_date=timezone.now().date())
        res = self._upload("workout_name,exercise,position,sets,reps,target_percent\n"
                           "Day 1,Back Squat,1,5,3,80\n",
                           url="/api/imports/", training_program=program.id)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(TrainingProgramWorkout.objects.filter(training_program=program).count(), 1)
        self.assertEqual(TrainingBlockWorkout.objects.count(), 0)

    def test_importing_again_appends_rather_than_colliding(self):
        block = self._block()
        sheet = ("workout_name,exercise,position,sets,reps,target_percent\n"
                 "Day 1,Back Squat,1,5,3,80\n")
        self._upload(sheet, url="/api/imports/", training_block=block.id)
        res = self._upload(sheet.replace("Day 1", "Day 2"), url="/api/imports/",
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
        res = self.client.post("/api/imports/", {"file": upload}, format="multipart")
        self.assertEqual(res.status_code, 200)

    def test_preview_writes_nothing(self):
        Athlete.objects.create(name="Jordan Lee")
        res = self._upload("athlete_name,exercise,max_lbs\nJordan Lee,Back Squat,315\n")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AthleteReferenceMax.objects.count(), 0)
        self.assertEqual(res.data["counts"]["ready"], 1)

    def test_import_requires_a_coach(self):
        self.client.force_authenticate(user=None)
        res = self._upload("athlete_name\nJordan Lee\n", url="/api/imports/")
        self.assertIn(res.status_code, (401, 403))
        self.assertEqual(Athlete.objects.count(), 0)


class AthleteAssignmentTests(APITestCase):
    """What one athlete is training (`athletes/{id}/program/`).

    His page was built where a program pins onto one athlete; here it belongs to
    a TrainingGroup and the athlete trains it by membership. These pin that the route
    still answers his question, and that a write says what it really did.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        self.athlete = Athlete.objects.create(name="Jordan Lee")
        self.group = TrainingGroup.objects.create(name="Varsity", coach=self.coach)
        self.program = TrainingProgram.objects.create(
            training_group=self.group, name="Fall", start_date=timezone.now().date())
        workout = TrainingProgramWorkout.objects.create(
            training_program=self.program, name="Day 1", position=1)
        TrainingProgramExercise.objects.create(
            training_program_workout=workout, exercise=self.squat, position=1,
            sets=5, reps=3, target_percent=80)

    def _url(self):
        return f"/api/athletes/{self.athlete.id}/program/"

    def test_an_athlete_in_no_group_has_no_plan(self):
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["assignment"], [])

    def test_assigning_a_program_puts_them_in_its_group_and_says_so(self):
        res = self.client.put(self._url(), {"workout_program_id": self.program.id},
                              format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["groups_changed"],
                         [{"id": self.group.id, "name": "Varsity", "action": "added"}])
        self.assertIn(self.group, self.athlete.training_groups.all())

    def test_the_plan_comes_back_with_real_pounds_not_just_a_percent(self):
        """A percent on its own tells a coach nothing about what goes on the bar."""
        AthleteReferenceMax.objects.create(athlete=self.athlete, exercise=self.squat,
                                           reference_weight_lbs=315, rep_basis=1)
        self.athlete.training_groups.add(self.group)
        row = self.client.get(self._url()).data["assignment"][0]["workouts"][0]["exercises"][0]
        self.assertEqual(row["target_percent"], 80)
        self.assertEqual(row["target_weight_lbs"], 250.0)   # 315 x 80% = 252 -> 250

    def test_an_athlete_with_no_max_still_reads_without_error(self):
        self.athlete.training_groups.add(self.group)
        row = self.client.get(self._url()).data["assignment"][0]["workouts"][0]["exercises"][0]
        self.assertIsNone(row["target_weight_lbs"])

    def test_two_groups_both_show_up_with_the_group_that_owns_each(self):
        """D13: an athlete can carry more than one plan, and a coach needs to see
        which TrainingGroup each one comes from."""
        speed = TrainingGroup.objects.create(name="Speed", coach=self.coach)
        TrainingProgram.objects.create(training_group=speed, name="Sprint",
                                       start_date=timezone.now().date())
        self.athlete.training_groups.add(self.group, speed)
        assignment = self.client.get(self._url()).data["assignment"]
        self.assertEqual({a["training_group"]["name"] for a in assignment},
                         {"Varsity", "Speed"})

    def test_removing_the_assignment_takes_them_out_of_the_prescribing_groups_only(self):
        """A TrainingGroup with no plan attached is roster information a coach set up on
        purpose — clearing an assignment shouldn't quietly discard it."""
        empty = TrainingGroup.objects.create(name="Freshmen", coach=self.coach)
        self.athlete.training_groups.add(self.group, empty)
        res = self.client.delete(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual([g["name"] for g in res.data["groups_changed"]], ["Varsity"])
        self.assertEqual([g.name for g in self.athlete.training_groups.all()], ["Freshmen"])

    def test_unknown_athlete_and_unknown_program_are_404(self):
        self.assertEqual(self.client.get("/api/athletes/999999/program/").status_code, 404)
        res = self.client.put(self._url(), {"workout_program_id": 999999}, format="json")
        self.assertEqual(res.status_code, 404)

    def test_assignment_requires_a_coach(self):
        self.client.force_authenticate(user=None)
        res = self.client.put(self._url(), {"workout_program_id": self.program.id},
                              format="json")
        self.assertIn(res.status_code, (401, 403))


class SessionDeleteProtectionTests(APITestCase):
    """Deleting a session must not be able to delete the lifting inside it.

    This was a live data-loss path: `Set.session` cascaded, so removing a session
    silently took every set and rep recorded during it, with nothing to undo it.
    A training day is ended by setting `ended_at`, never by being deleted, so the
    protection costs nothing real.
    """

    def setUp(self):
        self.session = TrainingSession.objects.create(label="Thursday")
        self.athlete = Athlete.objects.create(name="Jordan Lee")
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]

    def test_a_session_with_lifting_in_it_refuses_to_be_deleted(self):
        a_set = Set.objects.create(session=self.session, athlete=self.athlete,
                                   exercise=self.squat, set_number=1,
                                   ended_at=timezone.now())
        Rep.objects.create(set=a_set, rep_number=1, timestamp=timezone.now(),
                           mean_velocity=0.7, peak_velocity=0.8, duration_ms=700,
                           velocity_color="green")

        with self.assertRaises(ProtectedError):
            self.session.delete()

        self.assertEqual(Set.objects.count(), 1)
        self.assertEqual(Rep.objects.count(), 1)
        self.assertEqual(TrainingSession.objects.count(), 1)

    def test_an_empty_session_can_still_be_deleted(self):
        """Nobody lifted, so there is nothing to protect — a mis-created session
        should not be permanent."""
        self.session.delete()
        self.assertEqual(TrainingSession.objects.count(), 0)

    def test_the_protection_is_in_the_applied_migration_not_just_the_model(self):
        """A model that says PROTECT while the database still says CASCADE would
        pass every test above and still lose data in production."""
        field = Set._meta.get_field("session")
        self.assertIs(field.remote_field.on_delete, models.PROTECT)
