"""Proves dashboard privacy/state contracts and protects atomic set completion behavior."""

from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Athlete, MonitoringEvent, Node, Program, RackScreen, Rep, Session, Set
from .notification_flow.broadcast.publisher import DASHBOARD_TOPIC, publish_pending_event
from .notification_flow.event_processor.process_pulse import process_pulse_event
from .notification_flow.mqtt_ingester.parser import parse_pulse_payload, parse_rep_payload
from .notification_flow.mqtt_ingester.subscriber import on_message


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
        Session.objects.create(label="[SIMULATION] Real label", is_simulated=False)
        Session.objects.create(label="Anything", is_simulated=True)
        Node.objects.create(node_id="sim-rack-real", is_simulated=False)
        Node.objects.create(node_id="anything", is_simulated=True)
        MonitoringEvent.objects.create(reason="set_completed", is_simulated=True)

        call_command("clear_simulation_data", confirm=True)

        self.assertTrue(Athlete.objects.filter(id=real_athlete.id).exists())
        self.assertFalse(Athlete.objects.filter(id=simulated_athlete.id).exists())
        self.assertTrue(Session.objects.filter(label="[SIMULATION] Real label").exists())
        self.assertTrue(Node.objects.filter(node_id="sim-rack-real").exists())
        self.assertFalse(MonitoringEvent.objects.filter(is_simulated=True).exists())
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
        older_session = Session.objects.create(label="Older session", notes="private session note")
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
            "active_racks": 1,
        })
        rack = response.data["racks"][0]
        self.assertEqual(rack["latest_set"]["id"], completed_set.id)
        self.assertEqual(rack["latest_set"]["target_zone"], {"min": 0.75, "max": 0.9})
        self.assertEqual(rack["status_color"], "green")
        self.assertEqual(response.data["leaderboard"][0]["athlete"]["name"], "Jordan Lee")
        self.assertEqual(response.data["insights"][0]["type"], "fastest_set_average")
        self.assertEqual(rack["latest_set"]["measured_insights"]["velocity_loss"], 0)
        self.assertNotContains(response, "private-nfc-id")
        self.assertNotContains(response, "private coach note")
        self.assertNotContains(response, "private session note")

        wall_response = APIClient().get("/api/wall-state/")
        self.assertEqual(wall_response.status_code, 200)
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
