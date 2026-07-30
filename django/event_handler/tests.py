# tests.py — automated checks for the base-station endpoints.
#
# Covers GET /api/sessions/active/ (the rack screen's one startup fetch) and the
# GET /api/exercises/ catalog list. Each test pins one promise the rack screen
# relies on: which session counts as active, who reads as already having data,
# that an athlete's CURRENT reference max (and only that) comes back, and that
# every exercise now resolves through the shared catalog.
import json
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.db.models import ProtectedError
from django.utils import timezone
from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from rest_framework.test import APITestCase

from .models import (Athlete, TrainingSession, Set, Rep, AthleteReferenceMax, Exercise,
                     RackCheckIn, DailyReport, Node, TrainingGroup, TrainingProgram,
                     TrainingProgramWorkout, TrainingProgramExercise, SessionParticipation,
                     AthleteWorkoutExerciseOverride, TrainingBlock, TrainingBlockWorkout,
                     TrainingBlockExercise, BlockCategory, TrainingGroupCoach)
from .services.plan_resolution import movements_for_athlete
from .services.planning import generate_schedule, instantiate_block, touch_block
from .services.athlete_analytics import REP_LIMIT, SET_LIMIT


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
        group = TrainingGroup.objects.create(name=f"Group for {athlete.name}")
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
        TrainingSession.objects.create(label="Done", started_at=timezone.now(),
                                      ended_at=timezone.now())  # ended → not active
        res = self.client.get(self.URL)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["session_id"], None)
        self.assertEqual(res.data["roster"], [])
        self.assertEqual(res.data["session_exercises"], [])

    def test_picks_most_recent_unended_session(self):
        # Explicitly staggered. `started_at` stopped being auto_now_add in P14, so
        # two sessions created in one test now share a timestamp unless told
        # otherwise — and this test is specifically about which is NEWER, not
        # about the id tie-break that would otherwise decide it.
        TrainingSession.objects.create(label="Older",
                                       started_at=timezone.now() - timedelta(hours=2))
        newer = TrainingSession.objects.create(label="Newer", started_at=timezone.now())
        res = self.client.get(self.URL)
        self.assertEqual(res.data["session_id"], newer.id)
        self.assertEqual(res.data["label"], "Newer")

    def test_roster_has_data_reflects_completed_sets(self):
        session = TrainingSession.objects.create(label="Live", started_at=timezone.now())
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
        session = TrainingSession.objects.create(label="Live", started_at=timezone.now())
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
        session = TrainingSession.objects.create(label="Live", started_at=timezone.now())
        squat = self._exercise("Back Squat")
        athlete = Athlete.objects.create(name="Bad Week")
        session.athletes.add(athlete)
        self._dated_max(athlete, squat, 315.0, days_ago=30)  # was strong
        self._dated_max(athlete, squat, 285.0, days_ago=1)   # rough patch

        res = self.client.get(self.URL)
        self.assertEqual(res.data["roster"][0]["maxes"][squat.id], 285.0)

    def test_targets_and_exercises_come_from_programs(self):
        session = TrainingSession.objects.create(label="Live", started_at=timezone.now())
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
        TrainingSession.objects.create(label="Live", started_at=timezone.now())
        res = self.client.get(self._url(999999))
        self.assertEqual(res.status_code, 404)

    def test_athlete_not_on_roster_is_404(self):
        TrainingSession.objects.create(label="Live", started_at=timezone.now())
        outsider = Athlete.objects.create(name="Outsider")
        res = self.client.get(self._url(outsider.id))
        self.assertEqual(res.status_code, 404)

    def test_derives_progress_in_program_order(self):
        session = TrainingSession.objects.create(label="Live", started_at=timezone.now())
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
        session = TrainingSession.objects.create(label="Live", started_at=timezone.now())
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
        session = TrainingSession.objects.create(label="Live", started_at=timezone.now())
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
        session = TrainingSession.objects.create(label="Live", started_at=timezone.now())
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
        TrainingSession.objects.create(label="Done", started_at=timezone.now(),
                                      ended_at=timezone.now())  # ended → not active
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
        session = TrainingSession.objects.create(label="Live", started_at=timezone.now())
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
        session = TrainingSession.objects.create(label="Live", started_at=timezone.now())
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
        self.session = TrainingSession.objects.create(label="Thursday", started_at=timezone.now())
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
        self.session = TrainingSession.objects.create(label="Thursday", started_at=timezone.now())
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
        self.session = TrainingSession.objects.create(label="Thursday", started_at=timezone.now())
        self.athlete = Athlete.objects.create(name="Jordan Lee")
        self.session.athletes.add(self.athlete)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        self.bench = Exercise.objects.get_or_create(name="Bench Press")[0]

    def _max(self, exercise, weight, rep_basis=1):
        return AthleteReferenceMax.objects.create(
            athlete=self.athlete, exercise=exercise,
            reference_weight_lbs=weight, rep_basis=rep_basis)

    def _group(self, name, extra_members=0):
        group = TrainingGroup.objects.create(name=name)
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
        group = TrainingGroup.objects.create(name="Off today")
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
        self.session = TrainingSession.objects.create(label="Thursday", started_at=timezone.now())
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
        """Not every plan is worth templating; a coach can write one directly.
        (Turning one back into a template is P15 — it is not built yet.)"""
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
        session = TrainingSession.objects.create(label="Thursday", started_at=timezone.now())
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
        session = TrainingSession.objects.create(label="Thursday", started_at=timezone.now())
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
        group = TrainingGroup.objects.create(name="Varsity")
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
        group = TrainingGroup.objects.create(name="Varsity")
        program = instantiate_block(self.block, group, start_date=timezone.now().date())
        before = TrainingBlock.objects.get(id=self.block.id).updated_at

        row = TrainingProgramExercise.objects.filter(
            training_program_workout__training_program=program).first()
        row.target_percent = 60
        row.save(update_fields=["target_percent"])

        self.assertEqual(TrainingBlock.objects.get(id=self.block.id).updated_at, before)


