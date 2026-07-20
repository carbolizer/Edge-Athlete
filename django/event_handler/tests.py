"""Proves dashboard privacy/state contracts and protects atomic set completion behavior."""

from datetime import timedelta
import json
from threading import Barrier, Event, Thread
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import DatabaseError, IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Athlete, MonitoringEvent, Node, Program, RackScreen, RackWorkoutState, Rep, Session, Set, Workout, WorkoutExercise, WorkoutProgram, WorkoutProgramItem, AthleteWorkoutAssignment, AthleteWorkoutProgramAssignment, AthleteWorkoutExerciseOverride, AthleteDayProgress, AthleteRackParticipation, DailyReport
from .serializers import ProgramSerializer
from .realtime.broadcast.publisher import DASHBOARD_TOPIC, publish_pending_event
from .realtime.event_processor.process_pulse import process_pulse_event
from .realtime.mqtt_ingester.parser import parse_pulse_payload, parse_rep_payload
from .realtime.mqtt_ingester.subscriber import on_message
from .services.training_limits import (
    MAX_REPORT_SNAPSHOT_BYTES,
    MAX_SESSION_ATHLETES,
    MAX_SESSION_REPS,
    MAX_SESSION_SETS,
)
from .services.reports import reports_for_athlete


class SimulatorTests(TestCase):
    @override_settings(SIMULATOR_ENABLED=True)
    @patch("event_handler.management.commands.simulate_node.mqtt.Client")
    def test_finite_simulation_publishes_contracts_and_persists_monitoring_data(self, client_class):
        mqtt_client = client_class.return_value
        mqtt_client.publish.return_value.rc = 0
        mqtt_client.publish.return_value.is_published.return_value = True

        call_command(
            "simulate_node",
            racks=1,
            rack=3,
            interval=0,
            rest=0,
            reps_per_set=3,
            sets=1,
            seed=7,
        )

        node = Node.objects.get(node_id="sim-rack-3")
        workout_set = Set.objects.get(node=node)
        self.assertEqual(workout_set.rack_number, 3)
        self.assertEqual(workout_set.reps_completed, 3)
        self.assertIsNotNone(workout_set.ended_at)
        self.assertEqual(workout_set.reps.count(), 3)
        self.assertEqual(MonitoringEvent.objects.filter(reason="set_completed").count(), 1)

        published = [(call.args[0], json.loads(call.args[1])) for call in mqtt_client.publish.call_args_list]
        pulse = next(body for topic, body in published if topic == "edgeathlete/node/sim-rack-3/pulse")
        reps = [body for topic, body in published if topic == "edgeathlete/node/sim-rack-3/rep"]
        self.assertEqual(pulse["event_type"], "pulse")
        self.assertEqual(reps, [])
        self.assertTrue(workout_set.is_simulated)
        self.assertTrue(MonitoringEvent.objects.get().is_simulated)
        mqtt_client.disconnect.assert_called_once()

    @override_settings(SIMULATOR_ENABLED=True)
    @patch("event_handler.management.commands.simulate_node.mqtt.Client")
    def test_rack_mode_publishes_reps_without_persisting_sets(self, client_class):
        mqtt_client = client_class.return_value
        mqtt_client.publish.return_value.rc = 0
        mqtt_client.publish.return_value.is_published.return_value = True

        call_command(
            "simulate_node", mode="rack", racks=1, interval=0, rest=0,
            reps_per_set=3, sets=1, seed=7,
        )

        published = [(call.args[0], json.loads(call.args[1])) for call in mqtt_client.publish.call_args_list]
        reps = [body for topic, body in published if topic == "edgeathlete/node/sim-rack-1/rep"]
        self.assertEqual([rep["rep_number"] for rep in reps], [1, 2, 3])
        self.assertFalse(Set.objects.exists())

        session = Session.objects.get(is_simulated=True)
        athlete = Athlete.objects.get(is_simulated=True)
        node = Node.objects.get(is_simulated=True)
        client = APIClient()
        created = client.post("/api/sets/", {
            "session": session.id,
            "athlete": athlete.id,
            "node": node.id,
            "exercise": "Back squat",
            "set_number": 1,
            "weight_lbs": 225,
        }, format="json")
        self.assertEqual(created.status_code, 201)
        completed = client.post(f"/api/sets/{created.data['id']}/complete/", {
            "reps_completed": 1,
            "is_false_set": False,
            "reps": [{
                "rep_number": 1,
                "mean_velocity": 0.7,
                "peak_velocity": 0.9,
                "duration_ms": 700,
                "timestamp": timezone.now().isoformat(),
                "velocity_color": "green",
            }],
        }, format="json")
        self.assertEqual(completed.status_code, 200)
        self.assertTrue(Set.objects.get().is_simulated)
        self.assertTrue(MonitoringEvent.objects.get(reason="set_completed").is_simulated)

        call_command("clear_simulation_data", confirm=True)
        self.assertFalse(Set.objects.exists())
        self.assertFalse(Athlete.objects.filter(is_simulated=True).exists())

    def test_velocity_color_uses_program_zone(self):
        from .management.commands.simulate_node import velocity_color

        self.assertEqual(velocity_color(0.59, 0.60, 0.80), "red")
        self.assertEqual(velocity_color(0.70, 0.60, 0.80), "green")
        self.assertEqual(velocity_color(0.81, 0.60, 0.80), "yellow")

    @patch("event_handler.management.commands.simulate_node.mqtt.Client")
    def test_simulator_is_disabled_without_explicit_setting(self, client_class):
        with self.assertRaisesMessage(Exception, "Simulation is disabled"):
            call_command("simulate_node", sets=1)
        client_class.assert_not_called()

    @override_settings(SIMULATOR_ENABLED=True)
    def test_monitoring_simulator_rejects_session_set_and_rep_overflow_before_writes(self):
        with self.assertRaisesMessage(Exception, f"{MAX_SESSION_SETS}-set session limit"):
            call_command(
                "simulate_node",
                mode="monitoring",
                racks=1,
                sets=MAX_SESSION_SETS + 1,
                reps_per_set=1,
            )
        with self.assertRaisesMessage(Exception, f"{MAX_SESSION_REPS}-rep session limit"):
            call_command(
                "simulate_node",
                mode="monitoring",
                racks=1,
                sets=MAX_SESSION_REPS // 100 + 1,
                reps_per_set=100,
            )

        self.assertFalse(Session.objects.exists())
        self.assertFalse(Set.objects.exists())
        self.assertFalse(Rep.objects.exists())

    @override_settings(SIMULATOR_ENABLED=True)
    @patch("event_handler.management.commands.simulate_node.mqtt.Client")
    def test_rejects_active_real_session_before_creating_simulation_records(self, client_class):
        Session.objects.create(label="Real training")
        mqtt_client = client_class.return_value

        with self.assertRaisesMessage(Exception, "End the active non-simulation session"):
            call_command("simulate_node", sets=1)

        self.assertFalse(Session.objects.filter(label__startswith="[SIMULATION]").exists())
        mqtt_client.disconnect.assert_called_once()

    @override_settings(SIMULATOR_ENABLED=True)
    @patch("event_handler.management.commands.simulate_node.build_rep_payload", side_effect=RuntimeError("sensor failed"))
    @patch("event_handler.management.commands.simulate_node.mqtt.Client")
    def test_runtime_failure_closes_started_set_as_false(self, client_class, build_rep):
        mqtt_client = client_class.return_value
        mqtt_client.publish.return_value.rc = 0
        mqtt_client.publish.return_value.is_published.return_value = True

        with self.assertRaisesMessage(RuntimeError, "sensor failed"):
            call_command("simulate_node", racks=1, sets=1, interval=0, rest=0)

        workout_set = Set.objects.get()
        self.assertTrue(workout_set.is_false_set)
        self.assertIsNotNone(workout_set.ended_at)
        self.assertFalse(Set.objects.filter(ended_at=None).exists())


    def test_rep_parser_enforces_shared_contract(self):
        parsed = parse_rep_payload(
            b'{"node_id":"sim-rack-1","rep_number":1,"mean_velocity":0.7,"peak_velocity":0.9,"duration_ms":700,"timestamp":"2026-07-14T20:00:00Z"}'
        )
        self.assertEqual(parsed["mean_velocity"], 0.7)
        with self.assertRaisesMessage(ValueError, "peak_velocity"):
            parse_rep_payload(
                b'{"node_id":"sim-rack-1","rep_number":1,"mean_velocity":0.9,"peak_velocity":0.7,"duration_ms":700,"timestamp":"2026-07-14T20:00:00Z"}'
            )
        with self.assertRaisesMessage(ValueError, "timezone-aware"):
            parse_rep_payload(
                b'{"node_id":"sim-rack-1","rep_number":1,"mean_velocity":0.7,"peak_velocity":0.9,"duration_ms":700,"timestamp":"not-a-date"}'
            )

    @override_settings(SIMULATOR_ENABLED=True)
    def test_cleanup_deletes_only_owned_simulation_records(self):
        real_athlete = Athlete.objects.create(name="Real", nfc_tag_id="simulation-athlete-real")
        simulated_athlete = Athlete.objects.create(name="[SIM] Athlete", is_simulated=True)
        Session.objects.create(
            label="[SIMULATION] Real label",
            is_simulated=False,
            ended_at=timezone.now(),
        )
        simulated_session = Session.objects.create(label="Anything", is_simulated=True)
        Node.objects.create(node_id="sim-rack-real", is_simulated=False)
        Node.objects.create(node_id="anything", is_simulated=True)
        MonitoringEvent.objects.create(reason="set_completed", is_simulated=True)
        RackWorkoutState.objects.create(rack_number=7, active_session=simulated_session)

        call_command("clear_simulation_data", confirm=True)

        self.assertTrue(Athlete.objects.filter(id=real_athlete.id).exists())
        self.assertFalse(Athlete.objects.filter(id=simulated_athlete.id).exists())
        self.assertTrue(Session.objects.filter(label="[SIMULATION] Real label").exists())
        self.assertTrue(Node.objects.filter(node_id="sim-rack-real").exists())
        self.assertFalse(MonitoringEvent.objects.filter(is_simulated=True).exists())
        self.assertFalse(RackWorkoutState.objects.filter(rack_number=7).exists())
        self.assertTrue(MonitoringEvent.objects.filter(reason="simulation_cleared").exists())

    def test_cleanup_requires_enablement(self):
        with self.assertRaisesMessage(Exception, "cleanup is disabled"):
            call_command("clear_simulation_data", confirm=True)

    @override_settings(SIMULATOR_ENABLED=True)
    def test_cleanup_requires_confirmation(self):
        with self.assertRaisesMessage(Exception, "Pass --confirm"):
            call_command("clear_simulation_data")

    @override_settings(SIMULATOR_ENABLED=True)
    def test_cleanup_rejects_simulated_athlete_linked_to_real_session(self):
        athlete = Athlete.objects.create(name="[SIM] Athlete", is_simulated=True)
        real_session = Session.objects.create(label="Real session")
        real_session.athletes.add(athlete)

        with self.assertRaisesMessage(Exception, "cleanup aborted"):
            call_command("clear_simulation_data", confirm=True)

        self.assertTrue(Athlete.objects.filter(id=athlete.id).exists())
        self.assertTrue(real_session.athletes.filter(id=athlete.id).exists())


class SessionAdminTests(TestCase):
    def test_session_admin_is_browse_only_and_other_admin_models_remain_editable(self):
        request = SimpleNamespace(user=User.objects.create_superuser(
            username="admin-permission-test",
            password="test-only",
            email="admin@example.com",
        ))
        session_admin = admin.site._registry[Session]
        athlete_admin = admin.site._registry[Athlete]

        self.assertTrue(session_admin.has_view_permission(request))
        self.assertFalse(session_admin.has_add_permission(request))
        self.assertFalse(session_admin.has_change_permission(request))
        self.assertFalse(session_admin.has_delete_permission(request))
        self.assertTrue(athlete_admin.has_add_permission(request))
        self.assertTrue(athlete_admin.has_change_permission(request))
        self.assertTrue(athlete_admin.has_delete_permission(request))


class RoomStateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.coach = User.objects.create_user(username="coach", password="test-only", is_staff=True)
        self.client.force_authenticate(self.coach)

    def test_detailed_room_state_requires_coach_authentication(self):
        anonymous_client = APIClient()

        response = anonymous_client.get("/api/room-state/")

        self.assertEqual(response.status_code, 401)

    def test_detailed_room_state_rejects_authenticated_non_coach(self):
        non_coach = User.objects.create_user(username="athlete", password="test-only")
        client = APIClient()
        client.force_authenticate(non_coach)

        response = client.get("/api/room-state/")

        self.assertEqual(response.status_code, 403)

    def test_empty_state_includes_assigned_racks_without_private_screen_ids(self):
        Node.objects.create(node_id="node-1", rack_number=1)
        RackScreen.objects.create(device_id="private-tablet-id", rack_number=2)

        response = self.client.get("/api/room-state/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["session"])
        self.assertEqual(response.data["summary"]["completed_sets"], 0)
        self.assertEqual([rack["rack_number"] for rack in response.data["racks"]], [1, 2])
        self.assertNotContains(response, "private-tablet-id")

    def test_returns_newest_active_session_summary_racks_and_leaderboard(self):
        athlete = Athlete.objects.create(
            name="Jordan Lee",
            nfc_tag_id="private-nfc-id",
            notes="private coach note",
        )
        older_session = Session.objects.create(
            label="Older session",
            notes="private session note",
            ended_at=timezone.now() - timedelta(hours=1),
        )
        active_session = Session.objects.create(label="Back Squat Day")
        active_session.athletes.add(athlete)
        Session.objects.filter(id=older_session.id).update(started_at=timezone.now() - timedelta(hours=1))
        node = Node.objects.create(node_id="node-3", rack_number=3, battery_level=78)
        Program.objects.create(
            athlete=athlete,
            exercise="Back squat",
            target_sets=5,
            target_reps=3,
            target_weight_lbs=225,
            velocity_zone_min=0.75,
            velocity_zone_max=0.9,
        )
        completed_set = Set.objects.create(
            session=active_session,
            athlete=athlete,
            node=node,
            exercise="Back squat",
            set_number=1,
            weight_lbs=225,
        )
        completed_set.ended_at = timezone.now()
        completed_set.reps_completed = 2
        completed_set.avg_velocity = 0.8
        completed_set.peak_velocity = 0.9
        completed_set.save()
        Rep.objects.create(
            set=completed_set,
            rep_number=1,
            timestamp=timezone.now(),
            mean_velocity=0.8,
            peak_velocity=0.9,
            duration_ms=600,
            velocity_color="green",
        )
        false_set = Set.objects.create(
            session=active_session,
            athlete=athlete,
            node=node,
            exercise="Back squat",
            set_number=2,
            is_false_set=True,
            reps_completed=9,
            avg_velocity=1.5,
            ended_at=timezone.now(),
        )
        Set.objects.filter(id=false_set.id).update(started_at=timezone.now() - timedelta(minutes=5))

        response = self.client.get("/api/room-state/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["session"]["label"], "Back Squat Day")
        self.assertEqual(response.data["summary"], {
            "participant_count": 1,
            "athletes_with_sets": 1,
            "completed_sets": 1,
            "completed_reps": 2,
            "room_avg_velocity": 0.8,
            "active_racks": 0,
        })
        rack = response.data["racks"][0]
        self.assertEqual(rack["latest_set"]["id"], completed_set.id)
        self.assertEqual(rack["latest_set"]["target_zone"], {"min": 0.75, "max": 0.9})
        self.assertEqual(rack["status_color"], "green")
        self.assertIsNone(response.data["movement"])
        self.assertEqual(response.data["leaderboard"], [])
        self.assertEqual(response.data["insights"], [])
        self.assertEqual(rack["latest_set"]["measured_insights"]["velocity_loss"], 0)
        self.assertNotContains(response, "private-nfc-id")
        self.assertNotContains(response, "private coach note")
        self.assertNotContains(response, "private session note")

        wall_response = APIClient().get("/api/wall-state/")
        self.assertEqual(wall_response.status_code, 200)
        self.assertEqual(wall_response["Cache-Control"], "private, no-store")
        self.assertEqual(wall_response["Pragma"], "no-cache")
        self.assertContains(wall_response, "Jordan Lee")
        self.assertNotContains(wall_response, "node-3")
        self.assertNotContains(wall_response, f'"id":{athlete.id}')
        self.assertNotContains(wall_response, '"weight_lbs"')
        self.assertNotContains(wall_response, '"target_zone"')
        self.assertNotContains(wall_response, '"measured_insights"')

    def test_saved_set_stays_on_original_rack_after_node_moves(self):
        athlete = Athlete.objects.create(name="Jordan Lee")
        session = Session.objects.create(label="Training")
        node = Node.objects.create(node_id="node-1", rack_number=1)
        workout_set = Set.objects.create(
            session=session,
            athlete=athlete,
            node=node,
            exercise="Squat",
            set_number=1,
        )
        workout_set.ended_at = timezone.now()
        workout_set.save(update_fields=["ended_at"])

        node.rack_number = 2
        node.save(update_fields=["rack_number"])

        self.assertEqual(workout_set.rack_number, 1)
        response = self.client.get("/api/room-state/")
        rack_one = next(rack for rack in response.data["racks"] if rack["rack_number"] == 1)
        self.assertEqual(rack_one["latest_set"]["athlete"]["name"], "Jordan Lee")

    def test_active_set_does_not_hide_latest_completed_result(self):
        athlete = Athlete.objects.create(name="Jordan Lee")
        session = Session.objects.create(label="Training")
        node = Node.objects.create(node_id="node-1", rack_number=1)
        completed = Set.objects.create(session=session, athlete=athlete, node=node, exercise="Squat", set_number=1)
        completed.ended_at = timezone.now()
        completed.avg_velocity = 0.8
        completed.save()
        Set.objects.create(session=session, athlete=athlete, node=node, exercise="Squat", set_number=2)

        response = self.client.get("/api/room-state/")

        rack = response.data["racks"][0]
        self.assertEqual(rack["status"], "active")
        self.assertEqual(rack["latest_set"]["id"], completed.id)

    def test_reports_assignment_conflicts_and_unassigned_sets(self):
        athlete = Athlete.objects.create(name="Jordan Lee")
        session = Session.objects.create(label="Training")
        node_one = Node.objects.create(node_id="node-1", rack_number=1)
        Node.objects.create(node_id="node-1b", rack_number=1)
        RackScreen.objects.create(device_id="screen-a", rack_number=1)
        RackScreen.objects.create(device_id="screen-b", rack_number=1)
        Set.objects.create(
            session=session,
            athlete=athlete,
            node=None,
            exercise="Bench press",
            set_number=1,
        )
        Set.objects.create(
            session=session,
            athlete=athlete,
            node=node_one,
            exercise="Bench press",
            set_number=2,
        )

        response = self.client.get("/api/room-state/")

        self.assertTrue(response.data["racks"][0]["assignment_conflict"])
        self.assertEqual(response.data["meta"]["unassigned_session_sets"], 1)


class ProgramVelocityZoneTests(TestCase):
    def setUp(self):
        self.athlete = Athlete.objects.create(name="Jordan Lee")
        self.base_payload = {
            "athlete": self.athlete.id,
            "exercise": "Back squat",
            "target_sets": 5,
            "target_reps": 3,
            "target_weight_lbs": 225,
        }

    def test_accepts_and_serializes_non_velocity_program(self):
        form = ProgramSerializer(data={
            **self.base_payload,
            "velocity_zone_min": None,
            "velocity_zone_max": None,
        })

        self.assertTrue(form.is_valid(), form.errors)
        program = form.save()
        self.assertIsNone(ProgramSerializer(program).data["velocity_zone_min"])
        self.assertIsNone(ProgramSerializer(program).data["velocity_zone_max"])

    def test_rejects_partial_negative_and_inverted_velocity_zones(self):
        invalid_zones = [
            (None, 0.8), (-0.1, 0.8), (0.9, 0.8),
            (float("nan"), 0.8), (0.7, float("inf")), (0.7, 10.1),
        ]

        for minimum, maximum in invalid_zones:
            with self.subTest(minimum=minimum, maximum=maximum):
                form = ProgramSerializer(data={
                    **self.base_payload,
                    "velocity_zone_min": minimum,
                    "velocity_zone_max": maximum,
                })
                self.assertFalse(form.is_valid())

    def test_model_validation_rejects_partial_zone(self):
        program = Program(
            athlete=self.athlete,
            exercise="Back squat",
            target_sets=5,
            target_reps=3,
            target_weight_lbs=225,
            velocity_zone_min=0.7,
            velocity_zone_max=None,
        )

        with self.assertRaises(ValidationError):
            program.full_clean()


class ProgramVelocityZoneConstraintTests(TransactionTestCase):
    def test_database_rejects_partial_zone(self):
        athlete = Athlete.objects.create(name="Jordan Lee")

        with self.assertRaises(IntegrityError):
            Program.objects.create(
                athlete=athlete,
                exercise="Back squat",
                target_sets=5,
                target_reps=3,
                target_weight_lbs=225,
                velocity_zone_min=0.7,
                velocity_zone_max=None,
            )


class WorkoutCatalogApiTests(TestCase):
    headers = b"workout_name,exercise,position,sets,reps,default_weight_lbs,velocity_min,velocity_max\n"

    def setUp(self):
        self.coach = User.objects.create_user(username="workout-coach", password="test-only", is_staff=True)
        self.non_coach = User.objects.create_user(username="workout-athlete", password="test-only")
        self.client = APIClient()
        self.client.force_authenticate(self.coach)

    def upload(self, path, body, *, client=None):
        return (client or self.client).post(
            path,
            {"file": SimpleUploadedFile("workouts.csv", body, content_type="text/csv")},
            format="multipart",
        )

    def valid_payload(self, name="Lower Strength"):
        return {
            "name": name,
            "exercises": [
                {
                    "exercise": "Romanian deadlift",
                    "position": 2,
                    "sets": 3,
                    "reps": 8,
                    "default_weight_lbs": 185,
                    "velocity_min": None,
                    "velocity_max": None,
                },
                {
                    "exercise": "Back squat",
                    "position": 1,
                    "sets": 4,
                    "reps": 5,
                    "default_weight_lbs": 225,
                    "velocity_min": 0.55,
                    "velocity_max": 0.75,
                },
            ],
        }

    def test_all_catalog_routes_require_active_staff_and_successes_are_private(self):
        routes = [
            ("get", "/api/workouts/"),
            ("post", "/api/workouts/"),
            ("post", "/api/workouts/imports/preview/"),
            ("post", "/api/workouts/imports/"),
        ]
        anonymous = APIClient()
        regular = APIClient()
        regular.force_authenticate(self.non_coach)

        for method, path in routes:
            with self.subTest(path=path, identity="anonymous"):
                response = getattr(anonymous, method)(path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response["Cache-Control"], "private, no-store")
            with self.subTest(path=path, identity="non_coach"):
                response = getattr(regular, method)(path)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response["Cache-Control"], "private, no-store")

        created = self.client.post("/api/workouts/", self.valid_payload(), format="json")
        listed = self.client.get("/api/workouts/")
        previewed = self.upload(
            "/api/workouts/imports/preview/",
            self.headers + b"Upper,Press,1,3,5,95,,\n",
        )
        imported = self.upload(
            "/api/workouts/imports/",
            self.headers + b"Upper,Press,1,3,5,95,,\n",
        )
        for response in (created, listed, previewed, imported):
            self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_manual_create_is_atomic_ordered_and_casefold_unique(self):
        created = self.client.post("/api/workouts/", self.valid_payload("  Lower Strength  "), format="json")

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["name"], "Lower Strength")
        self.assertEqual([row["position"] for row in created.data["exercises"]], [1, 2])
        self.assertEqual(Workout.objects.get().normalized_name, "lower strength")

        duplicate = self.client.post("/api/workouts/", self.valid_payload("LOWER STRENGTH"), format="json")
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.data["errors"][0]["code"], "workout_name_conflict")
        self.assertEqual(Workout.objects.count(), 1)
        self.assertEqual(WorkoutExercise.objects.count(), 2)

    def test_manual_validation_rejects_positions_and_nonfinite_numbers_without_writes(self):
        invalid_payloads = []
        duplicate = self.valid_payload()
        duplicate["exercises"][0]["position"] = 1
        invalid_payloads.append((duplicate, "duplicate_position"))
        missing = self.valid_payload()
        missing["exercises"][1]["position"] = 3
        invalid_payloads.append((missing, "non_contiguous_positions"))
        nonfinite = self.valid_payload()
        nonfinite["exercises"][0]["default_weight_lbs"] = "NaN"
        invalid_payloads.append((nonfinite, "invalid_number"))
        velocity = self.valid_payload()
        velocity["exercises"][0]["velocity_min"] = 0.8
        invalid_payloads.append((velocity, "velocity_pair_required"))

        for payload, code in invalid_payloads:
            with self.subTest(code=code):
                response = self.client.post("/api/workouts/", payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(code, [error["code"] for error in response.data["errors"]])
                self.assertTrue(all("row" in error and "field" in error for error in response.data["errors"]))
                self.assertFalse(Workout.objects.exists())

    def test_manual_rejects_oversized_integer_fields_without_conversion_or_writes(self):
        oversized_values = ("9" * 5000, 2_147_483_648)
        for field in ("position", "sets", "reps"):
            for value in oversized_values:
                with self.subTest(field=field, value_type=type(value).__name__):
                    payload = self.valid_payload()
                    payload["exercises"][0][field] = value

                    response = self.client.post("/api/workouts/", payload, format="json")

                    self.assertEqual(response.status_code, 400)
                    field_errors = [error for error in response.data["errors"] if error["field"] == field]
                    self.assertTrue(field_errors)
                    self.assertEqual(field_errors[0]["code"], "out_of_range")
                    self.assertEqual(field_errors[0]["row"], 1)
                    self.assertFalse(Workout.objects.exists())

    def test_csv_rejects_oversized_integer_fields_without_conversion_or_writes(self):
        oversized_values = ("9" * 5000, "2147483648")
        columns = {
            "position": 2,
            "sets": 3,
            "reps": 4,
        }
        for field, column in columns.items():
            for value in oversized_values:
                with self.subTest(field=field, digits=len(value)):
                    row = ["Huge", "Squat", "1", "3", "5", "100", "", ""]
                    row[column] = value
                    response = self.upload(
                        "/api/workouts/imports/",
                        self.headers + (",".join(row) + "\n").encode(),
                    )

                    self.assertEqual(response.status_code, 400)
                    field_errors = [error for error in response.data["errors"] if error["field"] == field]
                    self.assertTrue(field_errors)
                    self.assertEqual(field_errors[0]["code"], "out_of_range")
                    self.assertEqual(field_errors[0]["row"], 2)
                    self.assertFalse(Workout.objects.exists())

    def test_list_is_paginated_and_exercises_are_position_ordered(self):
        workouts = [Workout(name=f"Workout {index:03d}", normalized_name=f"workout {index:03d}") for index in range(51)]
        Workout.objects.bulk_create(workouts)
        first = Workout.objects.order_by("name").first()
        WorkoutExercise.objects.create(workout=first, exercise="Second", position=2, sets=1, reps=1, default_weight_lbs=0)
        WorkoutExercise.objects.create(workout=first, exercise="First", position=1, sets=1, reps=1, default_weight_lbs=0)

        page_one = self.client.get("/api/workouts/?page_size=50")
        page_two = self.client.get("/api/workouts/?page=2&page_size=50")

        self.assertEqual(page_one.status_code, 200)
        self.assertEqual(page_one.data["count"], 51)
        self.assertEqual(len(page_one.data["results"]), 50)
        self.assertEqual(len(page_two.data["results"]), 1)
        self.assertEqual([row["position"] for row in page_one.data["results"][0]["exercises"]], [1, 2])

    def test_csv_preview_accepts_bom_crlf_quoted_commas_header_order_and_writes_nothing(self):
        body = (
            b"\xef\xbb\xbfexercise,workout_name,reps,sets,position,velocity_max,default_weight_lbs,velocity_min\r\n"
            b'"Back squat, paused",Lower Strength,5,4,1,0.75,225,0.55\r\n'
            b"Romanian deadlift,Lower Strength,8,3,2,,185,\r\n"
        )

        response = self.upload("/api/workouts/imports/preview/", body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["valid"])
        self.assertEqual(response.data["errors"], [])
        self.assertEqual(response.data["workouts"][0]["exercises"][0]["exercise"], "Back squat, paused")
        self.assertIsNone(response.data["workouts"][0]["exercises"][1]["velocity_min"])
        self.assertFalse(Workout.objects.exists())

    def test_invalid_csv_preview_returns_row_field_errors_without_writes(self):
        response = self.upload(
            "/api/workouts/imports/preview/",
            self.headers + b"Lower Strength,Back squat,1,0,5,225,0.55,0.75\n",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["valid"])
        self.assertEqual(response.data["errors"][0]["row"], 2)
        self.assertEqual(response.data["errors"][0]["field"], "sets")
        self.assertEqual(response.data["errors"][0]["code"], "invalid_integer")
        self.assertFalse(Workout.objects.exists())
        self.assertFalse(WorkoutExercise.objects.exists())

    def test_manual_creation_enforces_exercise_limit_without_writes(self):
        payload = self.valid_payload()
        payload["exercises"] = [payload["exercises"][0]] * 1001

        response = self.client.post("/api/workouts/", payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"][0]["code"], "row_limit_exceeded")
        self.assertFalse(Workout.objects.exists())

    def test_csv_import_revalidates_create_only_and_rolls_back_all_workouts(self):
        valid = self.headers + b"Existing,Squat,1,3,5,100,,\n"
        first = self.upload("/api/workouts/imports/", valid)
        self.assertEqual(first.status_code, 201)

        mixed = self.headers + b"New Workout,Press,1,3,5,95,,\n existing ,Row,1,2,8,100,,\n"
        rejected = self.upload("/api/workouts/imports/", mixed)

        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.data["errors"][0]["code"], "workout_name_conflict")
        self.assertEqual(list(Workout.objects.values_list("name", flat=True)), ["Existing"])

    def test_csv_rejects_invalid_files_headers_and_rows_without_writes(self):
        cases = [
            (b"", "empty_file"),
            (b"\xff", "invalid_encoding"),
            (self.headers + b'Broken,"unterminated', "malformed_csv"),
            (b"workout_name,exercise,position,sets,reps,default_weight_lbs,velocity_min\n", "missing_headers"),
            (self.headers.replace(b"velocity_max", b"velocity_min"), "duplicate_headers"),
            (self.headers.replace(b"velocity_max", b"unexpected"), "unknown_headers"),
            (self.headers, "empty_csv"),
        ]
        for body, code in cases:
            with self.subTest(code=code):
                response = self.upload("/api/workouts/imports/", body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(code, [error["code"] for error in response.data["errors"]])
                self.assertFalse(Workout.objects.exists())

    def test_csv_enforces_exact_byte_and_row_limits(self):
        one_row = self.headers + b"Exact,Squat,1,3,5,100,,\n"
        exact_size = one_row + b"\n" * (1024 * 1024 - len(one_row))
        accepted = self.upload("/api/workouts/imports/preview/", exact_size)
        oversized = self.upload("/api/workouts/imports/preview/", exact_size + b"\n")

        rows_1000 = self.headers + b"".join(
            f"Large,Squat,{position},1,1,0,,\n".encode() for position in range(1, 1001)
        )
        rows_1001 = rows_1000 + b"Large,Squat,1001,1,1,0,,\n"
        accepted_rows = self.upload("/api/workouts/imports/preview/", rows_1000)
        rejected_rows = self.upload("/api/workouts/imports/preview/", rows_1001)

        self.assertTrue(accepted.data["valid"])
        self.assertEqual(oversized.status_code, 400)
        self.assertEqual(oversized.data["errors"][0]["code"], "file_too_large")
        self.assertTrue(accepted_rows.data["valid"])
        self.assertEqual(rejected_rows.data["errors"][0]["code"], "row_limit_exceeded")
        self.assertFalse(Workout.objects.exists())

    def test_workout_models_are_not_registered_in_admin(self):
        self.assertFalse(admin.site.is_registered(Workout))
        self.assertFalse(admin.site.is_registered(WorkoutExercise))

    def test_only_normalized_name_constraint_is_translated_to_conflict(self):
        class ConstraintViolation(Exception):
            pass

        name_cause = ConstraintViolation()
        name_cause.diag = SimpleNamespace(constraint_name="workout_normalized_name_unique")
        name_error = IntegrityError("duplicate workout")
        name_error.__cause__ = name_cause
        with patch("event_handler.views.create_workouts", side_effect=name_error):
            conflict = self.client.post("/api/workouts/", self.valid_payload(), format="json")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.data["code"], "workout_name_conflict")

        other_cause = ConstraintViolation()
        other_cause.diag = SimpleNamespace(constraint_name="workout_exercise_positive_sets")
        other_error = IntegrityError("unrelated constraint")
        other_error.__cause__ = other_cause
        with patch("event_handler.views.create_workouts", side_effect=other_error):
            with self.assertRaises(IntegrityError):
                self.client.post("/api/workouts/", self.valid_payload(), format="json")


class WorkoutDatabaseConstraintTests(TransactionTestCase):
    def setUp(self):
        self.workout = Workout.objects.create(name="Constraint Test")

    def test_database_rejects_trimmed_empty_exercise(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            WorkoutExercise.objects.create(
                workout=self.workout,
                exercise=" \t ",
                position=1,
                sets=1,
                reps=1,
                default_weight_lbs=0,
            )

    def test_database_rejects_nonfinite_weight(self):
        for weight in (float("nan"), float("inf")):
            with self.subTest(weight=weight):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    WorkoutExercise.objects.create(
                        workout=self.workout,
                        exercise="Squat",
                        position=1,
                        sets=1,
                        reps=1,
                        default_weight_lbs=weight,
                    )


class WorkoutProgramApiTests(TestCase):
    def setUp(self):
        self.coach = User.objects.create_user(username="program-coach", password="test-only", is_staff=True)
        self.non_coach = User.objects.create_user(username="program-athlete", password="test-only")
        self.client = APIClient()
        self.client.force_authenticate(self.coach)
        self.workouts = [
            Workout.objects.create(name="Lower Strength"),
            Workout.objects.create(name="Upper Strength"),
            Workout.objects.create(name="Power"),
        ]

    def valid_payload(self, name="Full Body"):
        return {
            "name": name,
            "items": [
                {"position": 2, "workout_id": self.workouts[1].id},
                {"position": 1, "workout_id": self.workouts[0].id},
            ],
        }

    def test_route_requires_active_staff_and_all_responses_are_private(self):
        anonymous = APIClient()
        regular = APIClient()
        regular.force_authenticate(self.non_coach)

        for method in ("get", "post"):
            with self.subTest(method=method, identity="anonymous"):
                response = getattr(anonymous, method)("/api/workout-programs/")
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response["Cache-Control"], "private, no-store")
            with self.subTest(method=method, identity="non_coach"):
                response = getattr(regular, method)("/api/workout-programs/")
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response["Cache-Control"], "private, no-store")

        invalid = self.client.post("/api/workout-programs/", {"name": "Bad", "items": []}, format="json")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid["Cache-Control"], "private, no-store")

    def test_create_is_normalized_ordered_atomic_and_locks_workouts(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.post(
                "/api/workout-programs/",
                self.valid_payload("  Full Body  "),
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response.data["name"], "Full Body")
        self.assertEqual(WorkoutProgram.objects.get().normalized_name, "full body")
        self.assertEqual([item["position"] for item in response.data["items"]], [1, 2])
        self.assertEqual(response.data["items"][0]["workout"], {
            "id": self.workouts[0].id,
            "name": "Lower Strength",
        })
        self.assertEqual(set(response.data["items"][0]["workout"]), {"id", "name"})
        self.assertTrue(any("FOR UPDATE" in query["sql"] for query in queries.captured_queries))

    def test_casefold_duplicate_name_returns_stable_conflict_without_items(self):
        created = self.client.post("/api/workout-programs/", self.valid_payload("Full Body"), format="json")
        duplicate = self.client.post("/api/workout-programs/", self.valid_payload(" full BODY "), format="json")

        self.assertEqual(created.status_code, 201)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.data["code"], "workout_program_name_conflict")
        self.assertEqual(WorkoutProgram.objects.count(), 1)
        self.assertEqual(WorkoutProgramItem.objects.count(), 2)

    def test_validation_rejects_shape_order_and_membership_errors_without_writes(self):
        cases = [
            ({"name": "Empty", "items": []}, "required", "items"),
            ({"name": "Bad", "items": ["not-an-object"]}, "invalid_item", None),
            ({"name": "Bad", "items": [{"position": "1", "workout_id": self.workouts[0].id}]}, "invalid_integer", "position"),
            ({"name": "Bad", "items": [{"position": True, "workout_id": self.workouts[0].id}]}, "invalid_integer", "position"),
            ({"name": "Bad", "items": [{"position": 1, "workout_id": "1"}]}, "invalid_integer", "workout_id"),
            ({"name": "Bad", "items": [{"position": 2_147_483_648, "workout_id": self.workouts[0].id}]}, "out_of_range", "position"),
            ({"name": "Bad", "items": [{"position": 1, "workout_id": 2_147_483_648}]}, "out_of_range", "workout_id"),
            ({"name": "Bad", "items": [
                {"position": 1, "workout_id": self.workouts[0].id},
                {"position": 1, "workout_id": self.workouts[1].id},
            ]}, "duplicate_position", "position"),
            ({"name": "Bad", "items": [
                {"position": 1, "workout_id": self.workouts[0].id},
                {"position": 2, "workout_id": self.workouts[0].id},
            ]}, "duplicate_workout", "workout_id"),
            ({"name": "Bad", "items": [
                {"position": 1, "workout_id": self.workouts[0].id},
                {"position": 3, "workout_id": self.workouts[1].id},
            ]}, "non_contiguous_positions", "position"),
            ({"name": "Bad", "items": [{"position": 1, "workout_id": 999999}]}, "workout_not_found", "workout_id"),
        ]
        for payload, code, field in cases:
            with self.subTest(code=code, field=field):
                response = self.client.post("/api/workout-programs/", payload, format="json")
                self.assertEqual(response.status_code, 400)
                matching = [error for error in response.data["errors"] if error["code"] == code]
                self.assertTrue(matching)
                self.assertEqual(matching[0]["field"], field)
                self.assertFalse(WorkoutProgram.objects.exists())
                self.assertFalse(WorkoutProgramItem.objects.exists())

    def test_item_limit_rejects_1001_and_accepts_1000(self):
        too_many = self.client.post("/api/workout-programs/", {
            "name": "Too Large",
            "items": [{"position": index, "workout_id": self.workouts[0].id} for index in range(1, 1002)],
        }, format="json")
        self.assertEqual(too_many.status_code, 400)
        self.assertEqual(too_many.data["errors"][0]["code"], "item_limit_exceeded")
        self.assertFalse(WorkoutProgram.objects.exists())

        bulk_workouts = [
            Workout(name=f"Bounded {index:04d}", normalized_name=f"bounded {index:04d}")
            for index in range(1000)
        ]
        Workout.objects.bulk_create(bulk_workouts)
        accepted = self.client.post("/api/workout-programs/", {
            "name": "Maximum",
            "items": [
                {"position": index, "workout_id": workout.id}
                for index, workout in enumerate(bulk_workouts, start=1)
            ],
        }, format="json")
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(len(accepted.data["items"]), 1000)
        self.assertEqual(WorkoutProgramItem.objects.count(), 1000)

    def test_list_is_paginated_and_returns_items_in_position_order(self):
        programs = [
            WorkoutProgram(name=f"Program {index:03d}", normalized_name=f"program {index:03d}")
            for index in range(51)
        ]
        WorkoutProgram.objects.bulk_create(programs)
        first = WorkoutProgram.objects.order_by("name").first()
        WorkoutProgramItem.objects.create(workout_program=first, workout=self.workouts[1], position=2)
        WorkoutProgramItem.objects.create(workout_program=first, workout=self.workouts[0], position=1)

        page_one = self.client.get("/api/workout-programs/?page_size=50")
        page_two = self.client.get("/api/workout-programs/?page=2&page_size=50")

        self.assertEqual(page_one.status_code, 200)
        self.assertEqual(page_one.data["count"], 51)
        self.assertEqual(len(page_one.data["results"]), 50)
        self.assertEqual(len(page_two.data["results"]), 1)
        self.assertEqual([item["position"] for item in page_one.data["results"][0]["items"]], [1, 2])

    def test_models_are_not_registered_in_admin_and_legacy_program_route_is_unchanged(self):
        self.assertFalse(admin.site.is_registered(WorkoutProgram))
        self.assertFalse(admin.site.is_registered(WorkoutProgramItem))
        athlete = Athlete.objects.create(name="Legacy Athlete")
        Program.objects.create(
            athlete=athlete,
            exercise="Legacy Squat",
            target_sets=3,
            target_reps=5,
            target_weight_lbs=100,
        )

        response = self.client.get("/api/programs/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["exercise"], "Legacy Squat")

    def test_only_program_name_constraint_is_translated_to_409(self):
        class ConstraintViolation(Exception):
            pass

        name_cause = ConstraintViolation()
        name_cause.diag = SimpleNamespace(constraint_name="workout_program_normalized_name_unique")
        name_error = IntegrityError("duplicate program")
        name_error.__cause__ = name_cause
        with patch("event_handler.views.create_workout_program", side_effect=name_error):
            conflict = self.client.post("/api/workout-programs/", self.valid_payload(), format="json")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.data["code"], "workout_program_name_conflict")

        other_cause = ConstraintViolation()
        other_cause.diag = SimpleNamespace(constraint_name="workout_program_item_unique_position")
        other_error = IntegrityError("unrelated constraint")
        other_error.__cause__ = other_cause
        with patch("event_handler.views.create_workout_program", side_effect=other_error):
            with self.assertRaises(IntegrityError):
                self.client.post("/api/workout-programs/", self.valid_payload(), format="json")


class WorkoutProgramConstraintTests(TransactionTestCase):
    def setUp(self):
        self.workout_one = Workout.objects.create(name="One")
        self.workout_two = Workout.objects.create(name="Two")
        self.program = WorkoutProgram.objects.create(name="Program")
        WorkoutProgramItem.objects.create(
            workout_program=self.program,
            workout=self.workout_one,
            position=1,
        )

    def test_database_rejects_duplicate_position_and_workout_membership(self):
        invalid_items = [
            {"workout": self.workout_two, "position": 1},
            {"workout": self.workout_one, "position": 2},
        ]
        for item in invalid_items:
            with self.subTest(item=item):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    WorkoutProgramItem.objects.create(workout_program=self.program, **item)


class AthleteWorkoutAssignmentApiTests(TestCase):
    device_id = "10000000-0000-4000-8000-000000000001"

    def setUp(self):
        self.coach = User.objects.create_user(
            username="athlete-workout-coach", password="test-only", is_staff=True,
        )
        self.non_coach = User.objects.create_user(
            username="athlete-workout-viewer", password="test-only",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.coach)
        self.athlete = Athlete.objects.create(
            name="Assigned Athlete", nfc_tag_id="private-nfc", notes="private note",
        )
        self.other_athlete = Athlete.objects.create(name="Other Athlete")
        self.session = Session.objects.create(label="Assignment Day")
        self.session.athletes.add(self.athlete, self.other_athlete)
        self.screen = RackScreen.objects.create(device_id=self.device_id, rack_number=1)
        self.rack_workout = Workout.objects.create(name="Rack Workout")
        self.rack_exercise = WorkoutExercise.objects.create(
            workout=self.rack_workout,
            exercise="Rack squat",
            position=1,
            sets=3,
            reps=5,
            default_weight_lbs=100,
            velocity_min=0.5,
            velocity_max=0.8,
        )
        self.athlete_workout = Workout.objects.create(name="Athlete Workout")
        self.athlete_exercise = WorkoutExercise.objects.create(
            workout=self.athlete_workout,
            exercise="Athlete press",
            position=1,
            sets=4,
            reps=6,
            default_weight_lbs=75,
            velocity_min=0.4,
            velocity_max=0.7,
        )
        self.second_exercise = WorkoutExercise.objects.create(
            workout=self.athlete_workout,
            exercise="Athlete row",
            position=2,
            sets=2,
            reps=10,
            default_weight_lbs=50,
        )
        self.program = WorkoutProgram.objects.create(name="Athlete Program")
        self.program_item = WorkoutProgramItem.objects.create(
            workout_program=self.program,
            workout=self.athlete_workout,
            position=1,
        )

    def assignment_url(self, athlete=None):
        return f"/api/athletes/{(athlete or self.athlete).id}/workout-assignment/"

    def override_url(self, exercise=None, athlete=None):
        return (
            f"/api/athletes/{(athlete or self.athlete).id}/workout-exercises/"
            f"{(exercise or self.athlete_exercise).id}/override/"
        )

    def assign_athlete(self, payload=None):
        return self.client.put(
            self.assignment_url(),
            payload or {"workout_program_id": self.program.id},
            format="json",
        )

    def identify(self):
        return APIClient().put(
            "/api/racks/1/athlete/",
            {"device_id": self.device_id, "athlete_id": self.athlete.id},
            format="json",
        )

    def test_assignment_and_override_routes_require_coach_and_are_private(self):
        regular = APIClient()
        regular.force_authenticate(self.non_coach)
        routes = [self.assignment_url(), self.override_url()]
        for route in routes:
            for method in ("get", "delete"):
                with self.subTest(route=route, method=method, identity="anonymous"):
                    response = getattr(APIClient(), method)(route)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response["Cache-Control"], "private, no-store")
                with self.subTest(route=route, method=method, identity="non_coach"):
                    response = getattr(regular, method)(route)
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_whole_program_assignment_get_replace_and_delete(self):
        other_program = WorkoutProgram.objects.create(name="Other Athlete Program")
        WorkoutProgramItem.objects.create(
            workout_program=other_program,
            workout=self.rack_workout,
            position=1,
        )
        assigned = self.assign_athlete()
        loaded = self.client.get(self.assignment_url())
        replaced = self.assign_athlete({"workout_program_id": other_program.id})
        deleted = self.client.delete(self.assignment_url())

        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(assigned.data["type"], "workout_program")
        self.assertEqual(loaded.data["workout_program"]["id"], self.program.id)
        self.assertEqual(replaced.status_code, 200)
        self.assertEqual(replaced.data["workout_program"]["id"], other_program.id)
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(AthleteWorkoutProgramAssignment.objects.exists())
        self.assertEqual(MonitoringEvent.objects.filter(reason="athlete_assignment_changed").count(), 3)

    def test_assignment_validation_is_stable_and_atomic(self):
        empty_program = WorkoutProgram.objects.create(name="Empty Program")
        invalid_cases = [
            ({"workout_program_id": "bad"}, 400, "malformed_request"),
            ({"workout_program_id": 999999}, 404, "workout_program_not_found"),
            ({"workout_program_id": self.program.id, "workout_id": self.athlete_workout.id}, 400, "unknown_fields"),
            ({"workout_program_id": empty_program.id}, 409, "workout_program_incomplete"),
        ]
        for payload, status, code in invalid_cases:
            with self.subTest(code=code):
                response = self.assign_athlete(payload)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.data["code"], code)
                self.assertFalse(AthleteWorkoutProgramAssignment.objects.exists())

    def test_no_rack_assignment_roster_identity_and_effective_workout_are_private(self):
        self.assign_athlete()

        before = APIClient().get("/api/racks/1/state/")
        identified = self.identify()

        self.assertEqual(before.data["active_athletes"], [{"id": self.athlete.id, "name": self.athlete.name}])
        self.assertTrue(before.data["identity_available"])
        self.assertIsNone(before.data["assignment"])
        self.assertIsNone(before.data["effective_workout"])
        self.assertIsNone(before.data["effective_assignment_source"])
        self.assertEqual(identified.status_code, 200)
        self.assertIsNone(identified.data["assignment"])
        self.assertEqual(identified.data["effective_workout"]["id"], self.athlete_workout.id)
        self.assertEqual(identified.data["effective_assignment_source"], "athlete_program")
        self.assertEqual(identified.data["progress"]["program"]["id"], self.program.id)
        self.assertNotContains(identified, "private-nfc")
        self.assertNotContains(identified, "private note")
        self.assertNotContains(identified, "assigned_workout")
        self.assertNotContains(identified, "assigned_program_item")
        state = RackWorkoutState.objects.get(rack_number=1)
        self.assertIsNone(state.assigned_workout_id)
        self.assertEqual(state.selected_athlete_id, self.athlete.id)

    def test_other_athlete_assignment_enables_roster_without_cross_athlete_details(self):
        assigned_other = self.client.put(
            self.assignment_url(self.other_athlete),
            {"workout_program_id": self.program.id},
            format="json",
        )

        state = APIClient().get("/api/racks/1/state/")
        rejected = self.identify()

        self.assertEqual(assigned_other.status_code, 200)
        self.assertEqual(state.data["active_athletes"], [{"id": self.other_athlete.id, "name": self.other_athlete.name}])
        self.assertIsNone(state.data["assignment"])
        self.assertIsNone(state.data["effective_workout"])
        self.assertNotContains(state, "Athlete Workout")
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.data["code"], "athlete_program_required")

    def test_athlete_program_drives_execution_and_cannot_be_deleted_after_progress(self):
        coach = self.client
        coach.put(
            "/api/racks/1/assignment/",
            {"workout_id": self.rack_workout.id},
            format="json",
        )
        self.assign_athlete()
        self.identify()

        athlete_effective = APIClient().get("/api/racks/1/state/")
        deleted = coach.delete(self.assignment_url())
        restored = APIClient().get("/api/racks/1/state/")

        self.assertEqual(athlete_effective.data["effective_workout"]["id"], self.athlete_workout.id)
        self.assertEqual(athlete_effective.data["effective_assignment_source"], "athlete_program")
        self.assertEqual(deleted.status_code, 409)
        self.assertEqual(deleted.data["code"], "athlete_progress_active")
        self.assertEqual(restored.data["progress"]["program"]["id"], self.program.id)
        self.assertIsNone(restored.data["assignment"])

    def test_no_assignment_reports_identity_unavailable_and_no_source(self):
        response = APIClient().get("/api/racks/1/state/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["identity_available"])
        self.assertEqual(response.data["active_athletes"], [])
        self.assertIsNone(response.data["effective_workout"])
        self.assertIsNone(response.data["effective_assignment_source"])

    def test_delete_after_sign_in_is_blocked_and_preserves_identity(self):
        self.assign_athlete()
        self.identify()

        response = self.client.delete(self.assignment_url())

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "athlete_progress_active")
        self.assertEqual(RackWorkoutState.objects.get(rack_number=1).selected_athlete_id, self.athlete.id)

    def test_sparse_overrides_apply_independently_and_delete_restores_defaults(self):
        self.assign_athlete()
        sets_override = self.client.patch(
            self.override_url(), {"sets": 7}, format="json",
        )
        weight_override = self.client.patch(
            self.override_url(), {"weight_lbs": 95}, format="json",
        )
        effective = self.client.get(self.assignment_url())

        target = effective.data["workout_program"]["items"][0]["workout"]["exercises"][0]
        self.assertEqual(sets_override.status_code, 200)
        self.assertEqual(weight_override.status_code, 200)
        self.assertEqual(target["sets"], 7)
        self.assertEqual(target["reps"], 6)
        self.assertEqual(target["default_weight_lbs"], 95)
        self.assertEqual(target["velocity_min"], 0.4)
        self.assertEqual(target["velocity_max"], 0.7)
        self.assertNotContains(effective, '"overrides"')

        inherited = self.client.patch(
            self.override_url(), {"sets": None}, format="json",
        )
        self.assertEqual(inherited.status_code, 200)
        self.assertIsNone(inherited.data["sets"])
        after_inherit = self.client.get(self.assignment_url())
        self.assertEqual(after_inherit.data["workout_program"]["items"][0]["workout"]["exercises"][0]["sets"], 4)

        removed = self.client.delete(self.override_url())
        restored = self.client.get(self.assignment_url())
        self.assertEqual(removed.status_code, 204)
        restored_target = restored.data["workout_program"]["items"][0]["workout"]["exercises"][0]
        self.assertEqual(restored_target["sets"], 4)
        self.assertEqual(restored_target["default_weight_lbs"], 75)

    def test_override_validation_rejects_invalid_empty_unknown_and_wrong_workout(self):
        self.assign_athlete()
        invalid_cases = [
            ({"sets": 0}, "override_validation_failed"),
            ({"reps": True}, "override_validation_failed"),
            ({"weight_lbs": "NaN"}, "override_validation_failed"),
            ({"sets": None}, "empty_override"),
            ({"exercise": "changed"}, "unknown_fields"),
            ({"velocity_min": 0.1}, "unknown_fields"),
        ]
        for payload, code in invalid_cases:
            with self.subTest(code=code, payload=payload):
                response = self.client.patch(self.override_url(), payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["code"], code)
                self.assertFalse(AthleteWorkoutExerciseOverride.objects.exists())

        wrong = self.client.patch(
            self.override_url(self.rack_exercise), {"sets": 2}, format="json",
        )
        self.assertEqual(wrong.status_code, 409)
        self.assertEqual(wrong.data["code"], "exercise_not_in_athlete_workout")

    def test_active_progress_blocks_assignment_and_override_mutations(self):
        self.assign_athlete()
        identified = self.identify()
        progress = AthleteDayProgress.objects.get(id=identified.data["progress"]["id"])
        Set.objects.create(
            session=self.session,
            athlete=self.athlete,
            rack_number=1,
            exercise="Athlete press",
            set_number=1,
            athlete_day_progress=progress,
            workout_program_item=self.program_item,
            workout_exercise=self.athlete_exercise,
        )

        assignment = self.assign_athlete()
        override = self.client.patch(self.override_url(), {"sets": 8}, format="json")
        deletion = self.client.delete(self.assignment_url())

        for response in (assignment, override, deletion):
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data["code"], "athlete_progress_active")
        current = AthleteWorkoutProgramAssignment.objects.get(athlete=self.athlete)
        self.assertEqual(current.workout_program_id, self.program.id)
        self.assertFalse(AthleteWorkoutExerciseOverride.objects.exists())

    def test_identical_assignment_mutation_is_blocked_after_progress_starts(self):
        self.assign_athlete()
        self.identify()
        event_count = MonitoringEvent.objects.filter(reason="athlete_assignment_changed").count()
        response = self.assign_athlete()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "athlete_progress_active")
        self.assertEqual(
            AthleteWorkoutProgramAssignment.objects.get(athlete=self.athlete).workout_program_id,
            self.program.id,
        )
        self.assertEqual(MonitoringEvent.objects.filter(reason="athlete_assignment_changed").count(), event_count)


