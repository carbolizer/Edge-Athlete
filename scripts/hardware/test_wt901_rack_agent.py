import importlib.util
import asyncio
import json
import math
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).with_name("wt901_rack_agent.py")
SPEC = importlib.util.spec_from_file_location("wt901_rack_agent", MODULE_PATH)
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


def frame(acceleration=(0, 0, 2048), angular=(0, 0, 0), angles=(0, 0, 0)):
    return agent.FRAME_HEADER + struct.pack("<9h", *(acceleration + angular + angles))


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeScanner:
    discovered = {}
    calls = []

    @classmethod
    async def discover(cls, **kwargs):
        cls.calls.append(kwargs)
        return cls.discovered


class FakeService:
    def __init__(self, has_notify=True):
        self.has_notify = has_notify

    def get_characteristic(self, uuid):
        return object() if self.has_notify and uuid == agent.NOTIFY_UUID else None


class FakeServices:
    def __init__(self, has_service=True, has_notify=True):
        self.service = FakeService(has_notify) if has_service else None

    def get_service(self, uuid):
        return self.service if uuid == agent.SERVICE_UUID else None


class FakeClient:
    notifications = [frame(), frame(acceleration=(0, 0, 4096))]
    has_service = True
    has_notify = True
    addresses = []

    def __init__(self, address, timeout, disconnected_callback=None):
        self.address = address
        self.timeout = timeout
        self.disconnected_callback = disconnected_callback
        self.services = FakeServices(self.has_service, self.has_notify)
        self.addresses.append(address)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def start_notify(self, uuid, callback):
        self.notify_uuid = uuid
        for notification in self.notifications:
            callback(None, notification)


class WT901FrameDecoderTests(unittest.TestCase):
    def test_decodes_verified_frame(self):
        samples = agent.WT901FrameDecoder().feed(frame())
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].acceleration_g, (0.0, 0.0, 1.0))

    def test_handles_combined_fragmented_and_noisy_notifications(self):
        decoder = agent.WT901FrameDecoder()
        payload = frame()
        self.assertEqual(decoder.feed(payload[:7]), [])
        self.assertEqual(len(decoder.feed(payload[7:] + frame())), 2)
        self.assertEqual(len(decoder.feed(b"noise" + frame())), 1)

    def test_bounds_unframed_input(self):
        decoder = agent.WT901FrameDecoder()
        self.assertEqual(decoder.feed(b"x" * (agent.MAX_BUFFER_BYTES + 1)), [])
        self.assertEqual(decoder.rejected_bytes, agent.MAX_BUFFER_BYTES + 1)