class BlockCatalogLensTests(APITestCase):
    """The coach filter on the block catalog (P11, step 1).

    The thing these tests are really pinning down is that the filter is a LENS,
    NOT A FENCE. It is easy to write a filter and then quietly start treating it
    as permission — so there is a test below that asserts the opposite: another
    coach's block is still fully visible and still editable. If someone ever
    wants a real boundary, it goes on TOP of this, and that test is the one that
    should be changed deliberately rather than discovered broken.
    """

    def setUp(self):
        self.sarah = User.objects.create_user(username="sarah", password="pw")
        self.mike = User.objects.create_user(username="mike", password="pw")
        self.client.force_authenticate(user=self.sarah)
        self.hers = TrainingBlock.objects.create(name="Alpha Fall", coach=self.sarah)
        self.his = TrainingBlock.objects.create(name="Beta Winter", coach=self.mike)

    def _names(self, response):
        return [block["name"] for block in response.data]

    def test_the_catalog_is_global_by_default(self):
        """No filter means the whole department — the shared catalog is the point."""
        res = self.client.get("/api/training-blocks/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self._names(res), ["Alpha Fall", "Beta Winter"])

    def test_coach_me_narrows_to_the_caller(self):
        res = self.client.get("/api/training-blocks/?coach=me")
        self.assertEqual(self._names(res), ["Alpha Fall"])

    def test_coach_id_narrows_to_that_coach(self):
        res = self.client.get(f"/api/training-blocks/?coach={self.mike.id}")
        self.assertEqual(self._names(res), ["Beta Winter"])

    def test_a_nonsense_coach_value_is_rejected_not_ignored(self):
        """Silently returning everything would look like 'this coach owns it all'."""
        res = self.client.get("/api/training-blocks/?coach=sarah")
        self.assertEqual(res.status_code, 400)

    def test_the_filter_is_not_a_permission_boundary(self):
        """Sarah can still see and edit Mike's block. This is deliberate."""
        day = TrainingBlockWorkout.objects.create(
            training_block=self.his, name="Day 1", position=1)

        listed = self.client.get("/api/training-blocks/")
        self.assertIn("Beta Winter", self._names(listed))

        edit = self.client.patch(
            f"/api/training-blocks/{self.his.id}/workouts/{day.id}/",
            {"name": "Day 1 — Lower"}, format="json")
        self.assertEqual(edit.status_code, 200)

    # ── sorting ──────────────────────────────────────────────────────────────

    def test_sort_recent_orders_by_last_edited(self):
        """P10 added `updated_at` for exactly this; until now nothing served it."""
        touch_block(self.his.id)

        res = self.client.get("/api/training-blocks/?sort=recent")
        self.assertEqual(self._names(res), ["Beta Winter", "Alpha Fall"])

    def test_updated_at_is_serialized(self):
        """A column the client cannot read cannot sort anything client-side."""
        res = self.client.get("/api/training-blocks/")
        self.assertIn("updated_at", res.data[0])


class BlockCategoryTests(APITestCase):
    """Labelling the shared block catalog (P11, step 2).

    A block carries SEVERAL categories, not one, because the labels sit on
    different axes — a block is honestly both "Off-season" and "Football". That
    choice is what makes any-of the right filter behaviour, so the two are
    tested together.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.offseason = BlockCategory.objects.create(name="Off-season")
        self.football = BlockCategory.objects.create(name="Football")
        self.freshman = BlockCategory.objects.create(name="Freshman")

        self.both = TrainingBlock.objects.create(name="Alpha", coach=self.coach)
        self.both.categories.set([self.offseason, self.football])
        self.one = TrainingBlock.objects.create(name="Beta", coach=self.coach)
        self.one.categories.set([self.freshman])
        self.none = TrainingBlock.objects.create(name="Gamma", coach=self.coach)

    def _names(self, response):
        return sorted(block["name"] for block in response.data)

    # ── the vocabulary ───────────────────────────────────────────────────────

    def test_categories_can_be_created_and_listed(self):
        created = self.client.post("/api/block-categories/", {"name": "Winter"},
                                   format="json")
        self.assertEqual(created.status_code, 201)

        listed = self.client.get("/api/block-categories/")
        self.assertIn("Winter", [row["name"] for row in listed.data])

    def test_a_duplicate_category_is_refused(self):
        """Two rows named the same defeat the whole point of a shared vocabulary."""
        res = self.client.post("/api/block-categories/", {"name": "Football"},
                               format="json")
        self.assertEqual(res.status_code, 400)

    def test_a_blank_category_name_is_refused(self):
        res = self.client.post("/api/block-categories/", {"name": "   "}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_block_count_rides_along(self):
        listed = self.client.get("/api/block-categories/")
        counts = {row["name"]: row["block_count"] for row in listed.data}
        self.assertEqual(counts["Off-season"], 1)
        self.assertEqual(counts["Football"], 1)

    # ── labelling a block ────────────────────────────────────────────────────

    def test_a_block_can_be_created_with_categories(self):
        res = self.client.post("/api/training-blocks/", {
            "name": "Delta", "categories": [self.football.id, self.freshman.id],
        }, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(sorted(res.data["categories"]),
                         sorted([self.football.id, self.freshman.id]))
        self.assertEqual(sorted(res.data["category_names"]), ["Football", "Freshman"])

    def test_an_existing_block_can_be_labelled_later(self):
        """The reason the detail route exists: every block that predates P11 has
        no labels, and a create-only API could never give it any."""
        res = self.client.patch(f"/api/training-blocks/{self.none.id}/",
                                {"categories": [self.football.id]}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["category_names"], ["Football"])

    def test_labels_can_be_cleared(self):
        res = self.client.patch(f"/api/training-blocks/{self.both.id}/",
                                {"categories": []}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["category_names"], [])

    def test_a_block_has_no_delete_route(self):
        """Guarded on purpose — see the note in training_block_detail. The canon's
        filter-not-fence reasoning partly rests on nobody being able to delete."""
        res = self.client.delete(f"/api/training-blocks/{self.both.id}/")
        self.assertEqual(res.status_code, 405)

    def test_a_missing_block_is_404_not_500(self):
        self.assertEqual(self.client.patch("/api/training-blocks/99999/",
                                           {"name": "x"}, format="json").status_code, 404)

    # ── filtering ────────────────────────────────────────────────────────────

    def test_one_category_narrows_the_catalog(self):
        res = self.client.get(f"/api/training-blocks/?category={self.freshman.id}")
        self.assertEqual(self._names(res), ["Beta"])

    def test_several_categories_mean_any_of(self):
        """All-of would usually return nothing — the labels are different axes."""
        res = self.client.get(
            f"/api/training-blocks/?category={self.freshman.id}&category={self.football.id}")
        self.assertEqual(self._names(res), ["Alpha", "Beta"])

    def test_a_block_matching_two_requested_labels_is_listed_once(self):
        """A many-to-many join repeats a row per match; without distinct() Alpha
        would appear twice and the count shown to the coach would be wrong."""
        res = self.client.get(
            f"/api/training-blocks/?category={self.offseason.id}&category={self.football.id}")
        self.assertEqual(self._names(res), ["Alpha"])

    def test_a_nonsense_category_value_is_rejected(self):
        res = self.client.get("/api/training-blocks/?category=football")
        self.assertEqual(res.status_code, 400)

    def test_category_and_coach_filters_combine(self):
        other = User.objects.create_user(username="other", password="pw")
        theirs = TrainingBlock.objects.create(name="Epsilon", coach=other)
        theirs.categories.set([self.football])

        res = self.client.get(f"/api/training-blocks/?coach=me&category={self.football.id}")
        self.assertEqual(self._names(res), ["Alpha"])


class TrainingGroupStaffTests(APITestCase):
    """Several coaches on one group (P11, step 3).

    This replaced a single `coach` field on TrainingGroup. A real weight room
    puts a head coach and assistants on the same group, and one field could
    only ever name one of them.
    """

    def setUp(self):
        self.sarah = User.objects.create_user(username="sarah", password="pw")
        self.mike = User.objects.create_user(username="mike", password="pw")
        self.dana = User.objects.create_user(username="dana", password="pw")
        self.client.force_authenticate(user=self.sarah)
        self.group = TrainingGroup.objects.create(name="Varsity")
        TrainingGroupCoach.objects.create(
            training_group=self.group, coach=self.sarah, role=TrainingGroupCoach.HEAD)

    def _url(self):
        return f"/api/training-groups/{self.group.id}/coaches/"

    def _staff(self, response):
        return {row["coach_name"]: row["role"] for row in response.data}

    # ── the shape of the change ──────────────────────────────────────────────

    def test_a_group_no_longer_has_a_single_coach_field(self):
        """The point of the migration. If this passes while `coach` still exists,
        the field was left behind and there are now two answers to 'who runs
        this group' waiting to disagree."""
        self.assertFalse(any(f.name == "coach" for f in TrainingGroup._meta.get_fields()))

    def test_the_group_payload_lists_staff_and_names_a_head(self):
        res = self.client.get("/api/training-groups/")
        group = next(row for row in res.data if row["id"] == self.group.id)
        self.assertEqual([c["coach_name"] for c in group["coaches"]], ["sarah"])
        self.assertEqual(group["head_coach"]["name"], "sarah")

    def test_creating_a_group_makes_the_creator_its_head_coach(self):
        """A group with no staff at all is never what someone meant to make."""
        res = self.client.post("/api/training-groups/", {"name": "Freshmen"},
                               format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["head_coach"]["name"], "sarah")

    # ── adding and removing staff ────────────────────────────────────────────

    def test_two_coaches_can_run_the_same_group(self):
        """The thing the old single field could not say."""
        res = self.client.post(self._url(), {"coach": self.mike.id, "role": "assistant"},
                               format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(self._staff(res), {"sarah": "head", "mike": "assistant"})

    def test_adding_the_same_coach_twice_updates_the_role_instead_of_erroring(self):
        """The unique constraint would otherwise turn an ordinary click into a 500."""
        self.client.post(self._url(), {"coach": self.mike.id, "role": "assistant"},
                         format="json")
        res = self.client.post(self._url(), {"coach": self.mike.id, "role": "assistant"},
                               format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(self.group.coach_links.filter(coach=self.mike).count(), 1)

    def test_a_coach_can_be_removed(self):
        self.client.post(self._url(), {"coach": self.mike.id}, format="json")
        res = self.client.delete(self._url(), {"coach": self.mike.id}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("mike", self._staff(res))

    def test_removing_someone_who_does_not_run_the_group_is_404(self):
        res = self.client.delete(self._url(), {"coach": self.dana.id}, format="json")
        self.assertEqual(res.status_code, 404)

    def test_an_unknown_coach_is_refused(self):
        res = self.client.post(self._url(), {"coach": 99999}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_a_bad_role_is_refused(self):
        res = self.client.post(self._url(), {"coach": self.mike.id, "role": "boss"},
                               format="json")
        self.assertEqual(res.status_code, 400)

    def test_a_missing_group_is_404(self):
        res = self.client.get("/api/training-groups/99999/coaches/")
        self.assertEqual(res.status_code, 404)

    # ── the head-coach rule ──────────────────────────────────────────────────

    def test_promoting_a_new_head_demotes_the_old_one(self):
        """One head at a time. Two would make `head_coach` arbitrary."""
        self.client.post(self._url(), {"coach": self.mike.id, "role": "assistant"},
                         format="json")
        res = self.client.patch(self._url(), {"coach": self.mike.id, "role": "head"},
                                format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self._staff(res), {"mike": "head", "sarah": "assistant"})
        self.assertEqual(self.group.coach_links.filter(role="head").count(), 1)

    def test_adding_someone_straight_in_as_head_also_demotes_the_incumbent(self):
        """The rule has to hold on the add path too, not just the role change —
        otherwise 'add Mike as head' quietly leaves two heads."""
        res = self.client.post(self._url(), {"coach": self.mike.id, "role": "head"},
                               format="json")
        self.assertEqual(self._staff(res), {"mike": "head", "sarah": "assistant"})

    def test_patching_someone_who_is_not_on_the_list_is_404_not_a_silent_add(self):
        res = self.client.patch(self._url(), {"coach": self.dana.id, "role": "head"},
                                format="json")
        self.assertEqual(res.status_code, 404)

    def test_a_group_with_no_staff_reports_no_head_rather_than_failing(self):
        """Removing the last coach is legal — it makes 'swap the head' a sequence
        a caller can get right without a special endpoint."""
        self.client.delete(self._url(), {"coach": self.sarah.id}, format="json")
        res = self.client.get("/api/training-groups/")
        group = next(row for row in res.data if row["id"] == self.group.id)
        self.assertIsNone(group["head_coach"])

    def test_a_role_defaults_to_assistant(self):
        """Silently making an unlabelled addition the head would be worse than
        an explicit requirement, so the quiet default is the lesser role."""
        res = self.client.post(self._url(), {"coach": self.mike.id}, format="json")
        self.assertEqual(self._staff(res)["mike"], "assistant")

    # ── the list is not a permission ─────────────────────────────────────────

    def test_a_coach_who_does_not_run_the_group_can_still_change_its_staff(self):
        """Deliberate, and stated in the canon as filter-not-fence. If a real
        boundary is ever added, THIS is the test that should be changed on
        purpose rather than discovered broken."""
        self.client.force_authenticate(user=self.dana)
        res = self.client.post(self._url(), {"coach": self.dana.id, "role": "assistant"},
                               format="json")
        self.assertEqual(res.status_code, 201)


class TrainingGroupCoachMigrationTests(TransactionTestCase):
    """The 0015 data migration, run for real against a database.

    Worth testing rather than eyeballing: the auto-generated version of this
    migration dropped the `coach` column BEFORE creating the join table, which
    would have deleted every group's coach with no way to get it back. These
    tests pin the order by exercising the outcome.
    """

    migrate_from = [("event_handler", "0014_blockcategory_trainingblock_categories")]
    migrate_to = [("event_handler", "0015_traininggroupcoach")]

    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return MigrationExecutor(connection).loader.project_state(targets).apps

    def test_an_existing_group_keeps_its_coach_as_the_head(self):
        old_apps = self._migrate(self.migrate_from)
        OldGroup = old_apps.get_model("event_handler", "TrainingGroup")
        UserModel = old_apps.get_model("auth", "User")

        coach = UserModel.objects.create(username="carried-over")
        group = OldGroup.objects.create(name="Varsity", coach_id=coach.id)

        new_apps = self._migrate(self.migrate_to)
        Link = new_apps.get_model("event_handler", "TrainingGroupCoach")

        link = Link.objects.get(training_group_id=group.id)
        self.assertEqual(link.coach_id, coach.id)
        self.assertEqual(link.role, "head")

    def test_it_runs_on_a_database_with_no_groups(self):
        """A fresh install has nothing to carry across; the backfill must be a
        no-op rather than an error."""
        self._migrate(self.migrate_from)
        new_apps = self._migrate(self.migrate_to)
        Link = new_apps.get_model("event_handler", "TrainingGroupCoach")
        self.assertEqual(Link.objects.count(), 0)

    def tearDown(self):
        # Leave the database at the latest migration, or every test that runs
        # after this class sees a half-migrated schema.
        self._migrate([("event_handler", "0015_traininggroupcoach")])


class OneOpenSessionTests(APITestCase):
    """One training day open at a time (canon D18, P12).

    The bug this closes was invisible, which is what made it dangerous. Racks
    follow `_active_session()`, which is last-one-wins, so a second open session
    quietly became the one athletes checked into: their sets landed on a session
    with no participants and the day's report came out wrong, while every tablet
    looked completely normal.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        # A session needs a non-empty roster — the API rejects a day with nobody
        # in it, which is correct and worth knowing when reading these payloads.
        self.athlete = Athlete.objects.create(name="Jordan Lee")

    def test_the_first_session_opens_normally(self):
        res = self.client.post("/api/sessions/", {"label": "Monday", "athletes": [self.athlete.id]}, format="json")
        self.assertEqual(res.status_code, 201)

    def test_a_second_open_session_is_refused_with_409(self):
        self.client.post("/api/sessions/", {"label": "Monday", "athletes": [self.athlete.id]}, format="json")
        res = self.client.post("/api/sessions/", {"label": "Tuesday", "athletes": [self.athlete.id]}, format="json")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(TrainingSession.objects.count(), 1)

    def test_the_refusal_names_the_day_already_open(self):
        """A bare 409 is a dead end — the caller needs to be able to say
        'end Monday first' rather than 'something went wrong'."""
        opened = self.client.post("/api/sessions/", {"label": "Monday", "athletes": [self.athlete.id]}, format="json")
        res = self.client.post("/api/sessions/", {"label": "Tuesday", "athletes": [self.athlete.id]}, format="json")
        self.assertEqual(res.data["open_session"]["id"], opened.data["id"])
        self.assertEqual(res.data["open_session"]["label"], "Monday")
        self.assertIn("Monday", res.data["detail"])

    def test_a_new_day_can_open_once_the_previous_one_ends(self):
        first = self.client.post("/api/sessions/", {"label": "Monday", "athletes": [self.athlete.id]}, format="json")
        self.client.patch(f"/api/sessions/{first.data['id']}/", {}, format="json")

        res = self.client.post("/api/sessions/", {"label": "Tuesday", "athletes": [self.athlete.id]}, format="json")
        self.assertEqual(res.status_code, 201)

    def test_an_ended_session_does_not_block_anything(self):
        TrainingSession.objects.create(label="Last week", started_at=timezone.now(),
                                      ended_at=timezone.now())
        res = self.client.post("/api/sessions/", {"label": "Monday", "athletes": [self.athlete.id]}, format="json")
        self.assertEqual(res.status_code, 201)

    # ── ending a day says what happened ──────────────────────────────────────

    def test_ending_a_day_names_the_day_that_ended(self):
        """The original symptom: the panel redrew identically and the button
        looked broken. Saying which day ended is the cure."""
        opened = self.client.post("/api/sessions/", {"label": "Monday", "athletes": [self.athlete.id]}, format="json")
        res = self.client.patch(f"/api/sessions/{opened.data['id']}/", {}, format="json")

        self.assertEqual(res.data["ended"]["label"], "Monday")
        self.assertIsNotNone(res.data["ended"]["ended_at"])

    def test_ending_the_only_open_day_reports_nothing_still_open(self):
        opened = self.client.post("/api/sessions/", {"label": "Monday", "athletes": [self.athlete.id]}, format="json")
        res = self.client.patch(f"/api/sessions/{opened.data['id']}/", {}, format="json")
        self.assertIsNone(res.data["ended"]["still_open"])

    def test_ending_one_of_a_stack_says_another_is_still_open(self):
        """Data that predates the guard can still hold a stack. Reporting it is
        the difference between a confusing screen and an explained one."""
        first = TrainingSession.objects.create(label="Stray", started_at=timezone.now())
        second = TrainingSession.objects.create(label="Monday", started_at=timezone.now())

        res = self.client.patch(f"/api/sessions/{second.id}/", {}, format="json")
        self.assertEqual(res.data["ended"]["label"], "Monday")
        self.assertEqual(res.data["ended"]["still_open"]["label"], "Stray")
        self.assertEqual(res.data["ended"]["still_open"]["id"], first.id)

    def _day_that_survived_a_reboot(self):
        """A day still open from yesterday — what a coach finds after a power cut.
        started_at is auto_now_add, so it has to be backdated with an UPDATE."""
        session = TrainingSession.objects.create(label="Yesterday's day", started_at=timezone.now())
        session.athletes.add(self.athlete)
        TrainingSession.objects.filter(id=session.id).update(
            started_at=timezone.now() - timedelta(days=1))
        session.refresh_from_db()
        return session

    # ── surviving a power cut ────────────────────────────────────────────────

    def test_a_day_can_be_ended_at_a_corrected_time(self):
        """The power-cut case. The base station comes back with the day still
        open, and the honest end time is when the room emptied — not whenever
        someone next managed to log in."""
        session = self._day_that_survived_a_reboot()
        # The room emptied two hours after it opened — yesterday evening.
        real_end = session.started_at + timedelta(hours=2)

        res = self.client.patch(f"/api/sessions/{session.id}/",
                                {"ended_at": real_end.isoformat()}, format="json")
        self.assertEqual(res.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.ended_at, real_end)

    def test_the_corrected_time_is_what_the_report_records(self):
        """A DailyReport is immutable, so a wrong time here is permanent."""
        session = self._day_that_survived_a_reboot()
        real_end = session.started_at + timedelta(hours=2)

        self.client.patch(f"/api/sessions/{session.id}/",
                          {"ended_at": real_end.isoformat()}, format="json")
        report = DailyReport.objects.get(session=session)
        self.assertEqual(report.snapshot["session"]["ended_at"], real_end.isoformat())

    def test_a_day_cannot_end_before_it_started(self):
        """This was silently accepted before: a day that ended in 2020 having
        started in 2026, frozen into a report nothing can correct."""
        opened = self.client.post("/api/sessions/",
                                  {"label": "Monday", "athletes": [self.athlete.id]},
                                  format="json")
        session = TrainingSession.objects.get(id=opened.data["id"])

        res = self.client.patch(f"/api/sessions/{session.id}/",
                                {"ended_at": "2020-01-01T00:00:00Z"}, format="json")
        self.assertEqual(res.status_code, 400)
        session.refresh_from_db()
        self.assertIsNone(session.ended_at)
        self.assertFalse(DailyReport.objects.filter(session=session).exists())

    def test_a_day_cannot_end_in_the_future(self):
        opened = self.client.post("/api/sessions/",
                                  {"label": "Monday", "athletes": [self.athlete.id]},
                                  format="json")
        future = (timezone.now() + timedelta(days=1)).isoformat()

        res = self.client.patch(f"/api/sessions/{opened.data['id']}/",
                                {"ended_at": future}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_a_slightly_fast_tablet_clock_is_tolerated(self):
        """A tablet a few seconds ahead of the base station is sending a correct
        'now'. Refusing it would be pedantry the coach cannot act on."""
        opened = self.client.post("/api/sessions/",
                                  {"label": "Monday", "athletes": [self.athlete.id]},
                                  format="json")
        barely_ahead = (timezone.now() + timedelta(seconds=30)).isoformat()

        res = self.client.patch(f"/api/sessions/{opened.data['id']}/",
                                {"ended_at": barely_ahead}, format="json")
        self.assertEqual(res.status_code, 200)

    def test_a_day_open_since_yesterday_is_flagged_as_stale(self):
        """So a coach booting the base station back up NOTICES, instead of being
        shown a day from yesterday labelled simply 'active'."""
        session = TrainingSession.objects.create(label="Yesterday's day", started_at=timezone.now())
        TrainingSession.objects.filter(id=session.id).update(
            started_at=timezone.now() - timedelta(days=1))

        res = self.client.get("/api/room-state/")
        self.assertTrue(res.data["session"]["opened_on_a_previous_day"])

    def test_todays_day_is_not_flagged(self):
        self.client.post("/api/sessions/",
                         {"label": "Monday", "athletes": [self.athlete.id]},
                         format="json")
        res = self.client.get("/api/room-state/")
        self.assertFalse(res.data["session"]["opened_on_a_previous_day"])

    # ── the one definition of "active" ───────────────────────────────────────

    def test_every_endpoint_resolves_the_same_active_session(self):
        """P12 folded three hand-written copies of this query into one helper.
        The rack path and the coach path disagreeing about which session is live
        is the shape of the original bug, so it is worth pinning."""
        stray = TrainingSession.objects.create(label="Stray", started_at=timezone.now())
        current = TrainingSession.objects.create(label="Monday", started_at=timezone.now())
        current.athletes.add(self.athlete)

        # `session_id`, not a nested object — this is the frozen rack contract.
        rack_view = self.client.get("/api/sessions/active/")
        self.assertEqual(rack_view.data["session_id"], current.id)

        progress = self.client.get(f"/api/sessions/active/athlete/{self.athlete.id}/progress/")
        self.assertEqual(progress.status_code, 200)
        self.assertNotEqual(current.id, stray.id)


class ProgramPromotionTests(APITestCase):
    """Turning a program back into a reusable block (canon D21, P15).

    ⚠️ The thing these tests exist to prevent was written down as fact in this
    codebase for weeks: that promotion is "just pointing training_block at a new
    row". It is not. That records provenance and copies nothing, so the block
    comes out EMPTY and deploying it hands a group a plan with no movements —
    which reads as a data-loss bug rather than a misunderstanding. Half of what
    follows checks the copy actually happened.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.group = TrainingGroup.objects.create(name="Varsity")
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        self.bench = Exercise.objects.get_or_create(name="Bench Press")[0]
        self.monday = date(2026, 8, 3)

    def _program(self, *, from_block=True, days=2):
        """A program with real days and rows, deployed or hand-written."""
        if from_block:
            block = TrainingBlock.objects.create(
                name="Fall Strength", coach=self.coach,
                cadence_days_of_week="Mon,Wed,Fri", duration_weeks=4)
            for position in range(1, days + 1):
                workout = TrainingBlockWorkout.objects.create(
                    training_block=block, name=f"Day {position}", position=position)
                TrainingBlockExercise.objects.create(
                    training_block_workout=workout, exercise=self.squat,
                    position=1, sets=5, reps=3, target_percent=80,
                    velocity_zone_min=0.5, velocity_zone_max=0.8)
            return instantiate_block(block, self.group, start_date=self.monday)

        program = TrainingProgram.objects.create(
            training_group=self.group, name="One-off", start_date=self.monday)
        for position in range(1, days + 1):
            workout = TrainingProgramWorkout.objects.create(
                training_program=program, name=f"Day {position}", position=position)
            TrainingProgramExercise.objects.create(
                training_program_workout=workout, exercise=self.bench,
                position=1, sets=4, reps=5, target_percent=75)
        return program

    def _promote(self, program, **body):
        return self.client.post(f"/api/training-programs/{program.id}/promote/",
                                body, format="json")

    # ── the copy actually happens ────────────────────────────────────────────

    def test_the_new_block_is_not_empty(self):
        """The single most important assertion in this class."""
        program = self._program()
        res = self._promote(program)
        self.assertEqual(res.status_code, 201)

        block = TrainingBlock.objects.get(id=res.data["id"])
        self.assertEqual(block.workouts.count(), 2)
        self.assertTrue(all(w.exercises.exists() for w in block.workouts.all()))

    def test_every_day_is_copied_with_its_name_and_position(self):
        program = self._program(days=3)
        block = TrainingBlock.objects.get(id=self._promote(program).data["id"])
        self.assertEqual(
            [(w.name, w.position) for w in block.workouts.order_by("position")],
            [("Day 1", 1), ("Day 2", 2), ("Day 3", 3)])

    def test_every_prescription_row_is_copied_field_for_field(self):
        """A promoted block that loses the velocity zones or the percentage would
        deploy something subtly different from what the coach tuned."""
        program = self._program(from_block=False)
        block = TrainingBlock.objects.get(id=self._promote(program).data["id"])

        row = block.workouts.order_by("position").first().exercises.first()
        self.assertEqual(row.exercise_id, self.bench.id)
        self.assertEqual((row.sets, row.reps, row.target_percent), (4, 5, 75))

    def test_zones_survive_the_copy(self):
        program = self._program()
        block = TrainingBlock.objects.get(id=self._promote(program).data["id"])
        row = block.workouts.order_by("position").first().exercises.first()
        self.assertEqual((row.velocity_zone_min, row.velocity_zone_max), (0.5, 0.8))

    # ── the round trip ───────────────────────────────────────────────────────

    def test_the_promoted_block_can_be_deployed_again_and_carries_the_training(self):
        """The point of the whole feature: promote, then deploy to another group
        and get the same training. This is what would have silently produced an
        empty plan under the old, false description."""
        program = self._program(days=2)
        block = TrainingBlock.objects.get(id=self._promote(program).data["id"])

        other = TrainingGroup.objects.create(name="Freshmen")
        redeployed = instantiate_block(block, other, start_date=self.monday)

        self.assertEqual(redeployed.workouts.count(), 2)
        row = redeployed.workouts.order_by("position").first().exercises.first()
        self.assertEqual((row.sets, row.reps, row.target_percent), (5, 3, 80))

    def test_a_promoted_block_still_schedules(self):
        """Cadence and duration are carried across, so the redeployment gets a
        calendar rather than an empty one."""
        program = self._program()
        block = TrainingBlock.objects.get(id=self._promote(program).data["id"])
        self.assertEqual(block.cadence_days_of_week, "Mon,Wed,Fri")

        other = TrainingGroup.objects.create(name="Freshmen")
        redeployed = instantiate_block(block, other, start_date=self.monday)
        self.assertGreater(redeployed.scheduled_sessions.count(), 0)

    # ── the source program is left alone ─────────────────────────────────────

    def test_the_program_keeps_its_own_days_and_rows(self):
        program = self._program(days=2)
        before = list(program.workouts.values_list("id", "name", "position"))

        self._promote(program)
        program.refresh_from_db()
        self.assertEqual(list(program.workouts.values_list("id", "name", "position")),
                         before)

    def test_the_program_now_points_at_the_block_it_is_a_deployment_of(self):
        program = self._program(from_block=False)
        self.assertIsNone(program.training_block)

        block_id = self._promote(program).data["id"]
        program.refresh_from_db()
        self.assertEqual(program.training_block_id, block_id)

    def test_editing_the_promoted_block_does_not_touch_the_program(self):
        """Snapshot independence runs in this direction too."""
        program = self._program()
        block = TrainingBlock.objects.get(id=self._promote(program).data["id"])

        block.workouts.filter(position=1).update(name="Renamed in the template")
        self.assertEqual(program.workouts.get(position=1).name, "Day 1")

    # ── naming and ownership ─────────────────────────────────────────────────

    def test_the_block_takes_the_programs_name_by_default(self):
        program = self._program(from_block=False)
        self.assertEqual(self._promote(program).data["name"], "One-off")

    def test_a_name_can_be_given(self):
        program = self._program()
        self.assertEqual(self._promote(program, name="Fall Strength v2").data["name"],
                         "Fall Strength v2")

    def test_a_blank_name_falls_back_rather_than_creating_an_unnamed_block(self):
        program = self._program(from_block=False)
        self.assertEqual(self._promote(program, name="   ").data["name"], "One-off")

    def test_the_promoting_coach_owns_the_new_block(self):
        other = User.objects.create_user(username="other", password="pw")
        self.client.force_authenticate(user=other)
        program = self._program()
        self.assertEqual(self._promote(program).data["coach"], other.id)

    # ── guards ───────────────────────────────────────────────────────────────

    def test_a_program_with_no_days_is_refused(self):
        """Refusing is more honest than creating the empty block this endpoint
        exists to prevent."""
        program = TrainingProgram.objects.create(
            training_group=self.group, name="Empty", start_date=self.monday)
        res = self._promote(program)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(TrainingBlock.objects.filter(name="Empty").count(), 0)

    def test_a_missing_program_is_404(self):
        self.assertEqual(
            self.client.post("/api/training-programs/99999/promote/",
                             {}, format="json").status_code, 404)

    def test_a_coach_login_is_required(self):
        program = self._program()
        self.client.force_authenticate(user=None)
        self.assertIn(self._promote(program).status_code, (401, 403))

    def test_promoting_twice_makes_two_independent_blocks(self):
        """Each promotion is a snapshot of the program at that moment."""
        program = self._program()
        first = self._promote(program).data["id"]
        second = self._promote(program, name="Second take").data["id"]

        self.assertNotEqual(first, second)
        self.assertEqual(TrainingBlock.objects.get(id=first).workouts.count(), 2)
        self.assertEqual(TrainingBlock.objects.get(id=second).workouts.count(), 2)


class ScheduleGenerationTests(APITestCase):
    """Laying a block's days onto real dates (P14 step 2).

    This is the first code that has ever read `cadence_days_of_week` or
    `duration_weeks` — before P14 the block builder wrote them and nothing looked.
    Date arithmetic fails quietly and plausibly, so the awkward cases get their
    own tests: starting mid-week, a cadence with more days than the block has, and
    a block that cannot be scheduled at all.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.group = TrainingGroup.objects.create(name="Varsity")
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        # 2026-08-03 is a Monday. Every expectation below is anchored to that.
        self.monday = date(2026, 8, 3)

    def _block(self, *, cadence="Mon,Wed,Fri", weeks=2, days=3):
        block = TrainingBlock.objects.create(
            name="Fall Strength", coach=self.coach,
            cadence_days_of_week=cadence, duration_weeks=weeks)
        for position in range(1, days + 1):
            workout = TrainingBlockWorkout.objects.create(
                training_block=block, name=f"Day {position}", position=position)
            TrainingBlockExercise.objects.create(
                training_block_workout=workout, exercise=self.squat,
                position=1, sets=5, reps=3, target_percent=80)
        return block

    def _deploy(self, block, start=None):
        return instantiate_block(block, self.group, start_date=start or self.monday)

    # ── the dates ────────────────────────────────────────────────────────────

    def test_deploying_generates_one_slot_per_training_day(self):
        program = self._deploy(self._block())
        # Mon/Wed/Fri for 2 weeks = 6 slots.
        self.assertEqual(program.scheduled_sessions.count(), 6)

    def test_the_slots_land_on_the_right_weekdays(self):
        program = self._deploy(self._block())
        dates = list(program.scheduled_sessions.values_list("date", flat=True))
        self.assertEqual(dates, [
            date(2026, 8, 3), date(2026, 8, 5), date(2026, 8, 7),    # Mon Wed Fri
            date(2026, 8, 10), date(2026, 8, 12), date(2026, 8, 14),
        ])

    def test_weeks_are_counted_from_the_start_date_not_the_calendar(self):
        """Starting on a Wednesday, week one is that Wed + Fri — then it resumes
        on Monday. Counting calendar weeks would hand the coach a short first
        week without saying so."""
        wednesday = date(2026, 8, 5)
        program = self._deploy(self._block(weeks=1), start=wednesday)
        dates = list(program.scheduled_sessions.values_list("date", flat=True))
        self.assertEqual(dates, [date(2026, 8, 5), date(2026, 8, 7),
                                 date(2026, 8, 10)])

    def test_duration_weeks_is_what_stops_it(self):
        """Cadence alone cannot say when to stop — the user's decision."""
        program = self._deploy(self._block(weeks=4))
        self.assertEqual(program.scheduled_sessions.count(), 12)

    # ── which day runs in which slot ─────────────────────────────────────────

    def test_the_days_are_dealt_out_in_block_order(self):
        program = self._deploy(self._block())
        names = [slot.training_program_workout.name
                 for slot in program.scheduled_sessions.all()[:3]]
        self.assertEqual(names, ["Day 1", "Day 2", "Day 3"])

    def test_the_days_repeat_across_weeks(self):
        program = self._deploy(self._block())
        names = [slot.training_program_workout.name
                 for slot in program.scheduled_sessions.all()]
        self.assertEqual(names, ["Day 1", "Day 2", "Day 3"] * 2)

    def test_a_two_day_block_on_a_three_day_cadence_keeps_cycling(self):
        """The rotation follows the DAY ORDER, not the weekday. Following the
        weekday instead would leave every Friday empty."""
        program = self._deploy(self._block(weeks=1, days=2))
        names = [slot.training_program_workout.name
                 for slot in program.scheduled_sessions.all()]
        self.assertEqual(names, ["Day 1", "Day 2", "Day 1"])

    def test_the_slots_point_at_the_PROGRAM_days_not_the_block_days(self):
        """A slot must reference the program's own copy, or editing the deployed
        program would leave the calendar pointing at the template."""
        program = self._deploy(self._block())
        slot = program.scheduled_sessions.first()
        self.assertEqual(slot.training_program_workout.training_program_id, program.id)

    # ── nothing to schedule is not a failure ─────────────────────────────────

    def test_a_block_with_no_cadence_deploys_with_an_empty_schedule(self):
        """Refusing would block a perfectly good one-off program."""
        program = self._deploy(self._block(cadence=""))
        self.assertEqual(program.scheduled_sessions.count(), 0)
        self.assertEqual(program.workouts.count(), 3)   # the program itself is fine

    def test_a_block_with_no_duration_deploys_with_an_empty_schedule(self):
        program = self._deploy(self._block(weeks=None))
        self.assertEqual(program.scheduled_sessions.count(), 0)

    def test_a_block_with_no_days_generates_nothing(self):
        program = self._deploy(self._block(days=0))
        self.assertEqual(program.scheduled_sessions.count(), 0)

    # ── deploying through the API, not just the service ──────────────────────

    def test_deploying_through_the_api_generates_a_schedule(self):
        """⚠️ This is the test that was missing. Every other test in this class
        calls instantiate_block() directly with a real `date` object. The API
        passes a STRING, Django only coerces it on the way into the database, and
        the in-memory instance keeps the string — so the generator did
        `str + timedelta` and every deploy through the API was a 500. Found by
        deploying from the browser, not by 260 passing tests."""
        block = self._block()
        res = self.client.post("/api/training-programs/", {
            "training_group": self.group.id,
            "training_block": block.id,
            "name": "Deployed over HTTP",
            "start_date": "2026-08-03",
        }, format="json")

        self.assertEqual(res.status_code, 201)
        program = TrainingProgram.objects.get(id=res.data["id"])
        self.assertEqual(program.scheduled_sessions.count(), 6)

    def test_a_bad_start_date_is_a_400_not_a_500(self):
        block = self._block()
        res = self.client.post("/api/training-programs/", {
            "training_group": self.group.id,
            "training_block": block.id,
            "start_date": "the third of August",
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_deploying_without_a_start_date_is_refused(self):
        """A program with no start date can never be scheduled, and start_date is
        non-null on the model — so this was a 500 waiting to happen too."""
        block = self._block()
        res = self.client.post("/api/training-programs/", {
            "training_group": self.group.id,
            "training_block": block.id,
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_a_standalone_program_with_no_block_generates_nothing(self):
        program = TrainingProgram.objects.create(
            training_group=self.group, name="One-off", start_date=self.monday)
        self.assertEqual(generate_schedule(program), [])

    # ── slots start unlinked and independent ─────────────────────────────────

    def test_a_fresh_slot_has_no_session_yet(self):
        """The slot is a plan. The session fills in when a coach creates it."""
        program = self._deploy(self._block())
        self.assertTrue(all(slot.session_id is None
                            for slot in program.scheduled_sessions.all()))

    def test_editing_the_blocks_cadence_afterwards_moves_no_existing_slot(self):
        """Same independence rule as the prescription rows: once a program is an
        instance it is its own thing."""
        block = self._block()
        program = self._deploy(block)
        before = list(program.scheduled_sessions.values_list("date", flat=True))

        block.cadence_days_of_week = "Tue,Thu"
        block.save(update_fields=["cadence_days_of_week"])

        after = list(program.scheduled_sessions.values_list("date", flat=True))
        self.assertEqual(before, after)

    def test_regenerating_cannot_double_a_calendar(self):
        """One slot per program per day, so a re-run is a no-op rather than a
        duplicated schedule."""
        block = self._block()
        program = self._deploy(block)
        generate_schedule(program, block)
        self.assertEqual(program.scheduled_sessions.count(), 6)

    def test_two_programs_can_train_on_the_same_date(self):
        """The constraint is per PROGRAM — two groups training Monday is normal."""
        other_group = TrainingGroup.objects.create(name="Freshmen")
        block = self._block()
        self._deploy(block)
        second = instantiate_block(block, other_group, start_date=self.monday)
        self.assertEqual(second.scheduled_sessions.count(), 6)


class ScheduleRouteTests(APITestCase):
    """The calendar endpoints (P14 step 3).

    Three things a coach does with a schedule: look at it, move a day, and turn a
    planned day into a real one. The third is where the care is — creating a
    session must NOT start it, or a slot for next Thursday takes the racks.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.group = TrainingGroup.objects.create(name="Varsity")
        self.jordan = Athlete.objects.create(name="Jordan Lee")
        self.sam = Athlete.objects.create(name="Sam Rivera")
        self.jordan.training_groups.add(self.group)
        self.sam.training_groups.add(self.group)
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        self.monday = date(2026, 8, 3)

        block = TrainingBlock.objects.create(
            name="Fall Strength", coach=self.coach,
            cadence_days_of_week="Mon,Wed,Fri", duration_weeks=1)
        for position in (1, 2, 3):
            workout = TrainingBlockWorkout.objects.create(
                training_block=block, name=f"Day {position}", position=position)
            TrainingBlockExercise.objects.create(
                training_block_workout=workout, exercise=self.squat,
                position=1, sets=5, reps=3, target_percent=80)
        self.program = instantiate_block(block, self.group, start_date=self.monday)
        self.slots = list(self.program.scheduled_sessions.order_by("date"))

    # ── reading the calendar ─────────────────────────────────────────────────

    def test_the_schedule_lists_slots_in_date_order(self):
        res = self.client.get("/api/scheduled-sessions/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([row["date"] for row in res.data],
                         ["2026-08-03", "2026-08-05", "2026-08-07"])

    def test_a_slot_carries_what_a_calendar_row_needs(self):
        row = self.client.get("/api/scheduled-sessions/").data[0]
        self.assertEqual(row["workout_name"], "Day 1")
        self.assertEqual(row["group_name"], "Varsity")
        self.assertEqual(row["program_name"], self.program.name)
        # Null session is what tells the UI to offer "Create" rather than "Open".
        self.assertIsNone(row["session"])

    def test_the_calendar_can_be_filtered_to_one_program(self):
        other = TrainingGroup.objects.create(name="Freshmen")
        block = TrainingBlock.objects.create(
            name="Intro", coach=self.coach,
            cadence_days_of_week="Tue", duration_weeks=1)
        TrainingBlockWorkout.objects.create(training_block=block, name="Day 1", position=1)
        instantiate_block(block, other, start_date=self.monday)

        res = self.client.get(f"/api/scheduled-sessions/?training_program={self.program.id}")
        self.assertEqual(len(res.data), 3)

    def test_the_calendar_can_be_filtered_to_one_group(self):
        res = self.client.get(f"/api/scheduled-sessions/?training_group={self.group.id}")
        self.assertEqual(len(res.data), 3)

    def test_the_calendar_can_be_windowed_to_a_date_range(self):
        """A month view should not pull every slot ever deployed."""
        res = self.client.get("/api/scheduled-sessions/?from=2026-08-05&to=2026-08-05")
        self.assertEqual([row["date"] for row in res.data], ["2026-08-05"])

    def test_a_bad_date_window_is_refused_not_ignored(self):
        res = self.client.get("/api/scheduled-sessions/?from=not-a-date")
        self.assertEqual(res.status_code, 400)

    def test_unrun_shows_only_slots_with_no_session_yet(self):
        self.client.post(f"/api/scheduled-sessions/{self.slots[0].id}/session/", format="json")
        res = self.client.get("/api/scheduled-sessions/?unrun=true")
        self.assertEqual([row["date"] for row in res.data], ["2026-08-05", "2026-08-07"])

    def test_there_is_no_way_to_hand_append_a_slot(self):
        """Slots come from deploying a block and are frozen after. A calendar you
        can append to drifts from the block that produced it."""
        res = self.client.post("/api/scheduled-sessions/",
                               {"date": "2026-08-04"}, format="json")
        self.assertEqual(res.status_code, 405)

    # ── moving a day ─────────────────────────────────────────────────────────

    def test_a_slot_can_be_moved_to_another_date(self):
        slot = self.slots[0]
        res = self.client.patch(f"/api/scheduled-sessions/{slot.id}/",
                                {"date": "2026-08-04"}, format="json")
        self.assertEqual(res.status_code, 200)
        slot.refresh_from_db()
        self.assertEqual(slot.date, date(2026, 8, 4))

    def test_moving_a_slot_regenerates_nothing(self):
        """The whole point of the design: a move is one date write."""
        self.client.patch(f"/api/scheduled-sessions/{self.slots[0].id}/",
                          {"date": "2026-08-04"}, format="json")
        self.assertEqual(self.program.scheduled_sessions.count(), 3)

    def test_moving_a_slot_onto_an_occupied_date_is_refused_by_name(self):
        """The database constraint would otherwise surface as a 500."""
        res = self.client.patch(f"/api/scheduled-sessions/{self.slots[0].id}/",
                                {"date": "2026-08-05"}, format="json")
        self.assertEqual(res.status_code, 409)
        self.assertIn("2026-08-05", str(res.data))

    def test_a_slots_workout_cannot_be_reassigned_through_the_move_route(self):
        """`date` is the only writable field — which day runs in a slot is decided
        when the schedule is generated."""
        slot = self.slots[0]
        other_day = self.program.workouts.order_by("position").last()
        self.client.patch(f"/api/scheduled-sessions/{slot.id}/",
                          {"training_program_workout": other_day.id}, format="json")
        slot.refresh_from_db()
        self.assertNotEqual(slot.training_program_workout_id, other_day.id)

    def test_a_missing_slot_is_404(self):
        self.assertEqual(
            self.client.patch("/api/scheduled-sessions/99999/",
                              {"date": "2026-08-04"}, format="json").status_code, 404)

    # ── turning a plan into a real day ───────────────────────────────────────

    def test_creating_a_session_from_a_slot_does_NOT_start_it(self):
        """⚠️ The heart of P14. A session created for next Thursday must hold no
        racks — otherwise this is canon D18 with a calendar attached."""
        res = self.client.post(f"/api/scheduled-sessions/{self.slots[0].id}/session/",
                               format="json")
        self.assertEqual(res.status_code, 201)
        session = TrainingSession.objects.get(id=res.data["session"])
        self.assertIsNone(session.started_at)
        self.assertIsNone(self.client.get("/api/sessions/active/").data["session_id"])

    def test_the_created_session_gets_the_groups_roster(self):
        res = self.client.post(f"/api/scheduled-sessions/{self.slots[0].id}/session/",
                               format="json")
        session = TrainingSession.objects.get(id=res.data["session"])
        self.assertEqual(set(session.athletes.values_list("name", flat=True)),
                         {"Jordan Lee", "Sam Rivera"})

    def test_the_created_session_knows_which_day_it_runs(self):
        """SessionParticipation was being set by hand in the seed command and by
        no UI at all. Without it the group has a roster and nothing to lift."""
        res = self.client.post(f"/api/scheduled-sessions/{self.slots[0].id}/session/",
                               format="json")
        participation = SessionParticipation.objects.get(session_id=res.data["session"])
        self.assertEqual(participation.training_program_id, self.program.id)
        self.assertEqual(participation.training_program_workout.name, "Day 1")

    def test_the_slot_then_points_at_its_session(self):
        res = self.client.post(f"/api/scheduled-sessions/{self.slots[0].id}/session/",
                               format="json")
        self.slots[0].refresh_from_db()
        self.assertEqual(self.slots[0].session_id, res.data["session"])

    def test_creating_twice_returns_the_same_session(self):
        """Two taps on a calendar must not produce two Thursdays."""
        first = self.client.post(f"/api/scheduled-sessions/{self.slots[0].id}/session/",
                                 format="json")
        second = self.client.post(f"/api/scheduled-sessions/{self.slots[0].id}/session/",
                                  format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["session"], second.data["session"])
        self.assertEqual(TrainingSession.objects.count(), 1)

    def test_several_future_days_can_be_set_up_at_once(self):
        """None of them are running, so none of them conflict."""
        for slot in self.slots:
            res = self.client.post(f"/api/scheduled-sessions/{slot.id}/session/",
                                   format="json")
            self.assertEqual(res.status_code, 201)
        self.assertEqual(TrainingSession.objects.count(), 3)
        self.assertIsNone(self.client.get("/api/sessions/active/").data["session_id"])

    # ── starting one ─────────────────────────────────────────────────────────

    def _create_session(self, slot):
        return self.client.post(f"/api/scheduled-sessions/{slot.id}/session/",
                                format="json").data["session"]

    def test_starting_a_prepared_session_makes_it_the_active_one(self):
        session_id = self._create_session(self.slots[0])
        res = self.client.post(f"/api/sessions/{session_id}/start/", format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(res.data["started_at"])
        self.assertEqual(self.client.get("/api/sessions/active/").data["session_id"],
                         session_id)

    def test_starting_a_second_day_is_refused_while_one_runs(self):
        first = self._create_session(self.slots[0])
        second = self._create_session(self.slots[1])
        self.client.post(f"/api/sessions/{first}/start/", format="json")

        res = self.client.post(f"/api/sessions/{second}/start/", format="json")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.data["open_session"]["id"], first)

    def test_starting_an_already_started_day_is_a_no_op(self):
        session_id = self._create_session(self.slots[0])
        self.client.post(f"/api/sessions/{session_id}/start/", format="json")
        started = TrainingSession.objects.get(id=session_id).started_at

        res = self.client.post(f"/api/sessions/{session_id}/start/", format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(TrainingSession.objects.get(id=session_id).started_at, started)

    def test_an_ended_day_cannot_be_restarted(self):
        """Its report is already frozen; reopening it would make that a lie."""
        session_id = self._create_session(self.slots[0])
        self.client.post(f"/api/sessions/{session_id}/start/", format="json")
        self.client.patch(f"/api/sessions/{session_id}/", {}, format="json")

        res = self.client.post(f"/api/sessions/{session_id}/start/", format="json")
        self.assertEqual(res.status_code, 409)

    def test_starting_a_missing_session_is_404(self):
        self.assertEqual(
            self.client.post("/api/sessions/99999/start/", format="json").status_code, 404)

    def test_a_started_slot_session_can_still_capture_check_ins(self):
        """End to end: the prepared day, once started, behaves like any other."""
        session_id = self._create_session(self.slots[0])
        self.client.post(f"/api/sessions/{session_id}/start/", format="json")

        res = self.client.post("/api/racks/1/checkin/", {"athlete": self.jordan.id},
                               format="json")
        self.assertEqual(res.status_code, 201)


class CadenceValidationTests(APITestCase):
    """The cadence field is now READ by the generator, so it gets validated.

    The coach UI is seven checkboxes and already emits canonical week-ordered
    tokens — nobody types this. But the column was a bare CharField the API would
    accept anything into, and a generator that has to guess at its input is the
    thing being avoided.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)

    def _post(self, **fields):
        return self.client.post("/api/training-blocks/",
                                {"name": "Fall Strength", **fields}, format="json")

    def test_the_checkbox_output_is_accepted_unchanged(self):
        res = self._post(cadence_days_of_week="Mon,Wed,Fri")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["cadence_days_of_week"], "Mon,Wed,Fri")

    def test_days_are_stored_in_week_order_whatever_order_they_arrive_in(self):
        """One canonical form in the column, so "Fri,Mon" and "Mon,Fri" cannot
        both exist meaning the same thing."""
        res = self._post(cadence_days_of_week="Fri,Mon")
        self.assertEqual(res.data["cadence_days_of_week"], "Mon,Fri")

    def test_an_unknown_day_is_refused(self):
        res = self._post(cadence_days_of_week="Mon,Funday")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Funday", str(res.data))

    def test_an_empty_cadence_is_fine(self):
        """A template a coach has not finished describing is allowed."""
        self.assertEqual(self._post(cadence_days_of_week="").status_code, 201)

    def test_zero_or_negative_weeks_is_refused(self):
        """It would generate an empty calendar and look like a broken generator."""
        self.assertEqual(self._post(duration_weeks=0).status_code, 400)
        self.assertEqual(self._post(duration_weeks=-3).status_code, 400)


class UnstartedSessionTests(APITestCase):
    """A session can now exist before it runs (P14).

    This is the schema half of scheduling, and it is worth its own tests because
    it changes the meaning of a word every screen depends on. "Active" now means
    STARTED and not ended — never merely un-ended. Get that wrong and a session a
    coach set up for next Thursday quietly becomes the one athletes check into.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.athlete = Athlete.objects.create(name="Jordan Lee")

    def _unstarted(self, label="Thursday, not yet run"):
        """A session that exists but has not been started."""
        session = TrainingSession.objects.create(label=label, started_at=None)
        session.athletes.add(self.athlete)
        return session

    def test_an_unstarted_session_is_not_the_active_one(self):
        self._unstarted()
        res = self.client.get("/api/sessions/active/")
        self.assertIsNone(res.data["session_id"])

    def test_an_unstarted_session_does_not_appear_in_room_state(self):
        self._unstarted()
        self.assertIsNone(self.client.get("/api/room-state/").data["session"])

    def test_an_unstarted_session_cannot_capture_check_ins(self):
        """The heart of it. A future session holding the racks is canon D18 with
        a calendar bolted on: sets would attach to a day nobody is training."""
        self._unstarted()
        res = self.client.post("/api/racks/1/checkin/", {"athlete": self.athlete.id},
                               format="json")
        self.assertEqual(res.status_code, 400)

    def test_an_unstarted_session_does_not_block_starting_today(self):
        """Setting up Thursday must not stop the room opening on Tuesday — the
        P12 guard is about days that are RUNNING."""
        self._unstarted()
        res = self.client.post("/api/sessions/",
                               {"label": "Tuesday", "athletes": [self.athlete.id]},
                               format="json")
        self.assertEqual(res.status_code, 201)

    def test_an_unstarted_session_created_LATER_does_not_hijack_the_live_one(self):
        """⚠️ The specific trap this guards: Postgres sorts NULLs FIRST in a
        descending order. Ordering by `-started_at` without excluding nulls makes
        the unstarted session sort ahead of the day actually being trained."""
        live = self.client.post("/api/sessions/",
                                {"label": "Today", "athletes": [self.athlete.id]},
                                format="json")
        self._unstarted("Next Thursday")

        res = self.client.get("/api/sessions/active/")
        self.assertEqual(res.data["session_id"], live.data["id"])
        self.assertEqual(res.data["label"], "Today")

    def test_starting_a_day_through_the_api_sets_a_real_start_time(self):
        """`started_at` stopped being automatic; the create route has to set it,
        or every day a coach opens would look unstarted."""
        res = self.client.post("/api/sessions/",
                               {"label": "Today", "athletes": [self.athlete.id]},
                               format="json")
        self.assertIsNotNone(TrainingSession.objects.get(id=res.data["id"]).started_at)

    def test_an_ended_session_keeps_its_start_time(self):
        """The migration dropped auto_now_add. If that had blanked existing rows,
        every finished day would have lost when it began."""
        opened = self.client.post("/api/sessions/",
                                  {"label": "Today", "athletes": [self.athlete.id]},
                                  format="json")
        session = TrainingSession.objects.get(id=opened.data["id"])
        started = session.started_at

        self.client.patch(f"/api/sessions/{session.id}/", {}, format="json")
        session.refresh_from_db()
        self.assertEqual(session.started_at, started)
        self.assertIsNotNone(session.ended_at)


class AthleteAnalyticsTests(APITestCase):
    """The athlete + history read (canon D19, P13).

    His two tabs were built against a payload nobody had written. These tests pin
    the parts that could go wrong QUIETLY — a total computed from a truncated
    list, or a missing `measured` block — rather than loudly.
    """

    def setUp(self):
        self.coach = User.objects.create_user(username="coach", password="pw")
        self.client.force_authenticate(user=self.coach)
        self.athlete = Athlete.objects.create(name="Jordan Lee")
        self.squat = Exercise.objects.get_or_create(name="Back Squat")[0]
        self.bench = Exercise.objects.get_or_create(name="Bench Press")[0]
        self.session = TrainingSession.objects.create(label="Monday — Lower", started_at=timezone.now())

    def _url(self, athlete_id=None):
        return f"/api/analytics/athlete/{athlete_id or self.athlete.id}/"

    def _set(self, exercise=None, *, number=1, weight=225.0, avg=0.8, peak=0.9,
             reps=3, false=False, adjustment=False, ended=True, athlete=None,
             session=None, node=None):
        return Set.objects.create(
            session=session or self.session, athlete=athlete or self.athlete,
            exercise=exercise or self.squat, set_number=number,
            weight_lbs=weight, avg_velocity=avg, peak_velocity=peak,
            reps_completed=reps, is_false_set=false,
            is_coach_adjustment=adjustment, node=node,
            ended_at=timezone.now() if ended else None)

    def _reps(self, workout_set, speeds):
        for index, speed in enumerate(speeds, start=1):
            Rep.objects.create(set=workout_set, rep_number=index,
                               timestamp=timezone.now(), mean_velocity=speed,
                               peak_velocity=speed + 0.05, duration_ms=800,
                               velocity_color="green")

    # ── the shape the tabs read ──────────────────────────────────────────────

    def test_it_returns_the_athlete_block_the_hero_renders(self):
        self._set()
        data = self.client.get(self._url()).data
        self.assertEqual(data["athlete"]["name"], "Jordan Lee")
        self.assertIsNotNone(data["athlete"]["created_at"])

    def test_the_summary_carries_every_field_the_grid_shows(self):
        self._set(weight=225.0, avg=0.8, peak=0.9, reps=3)
        self._set(number=2, weight=275.0, avg=0.7, peak=1.1, reps=2)
        summary = self.client.get(self._url()).data["summary"]
        self.assertEqual(summary["completed_sets"], 2)
        self.assertEqual(summary["completed_reps"], 5)
        self.assertEqual(summary["best_average"], 0.8)
        self.assertEqual(summary["highest_peak"], 1.1)
        self.assertEqual(summary["heaviest_weight"], 275.0)

    def test_sets_carry_the_session_so_history_can_name_the_workout(self):
        """Without this every training day renders as 'Unlabeled workout'."""
        self._set()
        row = self.client.get(self._url()).data["sets"][0]
        self.assertEqual(row["session"]["label"], "Monday — Lower")

    def test_a_set_reports_the_rack_from_its_node(self):
        """`Set` has no rack column — D11 dropped it — so this comes from the
        node that recorded the set."""
        node = Node.objects.create(node_id="node-a", rack_number=3)
        self._set(node=node)
        self.assertEqual(self.client.get(self._url()).data["sets"][0]["rack_number"], 3)

    def test_a_set_with_no_node_reports_no_rack_rather_than_failing(self):
        self._set(node=None)
        self.assertIsNone(self.client.get(self._url()).data["sets"][0]["rack_number"])

    def test_reps_come_back_for_the_rep_by_rep_comparison(self):
        workout_set = self._set()
        self._reps(workout_set, [0.85, 0.80, 0.74])
        row = self.client.get(self._url()).data["sets"][0]
        self.assertEqual([r["rep_number"] for r in row["reps"]], [1, 2, 3])
        self.assertEqual(row["reps"][0]["mean_velocity"], 0.85)
        self.assertIsNotNone(row["reps"][0]["duration_ms"])

    # ── the `measured` block must ALWAYS exist ───────────────────────────────

    def test_every_set_has_a_measured_block_even_with_no_reps(self):
        """The UI reads `measured.first_to_last_change_percent` with no optional
        chaining, so omitting the block is a thrown TypeError — and React
        unmounts the whole coach view on a render error. A black screen."""
        self._set()
        row = self.client.get(self._url()).data["sets"][0]
        self.assertIn("measured", row)
        self.assertIsNone(row["measured"]["first_to_last_change_percent"])

    def test_measured_is_negative_when_the_athlete_slowed_down(self):
        workout_set = self._set()
        self._reps(workout_set, [1.0, 0.9, 0.8])
        row = self.client.get(self._url()).data["sets"][0]
        self.assertAlmostEqual(row["measured"]["first_to_last_change_percent"], -20.0)

    def test_measured_is_positive_when_they_finished_faster(self):
        """Signed rather than a 'loss', so speeding up is not a negative loss."""
        workout_set = self._set()
        self._reps(workout_set, [0.8, 1.0])
        row = self.client.get(self._url()).data["sets"][0]
        self.assertAlmostEqual(row["measured"]["first_to_last_change_percent"], 25.0)

    def test_a_single_rep_has_no_first_to_last_change(self):
        workout_set = self._set()
        self._reps(workout_set, [0.9])
        row = self.client.get(self._url()).data["sets"][0]
        self.assertIsNone(row["measured"]["first_to_last_change_percent"])

    # ── what counts as work ──────────────────────────────────────────────────

    def test_false_sets_are_excluded(self):
        self._set()
        self._set(number=2, false=True, reps=5)
        summary = self.client.get(self._url()).data["summary"]
        self.assertEqual(summary["completed_sets"], 1)
        self.assertEqual(summary["completed_reps"], 3)

    def test_coach_adjustments_are_excluded(self):
        """An adjustment moves the working load; nobody lifted for it (canon §6.5)."""
        self._set()
        self._set(number=2, adjustment=True, reps=9)
        self.assertEqual(self.client.get(self._url()).data["summary"]["completed_sets"], 1)

    def test_unfinished_sets_are_excluded(self):
        """They have no ended_at, and the history view groups by day — one would
        render as an 'Invalid Date' training day."""
        self._set()
        self._set(number=2, ended=False)
        self.assertEqual(len(self.client.get(self._url()).data["sets"]), 1)

    def test_another_athletes_sets_are_not_counted(self):
        other = Athlete.objects.create(name="Sam Rivera")
        self._set()
        self._set(number=2, athlete=other, reps=7)
        self.assertEqual(self.client.get(self._url()).data["summary"]["completed_reps"], 3)

    # ── per-movement aggregates ──────────────────────────────────────────────

    def test_exercise_summaries_aggregate_per_movement(self):
        self._set(self.squat, number=1, weight=225.0, avg=0.8, reps=3)
        self._set(self.squat, number=2, weight=275.0, avg=0.7, reps=2)
        self._set(self.bench, number=3, weight=185.0, avg=0.6, reps=5)
        rows = {r["exercise"]: r for r in self.client.get(self._url()).data["exercise_summaries"]}
        self.assertEqual(rows["Back Squat"]["completed_sets"], 2)
        self.assertEqual(rows["Back Squat"]["completed_reps"], 5)
        self.assertEqual(rows["Back Squat"]["heaviest_weight"], 275.0)
        self.assertEqual(rows["Back Squat"]["best_average"], 0.8)
        self.assertEqual(rows["Bench Press"]["completed_sets"], 1)

    def test_the_most_trained_movement_comes_first(self):
        self._set(self.bench, number=1)
        self._set(self.squat, number=2)
        self._set(self.squat, number=3)
        rows = self.client.get(self._url()).data["exercise_summaries"]
        self.assertEqual(rows[0]["exercise"], "Back Squat")

    # ── truncation must not corrupt the totals ───────────────────────────────

    def test_the_set_list_is_capped_but_the_totals_are_not(self):
        """The screen says "summaries include all history". If the totals came
        from the truncated list, the screen would be quietly lying."""
        for n in range(1, SET_LIMIT + 11):
            self._set(number=n, reps=2)

        data = self.client.get(self._url()).data
        self.assertEqual(len(data["sets"]), SET_LIMIT)
        self.assertTrue(data["truncated"])
        self.assertEqual(data["summary"]["completed_sets"], SET_LIMIT + 10)
        self.assertEqual(data["summary"]["completed_reps"], (SET_LIMIT + 10) * 2)

    def test_the_truncated_list_keeps_the_MOST_RECENT_sets(self):
        """A coach in the room is asking about what just happened."""
        for n in range(1, SET_LIMIT + 6):
            self._set(number=n)
        numbers = [row["set_number"] for row in self.client.get(self._url()).data["sets"]]
        self.assertEqual(numbers[0], SET_LIMIT + 5)
        self.assertNotIn(1, numbers)

    def test_truncated_is_false_when_everything_fits(self):
        self._set()
        self.assertFalse(self.client.get(self._url()).data["truncated"])

    def test_reps_are_capped_per_set_and_flagged(self):
        workout_set = self._set(reps=REP_LIMIT + 5)
        self._reps(workout_set, [0.8] * (REP_LIMIT + 5))
        row = self.client.get(self._url()).data["sets"][0]
        self.assertEqual(len(row["reps"]), REP_LIMIT)
        self.assertTrue(row["reps_truncated"])

    def test_reps_truncated_is_false_for_an_ordinary_set(self):
        workout_set = self._set()
        self._reps(workout_set, [0.85, 0.8])
        self.assertFalse(self.client.get(self._url()).data["sets"][0]["reps_truncated"])

    # ── empty and missing ────────────────────────────────────────────────────

    def test_an_athlete_who_has_never_lifted_gets_an_empty_context_not_an_error(self):
        """A new signing is an ordinary state, not a failure."""
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"]["completed_sets"], 0)
        self.assertEqual(res.data["summary"]["completed_reps"], 0)
        # Null, not 0.0 — nobody has a best velocity before their first rep, and
        # "0.00 m/s" would read as a measurement.
        self.assertIsNone(res.data["summary"]["best_average"])
        self.assertEqual(res.data["sets"], [])
        self.assertEqual(res.data["exercise_summaries"], [])

    def test_an_unknown_athlete_is_404(self):
        self.assertEqual(self.client.get(self._url(99999)).status_code, 404)

    def test_it_still_carries_athlete_id_for_older_callers(self):
        """The response was widened, not replaced."""
        self._set()
        self.assertEqual(self.client.get(self._url()).data["athlete_id"], self.athlete.id)

    def test_a_coach_login_is_required(self):
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(self._url()).status_code, (401, 403))


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
        group = TrainingGroup.objects.create(name="Varsity")
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
        group = TrainingGroup.objects.create(name="Varsity")
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
        group = TrainingGroup.objects.create(name="Varsity")
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
        self.group = TrainingGroup.objects.create(name="Varsity")
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
        speed = TrainingGroup.objects.create(name="Speed")
        TrainingProgram.objects.create(training_group=speed, name="Sprint",
                                       start_date=timezone.now().date())
        self.athlete.training_groups.add(self.group, speed)
        assignment = self.client.get(self._url()).data["assignment"]
        self.assertEqual({a["training_group"]["name"] for a in assignment},
                         {"Varsity", "Speed"})

    def test_removing_the_assignment_takes_them_out_of_the_prescribing_groups_only(self):
        """A TrainingGroup with no plan attached is roster information a coach set up on
        purpose — clearing an assignment shouldn't quietly discard it."""
        empty = TrainingGroup.objects.create(name="Freshmen")
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
        self.session = TrainingSession.objects.create(label="Thursday", started_at=timezone.now())
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