class AthleteWorkoutConstraintTests(TransactionTestCase):
    def test_assignment_exactly_one_and_targets_are_protected(self):
        athlete = Athlete.objects.create(name="Constraint Athlete")
        workout = Workout.objects.create(name="Constraint Workout")
        program = WorkoutProgram.objects.create(name="Constraint Program")
        item = WorkoutProgramItem.objects.create(
            workout_program=program,
            workout=workout,
            position=1,
        )
        invalid = [
            {},
            {"assigned_workout": workout, "assigned_program_item": item},
        ]
        for fields in invalid:
            with self.subTest(fields=fields):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    AthleteWorkoutAssignment.objects.create(athlete=athlete, **fields)

        assignment = AthleteWorkoutAssignment.objects.create(
            athlete=athlete,
            assigned_workout=workout,
        )
        with self.assertRaises(ProtectedError):
            workout.delete()
        assignment.delete()

    def test_override_constraints_unique_nonempty_positive_and_finite(self):
        athlete = Athlete.objects.create(name="Constraint Athlete")
        workout = Workout.objects.create(name="Constraint Workout")
        exercise = WorkoutExercise.objects.create(
            workout=workout,
            exercise="Squat",
            position=1,
            sets=1,
            reps=1,
            default_weight_lbs=0,
        )
        invalid = [
            {},
            {"sets": 0},
            {"reps": 0},
            {"weight_lbs": float("nan")},
            {"weight_lbs": float("inf")},
        ]
        for fields in invalid:
            with self.subTest(fields=fields):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    AthleteWorkoutExerciseOverride.objects.create(
                        athlete=athlete,
                        workout_exercise=exercise,
                        **fields,
                    )
        override = AthleteWorkoutExerciseOverride.objects.create(
            athlete=athlete,
            workout_exercise=exercise,
            sets=2,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            AthleteWorkoutExerciseOverride.objects.create(
                athlete=athlete,
                workout_exercise=exercise,
                reps=2,
            )
        exercise.delete()
        self.assertFalse(AthleteWorkoutExerciseOverride.objects.filter(id=override.id).exists())

    def test_athlete_delete_cascades_assignment_and_override(self):
        athlete = Athlete.objects.create(name="Cascade Athlete")
        workout = Workout.objects.create(name="Cascade Workout")
        exercise = WorkoutExercise.objects.create(
            workout=workout,
            exercise="Squat",
            position=1,
            sets=1,
            reps=1,
            default_weight_lbs=0,
        )
        AthleteWorkoutAssignment.objects.create(athlete=athlete, assigned_workout=workout)
        AthleteWorkoutExerciseOverride.objects.create(
            athlete=athlete,
            workout_exercise=exercise,
            sets=2,
        )
        athlete.delete()
        self.assertFalse(AthleteWorkoutAssignment.objects.exists())
        self.assertFalse(AthleteWorkoutExerciseOverride.objects.exists())


class RackRegistrationTests(TestCase):
    device_id = "48f01941-a0a5-4566-8e10-f187483318fd"

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_registration_requires_canonical_uuid_and_does_not_cache_identity(self):
        invalid = APIClient().post("/api/racks/register/", {"device_id": "not-a-uuid"}, format="json")
        created = APIClient().post("/api/racks/register/", {"device_id": self.device_id}, format="json")

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.data["code"], "invalid_device_id")
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created["Cache-Control"], "private, no-store")
        self.assertEqual(RackScreen.objects.count(), 1)

    def test_post_poll_keeps_device_id_out_of_url_and_refreshes_last_seen(self):
        screen = RackScreen.objects.create(device_id=self.device_id, rack_number=3)
        old_seen = screen.last_seen

        registered = APIClient().post("/api/racks/register/", {"device_id": self.device_id}, format="json")
        polled = APIClient().post("/api/racks/racknumber/", {"device_id": self.device_id}, format="json")

        screen.refresh_from_db()
        self.assertEqual(registered.status_code, 200)
        self.assertGreater(screen.last_seen, old_seen)
        self.assertEqual(polled.data, {"rack_number": 3})
        self.assertEqual(polled["Cache-Control"], "private, no-store")

    def test_polling_rejects_query_string_identity(self):
        response = APIClient().get(f"/api/racks/racknumber/?device_id={self.device_id}")

        self.assertEqual(response.status_code, 405)

    def test_registration_and_read_throttles_are_separate_per_client(self):
        client = APIClient()
        for index in range(30):
            device_id = f"00000000-0000-4000-8000-{index:012d}"
            self.assertEqual(
                client.post("/api/racks/register/", {"device_id": device_id}, format="json", REMOTE_ADDR="10.0.0.1").status_code,
                200,
            )
        blocked = client.post(
            "/api/racks/register/",
            {"device_id": "00000000-0000-4000-8000-999999999999"},
            format="json",
            REMOTE_ADDR="10.0.0.1",
        )
        read = client.post(
            "/api/racks/racknumber/",
            {"device_id": "00000000-0000-4000-8000-000000000000"},
            format="json",
            REMOTE_ADDR="10.0.0.1",
        )
        other_client = client.post(
            "/api/racks/register/",
            {"device_id": "10000000-0000-4000-8000-000000000000"},
            format="json",
            REMOTE_ADDR="10.0.0.2",
        )

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(read.status_code, 200)
        self.assertEqual(other_client.status_code, 200)


class RackWorkoutStateApiTests(TestCase):
    def setUp(self):
        self.coach = User.objects.create_user(
            username="rack-coach", password="test-only", is_staff=True,
        )
        self.non_coach = User.objects.create_user(
            username="rack-athlete", password="test-only",
        )
        self.athlete = Athlete.objects.create(
            name="Jordan Lee", nfc_tag_id="private-nfc", notes="private note",
        )
        self.other_athlete = Athlete.objects.create(name="Casey Morgan")
        self.session = Session.objects.create(label="Strength Day")
        self.session.athletes.add(self.athlete)
        self.program = Program.objects.create(
            athlete=self.athlete,
            exercise="Back squat",
            target_sets=5,
            target_reps=3,
            target_weight_lbs=225,
            velocity_zone_min=0.7,
            velocity_zone_max=0.9,
        )
        self.non_velocity_program = Program.objects.create(
            athlete=self.athlete,
            exercise="Split squat",
            target_sets=3,
            target_reps=8,
            target_weight_lbs=45,
            velocity_zone_min=None,
            velocity_zone_max=None,
        )
        RackScreen.objects.create(device_id="private-screen", rack_number=1)

    def patch_selection(self, client=None, athlete_id=None, program_id=None):
        client = client or APIClient()
        client.force_authenticate(self.coach)
        return client.patch("/api/racks/1/state/", {
            "athlete_id": athlete_id or self.athlete.id,
            "program_id": program_id or self.program.id,
        }, format="json")

    def test_patch_requires_coach_and_returns_stable_auth_statuses(self):
        payload = {"athlete_id": self.athlete.id, "program_id": self.program.id}
        anonymous = APIClient().patch("/api/racks/1/state/", payload, format="json")
        non_coach_client = APIClient()
        non_coach_client.force_authenticate(self.non_coach)
        forbidden = non_coach_client.patch("/api/racks/1/state/", payload, format="json")

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(forbidden.status_code, 403)
        self.assertFalse(RackWorkoutState.objects.exists())

    def test_get_is_open_private_and_returns_program_and_ready_node_shapes(self):
        Node.objects.create(node_id="node-ready", rack_number=1, is_active=True)
        selected = self.patch_selection()

        response = APIClient().get("/api/racks/1/state/")

        self.assertEqual(selected.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["rack_number"], 1)
        self.assertEqual(response.data["revision"], MonitoringEvent.objects.latest("id").id)
        self.assertEqual(response.data["active_session"], {"id": self.session.id, "label": "Strength Day"})
        self.assertEqual(response.data["selected_athlete"], {"id": self.athlete.id, "name": "Jordan Lee"})
        self.assertEqual(response.data["active_program"]["id"], self.program.id)
        self.assertEqual(len(response.data["programs"]), 2)
        self.assertIsNone(response.data["programs"][1]["velocity_zone_min"])
        self.assertEqual(response.data["node"], {"state": "ready", "node_id": "node-ready"})
        self.assertNotContains(response, "private-nfc")
        self.assertNotContains(response, "private note")
        self.assertNotContains(response, "private-screen")

    def test_get_reports_bounded_node_states_and_unknown_racks(self):
        RackScreen.objects.create(device_id="screen-2", rack_number=2)
        Node.objects.create(node_id="node-inactive", rack_number=2, is_active=False)
        RackScreen.objects.create(device_id="screen-3", rack_number=3)
        Node.objects.create(node_id="node-a", rack_number=3)
        Node.objects.create(node_id="node-b", rack_number=3)
        RackScreen.objects.create(device_id="screen-4", rack_number=4)

        self.assertEqual(APIClient().get("/api/racks/2/state/").data["node"], {
            "state": "inactive", "node_id": None,
        })
        self.assertEqual(APIClient().get("/api/racks/3/state/").data["node"], {
            "state": "conflict", "node_id": None,
        })
        self.assertEqual(APIClient().get("/api/racks/4/state/").data["node"], {
            "state": "unassigned", "node_id": None,
        })
        self.assertEqual(APIClient().get("/api/racks/0/state/").status_code, 404)
        self.assertEqual(APIClient().get("/api/racks/999/state/").status_code, 404)

    def test_patch_validates_selection_and_creates_simulation_owned_event(self):
        self.session.is_simulated = True
        self.session.save(update_fields=["is_simulated"])
        outside_program = Program.objects.create(
            athlete=self.other_athlete,
            exercise="Bench press",
            target_sets=3,
            target_reps=5,
            target_weight_lbs=185,
            velocity_zone_min=0.5,
            velocity_zone_max=0.7,
        )

        mismatch = self.patch_selection(program_id=outside_program.id)
        missing_athlete = self.patch_selection(athlete_id=99999)
        malformed = APIClient()
        malformed.force_authenticate(self.coach)
        malformed_response = malformed.patch(
            "/api/racks/1/state/", {"athlete_id": "bad"}, format="json",
        )
        success = self.patch_selection()

        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(mismatch.data["code"], "program_athlete_mismatch")
        self.assertEqual(missing_athlete.status_code, 404)
        self.assertEqual(missing_athlete.data["code"], "athlete_not_found")
        self.assertEqual(malformed_response.status_code, 400)
        self.assertEqual(malformed_response.data["code"], "malformed_request")
        self.assertEqual(success.status_code, 200)
        event = MonitoringEvent.objects.get(reason="rack_selection_changed")
        self.assertTrue(event.is_simulated)

    def test_patch_rejects_unfinished_set_without_changing_selection(self):
        Set.objects.create(
            session=self.session,
            athlete=self.athlete,
            rack_number=1,
            exercise="Back squat",
            set_number=1,
        )

        response = self.patch_selection()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "unfinished_set")
        self.assertFalse(RackWorkoutState.objects.exists())
        self.assertFalse(MonitoringEvent.objects.exists())

    def test_newest_session_makes_old_selection_stale(self):
        self.patch_selection()
        self.session.ended_at = timezone.now()
        self.session.save(update_fields=["ended_at"])
        newer = Session.objects.create(label="New session")
        newer.athletes.add(self.athlete)

        response = APIClient().get("/api/racks/1/state/")

        self.assertEqual(response.data["active_session"]["id"], newer.id)
        self.assertIsNone(response.data["selected_athlete"])
        self.assertEqual(response.data["programs"], [])
        self.assertIsNone(response.data["active_program"])

    def test_removed_session_member_is_not_exposed_as_selected(self):
        self.patch_selection()
        self.session.athletes.remove(self.athlete)
        coach_client = APIClient()
        coach_client.force_authenticate(self.coach)

        rack = APIClient().get("/api/racks/1/state/")
        room = coach_client.get("/api/room-state/")

        self.assertIsNone(rack.data["selected_athlete"])
        self.assertIsNone(rack.data["active_program"])
        self.assertEqual(rack.data["programs"], [])
        self.assertIsNone(room.data["racks"][0]["selection"])

    def test_room_includes_selection_and_state_only_rack_but_wall_omits_it(self):
        self.patch_selection()
        RackWorkoutState.objects.create(rack_number=5)
        coach_client = APIClient()
        coach_client.force_authenticate(self.coach)

        room = coach_client.get("/api/room-state/")
        wall = APIClient().get("/api/wall-state/")

        self.assertEqual([rack["rack_number"] for rack in room.data["racks"]], [1, 5])
        selected_rack = room.data["racks"][0]
        self.assertEqual(selected_rack["selection"]["athlete"]["id"], self.athlete.id)
        self.assertEqual(selected_rack["selection"]["active_program"]["id"], self.program.id)
        self.assertEqual(room.data["participants"], [{"id": self.athlete.id, "name": self.athlete.name}])
        self.assertIsNone(room.data["racks"][1]["selection"])
        self.assertNotContains(wall, '"selection"')
        self.assertNotContains(wall, "private-screen")