class AgentContractTests(unittest.TestCase):
    def test_movement_calibrates_and_is_bounded(self):
        estimator = agent.MovementEstimator(calibration_samples=1)
        estimator.update(agent.decode_frame(frame()))
        moving = agent.decode_frame(frame(acceleration=(0, 0, 4096)))
        self.assertAlmostEqual(estimator.update(moving), 0.99)

    def test_rejects_unsafe_node_id(self):
        with self.assertRaises(ValueError):
            agent.validate_node_id("rack/+/one")

    def test_health_payload_exposes_no_raw_data_or_address(self):
        status = agent.AgentStatus("wt901_test_1")
        diagnostics = {"state": "idle", "noise_floor": 0.02}
        status.sample(0.25, 0.3, diagnostics)
        status.accepted_rep()
        payload = status.payload()
        self.assertEqual(payload["state"], "live")
        self.assertEqual(payload["movement_g"], 0.25)
        self.assertEqual(payload["activity_score"], 0.3)
        self.assertEqual(payload["accepted_reps"], 1)
        self.assertEqual(payload["detector"], diagnostics)
        self.assertEqual(
            set(payload),
            {
                "schema_version", "node_id", "state", "movement_g",
                "activity_score", "accepted_reps", "detector", "sample_age_ms",
                "frames_received",
            },
        )

    def test_agent_rejects_non_loopback_binds(self):
        self.assertTrue(agent.is_loopback_bind("127.0.0.1"))
        self.assertTrue(agent.is_loopback_bind("::1"))
        self.assertTrue(agent.is_loopback_bind("localhost"))
        self.assertFalse(agent.is_loopback_bind("0.0.0.0"))
        self.assertFalse(agent.is_loopback_bind("192.168.1.10"))
        self.assertFalse(agent.is_loopback_bind("rack-host"))

    def test_legacy_arguments_remain_supported(self):
        options = agent.parse_args(["--address", "private", "--node-id", "wt901_test_1"])
        self.assertEqual(options.address, "private")
        self.assertEqual(options.node_id, "wt901_test_1")
        self.assertEqual(options.mqtt_host, agent.DEFAULT_MQTT_HOST)
        self.assertEqual(options.mqtt_port, agent.DEFAULT_MQTT_PORT)
        self.assertFalse(options.enable_provisional_reps)

    @staticmethod
    def detector_sample(acceleration_x=0.0, gyro_x=0.0, angle_x=0.0):
        return agent.ImuSample(
            (acceleration_x, 0.0, 1.0),
            (gyro_x, 0.0, 0.0),
            (angle_x, 0.0, 0.0),
        )

    def detector_reps(self, acceleration, gyro=None, angles=None):
        detector = agent.ProvisionalRepDetector()
        gyro = gyro or [0.0] * len(acceleration)
        angles = angles or [0.0] * len(acceleration)
        reps = []
        for acceleration_x, gyro_x, angle_x in zip(acceleration, gyro, angles):
            rep = detector.update(0.0, self.detector_sample(acceleration_x, gyro_x, angle_x))
            if rep is not None:
                reps.append(rep)
        return reps

    def test_provisional_rep_detector_requires_full_rest_to_rest_cycle(self):
        acceleration = (
            [0.0] * 50 + [0.20] * 10 + [-0.20] * 10 + [0.0] * 8
            + [-0.20] * 10 + [0.20] * 10 + [0.0] * 25
        )
        reps = self.detector_reps(acceleration)
        self.assertEqual(len(reps), 1)
        self.assertGreater(reps[0]["peak_velocity"], reps[0]["mean_velocity"])
        self.assertGreaterEqual(reps[0]["duration_ms"], 600)
        self.assertTrue(reps[0]["timestamp"].endswith("Z"))

    def test_provisional_rep_detector_integrates_confirmed_onset(self):
        acceleration = (
            [0.0] * 50 + [0.20] * 8 + [-0.20] * 8 + [0.0] * 8
            + [-0.20] * 8 + [0.20] * 8 + [0.0] * 20
        )

        self.assertEqual(len(self.detector_reps(acceleration)), 1)

    def test_provisional_rep_detector_selects_axis_from_confirmed_onset(self):
        detector = agent.ProvisionalRepDetector()
        still = self.detector_sample()
        for _ in range(20):
            detector.update(0.0, still)
        onset = [
            agent.ImuSample((0.20, 0.0, 1.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            agent.ImuSample((0.20, 0.0, 1.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            agent.ImuSample((0.20, 0.0, 1.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            agent.ImuSample((0.0, 0.25, 1.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        ]

        for sample in onset:
            detector.activity_score(0.0, sample)
            detector.update(0.0, sample, activity_score=0.20)

        self.assertEqual(detector._axis, (1.0, 0.0, 0.0))

    def test_provisional_rep_detector_integrates_raw_not_filtered_acceleration(self):
        detector = agent.ProvisionalRepDetector()
        still = self.detector_sample()
        moving = self.detector_sample(0.20)
        for _ in range(20):
            detector.update(0.0, still)

        for _ in range(agent.REP_ONSET_SAMPLES):
            detector.activity_score(0.0, moving)
            detector.update(0.0, moving, activity_score=0.20)

        expected_velocity = (
            0.20 * 9.80665 * agent.SAMPLE_INTERVAL_SECONDS * agent.REP_ONSET_SAMPLES
        )
        self.assertAlmostEqual(detector._velocity, expected_velocity, places=6)

    def test_provisional_rep_detector_does_not_accept_settling_bias(self):
        detector = agent.ProvisionalRepDetector()
        samples = [0.0] * 50 + [0.20] * 10 + [-0.20] * 10
        reps = [
            detector.update(0.0, self.detector_sample(value))
            for value in samples
        ]
        reps.extend(
            detector.update(
                0.0,
                self.detector_sample(-0.20),
                activity_score=0.0,
            )
            for _ in range(agent.REP_SETTLE_SAMPLES)
        )

        self.assertTrue(all(rep is None for rep in reps))
        self.assertEqual(detector.diagnostics()["rejected_cycles"], 1)

    def test_provisional_rep_detector_refractory_waits_for_low_activity(self):
        detector = agent.ProvisionalRepDetector()
        detector._reset_cycle(refractory=True)
        moving = self.detector_sample(0.20)
        still = self.detector_sample()

        for _ in range(20):
            detector.update(0.0, moving, activity_score=0.20)
        self.assertEqual(detector.diagnostics()["state"], "refractory")

        detector.update(0.0, still, activity_score=0.0)
        self.assertEqual(detector.diagnostics()["state"], "idle")

    def test_provisional_rep_detector_counts_consecutive_reps_without_full_settle(self):
        cycle = [0.20] * 10 + [-0.20] * 10 + [0.0] * 8 + [-0.20] * 10 + [0.20] * 10
        acceleration = [0.0] * 50 + cycle + [0.0] * 8 + cycle + [0.0] * 20
        self.assertEqual(len(self.detector_reps(acceleration)), 2)

    def test_provisional_rep_detector_rejects_pickup_wiggle_and_rotation(self):
        pickup = [0.0] * 50 + [0.20] * 10 + [-0.20] * 10 + [0.0] * 30
        wiggle = [0.0] * 50 + [0.05, -0.05] * 4 + [0.0] * 30
        angular = [0.0] * 50 + [0.0] * 8 + [0.0] * 30
        gyro = [0.0] * 50 + [120.0, -120.0] * 4 + [0.0] * 30
        self.assertEqual(self.detector_reps(pickup), [])
        self.assertEqual(self.detector_reps(wiggle), [])
        self.assertEqual(self.detector_reps(angular, gyro=gyro), [])

    def test_provisional_rep_detector_handles_angle_wrap_without_false_rep(self):
        acceleration = [0.0] * 60
        angles = [0.0] * 50 + [178.0, 179.0, -180.0, -179.0] + [0.0] * 6
        self.assertEqual(self.detector_reps(acceleration, angles=angles), [])

    def test_provisional_rep_detector_removes_gravity_during_rotation(self):
        detector = agent.ProvisionalRepDetector()
        rolls = [0.0] * 50 + list(range(0, 61, 5)) + list(range(60, -1, -5)) + [0.0] * 25
        reps = []
        for roll in rolls:
            radians = math.radians(roll)
            sample = agent.ImuSample(
                (0.0, math.sin(radians), math.cos(radians)),
                (120.0 if roll else 0.0, 0.0, 0.0),
                (roll, 0.0, 0.0),
            )
            rep = detector.update(0.0, sample)
            if rep is not None:
                reps.append(rep)
        self.assertEqual(reps, [])

    def test_provisional_rep_detector_adapts_settle_threshold_to_idle_noise(self):
        detector = agent.ProvisionalRepDetector()
        still = self.detector_sample()
        reps = [
            detector.update(0.0, still, activity_score=0.04)
            for _ in range(200)
        ]
        diagnostics = detector.diagnostics()
        self.assertTrue(all(rep is None for rep in reps))
        self.assertGreater(diagnostics["noise_floor"], 0.035)
        self.assertGreater(diagnostics["settle_threshold"], agent.REP_END_MOVEMENT_G)
        self.assertGreater(diagnostics["start_threshold"], diagnostics["settle_threshold"])

    def test_mqtt_rep_publisher_sends_existing_contract_without_raw_imu(self):
        published = []

        class FakeMqttClient:
            def connect(self, host, port, keepalive):
                self.connection = (host, port, keepalive)

            def loop_start(self):
                pass

            def publish(self, topic, payload, qos):
                published.append((topic, json.loads(payload), qos))

            def loop_stop(self):
                pass

            def disconnect(self):
                pass

        with mock.patch.dict("sys.modules", {
            "paho": SimpleNamespace(mqtt=SimpleNamespace(client=SimpleNamespace(Client=FakeMqttClient))),
            "paho.mqtt": SimpleNamespace(client=SimpleNamespace(Client=FakeMqttClient)),
            "paho.mqtt.client": SimpleNamespace(Client=FakeMqttClient),
        }):
            publisher = agent.MqttRepPublisher("broker", 1884)
            publisher.publish("wt901_test_1", {
                "mean_velocity": 0.42,
                "peak_velocity": 0.63,
                "duration_ms": 650,
                "timestamp": "2026-08-05T12:00:00Z",
            })
            publisher.close()

        self.assertEqual(published, [(
            "edgeathlete/node/wt901_test_1/rep",
            {
                "node_id": "wt901_test_1",
                "rep_number": 1,
                "mean_velocity": 0.42,
                "peak_velocity": 0.63,
                "duration_ms": 650,
                "timestamp": "2026-08-05T12:00:00Z",
            },
            1,
        )])

    def test_mqtt_rep_publisher_drops_when_broker_unavailable(self):
        class FailingMqttClient:
            def connect(self, *_args):
                raise OSError("broker down")

            def publish(self, *_args):
                raise AssertionError("publish should not run without connection")

        with mock.patch.dict("sys.modules", {
            "paho": SimpleNamespace(mqtt=SimpleNamespace(client=SimpleNamespace(Client=FailingMqttClient))),
            "paho.mqtt": SimpleNamespace(client=SimpleNamespace(Client=FailingMqttClient)),
            "paho.mqtt.client": SimpleNamespace(Client=FailingMqttClient),
        }):
            publisher = agent.MqttRepPublisher("broker", 1884)
            published = publisher.publish("wt901_test_1", {
                "mean_velocity": 0.42,
                "peak_velocity": 0.63,
                "duration_ms": 650,
                "timestamp": "2026-08-05T12:00:00Z",
            })
            publisher.close()

        self.assertFalse(published)

    def test_mqtt_rep_publisher_drops_publish_failure_after_connect(self):
        class FailingPublishMqttClient:
            def connect(self, *_args):
                pass

            def loop_start(self):
                pass

            def publish(self, *_args):
                raise OSError("broker down")

            def loop_stop(self):
                pass

            def disconnect(self):
                pass

        with mock.patch.dict("sys.modules", {
            "paho": SimpleNamespace(mqtt=SimpleNamespace(client=SimpleNamespace(Client=FailingPublishMqttClient))),
            "paho.mqtt": SimpleNamespace(client=SimpleNamespace(Client=FailingPublishMqttClient)),
            "paho.mqtt.client": SimpleNamespace(Client=FailingPublishMqttClient),
        }):
            publisher = agent.MqttRepPublisher("broker", 1884)
            published = publisher.publish("wt901_test_1", {
                "mean_velocity": 0.42,
                "peak_velocity": 0.63,
                "duration_ms": 650,
                "timestamp": "2026-08-05T12:00:00Z",
            })
            publisher.close()

        self.assertFalse(published)

    def test_mqtt_rep_publisher_drops_nonzero_connect_and_publish_return_codes(self):
        class NonzeroConnectMqttClient:
            def connect(self, *_args):
                return 1

            def loop_start(self):
                pass

        with mock.patch.dict("sys.modules", {
            "paho": SimpleNamespace(mqtt=SimpleNamespace(client=SimpleNamespace(Client=NonzeroConnectMqttClient))),
            "paho.mqtt": SimpleNamespace(client=SimpleNamespace(Client=NonzeroConnectMqttClient)),
            "paho.mqtt.client": SimpleNamespace(Client=NonzeroConnectMqttClient),
        }):
            publisher = agent.MqttRepPublisher("broker", 1884)
            connected = publisher._ensure_connected()

        class NonzeroPublishMqttClient:
            def connect(self, *_args):
                return 0

            def loop_start(self):
                pass

            def publish(self, *_args):
                return SimpleNamespace(rc=1)

            def loop_stop(self):
                pass

            def disconnect(self):
                pass

        with mock.patch.dict("sys.modules", {
            "paho": SimpleNamespace(mqtt=SimpleNamespace(client=SimpleNamespace(Client=NonzeroPublishMqttClient))),
            "paho.mqtt": SimpleNamespace(client=SimpleNamespace(Client=NonzeroPublishMqttClient)),
            "paho.mqtt.client": SimpleNamespace(Client=NonzeroPublishMqttClient),
        }):
            publisher = agent.MqttRepPublisher("broker", 1884)
            published = publisher.publish("wt901_test_1", {
                "mean_velocity": 0.42,
                "peak_velocity": 0.63,
                "duration_ms": 650,
                "timestamp": "2026-08-05T12:00:00Z",
            })
            publisher.close()

        self.assertFalse(connected)
        self.assertFalse(published)


class EnrollmentAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = FakeClock()
        FakeScanner.calls = []
        FakeClient.addresses = []
        FakeClient.notifications = [frame(), frame(acceleration=(0, 0, 4096))]
        FakeClient.has_service = True
        FakeClient.has_notify = True
        FakeScanner.discovered = {
            "private-a": (
                SimpleNamespace(address="private-a", name="WT901BLE"),
                SimpleNamespace(local_name="WT901BLE"),
            ),
            "private-b": (
                SimpleNamespace(address="private-b", name="WT901BLE"),
                SimpleNamespace(local_name="WT901BLE"),
            ),
            "other": (
                SimpleNamespace(address="other", name="Headphones"),
                SimpleNamespace(local_name="Headphones"),
            ),
        }
        self.enrollment = agent.EnrollmentAgent(
            FakeScanner,
            FakeClient,
            clock=self.clock,
            scan_seconds=0.25,
            handle_ttl_seconds=10,
            verification_ttl_seconds=10,
            calibration_samples=1,
        )

    async def asyncTearDown(self):
        await self.enrollment.close()

    async def test_real_scanner_contract_filters_and_distinguishes_duplicate_names(self):
        result = await self.enrollment.scan()
        self.assertEqual(FakeScanner.calls, [{"timeout": 0.25, "return_adv": True}])
        self.assertEqual([item["label"] for item in result["devices"]], ["WT901BLE", "WT901BLE"])
        handles = [item["handle"] for item in result["devices"]]
        self.assertEqual(len(set(handles)), 2)
        self.assertTrue(all("private" not in handle for handle in handles))
        self.assertNotIn("address", json.dumps(result))

    async def test_scan_handles_are_latest_scan_only_and_expire(self):
        first = await self.enrollment.scan()
        old_handle = first["devices"][0]["handle"]
        await self.enrollment.scan()
        with self.assertRaisesRegex(agent.ApiError, "scan_handle_expired"):
            await self.enrollment.verify(old_handle)
        current = (await self.enrollment.scan())["devices"][0]["handle"]
        self.clock.now += 11
        with self.assertRaisesRegex(agent.ApiError, "scan_handle_expired"):
            await self.enrollment.verify(current)

    async def test_verification_checks_service_and_decodes_fresh_frames_privately(self):
        handle = (await self.enrollment.scan())["devices"][0]["handle"]
        result = await self.enrollment.verify(handle)
        self.assertEqual(result["label"], "WT901BLE")
        self.assertAlmostEqual(result["movement_g"], 0.99)
        self.assertRegex(result["verification_token"], agent.OPAQUE_TOKEN_PATTERN)
        self.assertNotIn("private-a", json.dumps(result))
        self.assertEqual(FakeClient.addresses, ["private-a"])

    async def test_verification_rejects_missing_notify_characteristic(self):
        FakeClient.has_notify = False
        handle = (await self.enrollment.scan())["devices"][0]["handle"]
        with self.assertRaisesRegex(agent.ApiError, "not_wt901_notify_device"):
            await self.enrollment.verify(handle)

    async def test_verification_rejects_a_stalled_notification_stream(self):
        FakeClient.notifications = []
        self.enrollment._verification_timeout = 0.01
        handle = (await self.enrollment.scan())["devices"][0]["handle"]
        with self.assertRaisesRegex(agent.ApiError, "fresh_frames_unavailable"):
            await self.enrollment.verify(handle)

    async def test_verification_rejects_stationary_frames_after_calibration(self):
        FakeClient.notifications = [frame(), frame(), frame()]
        self.enrollment._verification_timeout = 0.01
        handle = (await self.enrollment.scan())["devices"][0]["handle"]
        with self.assertRaisesRegex(agent.ApiError, "movement_not_confirmed"):
            await self.enrollment.verify(handle)

    async def test_scan_sanitizes_hostile_advertised_label(self):
        FakeScanner.discovered = {
            "private-a": (
                SimpleNamespace(address="private-a", name=None),
                SimpleNamespace(local_name="WT901\u202e\u200b\x00 Sensor"),
            ),
        }
        result = await self.enrollment.scan()
        self.assertEqual(result["devices"][0]["label"], "WT901 Sensor")
        self.assertNotIn("\u202e", json.dumps(result))

    async def test_binding_is_private_exactly_reversible_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "bindings.json")
            enrollment = agent.EnrollmentAgent(
                FakeScanner, FakeClient, state_path=state_path, clock=self.clock,
                calibration_samples=1,
            )
            handle = (await enrollment.scan())["devices"][0]["handle"]
            verified = await enrollment.verify(handle)
            binding = enrollment.bind(verified["verification_token"], 3, None)
            self.assertRegex(binding["node_id"], agent.NODE_ID_PATTERN)
            self.assertNotIn("address", binding)
            self.assertEqual(os.stat(state_path).st_mode & 0o777, 0o600)

            restored = agent.EnrollmentAgent(
                FakeScanner, FakeClient, state_path=state_path, clock=self.clock,
            )
            health = restored.rack_health(3)
            self.assertEqual(health["node_id"], binding["node_id"])
            self.assertEqual(health["state"], "reconnecting")
            with self.assertRaisesRegex(agent.ApiError, "binding_not_found"):
                restored.unbind("wrong_binding_token")
            removed = restored.unbind(binding["binding_token"])
            self.assertEqual(removed["state"], "unbound")
            with self.assertRaisesRegex(agent.ApiError, "rack_not_bound"):
                restored.rack_health(3)
            await enrollment.close()
            await restored.close()

    async def test_binding_conflicts_do_not_replace_existing_binding(self):
        first_handle = (await self.enrollment.scan())["devices"][0]["handle"]
        first_verified = await self.enrollment.verify(first_handle)
        first = self.enrollment.bind(first_verified["verification_token"], 1, None)
        second_handle = (await self.enrollment.scan())["devices"][1]["handle"]
        second_verified = await self.enrollment.verify(second_handle)
        with self.assertRaisesRegex(agent.ApiError, "binding_reconciliation_required"):
            self.enrollment.bind(second_verified["verification_token"], 1, None)
        self.assertEqual(self.enrollment.rack_health(1)["node_id"], first["node_id"])


class FailingClient(FakeClient):
    failing_addresses = set()

    async def __aenter__(self):
        if self.address in self.failing_addresses:
            raise RuntimeError("unavailable")
        return self


class FailingScanner:
    @staticmethod
    async def discover(**_kwargs):
        raise RuntimeError("adapter unavailable")


class MultiBindingRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeClient.addresses = []
        FakeClient.notifications = [frame(), frame(acceleration=(0, 0, 4096))]
        FakeClient.has_service = True
        FakeClient.has_notify = True
        FailingClient.failing_addresses = set()
        self.enrollment = agent.EnrollmentAgent(
            FakeScanner, FailingClient, calibration_samples=1,
        )

    async def asyncTearDown(self):
        await self.enrollment.close()

    def bind(self, token, address, rack):
        self.enrollment._verifications[token] = {
            "address": address, "label": f"WT901-{rack}",
            "movement_g": 0.1, "expires": time_monotonic() + 60,
        }
        return self.enrollment.bind(token, rack, None)

    def replace(self, token, address, rack, expected_node_id):
        self.enrollment._verifications[token] = {
            "address": address, "label": f"WT901-{rack}-replacement",
            "movement_g": 0.2, "expires": time_monotonic() + 60,
        }
        return self.enrollment.bind(token, rack, expected_node_id)

    async def settle(self):
        for _ in range(5):
            await asyncio.sleep(0)

    async def test_two_bindings_start_separately_and_scan_does_not_cancel_them(self):
        first = self.bind("verification_token_one", "private-one", 1)
        second = self.bind("verification_token_two", "private-two", 2)
        first_task = self.enrollment._binding_tasks[first["binding_token"]]
        second_task = self.enrollment._binding_tasks[second["binding_token"]]
        await self.settle()
        await self.enrollment.scan()
        self.assertIsNot(first_task, second_task)
        self.assertFalse(first_task.done())
        self.assertFalse(second_task.done())
        self.assertIn("private-one", FakeClient.addresses)
        self.assertIn("private-two", FakeClient.addresses)

    async def test_adapter_scan_failure_keeps_binding_tasks_running(self):
        first = self.bind("verification_token_one", "private-one", 1)
        second = self.bind("verification_token_two", "private-two", 2)
        tasks = dict(self.enrollment._binding_tasks)
        self.enrollment._scanner = FailingScanner
        with self.assertRaisesRegex(agent.ApiError, "scan_unavailable"):
            await self.enrollment.scan()
        self.assertEqual(self.enrollment._binding_tasks, tasks)
        self.assertFalse(self.enrollment._binding_tasks[first["binding_token"]].done())
        self.assertFalse(self.enrollment._binding_tasks[second["binding_token"]].done())

    async def test_restored_bindings_start_isolated_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "bindings.json")
            original = agent.EnrollmentAgent(
                FakeScanner, FailingClient, state_path=state_path, calibration_samples=1,
            )
            original._verifications["verification_token_one"] = {
                "address": "private-one", "label": "WT901-A",
                "movement_g": 0.1, "expires": time_monotonic() + 60,
            }
            original._verifications["verification_token_two"] = {
                "address": "private-two", "label": "WT901-B",
                "movement_g": 0.1, "expires": time_monotonic() + 60,
            }
            original.bind("verification_token_one", 1, None)
            original.bind("verification_token_two", 2, None)
            await original.close()
            FakeClient.addresses = []

            restored = agent.EnrollmentAgent(
                FakeScanner, FailingClient, state_path=state_path, calibration_samples=1,
            )
            restored.start()
            await self.settle()
            self.assertEqual(len(restored._binding_tasks), 2)
            self.assertEqual(set(FakeClient.addresses), {"private-one", "private-two"})
            await restored.close()

    async def test_one_connection_failure_does_not_stop_other_binding(self):
        FailingClient.failing_addresses = {"private-bad"}
        bad = self.bind("verification_token_bad", "private-bad", 1)
        good = self.bind("verification_token_good", "private-good", 2)
        await self.settle()
        self.assertFalse(self.enrollment._binding_tasks[bad["binding_token"]].done())
        self.assertFalse(self.enrollment._binding_tasks[good["binding_token"]].done())
        self.assertEqual(self.enrollment.rack_health(1)["state"], "reconnecting")
        self.assertEqual(self.enrollment.rack_health(2)["state"], "live")
        self.assertIsNotNone(self.enrollment.rack_health(2)["detector"])

    async def test_unbind_cancels_only_the_exact_binding_task(self):
        first = self.bind("verification_token_one", "private-one", 1)
        second = self.bind("verification_token_two", "private-two", 2)
        first_task = self.enrollment._binding_tasks[first["binding_token"]]
        second_task = self.enrollment._binding_tasks[second["binding_token"]]
        self.enrollment.unbind(first["binding_token"])
        await self.settle()
        self.assertTrue(first_task.cancelled())
        self.assertFalse(second_task.done())
        self.assertEqual(self.enrollment.rack_health(2)["node_id"], second["node_id"])

    async def test_replacement_and_exact_new_token_rollback_restore_old_binding(self):
        old = self.bind("verification_token_old", "private-old", 1)
        old_task = self.enrollment._binding_tasks[old["binding_token"]]
        replacement = self.replace(
            "verification_token_new", "private-new", 1, old["node_id"],
        )
        await self.settle()
        self.assertTrue(old_task.cancelled())
        self.assertEqual(self.enrollment.rack_health(1)["node_id"], replacement["node_id"])
        rolled_back = self.enrollment.unbind(replacement["binding_token"])
        await self.settle()
        self.assertEqual(rolled_back["state"], "rolled_back")
        self.assertEqual(rolled_back["node_id"], old["node_id"])
        self.assertEqual(self.enrollment.rack_health(1)["node_id"], old["node_id"])
        self.assertIn(old["binding_token"], self.enrollment._binding_tasks)

    async def test_replacement_mismatch_keeps_current_binding_and_task(self):
        old = self.bind("verification_token_old", "private-old", 1)
        old_task = self.enrollment._binding_tasks[old["binding_token"]]
        self.enrollment._verifications["verification_token_new"] = {
            "address": "private-new", "label": "WT901-new",
            "movement_g": 0.2, "expires": time_monotonic() + 60,
        }
        with self.assertRaisesRegex(agent.ApiError, "binding_reconciliation_required"):
            self.enrollment.bind("verification_token_new", 1, "wt901_wrong")
        self.assertEqual(self.enrollment.rack_health(1)["node_id"], old["node_id"])
        self.assertIs(self.enrollment._binding_tasks[old["binding_token"]], old_task)
        self.assertIn("verification_token_new", self.enrollment._verifications)

    async def test_failed_replacement_persistence_leaves_exact_prior_runtime(self):
        old = self.bind("verification_token_old", "private-old", 1)
        old_task = self.enrollment._binding_tasks[old["binding_token"]]
        old_status = self.enrollment._statuses[old["binding_token"]]
        self.enrollment._verifications["verification_token_new"] = {
            "address": "private-new", "label": "WT901-new",
            "movement_g": 0.2, "expires": time_monotonic() + 60,
        }
        self.enrollment._state_path = "/unused/failure-injection"
        self.enrollment._persist_state = lambda *_args: (_ for _ in ()).throw(OSError("full"))
        with self.assertRaisesRegex(OSError, "full"):
            self.enrollment.bind("verification_token_new", 1, old["node_id"])
        self.assertEqual(list(self.enrollment._bindings), [old["binding_token"]])
        self.assertIs(self.enrollment._binding_tasks[old["binding_token"]], old_task)
        self.assertIs(self.enrollment._statuses[old["binding_token"]], old_status)
        self.assertFalse(old_task.cancelled())
        self.assertIn("verification_token_new", self.enrollment._verifications)

    async def test_failed_rollback_persistence_keeps_replacement_active(self):
        old = self.bind("verification_token_old", "private-old", 1)
        replacement = self.replace(
            "verification_token_new", "private-new", 1, old["node_id"],
        )
        replacement_task = self.enrollment._binding_tasks[replacement["binding_token"]]
        self.enrollment._state_path = "/unused/failure-injection"
        self.enrollment._persist_state = lambda *_args: (_ for _ in ()).throw(OSError("full"))
        with self.assertRaisesRegex(OSError, "full"):
            self.enrollment.unbind(replacement["binding_token"])
        self.assertEqual(self.enrollment.rack_health(1)["node_id"], replacement["node_id"])
        self.assertIs(
            self.enrollment._binding_tasks[replacement["binding_token"]], replacement_task,
        )
        self.assertFalse(replacement_task.cancelled())

    async def test_persisted_replacement_rolls_back_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "bindings.json")
            original = agent.EnrollmentAgent(
                FakeScanner, FailingClient, state_path=state_path, calibration_samples=1,
            )
            original._verifications["verification_token_old"] = {
                "address": "private-old", "label": "WT901-old",
                "movement_g": 0.2, "expires": time_monotonic() + 60,
            }
            old = original.bind("verification_token_old", 1, None)
            original._verifications["verification_token_new"] = {
                "address": "private-new", "label": "WT901-new",
                "movement_g": 0.2, "expires": time_monotonic() + 60,
            }
            replacement = original.bind(
                "verification_token_new", 1, old["node_id"],
            )
            await original.close()

            restored = agent.EnrollmentAgent(
                FakeScanner, FailingClient, state_path=state_path, calibration_samples=1,
            )
            restored.start()
            result = restored.unbind(replacement["binding_token"])
            self.assertEqual(result["state"], "rolled_back")
            self.assertEqual(restored.rack_health(1)["node_id"], old["node_id"])
            await restored.close()

def time_monotonic():
    return agent.time.monotonic()


class StateFileSecurityTests(unittest.TestCase):
    def valid_state(self):
        return {
            "schema_version": 1,
            "bindings": [{
                "binding_token": "a" * 24,
                "rack_number": 1,
                "node_id": "wt901_" + "b" * 24,
                "address": "private-address",
                "label": "WT901\u202e\u200b Sensor",
            }],
            "rollbacks": [],
        }

    def write_state(self, path, state, mode=0o600):
        with open(path, "w", encoding="utf-8") as state_file:
            json.dump(state, state_file)
        os.chmod(path, mode)

    def test_load_sanitizes_label_and_accepts_private_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.json")
            self.write_state(path, self.valid_state())
            enrollment = agent.EnrollmentAgent(FakeScanner, FakeClient, state_path=path)
            self.assertEqual(enrollment.rack_health(1)["label"], "WT901 Sensor")

    def test_rejects_symlink_nonprivate_oversized_and_invalid_state(self):
        cases = []
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "target.json")
            self.write_state(target, self.valid_state())
            symlink = os.path.join(directory, "link.json")
            os.symlink(target, symlink)
            cases.append(symlink)

            public = os.path.join(directory, "public.json")
            self.write_state(public, self.valid_state(), 0o640)
            cases.append(public)

            oversized = os.path.join(directory, "oversized.json")
            with open(oversized, "wb") as state_file:
                state_file.write(b"x" * (agent.MAX_STATE_BYTES + 1))
            os.chmod(oversized, 0o600)
            cases.append(oversized)

            invalid_node = self.valid_state()
            invalid_node["bindings"][0]["node_id"] = "not_generated"
            invalid = os.path.join(directory, "invalid.json")
            self.write_state(invalid, invalid_node)
            cases.append(invalid)

            too_many = self.valid_state()
            too_many["bindings"] = [
                {
                    "binding_token": f"token_{index:018d}",
                    "rack_number": (index % 8) + 1,
                    "node_id": f"wt901_{index:024x}",
                    "address": f"private-{index}",
                    "label": "WT901",
                }
                for index in range(9)
            ]
            over_capacity = os.path.join(directory, "over-capacity.json")
            self.write_state(over_capacity, too_many)
            cases.append(over_capacity)

            fifo = os.path.join(directory, "state.fifo")
            os.mkfifo(fifo, 0o600)
            cases.append(fifo)
            cases.append(directory)
            for path in cases:
                with self.subTest(path=path):
                    with self.assertRaises(ValueError):
                        agent.EnrollmentAgent(FakeScanner, FakeClient, state_path=path)

    def test_rejects_state_not_owned_by_current_euid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.json")
            self.write_state(path, self.valid_state())
            actual = os.stat(path)
            foreign = SimpleNamespace(
                st_mode=actual.st_mode,
                st_uid=os.geteuid() + 1,
                st_size=actual.st_size,
            )
            with mock.patch.object(agent.os, "fstat", return_value=foreign):
                with self.assertRaisesRegex(ValueError, "unsafe Agent binding state"):
                    agent.EnrollmentAgent(FakeScanner, FakeClient, state_path=path)


class AgentHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.status = agent.AgentStatus("wt901_test_1")
        self.status.sample(0.1)
        self.server = await agent.serve_status(
            self.status, "127.0.0.1", 0, {"http://basestation", "http://192.168.4.1"},
        )
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def request(self, origin):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(
            f"GET /health HTTP/1.1\r\nHost: localhost\r\nOrigin: {origin}\r\n\r\n".encode()
        )
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
        return response.decode()

    async def test_deployed_origin_is_allowed_and_other_origins_are_denied(self):
        allowed = await self.request("http://basestation")
        ap_allowed = await self.request("http://192.168.4.1")
        denied = await self.request("http://other-host")
        self.assertIn("200 OK", allowed)
        self.assertIn("Access-Control-Allow-Origin: http://basestation", allowed)
        self.assertIn("200 OK", ap_allowed)
        self.assertIn("Access-Control-Allow-Origin: http://192.168.4.1", ap_allowed)
        self.assertIn("403 Forbidden", denied)


class AgentUdsHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.socket_path = os.path.join(self.directory.name, "agent.sock")
        FakeClient.notifications = [frame(), frame(acceleration=(0, 0, 4096))]
        self.enrollment = agent.EnrollmentAgent(
            FakeScanner, FakeClient, calibration_samples=1,
        )
        FakeScanner.discovered = {}
        self.server = await agent.serve_uds(self.enrollment, self.socket_path)

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        await self.enrollment.close()
        self.directory.cleanup()

    async def request(self, request):
        reader, writer = await asyncio.open_unix_connection(self.socket_path)
        writer.write(request)
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
        return response.decode()

    async def post(self, path, body):
        encoded = json.dumps(body, separators=(",", ":")).encode()
        return await self.request(
            f"POST {path} HTTP/1.1\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(encoded)}\r\n\r\n".encode() + encoded
        )

    @staticmethod
    def response_body(response):
        return json.loads(response.split("\r\n\r\n", 1)[1])

    async def test_socket_is_private_and_scan_schema_is_fixed(self):
        self.assertEqual(os.stat(self.socket_path).st_mode & 0o777, 0o600)
        response = await self.request(
            b"POST /v1/scans HTTP/1.1\r\nContent-Type: application/json\r\n"
            b"Content-Length: 2\r\n\r\n{}"
        )
        self.assertIn("200 OK", response)
        self.assertIn('"schema_version":1,"devices":[]', response)

    async def test_rejects_extra_fields_wrong_methods_paths_and_oversized_body(self):
        extra = await self.request(
            b"POST /v1/scans HTTP/1.1\r\nContent-Type: application/json\r\n"
            b"Content-Length: 7\r\n\r\n{\"x\":1}"
        )
        wrong_method = await self.request(b"GET /v1/scans HTTP/1.1\r\n\r\n")
        wrong_path = await self.request(b"GET /v1/unknown HTTP/1.1\r\n\r\n")
        oversized = await self.request(
            f"POST /v1/scans HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: {agent.MAX_HTTP_BODY_BYTES + 1}\r\n\r\n".encode()
        )
        self.assertIn("400 Bad Request", extra)
        self.assertIn("405 Method Not Allowed", wrong_method)
        self.assertIn("404 Not Found", wrong_path)
        self.assertIn("413 Content Too Large", oversized)

    async def test_verification_binding_health_and_exact_rollback_routes(self):
        FakeScanner.discovered = {
            "private-address": (
                SimpleNamespace(address="private-address", name="WT901BLE"),
                SimpleNamespace(local_name="WT901BLE"),
            ),
        }
        scan = self.response_body(await self.post("/v1/scans", {}))
        verified_response = await self.post(
            "/v1/verifications", {"handle": scan["devices"][0]["handle"]},
        )
        verified = self.response_body(verified_response)
        binding_response = await self.post(
            "/v1/bindings",
            {
                "verification_token": verified["verification_token"],
                "rack_number": 2,
                "expected_node_id": None,
            },
        )
        binding = self.response_body(binding_response)
        health = await self.request(b"GET /v1/racks/2/health HTTP/1.1\r\n\r\n")
        wrong_delete = await self.request(
            b"DELETE /v1/bindings/not_the_binding_token HTTP/1.1\r\n\r\n"
        )
        deleted = await self.request(
            f"DELETE /v1/bindings/{binding['binding_token']} HTTP/1.1\r\n\r\n".encode()
        )
        self.assertIn("200 OK", verified_response)
        self.assertIn("201 Created", binding_response)
        self.assertIn("200 OK", health)
        self.assertIn(binding["node_id"], health)
        self.assertNotIn("private-address", verified_response + binding_response + health)
        self.assertIn("404 Not Found", wrong_delete)
        self.assertIn("200 OK", deleted)


if __name__ == "__main__":
    unittest.main()