class RackCatalogAssignmentApiTests(TestCase):
    device_id = "48f01941-a0a5-4566-8e10-f187483318fd"

    def setUp(self):
        cache.clear()
        self.coach = User.objects.create_user(
            username="catalog-rack-coach", password="test-only", is_staff=True,
        )
        self.coach_client = APIClient()
        self.coach_client.force_authenticate(self.coach)
        self.athlete = Athlete.objects.create(
            name="Jordan Lee", nfc_tag_id="private-nfc", notes="private note",
        )
        self.other_athlete = Athlete.objects.create(name="Casey Morgan")
        self.outside_athlete = Athlete.objects.create(name="Outside Athlete")
        self.session = Session.objects.create(label="Catalog Day")
        self.session.athletes.add(self.athlete, self.other_athlete)
        self.screen = RackScreen.objects.create(device_id=self.device_id, rack_number=1)
        self.workout = Workout.objects.create(name="Lower Strength")
        WorkoutExercise.objects.create(
            workout=self.workout,
            exercise="Romanian deadlift",
            position=2,
            sets=3,
            reps=8,
            default_weight_lbs=185,
        )
        WorkoutExercise.objects.create(
            workout=self.workout,
            exercise="Back squat",
            position=1,
            sets=4,
            reps=5,
            default_weight_lbs=225,
            velocity_min=0.55,
            velocity_max=0.75,
        )
        self.other_workout = Workout.objects.create(name="Upper Strength")
        self.program = WorkoutProgram.objects.create(name="Full Body")
        self.program_item = WorkoutProgramItem.objects.create(
            workout_program=self.program,
            workout=self.workout,
            position=1,
        )
        AthleteWorkoutProgramAssignment.objects.create(
            athlete=self.athlete,
            workout_program=self.program,
        )
        AthleteWorkoutProgramAssignment.objects.create(
            athlete=self.other_athlete,
            workout_program=self.program,
        )

    def tearDown(self):
        cache.clear()

    def assign(self, payload=None):
        return self.coach_client.put(
            "/api/racks/1/assignment/",
            payload or {"workout_id": self.workout.id},
            format="json",
        )

    def identify(self, athlete=None, device_id=None):
        return APIClient().put(
            "/api/racks/1/athlete/",
            {
                "device_id": device_id or self.device_id,
                "athlete_id": (athlete or self.athlete).id,
            },
            format="json",
        )

    def sign_out(self, device_id=None):
        return APIClient().delete(
            "/api/racks/1/athlete/",
            {"device_id": device_id or self.device_id},
            format="json",
        )

    def test_assignment_requires_coach_and_all_responses_are_private(self):
        non_coach = User.objects.create_user(username="not-coach", password="test-only")
        non_coach_client = APIClient()
        non_coach_client.force_authenticate(non_coach)
        payload = {"workout_id": self.workout.id}

        anonymous = APIClient().put("/api/racks/1/assignment/", payload, format="json")
        forbidden = non_coach_client.put("/api/racks/1/assignment/", payload, format="json")
        malformed = self.coach_client.put(
            "/api/racks/1/assignment/", {"workout_id": "bad"}, format="json",
        )

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(malformed.status_code, 400)
        for response in (anonymous, forbidden, malformed):
            self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertFalse(RackWorkoutState.objects.exists())

    def test_direct_assignment_and_identity_gate_effective_ordered_workout(self):
        assigned = self.assign()
        before_identity = APIClient().get("/api/racks/1/state/")

        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(assigned.data["assignment"], {
            "type": "workout",
            "workout": {"id": self.workout.id, "name": "Lower Strength"},
        })
        self.assertIsNone(before_identity.data["selected_athlete"])
        self.assertIsNone(before_identity.data["effective_workout"])

        identified = self.identify()

        self.assertEqual(identified.status_code, 200)
        self.assertEqual(identified["Cache-Control"], "private, no-store")
        self.assertEqual(identified.data["selected_athlete"], {
            "id": self.athlete.id, "name": "Jordan Lee",
        })
        effective = identified.data["effective_workout"]
        self.assertEqual(effective["id"], self.workout.id)
        self.assertEqual([exercise["position"] for exercise in effective["exercises"]], [1, 2])
        self.assertNotContains(identified, "private-nfc")
        self.assertNotContains(identified, "private note")
        self.assertNotContains(identified, self.device_id)

    def test_program_assignment_requires_included_workout_and_exposes_minimal_identity(self):
        missing_program = self.assign({
            "workout_program_id": 999999,
            "workout_id": self.workout.id,
        })
        not_included = self.assign({
            "workout_program_id": self.program.id,
            "workout_id": self.other_workout.id,
        })
        assigned = self.assign({
            "workout_program_id": self.program.id,
            "workout_id": self.workout.id,
        })

        self.assertEqual(missing_program.status_code, 404)
        self.assertEqual(missing_program.data["code"], "workout_program_not_found")
        self.assertEqual(not_included.status_code, 409)
        self.assertEqual(not_included.data["code"], "workout_not_in_program")
        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(assigned.data["assignment"], {
            "type": "program",
            "program": {"id": self.program.id, "name": "Full Body"},
            "workout": {"id": self.workout.id, "name": "Lower Strength"},
        })
        state = RackWorkoutState.objects.get(rack_number=1)
        self.assertEqual(state.assigned_program_item_id, self.program_item.id)
        self.assertIsNone(state.assigned_workout_id)

    def test_active_athletes_are_capped_ordered_and_privacy_safe(self):
        extra_athletes = [
            Athlete.objects.create(
                name=f"Athlete {index:03d}",
                nfc_tag_id=f"private-nfc-{index}",
                notes=f"private-note-{index}",
            )
            for index in range(101)
        ]
        self.session.athletes.add(*extra_athletes)
        AthleteWorkoutProgramAssignment.objects.bulk_create([
            AthleteWorkoutProgramAssignment(athlete=athlete, workout_program=self.program)
            for athlete in extra_athletes
        ])
        self.assign()

        response = APIClient().get("/api/racks/1/state/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["active_athletes"]), 100)
        self.assertTrue(response.data["active_athletes_truncated"])
        names = [athlete["name"] for athlete in response.data["active_athletes"]]
        self.assertEqual(names, sorted(names))
        self.assertNotContains(response, "private-nfc-")
        self.assertNotContains(response, "private-note-")

    def test_identity_requires_matching_canonical_screen_and_active_athlete(self):
        self.assign()
        invalid_device = self.identify(device_id="not-a-uuid")
        wrong_device = self.identify(device_id="00000000-0000-4000-8000-000000000000")
        outside = self.identify(athlete=self.outside_athlete)

        self.assertEqual(invalid_device.status_code, 400)
        self.assertEqual(invalid_device.data["code"], "invalid_device_id")
        self.assertEqual(wrong_device.status_code, 403)
        self.assertEqual(wrong_device.data["code"], "rack_screen_mismatch")
        self.assertEqual(outside.status_code, 409)
        self.assertEqual(outside.data["code"], "athlete_not_in_active_session")
        self.assertIsNone(RackWorkoutState.objects.get(rack_number=1).selected_athlete_id)

    def test_identity_requires_athlete_program_even_with_legacy_rack_assignment(self):
        AthleteWorkoutProgramAssignment.objects.filter(athlete=self.athlete).delete()
        assigned = self.assign()
        event_count = MonitoringEvent.objects.count()

        response = self.identify()

        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "athlete_program_required")
        persisted = RackWorkoutState.objects.get(rack_number=1)
        self.assertIsNone(persisted.selected_athlete_id)
        self.assertEqual(persisted.assigned_workout_id, self.workout.id)
        self.assertEqual(MonitoringEvent.objects.count(), event_count)

    def test_active_athletes_hidden_without_valid_current_catalog_assignment(self):
        AthleteWorkoutProgramAssignment.objects.all().delete()
        legacy = Program.objects.create(
            athlete=self.athlete,
            exercise="Legacy",
            target_sets=1,
            target_reps=1,
            target_weight_lbs=0,
        )
        states = [
            None,
            RackWorkoutState(rack_number=1, active_session=self.session),
            RackWorkoutState(rack_number=1, active_session=self.session, active_program=legacy),
        ]
        stale = Session.objects.create(label="Ended", ended_at=timezone.now())
        states.append(RackWorkoutState(
            rack_number=1,
            active_session=stale,
            assigned_workout=self.workout,
        ))
        for state in states:
            with self.subTest(state=state):
                RackWorkoutState.objects.filter(rack_number=1).delete()
                if state:
                    state.pk = 1
                    state.save(force_insert=True)
                response = APIClient().get("/api/racks/1/state/")
                self.assertEqual(response.data["active_athletes"], [])
                self.assertFalse(response.data["active_athletes_truncated"])

    def test_assignment_identity_and_signout_are_idempotent_without_duplicate_events(self):
        self.assign()
        self.assign()
        self.identify()
        self.identify()
        signed_out = self.sign_out()
        signed_out_again = self.sign_out()

        self.assertEqual(signed_out.status_code, 200)
        self.assertEqual(signed_out_again.status_code, 200)
        self.assertIsNone(signed_out_again.data["selected_athlete"])
        self.assertEqual(MonitoringEvent.objects.filter(reason="rack_assignment_changed").count(), 1)
        self.assertEqual(MonitoringEvent.objects.filter(reason="rack_identity_changed").count(), 2)

    def test_legacy_rack_assignment_mutation_clears_athlete_driven_identity(self):
        self.assign()
        self.identify()

        identical = self.assign()
        state = RackWorkoutState.objects.get(rack_number=1)
        self.assertEqual(identical.status_code, 200)
        self.assertIsNone(identical.data["selected_athlete"])
        self.assertIsNone(state.selected_athlete_id)

        self.identify()
        changed = self.assign({"workout_id": self.other_workout.id})
        state.refresh_from_db()

        self.assertEqual(changed.status_code, 200)
        self.assertIsNone(changed.data["selected_athlete"])
        self.assertIsNone(changed.data["effective_workout"])
        self.assertIsNone(state.selected_athlete_id)
        self.assertEqual(state.assigned_workout_id, self.other_workout.id)
        self.assertEqual(MonitoringEvent.objects.filter(reason="rack_assignment_changed").count(), 3)

    def test_unfinished_set_blocks_actual_assignment_identity_and_signout_changes(self):
        self.assign()
        self.identify()
        Set.objects.create(
            session=self.session,
            athlete=self.athlete,
            rack_number=1,
            exercise="Back squat",
            set_number=1,
        )

        same_assignment = self.assign()
        same_identity = self.identify()
        changed_assignment = self.assign({"workout_id": self.other_workout.id})
        changed_identity = self.identify(athlete=self.other_athlete)
        signout = self.sign_out()

        self.assertEqual(same_identity.status_code, 200)
        for response in (same_assignment, changed_assignment, changed_identity, signout):
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data["code"], "unfinished_set")
        state = RackWorkoutState.objects.get(rack_number=1)
        self.assertIsNone(state.assigned_workout_id)
        self.assertEqual(state.selected_athlete_id, self.athlete.id)

    def test_catalog_and_legacy_transitions_clear_opposite_state(self):
        legacy = Program.objects.create(
            athlete=self.athlete,
            exercise="Legacy squat",
            target_sets=3,
            target_reps=5,
            target_weight_lbs=100,
        )
        legacy_selected = self.coach_client.patch("/api/racks/1/state/", {
            "athlete_id": self.athlete.id,
            "program_id": legacy.id,
        }, format="json")
        catalog = self.assign()
        self.identify()
        legacy_again = self.coach_client.patch("/api/racks/1/state/", {
            "athlete_id": self.athlete.id,
            "program_id": legacy.id,
        }, format="json")

        self.assertEqual(legacy_selected.status_code, 200)
        self.assertEqual(catalog.status_code, 200)
        state = RackWorkoutState.objects.get(rack_number=1)
        self.assertEqual(legacy_again.status_code, 200)
        self.assertEqual(state.active_program_id, legacy.id)
        self.assertIsNone(state.assigned_workout_id)
        self.assertIsNone(state.assigned_program_item_id)
        self.assertIsNone(state.selected_athlete_id)

    def test_session_end_and_screen_reassignment_clear_identity(self):
        self.assign()
        self.identify()

        ended = self.coach_client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")

        self.assertEqual(ended.status_code, 200)
        self.assertIsNone(RackWorkoutState.objects.get(rack_number=1).selected_athlete_id)
        self.assertTrue(MonitoringEvent.objects.filter(reason="session_ended").exists())

        new_session = Session.objects.create(label="New Day")
        new_session.athletes.add(self.athlete, self.other_athlete)
        self.assign()
        self.identify()
        RackWorkoutState.objects.create(
            rack_number=2,
            active_session=new_session,
            assigned_workout=self.other_workout,
            selected_athlete=self.other_athlete,
        )
        reassigned = self.coach_client.patch(
            f"/api/racks/{self.device_id}/", {"rack_number": 2}, format="json",
        )

        self.assertEqual(reassigned.status_code, 200)
        self.assertIsNone(RackWorkoutState.objects.get(rack_number=1).selected_athlete_id)
        self.assertIsNone(RackWorkoutState.objects.get(rack_number=2).selected_athlete_id)
        self.assertTrue(MonitoringEvent.objects.filter(reason="rack_screen_reassigned").exists())

    def test_screen_reassignment_rejects_unfinished_sets_without_clearing_identity(self):
        self.assign()
        self.identify()
        Set.objects.create(
            session=self.session,
            athlete=self.athlete,
            rack_number=1,
            exercise="Back squat",
            set_number=1,
        )

        response = self.coach_client.patch(
            f"/api/racks/{self.device_id}/", {"rack_number": 2}, format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "unfinished_set")
        self.screen.refresh_from_db()
        self.assertEqual(self.screen.rack_number, 1)
        self.assertEqual(RackWorkoutState.objects.get(rack_number=1).selected_athlete_id, self.athlete.id)

    def test_identity_endpoint_is_throttled(self):
        self.assign()
        client = APIClient()
        payload = {"device_id": self.device_id, "athlete_id": self.athlete.id}
        for _ in range(120):
            self.assertEqual(
                client.put(
                    "/api/racks/1/athlete/", payload, format="json", REMOTE_ADDR="10.0.0.9",
                ).status_code,
                200,
            )
        blocked = client.put(
            "/api/racks/1/athlete/", payload, format="json", REMOTE_ADDR="10.0.0.9",
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked["Cache-Control"], "private, no-store")

    def test_identity_put_and_delete_require_exactly_one_rack_screen(self):
        self.assign()
        duplicate_id = "00000000-0000-4000-8000-000000000001"
        duplicate = RackScreen.objects.create(device_id=duplicate_id, rack_number=1)

        put_conflict = self.identify()
        delete_conflict = self.sign_out()

        for response in (put_conflict, delete_conflict):
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data["code"], "rack_screen_conflict")
        duplicate.delete()
        self.screen.rack_number = 2
        self.screen.save(update_fields=["rack_number"])

        stale_put = self.identify()
        stale_delete = self.sign_out()

        for response in (stale_put, stale_delete):
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data["code"], "rack_screen_conflict")
        self.assertIsNone(RackWorkoutState.objects.get(rack_number=1).selected_athlete_id)

    def test_session_end_rejects_unfinished_set_and_preserves_session_and_identity(self):
        self.assign()
        self.identify()
        unfinished = Set.objects.create(
            session=self.session,
            athlete=self.athlete,
            rack_number=1,
            exercise="Back squat",
            set_number=1,
        )

        response = self.coach_client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "unfinished_set")
        self.session.refresh_from_db()
        self.assertIsNone(self.session.ended_at)
        self.assertEqual(RackWorkoutState.objects.get(rack_number=1).selected_athlete_id, self.athlete.id)
        self.assertFalse(MonitoringEvent.objects.filter(reason="session_ended").exists())
        self.assertTrue(Set.objects.filter(id=unfinished.id, ended_at=None).exists())

    def test_session_end_rejects_unfinished_set_on_affected_rack_from_other_session(self):
        self.assign()
        self.identify()
        older_session = Session.objects.create(label="Older", ended_at=timezone.now())
        Set.objects.create(
            session=older_session,
            athlete=self.athlete,
            rack_number=1,
            exercise="Back squat",
            set_number=1,
        )

        response = self.coach_client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "unfinished_set")
        self.session.refresh_from_db()
        self.assertIsNone(self.session.ended_at)
        self.assertEqual(RackWorkoutState.objects.get(rack_number=1).selected_athlete_id, self.athlete.id)

    def test_session_end_retries_new_rack_association_then_finds_other_session_set(self):
        self.assign()
        self.identify()
        older_session = Session.objects.create(label="Older", ended_at=timezone.now())
        Set.objects.create(
            session=older_session,
            athlete=self.athlete,
            rack_number=2,
            exercise="Back squat",
            set_number=1,
        )
        associated = False

        def associate_rack_during_first_lock(_rack_number):
            nonlocal associated
            if not associated:
                associated = True
                RackWorkoutState.objects.create(
                    rack_number=2,
                    active_session=self.session,
                    assigned_workout=self.other_workout,
                )

        with patch(
            "event_handler.services.training_days.lock_rack_number",
            side_effect=associate_rack_during_first_lock,
        ):
            response = self.coach_client.patch(
                f"/api/sessions/{self.session.id}/", {}, format="json",
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "unfinished_set")
        self.session.refresh_from_db()
        self.assertIsNone(self.session.ended_at)
        self.assertEqual(RackWorkoutState.objects.get(rack_number=1).selected_athlete_id, self.athlete.id)

    def test_screen_reassignment_takes_advisory_locks_before_row_locks(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.coach_client.patch(
                f"/api/racks/{self.device_id}/", {"rack_number": 2}, format="json",
            )

        self.assertEqual(response.status_code, 200)
        sql = [query["sql"] for query in queries.captured_queries]
        advisory_index = next(
            index for index, statement in enumerate(sql)
            if "pg_advisory_xact_lock" in statement
        )
        screen_lock_index = next(
            index for index, statement in enumerate(sql)
            if 'FROM "event_handler_rackscreen"' in statement and "FOR UPDATE" in statement
        )
        state_lock_index = next(
            index for index, statement in enumerate(sql)
            if 'FROM "event_handler_rackworkoutstate"' in statement and "FOR UPDATE" in statement
        )
        self.assertLess(advisory_index, screen_lock_index)
        self.assertLess(advisory_index, state_lock_index)

    def test_screen_reassignment_revalidates_optimistic_old_rack_and_retries(self):
        changed = False

        def move_during_first_lock(_rack_number):
            nonlocal changed
            if not changed:
                changed = True
                RackScreen.objects.filter(id=self.screen.id).update(rack_number=3)

        with patch("event_handler.views._lock_rack_number", side_effect=move_during_first_lock) as lock:
            response = self.coach_client.patch(
                f"/api/racks/{self.device_id}/", {"rack_number": 2}, format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.screen.refresh_from_db()
        self.assertEqual(self.screen.rack_number, 2)
        self.assertGreaterEqual(lock.call_count, 3)


class RackCatalogAssignmentConstraintTests(TransactionTestCase):
    def test_database_rejects_multiple_assignment_modes(self):
        athlete = Athlete.objects.create(name="Legacy Athlete")
        legacy = Program.objects.create(
            athlete=athlete,
            exercise="Legacy",
            target_sets=1,
            target_reps=1,
            target_weight_lbs=0,
        )
        workout = Workout.objects.create(name="Catalog")
        program = WorkoutProgram.objects.create(name="Catalog Program")
        item = WorkoutProgramItem.objects.create(
            workout_program=program,
            workout=workout,
            position=1,
        )
        invalid_states = [
            {"active_program": legacy, "assigned_workout": workout},
            {"active_program": legacy, "assigned_program_item": item},
            {"assigned_workout": workout, "assigned_program_item": item},
        ]
        for rack_number, fields in enumerate(invalid_states, start=1):
            with self.subTest(fields=fields):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    RackWorkoutState.objects.create(rack_number=rack_number, **fields)

    def test_database_requires_active_nonlegacy_context_for_selected_athlete(self):
        athlete = Athlete.objects.create(name="Selected")
        session = Session.objects.create(label="Day")
        workout = Workout.objects.create(name="Workout")
        legacy = Program.objects.create(
            athlete=athlete,
            exercise="Legacy",
            target_sets=1,
            target_reps=1,
            target_weight_lbs=0,
        )
        invalid_states = [
            {"selected_athlete": athlete},
            {"assigned_workout": workout, "selected_athlete": athlete},
            {
                "active_session": session,
                "active_program": legacy,
                "selected_athlete": athlete,
            },
        ]
        for rack_number, fields in enumerate(invalid_states, start=10):
            with self.subTest(fields=fields):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    RackWorkoutState.objects.create(rack_number=rack_number, **fields)

        valid = RackWorkoutState.objects.create(
            rack_number=20,
            active_session=session,
            selected_athlete=athlete,
        )
        self.assertEqual(valid.selected_athlete_id, athlete.id)

    def test_assigned_catalog_rows_are_protected_from_deletion(self):
        session = Session.objects.create(label="Day")
        direct_workout = Workout.objects.create(name="Direct")
        program_workout = Workout.objects.create(name="Program Workout")
        program = WorkoutProgram.objects.create(name="Program")
        item = WorkoutProgramItem.objects.create(
            workout_program=program,
            workout=program_workout,
            position=1,
        )
        RackWorkoutState.objects.create(
            rack_number=30,
            active_session=session,
            assigned_workout=direct_workout,
        )
        RackWorkoutState.objects.create(
            rack_number=31,
            active_session=session,
            assigned_program_item=item,
        )

        with self.assertRaises(ProtectedError):
            direct_workout.delete()
        with self.assertRaises(ProtectedError):
            item.delete()


class RackSessionConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self._request_threads = []
        self.coach = User.objects.create_user(
            username="race-coach", password="test-only", is_staff=True,
        )
        self.athlete = Athlete.objects.create(name="Race Athlete")
        self.session = Session.objects.create(label="Race Day")
        self.session.athletes.add(self.athlete)
        self.node = Node.objects.create(node_id="race-node", rack_number=1)
        RackScreen.objects.create(
            device_id="00000000-0000-4000-8000-000000000010",
            rack_number=1,
        )
        self.workout = Workout.objects.create(name="Race Workout")
        RackWorkoutState.objects.create(
            rack_number=1,
            active_session=self.session,
            assigned_workout=self.workout,
        )

    def set_payload(self):
        return {
            "session": self.session.id,
            "athlete": self.athlete.id,
            "node": self.node.id,
            "exercise": "Back squat",
            "set_number": 1,
        }

    def prepare_bound_execution(self):
        exercise = WorkoutExercise.objects.create(
            workout=self.workout,
            exercise="Back squat",
            position=1,
            sets=2,
            reps=1,
            default_weight_lbs=100,
        )
        program = WorkoutProgram.objects.create(name="Race Program")
        item = WorkoutProgramItem.objects.create(
            workout_program=program,
            workout=self.workout,
            position=1,
        )
        AthleteWorkoutProgramAssignment.objects.create(
            athlete=self.athlete,
            workout_program=program,
        )
        AthleteDayProgress.objects.create(
            session=self.session,
            athlete=self.athlete,
            workout_program=program,
            current_program_item=item,
            current_workout_exercise=exercise,
            expected_set_number=1,
        )
        RackWorkoutState.objects.filter(rack_number=1).update(
            assigned_workout=None,
            selected_athlete=self.athlete,
        )

    def start_bound_set(self):
        return APIClient().post(
            "/api/racks/1/sets/",
            {"device_id": "00000000-0000-4000-8000-000000000010"},
            format="json",
        )

    def _start_request(self, request):
        started = Event()
        result = {}

        def run():
            close_old_connections()
            started.set()
            try:
                response = request()
                result["status"] = response.status_code
                result["data"] = getattr(response, "data", None)
            except Exception as error:  # surfaced by the main test thread
                result["error"] = error
            finally:
                close_old_connections()

        thread = Thread(target=run)
        self._request_threads.append(thread)
        thread.start()
        self.assertTrue(started.wait(timeout=2))
        time.sleep(0.1)
        self.assertTrue(thread.is_alive())
        return thread, result

    def _join_request(self, thread, result):
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self._request_threads.remove(thread)
        if "error" in result:
            raise result["error"]
        return result

    def tearDown(self):
        for thread in self._request_threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        close_old_connections()

    def test_set_start_waits_for_end_then_rejects_ended_session(self):
        from .views import _lock_rack_number
        self.prepare_bound_execution()

        with transaction.atomic():
            _lock_rack_number(1)
            thread, result = self._start_request(
                self.start_bound_set
            )
            coach_client = APIClient()
            coach_client.force_authenticate(self.coach)
            ended = coach_client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")
            self.assertEqual(ended.status_code, 200)

        result = self._join_request(thread, result)
        self.assertEqual(result["status"], 409)
        self.assertEqual(result["data"]["code"], "no_active_session")
        self.assertFalse(Set.objects.exists())

    def test_set_start_commits_first_and_end_rejects_unfinished_set(self):
        from .views import _lock_rack_number
        self.prepare_bound_execution()

        with transaction.atomic():
            _lock_rack_number(1)

            def end_session():
                client = APIClient()
                client.force_authenticate(self.coach)
                return client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")

            thread, result = self._start_request(end_session)
            created = self.start_bound_set()
            self.assertEqual(created.status_code, 201)

        result = self._join_request(thread, result)
        self.assertEqual(result["status"], 409)
        self.assertEqual(result["data"]["code"], "unfinished_set")
        self.session.refresh_from_db()
        self.assertIsNone(self.session.ended_at)
        self.assertEqual(Set.objects.count(), 1)

    def test_catalog_assignment_waits_for_end_then_rejects_no_active_session(self):
        from .views import _lock_rack_number

        other_workout = Workout.objects.create(name="Other Race Workout")
        with transaction.atomic():
            _lock_rack_number(1)

            def change_assignment():
                client = APIClient()
                client.force_authenticate(self.coach)
                return client.put(
                    "/api/racks/1/assignment/",
                    {"workout_id": other_workout.id},
                    format="json",
                )

            thread, result = self._start_request(change_assignment)
            coach_client = APIClient()
            coach_client.force_authenticate(self.coach)
            ended = coach_client.patch(f"/api/sessions/{self.session.id}/", {}, format="json")
            self.assertEqual(ended.status_code, 200)

        result = self._join_request(thread, result)
        self.assertEqual(result["status"], 409)
        self.assertEqual(result["data"]["code"], "no_active_session")
        state = RackWorkoutState.objects.get(rack_number=1)
        self.assertEqual(state.assigned_workout_id, self.workout.id)

    def test_set_create_locks_rack_before_submitted_session_and_rejects_ended(self):
        self.prepare_bound_execution()
        with CaptureQueriesContext(connection) as queries:
            created = self.start_bound_set()
        self.assertEqual(created.status_code, 201)
        sql = [query["sql"] for query in queries.captured_queries]
        advisory_index = next(
            index for index, statement in enumerate(sql)
            if "pg_advisory_xact_lock" in statement
        )
        session_lock_index = next(
            index for index, statement in enumerate(sql)
            if 'FROM "event_handler_session"' in statement and "FOR UPDATE" in statement
        )
        self.assertLess(advisory_index, session_lock_index)

        self.session.ended_at = timezone.now()
        self.session.save(update_fields=["ended_at"])
        rejected = self.start_bound_set()
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.data["code"], "no_active_session")
        self.assertEqual(Set.objects.count(), 1)

    def test_athlete_assignment_waits_for_rack_then_rejects_active_progress(self):
        from .views import _lock_rack_number

        exercise = WorkoutExercise.objects.create(
            workout=self.workout,
            exercise="Back squat",
            position=1,
            sets=1,
            reps=1,
            default_weight_lbs=0,
        )
        program = WorkoutProgram.objects.create(name="Race Athlete Program")
        WorkoutProgramItem.objects.create(
            workout_program=program,
            workout=self.workout,
            position=1,
        )
        AthleteWorkoutProgramAssignment.objects.create(
            athlete=self.athlete,
            workout_program=program,
        )
        other_workout = Workout.objects.create(name="Other Athlete Race Workout")
        WorkoutExercise.objects.create(
            workout=other_workout,
            exercise="Bench press",
            position=1,
            sets=1,
            reps=1,
            default_weight_lbs=0,
        )
        other_program = WorkoutProgram.objects.create(name="Other Race Athlete Program")
        WorkoutProgramItem.objects.create(
            workout_program=other_program,
            workout=other_workout,
            position=1,
        )
        identified = APIClient().put(
            "/api/racks/1/athlete/",
            {
                "device_id": "00000000-0000-4000-8000-000000000010",
                "athlete_id": self.athlete.id,
            },
            format="json",
        )
        self.assertEqual(identified.status_code, 200)
        with transaction.atomic():
            _lock_rack_number(1)

            def change_athlete_assignment():
                client = APIClient()
                client.force_authenticate(self.coach)
                return client.put(
                    f"/api/athletes/{self.athlete.id}/workout-assignment/",
                    {"workout_program_id": other_program.id},
                    format="json",
                )

            thread, result = self._start_request(change_athlete_assignment)
            created = self.start_bound_set()
            self.assertEqual(created.status_code, 201)

        result = self._join_request(thread, result)
        self.assertEqual(result["status"], 409)
        self.assertEqual(result["data"]["code"], "athlete_progress_active")
        assignment = AthleteWorkoutProgramAssignment.objects.get(athlete=self.athlete)
        self.assertEqual(assignment.workout_program_id, program.id)


class TrainingDayApiTests(TestCase):
    def setUp(self):
        self.coach = User.objects.create_user(
            username="training-day-coach", password="test-only", is_staff=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.coach)
        self.athlete = Athlete.objects.create(
            name="Report Athlete", nfc_tag_id="private-nfc", notes="private athlete note",
        )

    def create_session(self, **fields):
        session = Session.objects.create(label="Report Day", **fields)
        session.athletes.add(self.athlete)
        return session

    def create_report_fixture(self):
        session = self.create_session(notes="private session note")
        workout = Workout.objects.create(name="Report Workout")
        exercise = WorkoutExercise.objects.create(
            workout=workout,
            exercise="Back squat",
            position=1,
            sets=4,
            reps=5,
            default_weight_lbs=225,
            velocity_min=0.5,
            velocity_max=0.8,
        )
        AthleteWorkoutAssignment.objects.create(
            athlete=self.athlete,
            assigned_workout=workout,
        )
        AthleteWorkoutExerciseOverride.objects.create(
            athlete=self.athlete,
            workout_exercise=exercise,
            sets=5,
            weight_lbs=245,
        )
        RackWorkoutState.objects.create(
            rack_number=1,
            active_session=session,
            selected_athlete=self.athlete,
        )
        completed = Set.objects.create(
            session=session,
            athlete=self.athlete,
            rack_number=1,
            exercise="Back squat",
            set_number=1,
            weight_lbs=245,
            ended_at=timezone.now(),
            reps_completed=1,
            avg_velocity=0.7,
            peak_velocity=0.9,
        )
        rep = Rep.objects.create(
            set=completed,
            rep_number=1,
            timestamp=timezone.now(),
            mean_velocity=0.7,
            peak_velocity=0.9,
            duration_ms=600,
            velocity_color="green",
        )
        Set.objects.create(
            session=session,
            athlete=self.athlete,
            rack_number=1,
            exercise="False set",
            set_number=2,
            ended_at=timezone.now(),
            is_false_set=True,
        )
        Set.objects.create(
            session=session,
            athlete=self.athlete,
            rack_number=1,
            exercise="Simulation set",
            set_number=3,
            ended_at=timezone.now(),
            is_simulated=True,
        )
        return session, workout, exercise, completed, rep

    def test_start_requires_coach_and_rejects_second_active_day(self):
        payload = {"label": "Training Day", "athletes": [self.athlete.id], "notes": "private"}
        anonymous = APIClient().post("/api/sessions/", payload, format="json")
        started = self.client.post("/api/sessions/", payload, format="json")
        conflict = self.client.post(
            "/api/sessions/",
            {"label": "Another", "athletes": [self.athlete.id]},
            format="json",
        )

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(started.status_code, 201)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.data["code"], "active_training_day_exists")
        self.assertEqual(conflict["Cache-Control"], "private, no-store")
        self.assertEqual(Session.objects.filter(ended_at=None).count(), 1)

    def test_end_creates_exact_private_snapshot_and_clears_identity_atomically(self):
        session, _workout, _exercise, completed, rep = self.create_report_fixture()

        response = self.client.post(f"/api/sessions/{session.id}/end/", {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(DailyReport.objects.count(), 1)
        report = DailyReport.objects.get()
        session.refresh_from_db()
        self.assertIsNotNone(session.ended_at)
        self.assertEqual(report.snapshot["session"]["ended_at"], session.ended_at.isoformat())
        athlete_row = report.snapshot["athletes"][0]
        prescription = athlete_row["prescription"]
        self.assertEqual(prescription["source"], "athlete")
        self.assertEqual(prescription["exercises"][0]["sets"], 5)
        self.assertEqual(prescription["exercises"][0]["reps"], 5)
        self.assertEqual(prescription["exercises"][0]["default_weight_lbs"], 245)
        self.assertEqual(len(athlete_row["sets"]), 1)
        copied_set = athlete_row["sets"][0]
        self.assertEqual(copied_set["id"], completed.id)
        self.assertEqual(copied_set["reps"][0]["id"], rep.id)
        self.assertEqual(copied_set["reps"][0]["mean_velocity"], 0.7)
        self.assertEqual(report.snapshot["exclusions"], {
            "false_sets": 1,
            "simulated_sets": 1,
            "unsaved_live_reps": "not_persisted",
        })
        self.assertIsNone(RackWorkoutState.objects.get(rack_number=1).selected_athlete_id)
        self.assertEqual(MonitoringEvent.objects.filter(reason="session_ended").count(), 1)
        self.assertNotContains(response, "private-nfc")
        self.assertNotContains(response, "private athlete note")
        self.assertNotContains(response, "private session note")

    def test_end_retry_returns_same_report_without_duplicate_event(self):
        session, *_ = self.create_report_fixture()

        first = self.client.post(f"/api/sessions/{session.id}/end/", {}, format="json")
        second = self.client.post(f"/api/sessions/{session.id}/end/", {}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(DailyReport.objects.count(), 1)
        self.assertEqual(MonitoringEvent.objects.filter(reason="session_ended").count(), 1)

    def test_compatible_patch_delegates_to_report_end(self):
        session, *_ = self.create_report_fixture()

        response = self.client.patch(f"/api/sessions/{session.id}/", {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["session_id"], session.id)
        self.assertTrue(DailyReport.objects.filter(session=session).exists())

    def test_unfinished_conflict_reports_only_rack_numbers_and_preserves_state(self):
        session = self.create_session()
        RackWorkoutState.objects.create(rack_number=3, active_session=session)
        unfinished = Set.objects.create(
            session=session,
            athlete=self.athlete,
            rack_number=3,
            exercise="Squat",
            set_number=1,
        )
        Set.objects.create(
            session=session,
            athlete=self.athlete,
            rack_number=None,
            exercise="Press",
            set_number=1,
        )

        response = self.client.post(f"/api/sessions/{session.id}/end/", {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "unfinished_set")
        self.assertEqual(response.data["rack_numbers"], [3])
        self.assertEqual(response.data["unassigned_set_count"], 1)
        self.assertNotContains(response, self.athlete.name, status_code=409)
        session.refresh_from_db()
        self.assertIsNone(session.ended_at)
        self.assertTrue(Set.objects.filter(id=unfinished.id, ended_at=None).exists())
        self.assertFalse(DailyReport.objects.exists())

    def test_simulation_end_is_rejected_without_changes(self):
        session = self.create_session(is_simulated=True)

        response = self.client.post(f"/api/sessions/{session.id}/end/", {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "simulation_end_rejected")
        session.refresh_from_db()
        self.assertIsNone(session.ended_at)
        self.assertFalse(DailyReport.objects.exists())

    @patch("event_handler.services.training_days._build_snapshot", side_effect=RuntimeError("snapshot failed"))
    def test_snapshot_failure_rolls_back_end_identity_report_and_event(self, build_snapshot):
        session, *_ = self.create_report_fixture()

        with self.assertRaisesMessage(RuntimeError, "snapshot failed"):
            self.client.post(f"/api/sessions/{session.id}/end/", {}, format="json")

        session.refresh_from_db()
        self.assertIsNone(session.ended_at)
        self.assertEqual(RackWorkoutState.objects.get(rack_number=1).selected_athlete_id, self.athlete.id)
        self.assertFalse(DailyReport.objects.exists())
        self.assertFalse(MonitoringEvent.objects.filter(reason="session_ended").exists())

    def test_later_source_edits_do_not_change_snapshot(self):
        session, workout, _exercise, completed, rep = self.create_report_fixture()
        ended = self.client.post(f"/api/sessions/{session.id}/end/", {}, format="json")
        original = ended.data["snapshot"]

        workout.name = "Changed Workout"
        workout.save(update_fields=["name"])
        self.athlete.name = "Changed Athlete"
        self.athlete.save(update_fields=["name"])
        completed.exercise = "Changed exercise"
        completed.save(update_fields=["exercise"])
        rep.mean_velocity = 9.9
        rep.save(update_fields=["mean_velocity"])

        report = DailyReport.objects.get(session=session)
        self.assertEqual(report.snapshot, original)


class AthleteDrivenFoundationTests(TestCase):
    rack_one_device = "20000000-0000-4000-8000-000000000001"
    rack_three_device = "20000000-0000-4000-8000-000000000003"

    def setUp(self):
        self.coach = User.objects.create_user(
            username="athlete-driven-coach",
            password="test-only",
            is_staff=True,
        )
        self.coach_client = APIClient()
        self.coach_client.force_authenticate(self.coach)
        self.athlete = Athlete.objects.create(
            name="Foundation Athlete",
            nfc_tag_id="private-nfc",
            notes="private note",
        )
        first_workout = Workout.objects.create(name="Foundation Lower")
        self.first_workout = first_workout
        self.first_exercise = WorkoutExercise.objects.create(
            workout=first_workout,
            exercise="Back squat",
            position=1,
            sets=3,
            reps=5,
            default_weight_lbs=225,
            velocity_min=0.5,
            velocity_max=0.8,
        )
        second_workout = Workout.objects.create(name="Foundation Upper")
        self.final_exercise = WorkoutExercise.objects.create(
            workout=second_workout,
            exercise="Bench press",
            position=1,
            sets=4,
            reps=6,
            default_weight_lbs=135,
        )
        self.program = WorkoutProgram.objects.create(name="Foundation Program")
        self.first_item = WorkoutProgramItem.objects.create(
            workout_program=self.program,
            workout=first_workout,
            position=1,
        )
        self.final_item = WorkoutProgramItem.objects.create(
            workout_program=self.program,
            workout=second_workout,
            position=2,
        )
        AthleteWorkoutExerciseOverride.objects.create(
            athlete=self.athlete,
            workout_exercise=self.first_exercise,
            sets=5,
            weight_lbs=0,
        )
        RackScreen.objects.create(device_id=self.rack_one_device, rack_number=1)
        RackScreen.objects.create(device_id="20000000-0000-4000-8000-000000000021", rack_number=2)
        RackScreen.objects.create(device_id="20000000-0000-4000-8000-000000000022", rack_number=2)
        RackScreen.objects.create(device_id=self.rack_three_device, rack_number=3)

    def assignment_url(self):
        return f"/api/athletes/{self.athlete.id}/workout-assignment/"

    def assign_and_start(self):
        assigned = self.coach_client.put(
            self.assignment_url(),
            {"workout_program_id": self.program.id},
            format="json",
        )
        started = self.coach_client.post(
            "/api/sessions/",
            {"label": "Foundation Day", "athletes": [self.athlete.id]},
            format="json",
        )
        return assigned, started

    def identify(self, rack_number=1, device_id=None):
        return APIClient().put(
            f"/api/racks/{rack_number}/athlete/",
            {
                "device_id": device_id or self.rack_one_device,
                "athlete_id": self.athlete.id,
            },
            format="json",
        )

    def start_bound_set(self, **payload):
        Node.objects.get_or_create(node_id="foundation-node", defaults={"rack_number": 1})
        return APIClient().post(
            "/api/racks/1/sets/",
            {"device_id": self.rack_one_device, **payload},
            format="json",
        )

    def complete_bound_set(self, set_id, rep_count=1, is_false_set=False):
        reps = [{
            "rep_number": index + 1,
            "mean_velocity": 0.2 + index,
            "peak_velocity": 0.3 + index,
            "duration_ms": 600,
            "timestamp": (timezone.now() + timedelta(seconds=index)).isoformat(),
            "velocity_color": "red" if index == 0 else "yellow",
        } for index in range(rep_count)]
        return APIClient().post(
            f"/api/racks/1/sets/{set_id}/complete/",
            {
                "reps_completed": 0 if is_false_set else rep_count,
                "is_false_set": is_false_set,
                "reps": [] if is_false_set else reps,
            },
            format="json",
            HTTP_X_RACK_DEVICE_ID=self.rack_one_device,
        )

    def test_whole_program_assignment_returns_order_and_effective_targets(self):
        assigned = self.coach_client.put(
            self.assignment_url(),
            {"workout_program_id": self.program.id},
            format="json",
        )
        loaded = self.coach_client.get(self.assignment_url())

        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(loaded["Cache-Control"], "private, no-store")
        self.assertEqual(loaded.data["type"], "workout_program")
        items = loaded.data["workout_program"]["items"]
        self.assertEqual([item["position"] for item in items], [1, 2])
        self.assertEqual(items[0]["workout"]["exercises"][0]["sets"], 5)
        self.assertEqual(items[0]["workout"]["exercises"][0]["default_weight_lbs"], 0)
        rejected = self.coach_client.put(
            self.assignment_url(),
            {"workout_program_id": self.program.id, "workout_id": items[0]["workout"]["id"]},
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(rejected.data["code"], "unknown_fields")

    def test_start_day_activates_unique_screens_and_publishes_revision(self):
        _assigned, started = self.assign_and_start()

        self.assertEqual(started.status_code, 201)
        self.assertEqual(
            list(RackWorkoutState.objects.order_by("rack_number").values_list("rack_number", flat=True)),
            [1, 3],
        )
        self.assertEqual(MonitoringEvent.objects.filter(reason="session_started").count(), 1)
        rack = APIClient().get("/api/racks/1/state/")
        self.assertTrue(rack.data["identity_available"])
        self.assertEqual(rack.data["active_athletes"], [{"id": self.athlete.id, "name": self.athlete.name}])
        self.assertIsNone(rack.data["assignment"])

    def test_legacy_rack_assignment_route_remains_available_but_is_not_required(self):
        self.assign_and_start()
        legacy_workout = Workout.objects.create(name="Legacy Rack Workout")
        assigned = self.coach_client.put(
            "/api/racks/1/assignment/",
            {"workout_id": legacy_workout.id},
            format="json",
        )

        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(assigned["Cache-Control"], "private, no-store")
        self.assertEqual(assigned.data["assignment"]["workout"]["id"], legacy_workout.id)
        identified = self.identify()
        self.assertEqual(identified.status_code, 200)
        self.assertEqual(identified.data["progress"]["program"]["id"], self.program.id)
        self.assertIsNone(identified.data["assignment"])

    def test_sign_in_creates_progress_and_move_restores_the_same_step(self):
        self.assign_and_start()
        first = self.identify()
        moved = self.identify(3, self.rack_three_device)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(first.data["progress"]["id"], moved.data["progress"]["id"])
        self.assertEqual(moved.data["progress"]["current_workout"]["position"], 1)
        self.assertEqual(moved.data["progress"]["current_exercise"]["id"], self.first_exercise.id)
        self.assertEqual(moved.data["progress"]["expected_set_number"], 1)
        self.assertEqual(moved.data["progress"]["current_exercise"]["sets"], 5)
        self.assertIsNone(RackWorkoutState.objects.get(rack_number=1).selected_athlete_id)
        self.assertEqual(RackWorkoutState.objects.get(rack_number=3).selected_athlete_id, self.athlete.id)
        self.assertEqual(AthleteDayProgress.objects.count(), 1)
        self.assertEqual(
            list(AthleteRackParticipation.objects.order_by("rack_number").values_list("rack_number", flat=True)),
            [1, 3],
        )
        self.assertNotContains(moved, "private-nfc")
        self.assertNotContains(moved, "private note")
        self.assertNotContains(moved, self.rack_three_device)

    def test_unfinished_bound_set_blocks_sign_out_move_and_assignment_mutation(self):
        self.assign_and_start()
        signed_in = self.identify()
        progress = AthleteDayProgress.objects.get(id=signed_in.data["progress"]["id"])
        Set.objects.create(
            session=progress.session,
            athlete=self.athlete,
            rack_number=1,
            exercise=self.first_exercise.exercise,
            set_number=1,
            athlete_day_progress=progress,
            workout_program_item=self.first_item,
            workout_exercise=self.first_exercise,
        )

        signed_out = APIClient().delete(
            "/api/racks/1/athlete/",
            {"device_id": self.rack_one_device},
            format="json",
        )
        moved = self.identify(3, self.rack_three_device)
        reassigned = self.coach_client.put(
            self.assignment_url(),
            {"workout_program_id": self.program.id},
            format="json",
        )

        for response in (signed_out, moved):
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data["code"], "unfinished_set")
        self.assertEqual(reassigned.status_code, 409)
        self.assertEqual(reassigned.data["code"], "athlete_progress_active")
        self.assertEqual(RackWorkoutState.objects.get(rack_number=1).selected_athlete_id, self.athlete.id)

    def test_rack_bound_start_derives_current_step_and_rejects_client_selected_fields(self):
        self.assign_and_start()
        self.identify()

        for field, value in (
            ("session", 999), ("athlete", 999), ("exercise", "Client movement"),
            ("set_number", 9), ("weight_lbs", 999),
        ):
            rejected = self.start_bound_set(**{field: value})
            self.assertEqual(rejected.status_code, 400)
            self.assertEqual(rejected.data["code"], "unknown_fields")
        wrong_screen = APIClient().post(
            "/api/racks/1/sets/",
            {"device_id": self.rack_three_device},
            format="json",
        )
        self.assertEqual(wrong_screen.status_code, 403)
        self.assertEqual(wrong_screen.data["code"], "rack_screen_mismatch")

        created = self.start_bound_set()
        self.assertEqual(created.status_code, 201)
        workout_set = Set.objects.select_related("athlete_day_progress").get(id=created.data["id"])
        self.assertEqual(workout_set.session.label, "Foundation Day")
        self.assertEqual(workout_set.athlete, self.athlete)
        self.assertEqual(workout_set.node.node_id, "foundation-node")
        self.assertEqual(workout_set.rack_number, 1)
        self.assertEqual(workout_set.exercise, self.first_exercise.exercise)
        self.assertEqual(workout_set.workout_exercise, self.first_exercise)
        self.assertEqual(workout_set.workout_program_item, self.first_item)
        self.assertEqual(workout_set.set_number, 1)
        self.assertEqual(workout_set.weight_lbs, 0)
        self.assertEqual(workout_set.athlete_day_progress.status, AthleteDayProgress.IN_SET)

        hidden_state = APIClient().get("/api/racks/1/state/")
        state = APIClient().get(
            "/api/racks/1/state/",
            HTTP_X_RACK_DEVICE_ID=self.rack_one_device,
        )
        self.assertIsNone(hidden_state.data["progress"]["active_set"])
        self.assertEqual(state.data["progress"]["active_set"]["id"], workout_set.id)

    def test_bound_completion_requires_current_unique_rack_screen_without_writes(self):
        self.assign_and_start()
        self.identify()

        for expected_code, headers, mutate in (
            ("invalid_device_id", {}, lambda: None),
            (
                "rack_screen_mismatch",
                {"HTTP_X_RACK_DEVICE_ID": self.rack_three_device},
                lambda: None,
            ),
            (
                "rack_screen_conflict",
                {"HTTP_X_RACK_DEVICE_ID": self.rack_one_device},
                lambda: RackScreen.objects.create(
                    device_id="20000000-0000-4000-8000-000000000099",
                    rack_number=1,
                ),
            ),
        ):
            started = self.start_bound_set()
            mutate()
            response = APIClient().post(
                f"/api/racks/1/sets/{started.data['id']}/complete/",
                {"reps_completed": 0, "is_false_set": False, "reps": []},
                format="json",
                **headers,
            )
            self.assertEqual(response.status_code, 400 if expected_code == "invalid_device_id" else (403 if expected_code == "rack_screen_mismatch" else 409))
            self.assertEqual(response.data["code"], expected_code)
            workout_set = Set.objects.get(id=started.data["id"])
            progress = AthleteDayProgress.objects.get(athlete=self.athlete)
            self.assertIsNone(workout_set.ended_at)
            self.assertEqual(workout_set.reps.count(), 0)
            self.assertEqual(progress.status, AthleteDayProgress.IN_SET)
            workout_set.delete()
            progress.status = AthleteDayProgress.READY
            progress.save(update_fields=["status", "updated_at"])
            RackScreen.objects.filter(
                device_id="20000000-0000-4000-8000-000000000099"
            ).delete()

    def test_bound_completion_rejects_screen_moved_from_rack_without_advancing(self):
        self.assign_and_start()
        self.identify()
        started = self.start_bound_set()
        RackScreen.objects.filter(device_id=self.rack_one_device).update(rack_number=3)

        response = APIClient().post(
            f"/api/racks/1/sets/{started.data['id']}/complete/",
            {"reps_completed": 0, "is_false_set": False, "reps": []},
            format="json",
            HTTP_X_RACK_DEVICE_ID=self.rack_one_device,
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "rack_screen_conflict")
        workout_set = Set.objects.get(id=started.data["id"])
        progress = AthleteDayProgress.objects.get(athlete=self.athlete)
        self.assertIsNone(workout_set.ended_at)
        self.assertEqual(workout_set.reps.count(), 0)
        self.assertEqual(progress.status, AthleteDayProgress.IN_SET)

    def test_generic_completion_cannot_complete_bound_set(self):
        self.assign_and_start()
        self.identify()
        started = self.start_bound_set()

        response = APIClient().post(
            f"/api/sets/{started.data['id']}/complete/",
            {"reps_completed": 0, "is_false_set": False, "reps": []},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "rack_bound_set_required")
        self.assertIsNone(Set.objects.get(id=started.data["id"]).ended_at)

    def test_bound_completion_rejects_wrong_rack_and_unbound_sets(self):
        self.assign_and_start()
        self.identify()
        started = self.start_bound_set()

        wrong_rack = APIClient().post(
            f"/api/racks/3/sets/{started.data['id']}/complete/",
            {"reps_completed": 0, "is_false_set": False, "reps": []},
            format="json",
            HTTP_X_RACK_DEVICE_ID=self.rack_three_device,
        )
        self.assertEqual(wrong_rack.status_code, 409)
        self.assertEqual(wrong_rack.data["code"], "rack_set_mismatch")
        self.assertIsNone(Set.objects.get(id=started.data["id"]).ended_at)

        Set.objects.filter(id=started.data["id"]).delete()
        progress = AthleteDayProgress.objects.get(athlete=self.athlete)
        progress.status = AthleteDayProgress.READY
        progress.save(update_fields=["status", "updated_at"])
        unbound = Set.objects.create(
            session=progress.session,
            athlete=self.athlete,
            rack_number=1,
            exercise="Legacy set",
            set_number=1,
        )
        rejected = APIClient().post(
            f"/api/racks/1/sets/{unbound.id}/complete/",
            {"reps_completed": 0, "is_false_set": False, "reps": []},
            format="json",
            HTTP_X_RACK_DEVICE_ID=self.rack_one_device,
        )
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.data["code"], "unexpected_workout_step")
        self.assertIsNone(Set.objects.get(id=unbound.id).ended_at)

    def test_generic_creation_cannot_add_unfinished_set_or_block_schema_two_end(self):
        self.assign_and_start()
        self.identify()
        node = Node.objects.create(node_id="generic-poison-node", rack_number=3)
        session = Session.objects.get(ended_at=None)

        response = APIClient().post("/api/sets/", {
            "session": session.id,
            "athlete": self.athlete.id,
            "node": node.id,
            "exercise": "Injected exercise",
            "set_number": 999,
        }, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "rack_bound_set_required")
        self.assertFalse(Set.objects.exists())
        ended = self.coach_client.post(f"/api/sessions/{session.id}/end/", {}, format="json")
        self.assertEqual(ended.status_code, 200)
        self.assertEqual(ended.data["schema_version"], 2)

    def test_false_and_variable_rep_completions_advance_only_qualifying_sets(self):
        self.assign_and_start()
        self.identify()
        AthleteWorkoutExerciseOverride.objects.filter(
            athlete=self.athlete, workout_exercise=self.first_exercise,
        ).update(sets=2)

        false_start = self.start_bound_set()
        false_result = self.complete_bound_set(false_start.data["id"], is_false_set=True)
        self.assertEqual(false_result.status_code, 200)
        progress = AthleteDayProgress.objects.get(athlete=self.athlete)
        self.assertEqual((progress.status, progress.expected_set_number), (AthleteDayProgress.READY, 1))

        under_start = self.start_bound_set()
        under_result = self.complete_bound_set(under_start.data["id"], rep_count=1)
        self.assertEqual(under_result.status_code, 200)
        progress.refresh_from_db()
        self.assertEqual((progress.status, progress.expected_set_number), (AthleteDayProgress.READY, 2))
        state = APIClient().get(
            "/api/racks/1/state/",
            HTTP_X_RACK_DEVICE_ID=self.rack_one_device,
        )
        completion = state.data["progress"]["current_exercise_completion"]
        self.assertEqual((completion["completed_sets"], completion["false_sets"]), (1, 1))
        self.assertEqual(completion["sets"][1]["reps_completed"], 1)
        self.assertEqual(completion["sets"][1]["weight_lbs"], 0)

        over_start = self.start_bound_set()
        over_result = self.complete_bound_set(over_start.data["id"], rep_count=7)
        self.assertEqual(over_result.status_code, 200)
        progress.refresh_from_db()
        self.assertEqual(progress.current_program_item, self.final_item)
        self.assertEqual(progress.current_workout_exercise, self.final_exercise)
        self.assertEqual(progress.expected_set_number, 1)

    def test_ordered_exercise_program_and_final_completion_do_not_wrap(self):
        second_exercise = WorkoutExercise.objects.create(
            workout=self.first_workout,
            exercise="Split squat",
            position=2,
            sets=1,
            reps=3,
            default_weight_lbs=50,
        )
        AthleteWorkoutExerciseOverride.objects.filter(
            athlete=self.athlete, workout_exercise=self.first_exercise,
        ).update(sets=1)
        AthleteWorkoutExerciseOverride.objects.create(
            athlete=self.athlete,
            workout_exercise=self.final_exercise,
            sets=1,
        )
        _assigned, started_day = self.assign_and_start()
        self.identify()

        first = self.start_bound_set()
        self.complete_bound_set(first.data["id"], rep_count=1)
        progress = AthleteDayProgress.objects.get(athlete=self.athlete)
        self.assertEqual(progress.current_workout_exercise, second_exercise)

        second = self.start_bound_set()
        self.complete_bound_set(second.data["id"], rep_count=1)
        progress.refresh_from_db()
        self.assertEqual(progress.current_program_item, self.final_item)
        self.assertEqual(progress.current_workout_exercise, self.final_exercise)

        final = self.start_bound_set()
        completed = self.complete_bound_set(final.data["id"], rep_count=1)
        self.assertEqual(completed.status_code, 200)
        progress.refresh_from_db()
        self.assertEqual(progress.status, AthleteDayProgress.COMPLETE)
        self.assertIsNone(progress.current_program_item_id)
        self.assertIsNone(progress.current_workout_exercise_id)
        self.assertIsNone(progress.expected_set_number)
        duplicate = self.complete_bound_set(final.data["id"], rep_count=1)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.data["code"], "set_already_complete")
        progress.refresh_from_db()
        self.assertEqual(progress.status, AthleteDayProgress.COMPLETE)

        signed_out = APIClient().delete(
            "/api/racks/1/athlete/", {"device_id": self.rack_one_device}, format="json",
        )
        restored = self.identify()
        self.assertEqual(signed_out.status_code, 200)
        self.assertEqual(restored.data["progress"]["status"], AthleteDayProgress.COMPLETE)

        ended = self.coach_client.post(f"/api/sessions/{started_day.data['id']}/end/", {}, format="json")
        next_day = self.coach_client.post(
            "/api/sessions/",
            {"label": "Foundation Day Two", "athletes": [self.athlete.id]},
            format="json",
        )
        next_identity = self.identify()
        self.assertEqual(ended.status_code, 200)
        self.assertEqual(next_day.status_code, 201)
        self.assertEqual(next_identity.data["progress"]["status"], AthleteDayProgress.READY)
        self.assertEqual(next_identity.data["progress"]["current_workout"]["position"], 1)
        self.assertEqual(next_identity.data["progress"]["current_exercise"]["id"], self.first_exercise.id)
        self.assertEqual(next_identity.data["progress"]["expected_set_number"], 1)

    def test_stale_bound_completion_rolls_back_set_and_reps(self):
        self.assign_and_start()
        self.identify()
        started = self.start_bound_set()
        progress = AthleteDayProgress.objects.get(athlete=self.athlete)
        progress.expected_set_number = 2
        progress.save(update_fields=["expected_set_number", "updated_at"])

        rejected = self.complete_bound_set(started.data["id"], rep_count=1)
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.data["code"], "unexpected_workout_step")
        workout_set = Set.objects.get(id=started.data["id"])
        self.assertIsNone(workout_set.ended_at)
        self.assertEqual(workout_set.reps.count(), 0)
        progress.refresh_from_db()
        self.assertEqual((progress.status, progress.expected_set_number), (AthleteDayProgress.IN_SET, 2))

    def test_end_day_creates_schema_two_program_progress_racks_and_bound_results(self):
        _assigned, started = self.assign_and_start()
        self.identify()
        created = self.start_bound_set()
        self.complete_bound_set(created.data["id"], rep_count=1)
        self.identify(3, self.rack_three_device)

        ended = self.coach_client.post(
            f"/api/sessions/{started.data['id']}/end/", {}, format="json",
        )

        self.assertEqual(ended.status_code, 200)
        report = DailyReport.objects.get(session_id=started.data["id"])
        self.assertEqual(report.schema_version, 2)
        self.assertEqual(report.snapshot["schema_version"], 2)
        entry = report.snapshot["athletes"][0]
        self.assertEqual(
            [item["position"] for item in entry["assigned_program"]["items"]],
            [1, 2],
        )
        self.assertEqual(entry["assigned_program"]["items"][0]["id"], self.first_item.id)
        effective = entry["assigned_program"]["items"][0]["workout"]["exercises"][0]
        self.assertEqual(effective["id"], self.first_exercise.id)
        self.assertEqual((effective["sets"], effective["default_weight_lbs"]), (5, 0))
        self.assertEqual(entry["final_progress"]["status"], AthleteDayProgress.READY)
        self.assertEqual(entry["final_progress"]["expected_set_number"], 2)
        self.assertEqual(entry["rack_participation"], [1, 3])
        result = entry["sets"][0]
        self.assertEqual(result["athlete_day_progress_id"], entry["final_progress"]["id"])
        self.assertEqual(result["workout_program_item_id"], self.first_item.id)
        self.assertEqual(result["workout_exercise_id"], self.first_exercise.id)
        self.assertEqual(len(result["reps"]), 1)
        self.assertEqual(report.snapshot["exclusions"]["unsaved_live_reps"], "not_persisted")
        detail = self.coach_client.get(f"/api/reports/{report.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn("snapshot", detail.data)
        self.assertEqual(
            detail.data["athletes"][0]["assigned_program"]["items"][0]["id"],
            self.first_item.id,
        )
        self.assertEqual(self.coach_client.get(f"/api/reports/{report.id}/pdf/").status_code, 200)

    def test_sign_in_and_sign_out_without_a_set_remains_in_schema_two_report(self):
        _assigned, started = self.assign_and_start()
        self.assertEqual(self.identify().status_code, 200)
        signed_out = APIClient().delete(
            "/api/racks/1/athlete/", {"device_id": self.rack_one_device}, format="json",
        )
        ended = self.coach_client.post(
            f"/api/sessions/{started.data['id']}/end/", {}, format="json",
        )

        self.assertEqual(signed_out.status_code, 200)
        self.assertEqual(ended.status_code, 200)
        entry = DailyReport.objects.get(session_id=started.data["id"]).snapshot["athletes"][0]
        self.assertEqual(entry["rack_participation"], [1])
        self.assertEqual(entry["sets"], [])

    def test_false_only_visit_keeps_bound_result_but_excludes_completion_totals(self):
        _assigned, started = self.assign_and_start()
        self.identify()
        created = self.start_bound_set()
        completed = self.complete_bound_set(created.data["id"], is_false_set=True)
        ended = self.coach_client.post(
            f"/api/sessions/{started.data['id']}/end/", {}, format="json",
        )

        self.assertEqual(completed.status_code, 200)
        self.assertEqual(ended.status_code, 200)
        report = DailyReport.objects.get(session_id=started.data["id"])
        result = report.snapshot["athletes"][0]["sets"][0]
        persisted_set = Set.objects.get(id=created.data["id"])
        self.assertTrue(result["is_false_set"])
        self.assertEqual(result["athlete_day_progress_id"], persisted_set.athlete_day_progress_id)
        self.assertEqual(result["workout_program_item_id"], self.first_item.id)
        self.assertEqual(result["workout_exercise_id"], self.first_exercise.id)
        self.assertEqual(result["reps"], [])

        detail = self.coach_client.get(f"/api/reports/{report.id}/")
        athlete_detail = self.coach_client.get(
            f"/api/athletes/{self.athlete.id}/reports/{report.id}/",
        )
        pdf = self.coach_client.get(f"/api/reports/{report.id}/pdf/")
        self.assertEqual(detail.data["summary"]["completed_sets"], 0)
        self.assertEqual(detail.data["summary"]["completed_reps"], 0)
        self.assertTrue(detail.data["athletes"][0]["sets"][0]["is_false_set"])
        self.assertEqual(athlete_detail.data["summary"]["completed_sets"], 0)
        self.assertEqual(pdf.status_code, 200)
        self.assertIn(b"False set", pdf.content)


class AthleteDrivenRoomSnapshotTests(TestCase):
    def setUp(self):
        self.coach = User.objects.create_user(
            username="phase-three-coach", password="test-only", is_staff=True,
        )
        self.coach_client = APIClient()
        self.coach_client.force_authenticate(self.coach)
        self.session = Session.objects.create(label="Phase Three Day")
        self.program = WorkoutProgram.objects.create(name="Phase Three Program")
        self.workouts_created = 0

    def create_exercise(self, name, *, velocity=True):
        self.workouts_created += 1
        workout = Workout.objects.create(name=f"Phase Three Workout {self.workouts_created}")
        exercise = WorkoutExercise.objects.create(
            workout=workout,
            exercise=name,
            position=1,
            sets=3,
            reps=3,
            default_weight_lbs=100,
            velocity_min=0.5 if velocity else None,
            velocity_max=0.8 if velocity else None,
        )
        item = WorkoutProgramItem.objects.create(
            workout_program=self.program,
            workout=workout,
            position=self.workouts_created,
        )
        return exercise, item

    def add_participant(self, name, exercise, item, rack_number, *, screen_count=1):
        athlete = Athlete.objects.create(name=name)
        self.session.athletes.add(athlete)
        progress = AthleteDayProgress.objects.create(
            session=self.session,
            athlete=athlete,
            workout_program=self.program,
            current_program_item=item,
            current_workout_exercise=exercise,
            expected_set_number=1,
        )
        RackWorkoutState.objects.create(
            rack_number=rack_number,
            active_session=self.session,
            selected_athlete=athlete,
        )
        for screen_index in range(screen_count):
            RackScreen.objects.create(
                device_id=f"40000000-0000-4000-8000-{rack_number:08d}{screen_index:04d}",
                rack_number=rack_number,
            )
        return athlete, progress

    def add_result(self, athlete, progress, exercise, item, velocity, *, rack_number=None, **fields):
        return Set.objects.create(
            session=self.session,
            athlete=athlete,
            rack_number=rack_number,
            exercise=exercise.exercise,
            set_number=fields.pop("set_number", 1),
            ended_at=fields.pop("ended_at", timezone.now()),
            reps_completed=fields.pop("reps_completed", 3),
            avg_velocity=velocity,
            peak_velocity=velocity,
            athlete_day_progress=progress,
            workout_program_item=item,
            workout_exercise=exercise,
            **fields,
        )

    def test_movement_counts_only_unique_registrations_and_breaks_ties_stably(self):
        z_press, z_item = self.create_exercise("Z press")
        back_squat, squat_item = self.create_exercise(" back SQUAT ")
        non_vbt, non_vbt_item = self.create_exercise("Mobility", velocity=False)
        for rack, name in ((1, "Z One"), (2, "Z Two")):
            self.add_participant(name, z_press, z_item, rack)
        for rack, name in ((3, "Squat One"), (4, "Squat Two")):
            self.add_participant(name, back_squat, squat_item, rack)
        self.add_participant("Duplicate Screen", z_press, z_item, 5, screen_count=2)
        self.add_participant("Unregistered", z_press, z_item, 6, screen_count=0)
        self.add_participant("Non VBT", non_vbt, non_vbt_item, 7)

        response = self.coach_client.get("/api/room-state/")

        self.assertEqual(response.data["summary"]["active_racks"], 5)
        self.assertEqual(response.data["movement"], {
            "id": back_squat.id,
            "name": "back SQUAT",
            "velocity_min": 0.5,
            "velocity_max": 0.8,
            "participant_count": 2,
        })
        duplicate_rack = next(rack for rack in response.data["racks"] if rack["rack_number"] == 5)
        self.assertTrue(duplicate_rack["assignment_conflict"])

        same_name, same_name_item = self.create_exercise("BACK SQUAT")
        self.add_participant("Same Stable One", same_name, same_name_item, 8)
        self.add_participant("Same Stable Two", same_name, same_name_item, 9)
        tied = self.coach_client.get("/api/room-state/")
        self.assertEqual(tied.data["movement"]["id"], back_squat.id)

    def test_empty_and_changed_movement_clear_dependent_results(self):
        mobility, mobility_item = self.create_exercise("Mobility", velocity=False)
        _athlete, _progress = self.add_participant("Mobility Athlete", mobility, mobility_item, 1)
        empty = APIClient().get("/api/wall-state/")
        self.assertIsNone(empty.data["movement"])
        self.assertEqual(empty.data["leaderboard"], [])
        self.assertEqual(empty.data["insights"], [])

        squat, squat_item = self.create_exercise("Squat")
        press, press_item = self.create_exercise("Press")
        athlete, progress = self.add_participant("Moving Athlete", squat, squat_item, 2)
        self.add_result(athlete, progress, squat, squat_item, 0.9, rack_number=2)
        first = APIClient().get("/api/wall-state/")
        self.assertEqual(first.data["movement"]["name"], "Squat")
        self.assertEqual(len(first.data["leaderboard"]), 1)

        progress.current_program_item = press_item
        progress.current_workout_exercise = press
        progress.save(update_fields=["current_program_item", "current_workout_exercise", "updated_at"])
        changed = APIClient().get("/api/wall-state/")
        self.assertEqual(changed.data["movement"]["name"], "Press")
        self.assertEqual(changed.data["leaderboard"], [])
        self.assertEqual(changed.data["insights"], [])

    def test_leaderboard_filters_by_stable_binding_orders_bounds_and_omits_public_ids(self):
        exercise, item = self.create_exercise("Bench press")
        signed_athlete, signed_progress = self.add_participant("Signed Athlete", exercise, item, 1)
        self.add_result(signed_athlete, signed_progress, exercise, item, 0.5, rack_number=1)
        leaders = []
        for index in range(23):
            name = "alex" if index == 0 else "Alex" if index == 1 else f"Lifter {index:02d}"
            athlete = Athlete.objects.create(name=name)
            self.session.athletes.add(athlete)
            progress = AthleteDayProgress.objects.create(
                session=self.session,
                athlete=athlete,
                workout_program=self.program,
                current_program_item=item,
                current_workout_exercise=exercise,
                expected_set_number=2,
            )
            velocity = 1.0 if index < 2 else 0.99 - index / 100
            self.add_result(athlete, progress, exercise, item, velocity, rack_number=99 + index)
            leaders.append((athlete, progress))
        first_alex, second_alex = leaders[0][0], leaders[1][0]
        self.assertLess(first_alex.id, second_alex.id)
        self.add_result(first_alex, leaders[0][1], exercise, item, 9.0, is_false_set=True, set_number=2)
        self.add_result(second_alex, leaders[1][1], exercise, item, 8.0, is_simulated=True, set_number=2)
        self.add_result(leaders[2][0], leaders[2][1], exercise, item, 7.0, ended_at=None, set_number=2)
        Set.objects.create(
            session=self.session,
            athlete=leaders[3][0],
            exercise=exercise.exercise,
            set_number=2,
            ended_at=timezone.now(),
            avg_velocity=6.0,
        )

        wall = APIClient().get("/api/wall-state/")
        coach = self.coach_client.get("/api/room-state/")

        self.assertEqual(len(wall.data["leaderboard"]), 20)
        self.assertTrue(wall.data["truncated"]["leaderboard"])
        self.assertEqual(
            [row["athlete"]["name"] for row in wall.data["leaderboard"][:2]],
            [first_alex.name, second_alex.name],
        )
        self.assertEqual(wall.data["leaderboard"][0]["best_avg_velocity"], 1.0)
        self.assertNotIn("id", wall.data["movement"])
        self.assertNotIn("id", wall.data["leaderboard"][0]["athlete"])
        self.assertEqual(coach.data["leaderboard"][0]["athlete"]["id"], first_alex.id)

    def test_coach_observes_signed_in_progress_latest_result_and_hardware_conflict(self):
        exercise, item = self.create_exercise("Clean pull")
        athlete, progress = self.add_participant("Observed Athlete", exercise, item, 1)
        progress.expected_set_number = 2
        progress.save(update_fields=["expected_set_number", "updated_at"])
        result = self.add_result(athlete, progress, exercise, item, 0.77, rack_number=1)
        Rep.objects.create(
            set=result, rep_number=1, timestamp=timezone.now(), mean_velocity=0.4,
            peak_velocity=0.6, duration_ms=500,
        )
        Rep.objects.create(
            set=result, rep_number=2, timestamp=timezone.now(), mean_velocity=0.7,
            peak_velocity=0.8, duration_ms=500,
        )
        Node.objects.create(node_id="phase-three-node-a", rack_number=1)
        Node.objects.create(node_id="phase-three-node-b", rack_number=1)

        response = self.coach_client.get("/api/room-state/")
        rack = response.data["racks"][0]
        training = rack["training"]

        self.assertEqual(training["athlete"], {"id": athlete.id, "name": athlete.name})
        self.assertEqual(training["program"]["name"], self.program.name)
        self.assertEqual(training["workout"]["id"], item.workout_id)
        self.assertEqual(training["exercise"]["id"], exercise.id)
        self.assertEqual(training["expected_set_number"], 2)
        self.assertEqual(training["progression"]["completed_sets"], 1)
        self.assertEqual(training["latest_result"]["id"], result.id)
        self.assertTrue(rack["assignment_conflict"])
        self.assertEqual(Program.objects.count(), 0)
        self.assertEqual(rack["latest_set"]["target_zone"], {"min": 0.5, "max": 0.8})
        self.assertEqual(rack["latest_set"]["measured_insights"]["reps_below_zone"], 1)
        self.assertEqual(rack["latest_set"]["measured_insights"]["reps_in_zone"], 1)


class AthleteDrivenConstraintTests(TransactionTestCase):
    def test_selected_athlete_and_unfinished_progress_are_exclusive(self):
        athlete = Athlete.objects.create(name="Exclusive Athlete")
        session = Session.objects.create(label="Exclusive Day")
        workout = Workout.objects.create(name="Exclusive Workout")
        exercise = WorkoutExercise.objects.create(
            workout=workout, exercise="Squat", position=1, sets=1, reps=1, default_weight_lbs=0,
        )
        program = WorkoutProgram.objects.create(name="Exclusive Program")
        item = WorkoutProgramItem.objects.create(
            workout_program=program, workout=workout, position=1,
        )
        progress = AthleteDayProgress.objects.create(
            session=session,
            athlete=athlete,
            workout_program=program,
            current_program_item=item,
            current_workout_exercise=exercise,
            expected_set_number=1,
        )
        RackWorkoutState.objects.create(rack_number=1, active_session=session, selected_athlete=athlete)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RackWorkoutState.objects.create(rack_number=2, active_session=session, selected_athlete=athlete)
        Set.objects.create(
            session=session,
            athlete=athlete,
            exercise="Squat",
            set_number=1,
            athlete_day_progress=progress,
            workout_program_item=item,
            workout_exercise=exercise,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Set.objects.create(
                session=session,
                athlete=athlete,
                exercise="Squat",
                set_number=2,
                athlete_day_progress=progress,
                workout_program_item=item,
                workout_exercise=exercise,
            )

    def test_concurrent_sign_ins_leave_the_athlete_on_one_rack(self):
        coach = User.objects.create_user(
            username="exclusive-sign-in-coach", password="test-only", is_staff=True,
        )
        athlete = Athlete.objects.create(name="Concurrent Sign In Athlete")
        workout = Workout.objects.create(name="Concurrent Sign In Workout")
        WorkoutExercise.objects.create(
            workout=workout, exercise="Press", position=1, sets=1, reps=1, default_weight_lbs=0,
        )
        program = WorkoutProgram.objects.create(name="Concurrent Sign In Program")
        WorkoutProgramItem.objects.create(workout_program=program, workout=workout, position=1)
        AthleteWorkoutProgramAssignment.objects.create(athlete=athlete, workout_program=program)
        session = Session.objects.create(label="Concurrent Sign In Day")
        session.athletes.add(athlete)
        devices = {
            1: "30000000-0000-4000-8000-000000000001",
            2: "30000000-0000-4000-8000-000000000002",
        }
        for rack_number, device_id in devices.items():
            RackScreen.objects.create(device_id=device_id, rack_number=rack_number)
            RackWorkoutState.objects.create(rack_number=rack_number, active_session=session)
        barrier = Barrier(3)
        statuses = []
        errors = []

        def sign_in(rack_number):
            close_old_connections()
            try:
                client = APIClient()
                barrier.wait(timeout=5)
                response = client.put(
                    f"/api/racks/{rack_number}/athlete/",
                    {"device_id": devices[rack_number], "athlete_id": athlete.id},
                    format="json",
                )
                statuses.append(response.status_code)
            except Exception as error:
                errors.append(error)
            finally:
                close_old_connections()

        threads = [Thread(target=sign_in, args=(rack_number,)) for rack_number in devices]
        for thread in threads:
            thread.start()
        try:
            barrier.wait(timeout=5)
        finally:
            for thread in threads:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
            close_old_connections()

        self.assertEqual(errors, [])
        self.assertEqual(statuses, [200, 200])
        self.assertEqual(RackWorkoutState.objects.filter(selected_athlete=athlete).count(), 1)
        self.assertEqual(AthleteDayProgress.objects.filter(session=session, athlete=athlete).count(), 1)


class AthleteDrivenCompletionConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_concurrent_duplicate_completion_advances_once(self):
        athlete = Athlete.objects.create(name="Concurrent Completion Athlete")
        workout = Workout.objects.create(name="Concurrent Completion Workout")
        exercise = WorkoutExercise.objects.create(
            workout=workout,
            exercise="Press",
            position=1,
            sets=2,
            reps=1,
            default_weight_lbs=100,
            velocity_min=0.5,
            velocity_max=0.8,
        )
        program = WorkoutProgram.objects.create(name="Concurrent Completion Program")
        item = WorkoutProgramItem.objects.create(workout_program=program, workout=workout, position=1)
        AthleteWorkoutProgramAssignment.objects.create(athlete=athlete, workout_program=program)
        session = Session.objects.create(label="Concurrent Completion Day")
        session.athletes.add(athlete)
        progress = AthleteDayProgress.objects.create(
            session=session,
            athlete=athlete,
            workout_program=program,
            current_program_item=item,
            current_workout_exercise=exercise,
            expected_set_number=1,
            status=AthleteDayProgress.IN_SET,
        )
        RackWorkoutState.objects.create(
            rack_number=1,
            active_session=session,
            selected_athlete=athlete,
        )
        device_id = "40000000-0000-4000-8000-000000000001"
        RackScreen.objects.create(device_id=device_id, rack_number=1)
        workout_set = Set.objects.create(
            session=session,
            athlete=athlete,
            rack_number=1,
            exercise=exercise.exercise,
            set_number=1,
            weight_lbs=100,
            athlete_day_progress=progress,
            workout_program_item=item,
            workout_exercise=exercise,
        )
        payload = {
            "reps_completed": 1,
            "is_false_set": False,
            "reps": [{
                "rep_number": 1,
                "mean_velocity": 0.7,
                "peak_velocity": 0.9,
                "duration_ms": 600,
                "timestamp": timezone.now().isoformat(),
                "velocity_color": "green",
            }],
        }
        barrier = Barrier(3)
        statuses = []
        errors = []

        def complete():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                response = APIClient().post(
                    f"/api/racks/1/sets/{workout_set.id}/complete/",
                    payload,
                    format="json",
                    HTTP_X_RACK_DEVICE_ID=device_id,
                )
                statuses.append(response.status_code)
            except Exception as error:
                errors.append(error)
            finally:
                close_old_connections()

        threads = [Thread(target=complete) for _index in range(2)]
        for thread in threads:
            thread.start()
        try:
            barrier.wait(timeout=5)
        finally:
            for thread in threads:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
            close_old_connections()

        self.assertEqual(errors, [])
        self.assertEqual(sorted(statuses), [200, 409])
        progress.refresh_from_db()
        workout_set.refresh_from_db()
        self.assertEqual((progress.status, progress.expected_set_number), (AthleteDayProgress.READY, 2))
        self.assertIsNotNone(workout_set.ended_at)
        self.assertEqual(workout_set.reps.count(), 1)
        self.assertEqual(Set.objects.filter(athlete_day_progress=progress).count(), 1)


class TrainingDayDatabaseTests(TransactionTestCase):
    reset_sequences = True

    def test_partial_unique_constraint_allows_only_one_active_session(self):
        Session.objects.create(label="One")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Session.objects.create(label="Two")
        Session.objects.filter(label="One").update(ended_at=timezone.now())
        self.assertIsNotNone(Session.objects.create(label="Two").id)

    def test_daily_report_trigger_blocks_update_delete_and_session_delete(self):
        session = Session.objects.create(label="Ended", ended_at=timezone.now())
        report = DailyReport.objects.create(
            session=session,
            schema_version=1,
            snapshot={"schema_version": 1},
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            DailyReport.objects.filter(id=report.id).update(snapshot={"changed": True})
        with self.assertRaises(DatabaseError), transaction.atomic():
            DailyReport.objects.filter(id=report.id).delete()
        with self.assertRaises(ProtectedError):
            session.delete()

    def test_concurrent_session_starts_return_one_created_and_one_conflict(self):
        coach = User.objects.create_user(
            username="concurrent-start-coach", password="test-only", is_staff=True,
        )
        barrier = Barrier(3)
        athlete = Athlete.objects.create(name="Concurrent Athlete")
        results = []
        errors = []

        def start(label):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(coach)
                barrier.wait(timeout=5)
                response = client.post(
                    "/api/sessions/",
                    {"label": label, "athletes": [athlete.id]},
                    format="json",
                )
                results.append(response.status_code)
            except Exception as error:
                errors.append(error)
            finally:
                close_old_connections()

        threads = [Thread(target=start, args=(label,)) for label in ("One", "Two")]
        for thread in threads:
            thread.start()
        try:
            barrier.wait(timeout=5)
        finally:
            for thread in threads:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
            close_old_connections()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [201, 409])
        self.assertEqual(Session.objects.filter(ended_at=None).count(), 1)


class Migration0010Tests(TransactionTestCase):
    migrate_from = ("event_handler", "0009_athlete_workout_assignments_and_overrides")
    migrate_to = ("event_handler", "0010_daily_report_and_one_active_session")
    restore_to = ("event_handler", "0012_athlete_driven_training_foundation")

    def setUp(self):
        close_old_connections()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        self.apps = executor.loader.project_state([self.migrate_from]).apps

    def tearDown(self):
        close_old_connections()
        executor = MigrationExecutor(connection)
        if self.migrate_to not in executor.loader.applied_migrations:
            apps = executor.loader.project_state([self.migrate_from]).apps
            session_model = apps.get_model("event_handler", "Session")
            active_ids = list(
                session_model.objects.filter(ended_at=None)
                .order_by("id")
                .values_list("id", flat=True)
            )
            if len(active_ids) > 1:
                session_model.objects.filter(id__in=active_ids[1:]).update(ended_at=timezone.now())
            executor = MigrationExecutor(connection)
            executor.migrate([self.migrate_to])
        executor = MigrationExecutor(connection)
        if self.restore_to not in executor.loader.applied_migrations:
            executor.migrate([self.restore_to])
        close_old_connections()

    def _index_exists(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = current_schema() AND indexname = %s)",
                ["session_one_active_training_day"],
            )
            return cursor.fetchone()[0]

    def _trigger_exists(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_trigger trigger
                    JOIN pg_class relation ON relation.oid = trigger.tgrelid
                    WHERE trigger.tgname = %s
                      AND relation.relname = %s
                      AND NOT trigger.tgisinternal
                )
                """,
                ["event_handler_daily_report_immutable_trigger", "event_handler_dailyreport"],
            )
            return cursor.fetchone()[0]

    def _assert_source_rows(self, apps, session_ids, athlete_id, set_id):
        session_model = apps.get_model("event_handler", "Session")
        athlete_model = apps.get_model("event_handler", "Athlete")
        set_model = apps.get_model("event_handler", "Set")
        self.assertEqual(set(session_model.objects.filter(id__in=session_ids).values_list("id", flat=True)), session_ids)
        self.assertTrue(athlete_model.objects.filter(id=athlete_id).exists())
        self.assertTrue(set_model.objects.filter(id=set_id).exists())
        self.assertEqual(session_model.objects.get(id=min(session_ids)).athletes.count(), 1)

    def test_preflight_forward_reverse_and_reapply_preserve_source_rows(self):
        athlete_model = self.apps.get_model("event_handler", "Athlete")
        session_model = self.apps.get_model("event_handler", "Session")
        set_model = self.apps.get_model("event_handler", "Set")
        athlete = athlete_model.objects.create(name="Migration Athlete")
        first = session_model.objects.create(label="Migration Active One")
        second = session_model.objects.create(label="Migration Active Two")
        first.athletes.add(athlete)
        workout_set = set_model.objects.create(
            session=first,
            athlete=athlete,
            exercise="Squat",
            set_number=1,
        )
        session_ids = {first.id, second.id}

        executor = MigrationExecutor(connection)
        with self.assertRaisesMessage(RuntimeError, "at most one active Session"):
            executor.migrate([self.migrate_to])

        executor = MigrationExecutor(connection)
        self.assertNotIn(self.migrate_to, executor.loader.applied_migrations)
        self.assertNotIn("event_handler_dailyreport", connection.introspection.table_names())
        self.assertFalse(self._index_exists())
        self.assertFalse(self._trigger_exists())
        self._assert_source_rows(self.apps, session_ids, athlete.id, workout_set.id)

        session_model.objects.filter(id=second.id).update(ended_at=timezone.now())
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        forward_apps = executor.loader.project_state([self.migrate_to]).apps
        self.assertIn("event_handler_dailyreport", connection.introspection.table_names())
        self.assertTrue(self._index_exists())
        self.assertTrue(self._trigger_exists())
        self._assert_source_rows(forward_apps, session_ids, athlete.id, workout_set.id)

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        reverse_apps = executor.loader.project_state([self.migrate_from]).apps
        self.assertNotIn("event_handler_dailyreport", connection.introspection.table_names())
        self.assertFalse(self._index_exists())
        self.assertFalse(self._trigger_exists())
        self._assert_source_rows(reverse_apps, session_ids, athlete.id, workout_set.id)

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        reapplied_apps = executor.loader.project_state([self.migrate_to]).apps
        self.assertIn("event_handler_dailyreport", connection.introspection.table_names())
        self.assertTrue(self._index_exists())
        self.assertTrue(self._trigger_exists())
        self._assert_source_rows(reapplied_apps, session_ids, athlete.id, workout_set.id)


class Migration0012Tests(TransactionTestCase):
    migrate_from = ("event_handler", "0011_daily_report_browse_indexes")
    migrate_to = ("event_handler", "0012_athlete_driven_training_foundation")

    def setUp(self):
        close_old_connections()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        self.apps = executor.loader.project_state([self.migrate_from]).apps

    def tearDown(self):
        close_old_connections()
        executor = MigrationExecutor(connection)
        if self.migrate_to not in executor.loader.applied_migrations:
            rack_state = self.apps.get_model("event_handler", "RackWorkoutState")
            duplicate_ids = list(
                rack_state.objects.exclude(selected_athlete_id=None)
                .order_by("selected_athlete_id", "rack_number")
                .values_list("selected_athlete_id", flat=True)
            )
            seen = set()
            for athlete_id in duplicate_ids:
                if athlete_id in seen:
                    rack_state.objects.filter(selected_athlete_id=athlete_id).order_by("rack_number").last().delete()
                seen.add(athlete_id)
            executor = MigrationExecutor(connection)
            executor.migrate([self.migrate_to])
        close_old_connections()

    def test_preflight_rejects_duplicate_sign_ins_without_changing_source_rows(self):
        athlete_model = self.apps.get_model("event_handler", "Athlete")
        session_model = self.apps.get_model("event_handler", "Session")
        rack_state = self.apps.get_model("event_handler", "RackWorkoutState")
        set_model = self.apps.get_model("event_handler", "Set")
        athlete = athlete_model.objects.create(name="Migration Exclusive Athlete")
        session = session_model.objects.create(label="Migration Foundation Day")
        workout_set = set_model.objects.create(
            session=session,
            athlete=athlete,
            exercise="Legacy squat",
            set_number=1,
        )
        rack_state.objects.create(rack_number=1, active_session=session, selected_athlete=athlete)
        rack_state.objects.create(rack_number=2, active_session=session, selected_athlete=athlete)

        executor = MigrationExecutor(connection)
        with self.assertRaisesMessage(RuntimeError, "at most one rack"):
            executor.migrate([self.migrate_to])

        executor = MigrationExecutor(connection)
        self.assertNotIn(self.migrate_to, executor.loader.applied_migrations)
        self.assertEqual(rack_state.objects.filter(selected_athlete=athlete).count(), 2)
        self.assertNotIn("event_handler_athletedayprogress", connection.introspection.table_names())

        rack_state.objects.filter(rack_number=2).delete()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        forward_apps = executor.loader.project_state([self.migrate_to]).apps
        self.assertTrue(forward_apps.get_model("event_handler", "AthleteWorkoutProgramAssignment"))
        self.assertEqual(
            forward_apps.get_model("event_handler", "RackWorkoutState").objects.get().selected_athlete_id,
            athlete.id,
        )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        reverse_apps = executor.loader.project_state([self.migrate_from]).apps
        preserved = reverse_apps.get_model("event_handler", "Set").objects.get(id=workout_set.id)
        self.assertEqual(preserved.exercise, "Legacy squat")
        self.assertEqual(preserved.athlete_id, athlete.id)
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])


class Migration0013Tests(TransactionTestCase):
    migrate_from = ("event_handler", "0012_athlete_driven_training_foundation")
    migrate_to = ("event_handler", "0013_athlete_rack_participation")

    def setUp(self):
        close_old_connections()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        self.apps = executor.loader.project_state([self.migrate_from]).apps

    def tearDown(self):
        close_old_connections()
        executor = MigrationExecutor(connection)
        if self.migrate_to not in executor.loader.applied_migrations:
            executor.migrate([self.migrate_to])
        close_old_connections()

    def test_forward_reverse_preserves_training_rows_and_drops_participation_metadata(self):
        athlete_model = self.apps.get_model("event_handler", "Athlete")
        session_model = self.apps.get_model("event_handler", "Session")
        set_model = self.apps.get_model("event_handler", "Set")
        report_model = self.apps.get_model("event_handler", "DailyReport")
        athlete = athlete_model.objects.create(name="Participation Migration Athlete")
        session = session_model.objects.create(label="Participation Migration Day")
        session.athletes.add(athlete)
        workout_set = set_model.objects.create(
            session=session,
            athlete=athlete,
            exercise="Migration squat",
            set_number=1,
        )
        report = report_model.objects.create(
            session=session,
            schema_version=2,
            snapshot={"schema_version": 2, "athletes": []},
        )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        forward_apps = executor.loader.project_state([self.migrate_to]).apps
        participation_model = forward_apps.get_model("event_handler", "AthleteRackParticipation")
        participation_model.objects.create(session_id=session.id, athlete_id=athlete.id, rack_number=4)
        self.assertEqual(participation_model.objects.get().rack_number, 4)

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        reverse_apps = executor.loader.project_state([self.migrate_from]).apps
        self.assertNotIn("event_handler_athleterackparticipation", connection.introspection.table_names())
        self.assertEqual(reverse_apps.get_model("event_handler", "Athlete").objects.get(id=athlete.id).name, athlete.name)
        self.assertEqual(reverse_apps.get_model("event_handler", "Set").objects.get(id=workout_set.id).exercise, "Migration squat")
        self.assertEqual(reverse_apps.get_model("event_handler", "DailyReport").objects.get(id=report.id).schema_version, 2)

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        reapplied_apps = executor.loader.project_state([self.migrate_to]).apps
        self.assertFalse(reapplied_apps.get_model("event_handler", "AthleteRackParticipation").objects.exists())


class Migration0011Tests(TransactionTestCase):
    migrate_from = ("event_handler", "0010_daily_report_and_one_active_session")
    migrate_to = ("event_handler", "0011_daily_report_browse_indexes")

    def setUp(self):
        close_old_connections()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        self.apps = executor.loader.project_state([self.migrate_from]).apps

    def tearDown(self):
        close_old_connections()
        executor = MigrationExecutor(connection)
        if self.migrate_to not in executor.loader.applied_migrations:
            executor.migrate([self.migrate_to])
        close_old_connections()

    def _report_index_definitions(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname IN (%s, %s)
                """,
                ["daily_report_newest_idx", "daily_report_athlete_ids_gin"],
            )
            return dict(cursor.fetchall())

    def _assert_source_rows(self, session_id, report_id):
        session_model = self.apps.get_model("event_handler", "Session")
        report_model = self.apps.get_model("event_handler", "DailyReport")
        self.assertTrue(session_model.objects.filter(id=session_id).exists())
        self.assertTrue(report_model.objects.filter(id=report_id, session_id=session_id).exists())

    def test_indexes_forward_reverse_and_reapply_preserve_reports(self):
        session_model = self.apps.get_model("event_handler", "Session")
        report_model = self.apps.get_model("event_handler", "DailyReport")
        session = session_model.objects.create(label="Indexed Report", ended_at=timezone.now())
        report = report_model.objects.create(
            session=session,
            schema_version=1,
            snapshot={"schema_version": 1, "athletes": []},
        )

        self.assertEqual(self._report_index_definitions(), {})
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        definitions = self._report_index_definitions()
        self.assertEqual(set(definitions), {"daily_report_newest_idx", "daily_report_athlete_ids_gin"})
        self.assertIn("generated_at DESC, id DESC", definitions["daily_report_newest_idx"])
        self.assertIn("USING gin", definitions["daily_report_athlete_ids_gin"])
        self.assertIn("jsonb_path_query_array", definitions["daily_report_athlete_ids_gin"])
        self._assert_source_rows(session.id, report.id)

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        self.assertEqual(self._report_index_definitions(), {})
        self._assert_source_rows(session.id, report.id)

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.assertEqual(
            set(self._report_index_definitions()),
            {"daily_report_newest_idx", "daily_report_athlete_ids_gin"},
        )
        self._assert_source_rows(session.id, report.id)


class TrainingLimitApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.coach = User.objects.create_user(
            username="limit-coach", password="test-only", is_staff=True,
        )
        self.coach_client = APIClient()
        self.coach_client.force_authenticate(self.coach)
        self.athlete = Athlete.objects.create(name="Limit Athlete")

    def tearDown(self):
        cache.clear()

    def create_session(self):
        session = Session.objects.create(label="Limit Day")
        session.athletes.add(self.athlete)
        return session

    def test_start_rejects_more_than_100_athletes_without_session_write(self):
        athletes = [Athlete.objects.create(name=f"Athlete {index}") for index in range(MAX_SESSION_ATHLETES + 1)]

        response = self.coach_client.post(
            "/api/sessions/",
            {"label": "Too Many", "athletes": [athlete.id for athlete in athletes]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("athletes", response.data)
        self.assertFalse(Session.objects.exists())

    def test_start_and_report_accept_exactly_100_athletes(self):
        athletes = [self.athlete] + [
            Athlete.objects.create(name=f"Boundary Athlete {index}")
            for index in range(1, MAX_SESSION_ATHLETES)
        ]
        started = self.coach_client.post(
            "/api/sessions/",
            {"label": "Boundary Day", "athletes": [athlete.id for athlete in athletes]},
            format="json",
        )

        self.assertEqual(started.status_code, 201)
        ended = self.coach_client.post(f"/api/sessions/{started.data['id']}/end/", {}, format="json")
        self.assertEqual(ended.status_code, 200)
        self.assertEqual(len(ended.data["snapshot"]["athletes"]), MAX_SESSION_ATHLETES)

    def test_generic_set_create_cannot_poison_real_active_session(self):
        session = self.create_session()
        outsider = Athlete.objects.create(name="Roster Outsider")

        response = APIClient().post("/api/sets/", {
            "session": session.id,
            "athlete": outsider.id,
            "exercise": "Squat",
            "set_number": 1,
        }, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "rack_bound_set_required")
        self.assertFalse(Set.objects.exists())

    def test_generic_set_create_cannot_consume_real_session_set_limit(self):
        session = self.create_session()
        Set.objects.bulk_create([
            Set(
                session=session,
                athlete=self.athlete,
                exercise="Squat",
                set_number=index,
            )
            for index in range(1, MAX_SESSION_SETS + 1)
        ])

        response = APIClient().post("/api/sets/", {
            "session": session.id,
            "athlete": self.athlete.id,
            "exercise": "Squat",
            "set_number": MAX_SESSION_SETS + 1,
        }, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "rack_bound_set_required")
        self.assertEqual(Set.objects.filter(session=session).count(), MAX_SESSION_SETS)

    def test_set_complete_rejects_cumulative_rep_overflow_without_write(self):
        session = self.create_session()
        completed = Set.objects.create(
            session=session,
            athlete=self.athlete,
            exercise="Squat",
            set_number=1,
            ended_at=timezone.now(),
            reps_completed=MAX_SESSION_REPS,
        )
        Rep.objects.bulk_create([
            Rep(
                set=completed,
                rep_number=index,
                timestamp=timezone.now(),
                mean_velocity=0.5,
                peak_velocity=0.7,
                duration_ms=600,
                velocity_color="green",
            )
            for index in range(1, MAX_SESSION_REPS + 1)
        ])
        target = Set.objects.create(
            session=session,
            athlete=self.athlete,
            exercise="Squat",
            set_number=2,
        )

        response = APIClient().post(f"/api/sets/{target.id}/complete/", {
            "reps_completed": 1,
            "is_false_set": False,
            "reps": [{
                "rep_number": 1,
                "mean_velocity": 0.5,
                "peak_velocity": 0.7,
                "duration_ms": 600,
                "timestamp": timezone.now().isoformat(),
                "velocity_color": "green",
            }],
        }, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "session_rep_limit")
        target.refresh_from_db()
        self.assertIsNone(target.ended_at)
        self.assertEqual(Rep.objects.filter(set__session=session).count(), MAX_SESSION_REPS)
        self.assertFalse(MonitoringEvent.objects.exists())

    @patch("event_handler.services.training_days._build_snapshot")
    def test_report_set_preflight_rejects_before_snapshot_materialization(self, build_snapshot):
        session = self.create_session()
        Set.objects.bulk_create([
            Set(
                session=session,
                athlete=self.athlete,
                exercise="Squat",
                set_number=index,
                ended_at=timezone.now(),
            )
            for index in range(1, MAX_SESSION_SETS + 2)
        ])

        response = self.coach_client.post(f"/api/sessions/{session.id}/end/", {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "report_too_large")
        self.assertEqual(response.data["dimensions"]["sets"], MAX_SESSION_SETS + 1)
        self.assertNotIn(self.athlete.name, str(response.data["dimensions"]))
        build_snapshot.assert_not_called()
        session.refresh_from_db()
        self.assertIsNone(session.ended_at)
        self.assertFalse(DailyReport.objects.exists())

    @patch("event_handler.services.training_days._build_snapshot")
    def test_report_athlete_union_preflight_rejects_101_before_snapshot_materialization(self, build_snapshot):
        session = self.create_session()
        extra = [
            Athlete.objects.create(name=f"Report Athlete {index}")
            for index in range(MAX_SESSION_ATHLETES - 1)
        ]
        session.athletes.add(*extra)
        outsider = Athlete.objects.create(name="Legacy Set Outsider")
        Set.objects.create(
            session=session,
            athlete=outsider,
            exercise="Squat",
            set_number=1,
            ended_at=timezone.now(),
        )

        response = self.coach_client.post(f"/api/sessions/{session.id}/end/", {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "report_too_large")
        self.assertEqual(response.data["dimensions"]["athletes"], MAX_SESSION_ATHLETES + 1)
        build_snapshot.assert_not_called()
        session.refresh_from_db()
        self.assertIsNone(session.ended_at)

    @patch("event_handler.services.training_days._build_snapshot")
    def test_report_rep_preflight_rejects_before_snapshot_materialization(self, build_snapshot):
        session = self.create_session()
        workout_set = Set.objects.create(
            session=session,
            athlete=self.athlete,
            exercise="Squat",
            set_number=1,
            ended_at=timezone.now(),
        )
        Rep.objects.bulk_create([
            Rep(
                set=workout_set,
                rep_number=index,
                timestamp=timezone.now(),
                mean_velocity=0.5,
                peak_velocity=0.7,
                duration_ms=600,
                velocity_color="green",
            )
            for index in range(1, MAX_SESSION_REPS + 2)
        ])

        response = self.coach_client.post(f"/api/sessions/{session.id}/end/", {}, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["dimensions"]["reps"], MAX_SESSION_REPS + 1)
        build_snapshot.assert_not_called()
        session.refresh_from_db()
        self.assertIsNone(session.ended_at)

    @patch("event_handler.services.training_days._build_snapshot")
    def test_snapshot_exact_byte_limit_passes_and_one_byte_over_rolls_back(self, build_snapshot):
        session = self.create_session()
        build_snapshot.return_value = {"blob": "x" * (MAX_REPORT_SNAPSHOT_BYTES - 11)}

        accepted = self.coach_client.post(f"/api/sessions/{session.id}/end/", {}, format="json")

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(
            len(json.dumps(accepted.data["snapshot"], separators=(",", ":"), sort_keys=True).encode("utf-8")),
            MAX_REPORT_SNAPSHOT_BYTES,
        )

        next_session = Session.objects.create(label="Overflow Day")
        next_session.athletes.add(self.athlete)
        state = RackWorkoutState.objects.create(
            rack_number=1,
            active_session=next_session,
            selected_athlete=self.athlete,
        )
        build_snapshot.return_value = {"blob": "x" * (MAX_REPORT_SNAPSHOT_BYTES - 10)}

        rejected = self.coach_client.post(f"/api/sessions/{next_session.id}/end/", {}, format="json")

        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.data["code"], "report_too_large")
        self.assertEqual(rejected.data["dimensions"]["snapshot_bytes"], MAX_REPORT_SNAPSHOT_BYTES + 1)
        next_session.refresh_from_db()
        state.refresh_from_db()
        self.assertIsNone(next_session.ended_at)
        self.assertEqual(state.selected_athlete_id, self.athlete.id)
        self.assertEqual(DailyReport.objects.count(), 1)

    def test_anonymous_set_write_throttle_covers_create_and_complete(self):
        athlete = Athlete.objects.create(name="Simulated Throttle Athlete", is_simulated=True)
        session = Session.objects.create(label="Simulated Throttle Day", is_simulated=True)
        session.athletes.add(athlete)
        client = APIClient()
        for index in range(1, 121):
            response = client.post(
                "/api/sets/",
                {
                    "session": session.id,
                    "athlete": athlete.id,
                    "exercise": "Squat",
                    "set_number": index,
                },
                format="json",
                REMOTE_ADDR="10.0.0.50",
            )
            self.assertEqual(response.status_code, 201)
        blocked = client.post(
            "/api/sets/",
            {
                "session": session.id,
                "athlete": athlete.id,
                "exercise": "Squat",
                "set_number": 121,
            },
            format="json",
            REMOTE_ADDR="10.0.0.50",
        )
        self.assertEqual(blocked.status_code, 429)

        cache.clear()
        for set_id in range(100000, 100120):
            response = client.post(
                f"/api/sets/{set_id}/complete/",
                {"reps_completed": 0, "is_false_set": False, "reps": []},
                format="json",
                REMOTE_ADDR="10.0.0.51",
            )
            self.assertEqual(response.status_code, 404)
        blocked = client.post(
            "/api/sets/999999/complete/",
            {"reps_completed": 0, "is_false_set": False, "reps": []},
            format="json",
            REMOTE_ADDR="10.0.0.51",
        )
        self.assertEqual(blocked.status_code, 429)


class ReportBrowsingApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.coach = User.objects.create_user(
            username="report-browser-coach", password="test-only", is_staff=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.coach)

    def create_report(
        self,
        *,
        athlete=None,
        schema_version=1,
        ended_at="2026-07-16T20:00:00+00:00",
        weight_lbs=225,
        reps_completed=1,
        avg_velocity=0.7,
        peak_velocity=0.9,
        set_updates=None,
    ):
        session = Session.objects.create(
            label=f"Report {DailyReport.objects.count() + 1}",
            ended_at=timezone.now(),
            notes="private session note",
        )
        athletes = []
        if athlete is not None:
            session.athletes.add(athlete)
            athletes = [{
                "athlete": {
                    "id": athlete.id,
                    "name": athlete.name,
                    "notes": "private athlete note",
                    "nfc_tag_id": "private-nfc",
                },
                "prescription": {
                    "source": "athlete",
                    "rack_number": 1,
                    "program": {"id": 4, "name": "Program", "secret": "program-secret"},
                    "workout": {"id": 5, "name": "Strength", "secret": "workout-secret"},
                    "exercises": [{
                        "id": 6,
                        "exercise": "Squat",
                        "position": 1,
                        "sets": 3,
                        "reps": 5,
                        "default_weight_lbs": weight_lbs,
                        "velocity_min": 0,
                        "velocity_max": None,
                        "secret": "exercise-secret",
                    }],
                },
                "sets": [{
                    "id": 7,
                    "rack_number": 1,
                    "exercise": "Squat",
                    "set_number": 1,
                    "weight_lbs": weight_lbs,
                    "started_at": "2026-07-16T19:59:00+00:00",
                    "ended_at": ended_at,
                    "reps_completed": reps_completed,
                    "avg_velocity": avg_velocity,
                    "peak_velocity": peak_velocity,
                    "secret": "set-secret",
                    "reps": [{
                        "id": 8,
                        "rep_number": 1,
                        "timestamp": ended_at,
                        "mean_velocity": 0,
                        "peak_velocity": 0,
                        "duration_ms": 0,
                        "velocity_color": "green",
                        "secret": "rep-secret",
                    }],
                    **(set_updates or {}),
                }],
                "secret": "athlete-row-secret",
            }]
        return DailyReport.objects.create(
            session=session,
            schema_version=schema_version,
            snapshot={
                "schema_version": schema_version,
                "generated_at": ended_at,
                "session": {
                    "id": session.id,
                    "label": session.label,
                    "started_at": "2026-07-16T18:00:00+00:00",
                    "ended_at": ended_at,
                    "notes": "private snapshot note",
                },
                "athletes": athletes,
                "exclusions": {
                    "false_sets": 0,
                    "simulated_sets": 0,
                    "unsaved_live_reps": "not_persisted",
                    "secret": "exclusion-secret",
                },
                "raw_mqtt": "private-payload",
                "device_uuid": "private-device",
                "token": "private-token",
            },
        )

    def test_report_routes_require_coach_are_no_store_and_have_no_mutations(self):
        athlete = Athlete.objects.create(name="Authorization Athlete")
        report = self.create_report(athlete=athlete)
        anonymous = APIClient()
        non_coach = APIClient()
        non_coach.force_authenticate(User.objects.create_user(username="report-viewer", password="test-only"))

        for path in (
            "/api/reports/",
            f"/api/reports/{report.id}/",
            f"/api/athletes/{athlete.id}/reports/",
            f"/api/athletes/{athlete.id}/reports/{report.id}/",
        ):
            with self.subTest(path=path):
                self.assertEqual(anonymous.get(path).status_code, 401)
                self.assertEqual(non_coach.get(path).status_code, 403)
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Cache-Control"], "private, no-store")

        self.assertEqual(self.client.post("/api/reports/", {}, format="json").status_code, 405)
        self.assertEqual(self.client.patch(f"/api/reports/{report.id}/", {}, format="json").status_code, 405)

    def test_schema_one_daily_and_athlete_pdfs_are_private_safe_and_snapshot_only(self):
        athlete = Athlete.objects.create(name="PDF Athlete", notes="database-only-secret")
        report = self.create_report(athlete=athlete, weight_lbs=None, avg_velocity=None, peak_velocity=0)
        original = json.dumps(report.snapshot, sort_keys=True)
        anonymous = APIClient()
        non_coach = APIClient()
        non_coach.force_authenticate(User.objects.create_user(username="pdf-viewer", password="test-only"))

        paths = (
            (f"/api/reports/{report.id}/pdf/", f'attachment; filename="report-{report.id}.pdf"'),
            (
                f"/api/athletes/{athlete.id}/reports/{report.id}/pdf/",
                f'attachment; filename="athlete-{athlete.id}-report-{report.id}.pdf"',
            ),
        )
        for path, disposition in paths:
            with self.subTest(path=path):
                self.assertEqual(anonymous.get(path).status_code, 401)
                self.assertEqual(non_coach.get(path).status_code, 403)
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.content.startswith(b"%PDF-"))
                self.assertEqual(response["Content-Type"], "application/pdf")
                self.assertEqual(response["Content-Disposition"], disposition)
                self.assertEqual(response["Cache-Control"], "private, no-store")
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")
                self.assertIn(b"(Not)", response.content)
                self.assertIn(b"(measured)", response.content)
                self.assertIn(b"0 m/s", response.content)
                for private_value in (b"private", b"secret", b"raw_mqtt", b"device_uuid", b"token"):
                    self.assertNotIn(private_value, response.content.lower())
        report.refresh_from_db()
        self.assertEqual(json.dumps(report.snapshot, sort_keys=True), original)

    @patch("event_handler.views.render_report_pdf", return_value=b"%PDF-test")
    def test_pdf_throttle_is_shared_per_coach_and_runs_before_report_lookup(self, render_pdf):
        athlete = Athlete.objects.create(name="Throttled PDF Athlete")
        report = self.create_report(athlete=athlete)
        daily_path = f"/api/reports/{report.id}/pdf/"
        athlete_path = f"/api/athletes/{athlete.id}/reports/{report.id}/pdf/"

        for path in [daily_path] * 5 + [athlete_path] * 5:
            self.assertEqual(self.client.get(path).status_code, 200)
        blocked_missing = self.client.get("/api/reports/999999/pdf/")

        other_coach = User.objects.create_user(
            username="other-pdf-coach", password="test-only", is_staff=True,
        )
        other_client = APIClient()
        other_client.force_authenticate(other_coach)
        for _index in range(10):
            self.assertEqual(other_client.get("/api/reports/999999/pdf/").status_code, 404)
        blocked_existing = other_client.get(daily_path)

        self.assertEqual(blocked_missing.status_code, 429)
        self.assertEqual(blocked_existing.status_code, 429)
        self.assertEqual(blocked_missing["Cache-Control"], "private, no-store")
        self.assertEqual(blocked_existing["Cache-Control"], "private, no-store")
        self.assertEqual(render_pdf.call_count, 10)

    def test_pdf_stable_errors_do_not_change_report(self):
        athlete = Athlete.objects.create(name="PDF Failure Athlete")
        report = self.create_report(athlete=athlete)
        original = json.dumps(report.snapshot, sort_keys=True)

        with patch("event_handler.services.report_pdf.MAX_PDF_BYTES", 100):
            too_large = self.client.get(f"/api/reports/{report.id}/pdf/")
        with patch("event_handler.views.render_report_pdf", side_effect=RuntimeError("private snapshot")):
            failed = self.client.get(f"/api/reports/{report.id}/pdf/")

        self.assertEqual(too_large.status_code, 409)
        self.assertEqual(too_large.data["code"], "pdf_too_large")
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.data["code"], "pdf_render_failed")
        self.assertNotContains(failed, "private snapshot", status_code=500)
        report.refresh_from_db()
        self.assertEqual(json.dumps(report.snapshot, sort_keys=True), original)

    def test_report_list_is_newest_first_default_10_and_max_20(self):
        reports = [self.create_report() for _index in range(25)]

        default_page = self.client.get("/api/reports/")
        capped_page = self.client.get("/api/reports/?page_size=100")
        second_page = self.client.get("/api/reports/?page=2")

        self.assertEqual(default_page.status_code, 200)
        self.assertEqual(default_page.data["count"], 25)
        self.assertEqual(len(default_page.data["results"]), 10)
        self.assertEqual(
            [item["id"] for item in default_page.data["results"]],
            [report.id for report in reversed(reports[-10:])],
        )
        self.assertEqual(len(capped_page.data["results"]), 20)
        self.assertEqual(len(second_page.data["results"]), 10)
        self.assertNotIn("snapshot", default_page.data["results"][0])

    def test_report_detail_allowlists_snapshot_and_builds_summary(self):
        athlete = Athlete.objects.create(name="Privacy Athlete", notes="database private note")
        report = self.create_report(athlete=athlete)

        response = self.client.get(f"/api/reports/{report.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"], {
            "athlete_count": 1,
            "completed_sets": 1,
            "completed_reps": 1,
            "average_velocity": 0.7,
        })
        self.assertEqual(response.data["local_date"], "2026-07-16")
        self.assertEqual(response.data["timezone"], "UTC")
        self.assertNotIn("snapshot", response.data)
        rendered = response.content.decode()
        for secret in (
            "private", "secret", "raw_mqtt", "device_uuid", "token", "nfc_tag_id", "notes",
        ):
            self.assertNotIn(secret, rendered)

    def test_schema_two_false_set_allowlist_preserves_bindings_and_pdf_exclusion_label(self):
        athlete = Athlete.objects.create(name="False Set Report Athlete")
        report = self.create_report(
            athlete=athlete,
            schema_version=2,
            reps_completed=0,
            set_updates={
                "athlete_day_progress_id": 31,
                "workout_program_item_id": 32,
                "workout_exercise_id": 33,
                "is_false_set": True,
                "false_set_secret": "must-not-render",
                "reps": [],
            },
        )

        detail = self.client.get(f"/api/reports/{report.id}/")
        pdf = self.client.get(f"/api/reports/{report.id}/pdf/")

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["summary"]["completed_sets"], 0)
        self.assertEqual(detail.data["summary"]["completed_reps"], 0)
        result = detail.data["athletes"][0]["sets"][0]
        self.assertEqual(
            (result["athlete_day_progress_id"], result["workout_program_item_id"], result["workout_exercise_id"]),
            (31, 32, 33),
        )
        self.assertTrue(result["is_false_set"])
        self.assertNotContains(detail, "must-not-render")
        self.assertEqual(pdf.status_code, 200)
        self.assertIn(b"False set", pdf.content)
        self.assertNotIn(b"must-not-render", pdf.content)

    def test_athlete_reports_are_paginated_and_detail_is_scoped(self):
        athlete = Athlete.objects.create(name="History Athlete")
        reports = [self.create_report(athlete=athlete) for _index in range(21)]

        default_page = self.client.get(f"/api/athletes/{athlete.id}/reports/")
        capped_page = self.client.get(f"/api/athletes/{athlete.id}/reports/?page_size=100")
        detail = self.client.get(f"/api/athletes/{athlete.id}/reports/{reports[-1].id}/")

        self.assertEqual(default_page.status_code, 200)
        self.assertEqual(default_page.data["count"], 21)
        self.assertEqual(len(default_page.data["results"]), 10)
        self.assertEqual(len(capped_page.data["results"]), 20)
        self.assertNotIn("sets", default_page.data["results"][0]["athlete"])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["athlete"]["athlete"]["id"], athlete.id)
        self.assertEqual(len(detail.data["athlete"]["sets"]), 1)

    def test_athlete_filter_matches_numeric_id_not_substring_and_binds_parameter(self):
        athlete = Athlete.objects.create(name="ID Athlete")
        similar_id = int(f"{athlete.id}0")
        similar = Athlete.objects.create(id=similar_id, name="Similar ID Athlete")
        expected = self.create_report(athlete=athlete)
        self.create_report(athlete=similar)

        response = self.client.get(f"/api/athletes/{athlete.id}/reports/")
        sql, params = reports_for_athlete(987654321).query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan = off")
        query_plan = reports_for_athlete(athlete.id).explain()

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [expected.id])
        self.assertNotIn("987654321", sql)
        self.assertIn(987654321, params)
        self.assertIn("jsonb_path_query_array", sql)
        self.assertIn("daily_report_athlete_ids_gin", query_plan)

    @override_settings(TIME_ZONE="America/Los_Angeles")
    def test_timezone_and_null_values_remain_distinct_from_zero(self):
        athlete = Athlete.objects.create(name="Timezone Athlete")
        report = self.create_report(
            athlete=athlete,
            ended_at="2026-01-01T02:00:00+00:00",
            weight_lbs=None,
            reps_completed=0,
            avg_velocity=None,
            peak_velocity=0,
        )

        response = self.client.get(f"/api/reports/{report.id}/")
        workout_set = response.data["athletes"][0]["sets"][0]
        rep = workout_set["reps"][0]

        self.assertEqual(response.data["local_date"], "2025-12-31")
        self.assertEqual(response.data["timezone"], "America/Los_Angeles")
        self.assertIsNone(response.data["summary"]["average_velocity"])
        self.assertEqual(response.data["summary"]["completed_reps"], 0)
        self.assertIsNone(workout_set["weight_lbs"])
        self.assertIsNone(workout_set["avg_velocity"])
        self.assertEqual(workout_set["peak_velocity"], 0)
        self.assertEqual(rep["mean_velocity"], 0)
        self.assertEqual(rep["duration_ms"], 0)

    def test_unknown_athlete_report_combinations_use_generic_404(self):
        athlete = Athlete.objects.create(name="Known Athlete")
        other = Athlete.objects.create(name="Other Athlete")
        report = self.create_report(athlete=athlete)

        responses = [
            self.client.get("/api/reports/999999/"),
            self.client.get("/api/athletes/999999/reports/"),
            self.client.get(f"/api/athletes/999999/reports/{report.id}/"),
            self.client.get(f"/api/athletes/{other.id}/reports/{report.id}/"),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.data, {"code": "report_not_found", "detail": "Report not found."})
            self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_unsupported_schema_returns_409_without_snapshot(self):
        athlete = Athlete.objects.create(name="Future Athlete")
        report = self.create_report(athlete=athlete, schema_version=99)

        for path in (
            "/api/reports/",
            f"/api/reports/{report.id}/",
            f"/api/athletes/{athlete.id}/reports/",
            f"/api/athletes/{athlete.id}/reports/{report.id}/",
            f"/api/reports/{report.id}/pdf/",
            f"/api/athletes/{athlete.id}/reports/{report.id}/pdf/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.data["code"], "unsupported_report_schema")
                self.assertNotIn("snapshot", response.data)


class AthleteCollectionApiTests(TestCase):
    def setUp(self):
        self.coach = User.objects.create_user(
            username="athlete-list-coach", password="test-only", is_staff=True,
        )
        self.coach_client = APIClient()
        self.coach_client.force_authenticate(self.coach)
        self.athlete = Athlete.objects.create(
            name="Private Athlete", nfc_tag_id="private-nfc", notes="private note",
        )

    def test_athlete_list_denies_anonymous_and_non_coach_users(self):
        anonymous = APIClient().get("/api/athletes/")
        non_coach_client = APIClient()
        non_coach_client.force_authenticate(
            User.objects.create_user(username="athlete-list-viewer", password="test-only"),
        )
        non_coach = non_coach_client.get("/api/athletes/")

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(non_coach.status_code, 403)
        self.assertEqual(anonymous["Cache-Control"], "private, no-store")
        self.assertEqual(non_coach["Cache-Control"], "private, no-store")

    def test_coach_can_list_and_create_athletes_with_private_responses(self):
        listed = self.coach_client.get("/api/athletes/")
        created = self.coach_client.post(
            "/api/athletes/", {"name": "New Athlete"}, format="json",
        )

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data, [{"id": self.athlete.id, "name": self.athlete.name}])
        self.assertNotContains(listed, "private-nfc")
        self.assertNotContains(listed, "private note")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["name"], "New Athlete")
        self.assertEqual(listed["Cache-Control"], "private, no-store")
        self.assertEqual(created["Cache-Control"], "private, no-store")


class SetCompleteValidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_rejects_rep_count_mismatch(self):
        from .serializers import SetCompleteSerializer

        form = SetCompleteSerializer(data={
            "reps_completed": 2,
            "is_false_set": False,
            "reps": [],
        })

        self.assertFalse(form.is_valid())
        self.assertIn("non_field_errors", form.errors)

    def test_rejects_non_finite_rep_velocity_values(self):
        from .serializers import SetCompleteSerializer

        for label, value in (
            ("NaN", float("nan")),
            ("Infinity", float("inf")),
            ("negative Infinity", float("-inf")),
            ("exponent overflow", float("1e309")),
        ):
            for field in ("mean_velocity", "peak_velocity"):
                with self.subTest(label=label, field=field):
                    rep = {
                        "rep_number": 1,
                        "mean_velocity": 0.8,
                        "peak_velocity": 0.9,
                        "duration_ms": 600,
                        "timestamp": timezone.now().isoformat(),
                        "velocity_color": "green",
                    }
                    rep[field] = value
                    form = SetCompleteSerializer(data={
                        "reps_completed": 1,
                        "is_false_set": False,
                        "reps": [rep],
                    })

                    self.assertFalse(form.is_valid())
                    self.assertIn(field, form.errors["reps"][0])

    def test_endpoint_rejects_nan_infinity_and_exponent_overflow(self):
        athlete = Athlete.objects.create(name="Finite Rep Athlete")
        session = Session.objects.create(label="Finite Rep Day")
        workout_set = Set.objects.create(
            session=session,
            athlete=athlete,
            exercise="Back squat",
            set_number=1,
        )
        template = (
            '{"reps_completed":1,"is_false_set":false,"reps":[{'
            '"rep_number":1,"mean_velocity":%s,"peak_velocity":1,'
            '"duration_ms":600,"timestamp":"2026-07-16T20:00:00Z",'
            '"velocity_color":"green"}]}'
        )

        for value in ("NaN", "Infinity", "1e309"):
            with self.subTest(value=value):
                response = self.client.post(
                    f"/api/sets/{workout_set.id}/complete/",
                    data=template % value,
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
        workout_set.refresh_from_db()
        self.assertIsNone(workout_set.ended_at)
        self.assertEqual(workout_set.reps.count(), 0)

    def test_completion_derives_totals_and_rejects_duplicate_submission(self):
        athlete = Athlete.objects.create(name="Jordan Lee")
        session = Session.objects.create(label="Training")
        workout_set = Set.objects.create(
            session=session,
            athlete=athlete,
            exercise="Back squat",
            set_number=1,
        )
        payload = {
            "reps_completed": 1,
            "avg_velocity": 99,
            "peak_velocity": 99,
            "is_false_set": False,
            "reps": [{
                "rep_number": 1,
                "mean_velocity": 0.8,
                "peak_velocity": 0.9,
                "duration_ms": 600,
                "timestamp": timezone.now().isoformat(),
                "velocity_color": "green",
            }],
        }

        first_response = self.client.post(
            f"/api/sets/{workout_set.id}/complete/",
            payload,
            format="json",
        )
        second_response = self.client.post(
            f"/api/sets/{workout_set.id}/complete/",
            payload,
            format="json",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.data["avg_velocity"], 0.8)
        self.assertEqual(first_response.data["peak_velocity"], 0.9)
        self.assertEqual(second_response.status_code, 409)
        self.assertEqual(workout_set.reps.count(), 1)
        self.assertEqual(MonitoringEvent.objects.count(), 1)
        self.assertEqual(MonitoringEvent.objects.get().reason, "set_completed")


class CoachAthleteContextTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        coach = User.objects.create_user(username="context-coach", password="test-only", is_staff=True)
        self.client.force_authenticate(coach)
        self.athlete = Athlete.objects.create(name="Jordan Lee", nfc_tag_id="private-nfc", notes="Remember this")

    def test_analytics_returns_completed_context_without_private_fields(self):
        session = Session.objects.create(label="Strength Day", notes="private session note")
        completed = Set.objects.create(session=session, athlete=self.athlete, exercise="Back squat", set_number=1, weight_lbs=225)
        completed.ended_at = timezone.now()
        completed.reps_completed = 1
        completed.avg_velocity = 0.8
        completed.peak_velocity = 0.9
        completed.save()
        Rep.objects.create(set=completed, rep_number=1, timestamp=timezone.now(), mean_velocity=0.8, peak_velocity=0.9, duration_ms=600, velocity_color="green")
        Set.objects.create(session=session, athlete=self.athlete, exercise="Back squat", set_number=2)
        Set.objects.create(session=session, athlete=self.athlete, exercise="Back squat", set_number=3, ended_at=timezone.now(), is_false_set=True)

        response = self.client.get(f"/api/analytics/athlete/{self.athlete.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["completed_sets"], 1)
        self.assertEqual(response.data["sets"][0]["reps"][0]["mean_velocity"], 0.8)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertNotContains(response, "private-nfc")
        self.assertNotContains(response, "Remember this")
        self.assertNotContains(response, "private session note")

    def test_notes_save_and_reject_stale_version(self):
        loaded = self.client.get(f"/api/athletes/{self.athlete.id}/notes/")
        saved = self.client.put(
            f"/api/athletes/{self.athlete.id}/notes/",
            {"text": "New durable context", "expected_version": loaded.data["version"]},
            format="json",
        )
        conflict = self.client.put(
            f"/api/athletes/{self.athlete.id}/notes/",
            {"text": "Overwrite", "expected_version": loaded.data["version"]},
            format="json",
        )

        self.assertEqual(saved.status_code, 200)
        self.assertEqual(conflict.status_code, 409)
        self.athlete.refresh_from_db()
        self.assertEqual(self.athlete.notes, "New durable context")

    def test_generic_patch_cannot_bypass_note_version(self):
        response = self.client.patch(
            f"/api/athletes/{self.athlete.id}/",
            {"notes": "bypass"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class MonitoringPublisherTests(TestCase):
    def test_publishes_privacy_safe_retained_revision_and_marks_event(self):
        event = MonitoringEvent.objects.create(reason="set_completed")
        result = Mock()
        result.is_published.return_value = True
        client = Mock()
        client.publish.return_value = result

        self.assertTrue(publish_pending_event(client))

        topic, body = client.publish.call_args.args[:2]
        options = client.publish.call_args.kwargs
        event.refresh_from_db()
        self.assertEqual(topic, DASHBOARD_TOPIC)
        self.assertIn(f'"revision":{event.id}', body)
        self.assertNotIn("athlete", body)
        self.assertEqual(options, {"qos": 1, "retain": True})
        self.assertIsNotNone(event.published_at)

    def test_failed_publish_stays_pending(self):
        event = MonitoringEvent.objects.create(reason="set_completed")
        client = Mock()
        client.publish.side_effect = RuntimeError("broker unavailable")

        with self.assertRaises(RuntimeError):
            publish_pending_event(client)

        event.refresh_from_db()
        self.assertIsNone(event.published_at)
        self.assertEqual(event.publish_attempts, 1)

    def test_unacknowledged_publish_stays_pending(self):
        event = MonitoringEvent.objects.create(reason="set_completed")
        result = Mock()
        result.is_published.return_value = False
        client = Mock()
        client.publish.return_value = result

        with self.assertRaisesMessage(RuntimeError, "did not acknowledge"):
            publish_pending_event(client)

        event.refresh_from_db()
        self.assertIsNone(event.published_at)

    def test_drains_revisions_in_order(self):
        first = MonitoringEvent.objects.create(reason="set_completed")
        second = MonitoringEvent.objects.create(reason="set_completed")
        result = Mock()
        result.is_published.return_value = True
        client = Mock()
        client.publish.return_value = result

        publish_pending_event(client)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertIsNotNone(first.published_at)
        self.assertIsNone(second.published_at)


class PulseTests(TestCase):
    def test_contract_pulse_updates_current_node_health(self):
        Node.objects.create(node_id="node-1")
        payload = parse_pulse_payload(b'{"node_id":"node-1","event_type":"pulse","battery_level":87,"signal_strength":-55,"firmware_version":"1.0.0","timestamp":"2026-07-13T20:00:00Z"}')

        node = process_pulse_event(payload)

        self.assertEqual(node.node_id, "node-1")
        self.assertEqual(node.battery_level, 87)
        self.assertEqual(node.signal_strength, -55)
        self.assertEqual(node.firmware_version, "1.0.0")
        self.assertEqual(node.last_seen.isoformat(), "2026-07-13T20:00:00+00:00")
        self.assertEqual(MonitoringEvent.objects.get().reason, "node_health_changed")

    def test_rejects_unregistered_replayed_and_future_pulses(self):
        with self.assertRaisesMessage(ValueError, "node is not registered"):
            process_pulse_event(parse_pulse_payload(b'{"node_id":"unknown","event_type":"pulse","battery_level":87,"signal_strength":-55,"firmware_version":"1.0.0","timestamp":"2026-07-13T20:00:00Z"}'))

        node = Node.objects.create(node_id="node-1", last_seen=timezone.now())
        replay = parse_pulse_payload(
            ('{"node_id":"node-1","event_type":"pulse","battery_level":10,"signal_strength":-100,"firmware_version":"old","timestamp":"%s"}' % (timezone.now() - timedelta(minutes=1)).isoformat()).encode()
        )
        process_pulse_event(replay)
        node.refresh_from_db()
        self.assertNotEqual(node.battery_level, 10)

        future = parse_pulse_payload(
            ('{"node_id":"node-1","event_type":"pulse","battery_level":87,"signal_strength":-55,"firmware_version":"1.0.0","timestamp":"%s"}' % (timezone.now() + timedelta(minutes=10)).isoformat()).encode()
        )
        with self.assertRaisesMessage(ValueError, "too far in the future"):
            process_pulse_event(future)

    def test_topic_identity_must_match_payload_and_listener_continues(self):
        node = Node.objects.create(node_id="node-1")
        payload = b'{"node_id":"node-1","event_type":"pulse","battery_level":87,"signal_strength":-55,"firmware_version":"1.0.0","timestamp":"2026-07-13T20:00:00Z"}'

        on_message(None, None, SimpleNamespace(topic="edgeathlete/node/node-2/pulse", payload=payload))
        node.refresh_from_db()
        self.assertIsNone(node.battery_level)

        on_message(None, None, SimpleNamespace(topic="edgeathlete/node/node-1/pulse", payload=payload))
        node.refresh_from_db()
        self.assertEqual(node.battery_level, 87)
