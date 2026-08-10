import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest import mock
import uuid


MODULE_PATH = Path(__file__).with_name("gym_gateway.py")
SPEC = importlib.util.spec_from_file_location("gym_gateway", MODULE_PATH)
gateway = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gateway)


BOOT_ID = "11111111-1111-4111-8111-111111111111"
GATEWAY_ID = "22222222-2222-4222-8222-222222222222"
NODE_ID = "wt901_0123456789abcdef01234567"


def health(**extra):
    value = {
        "schema_version": 1,
        "node_id": NODE_ID,
        "state": "live",
        "sample_age_ms": 42,
    }
    value.update(extra)
    return value


def event(sequence, boot_id=BOOT_ID):
    value = gateway.make_event(
        sequence, 1, NODE_ID, 14, health(),
        now=lambda: "2026-08-07T15:04:05.123Z",
    )
    value["event_id"] = str(uuid.UUID(int=sequence))
    return value


def acknowledgement(events, through=None, boot_id=BOOT_ID):
    if through is None:
        through = events[-1]["sequence"]
    return {
        "schema_version": 1,
        "gateway_boot_id": boot_id,
        "results": [
            {
                "event_id": value["event_id"],
                "sequence": value["sequence"],
                "result": "accepted",
                "code": "health_recorded",
            }
            for value in events
        ],
        "acknowledged_through": through,
        "server_time": "2026-08-07T15:04:06.010Z",
    }


class UnixSocketServer:
    def __init__(self, path, response):
        self.path = path
        self.response = response
        self.request = b""

    def __enter__(self):
        ready = threading.Event()

        def serve():
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(self.path)
                server.listen(1)
                ready.set()
                connection, _ = server.accept()
                with connection:
                    self.request = connection.recv(4096)
                    connection.sendall(self.response)

        self.thread = threading.Thread(target=serve)
        self.thread.start()
        ready.wait(2)
        return self

    def __exit__(self, *_args):
        self.thread.join(2)


def http_response(payload, status="200 OK"):
    body = json.dumps(payload).encode()
    return (
        f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode() + body


class AgentTests(unittest.TestCase):
    def test_reads_only_whitelisted_health_over_uds(self):
        private = health(
            label="private sensor", movement_g=1.2, accepted_reps=99,
            detector={"secret": "raw"}, address="AA:BB:CC:DD:EE:FF",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "agent.sock")
            with UnixSocketServer(path, http_response(private)) as server:
                result = gateway.read_rack_health(path, 1, NODE_ID)
        self.assertEqual(result, health())
        self.assertIn(b"GET /v1/racks/1/health HTTP/1.1", server.request)
        self.assertNotIn(b"private", gateway.canonical_json(result))

    def test_malformed_oversized_and_wrong_node_map_to_reconnecting(self):
        responses = [
            b"not http",
            b"x" * (gateway.MAX_AGENT_RESPONSE_BYTES + 1),
            http_response(health(node_id="wt901_other")),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for index, response in enumerate(responses):
                path = str(Path(directory) / f"agent-{index}.sock")
                with UnixSocketServer(path, response):
                    with self.assertRaises(gateway.AgentUnavailable):
                        gateway.read_rack_health(path, 1, NODE_ID)
        self.assertEqual(gateway.reconnecting_health(NODE_ID)["state"], "reconnecting")
        self.assertEqual(set(gateway.reconnecting_health(NODE_ID)), {
            "schema_version", "node_id", "state", "sample_age_ms",
        })


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "state" / "queue.sqlite3"
        self.queue = gateway.DurableQueue(self.path)

    def tearDown(self):
        self.queue.close()
        self.directory.cleanup()

    def test_exact_schema_restrictive_mode_and_restart_persistence(self):
        self.queue.enqueue(BOOT_ID, event(1))
        self.queue.close()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.queue = gateway.DurableQueue(self.path)
        self.assertEqual(self.queue.stats()["depth"], 1)
        columns = {
            row[1] for row in self.queue.connection.execute("PRAGMA table_info(queued_event)")
        }
        self.assertEqual(columns, {
            "local_order", "event_id", "boot_id", "sequence", "occurred_at",
            "canonical_json", "byte_length", "enqueued_at",
        })
        self.assertEqual(self.queue.connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(self.queue.connection.execute("PRAGMA synchronous").fetchone()[0], 2)
        self.assertEqual(self.queue.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_canonical_envelope_and_one_boot_per_bounded_batch(self):
        first = event(1)
        self.queue.enqueue(BOOT_ID, first)
        second_boot = "33333333-3333-4333-8333-333333333333"
        second = event(1, second_boot)
        second["event_id"] = "44444444-4444-4444-8444-444444444444"
        self.queue.enqueue(second_boot, second)
        envelope = self.queue.batch(GATEWAY_ID)
        self.assertEqual(envelope["events"], [first])
        encoded = self.queue.connection.execute(
            "SELECT canonical_json FROM queued_event ORDER BY local_order LIMIT 1"
        ).fetchone()[0]
        self.assertEqual(encoded, gateway.canonical_json(first))
        self.assertLessEqual(len(gateway.canonical_json(envelope)), gateway.MAX_BATCH_BYTES)
        self.assertLessEqual(len(envelope["events"]), gateway.MAX_EVENTS_PER_BATCH)
        forbidden = {"gym_id", "label", "movement_g", "accepted_reps", "detector", "address"}
        self.assertTrue(forbidden.isdisjoint(envelope))
        self.assertTrue(forbidden.isdisjoint(envelope["events"][0]["payload"]))

    def test_batch_event_count_is_limited(self):
        for sequence in range(1, gateway.MAX_EVENTS_PER_BATCH + 2):
            self.queue.enqueue(BOOT_ID, event(sequence))
        envelope = self.queue.batch(GATEWAY_ID)
        self.assertEqual(len(envelope["events"]), gateway.MAX_EVENTS_PER_BATCH)
        self.assertLessEqual(len(gateway.canonical_json(envelope)), gateway.MAX_BATCH_BYTES)

    def test_queue_rejects_non_health_and_unknown_fields(self):
        invalid = event(1)
        invalid["movement_g"] = 1.2
        with self.assertRaises(ValueError):
            self.queue.enqueue(BOOT_ID, invalid)
        invalid = event(1)
        invalid["event_type"] = "accepted_rep"
        with self.assertRaises(ValueError):
            self.queue.enqueue(BOOT_ID, invalid)
        self.assertEqual(self.queue.stats()["depth"], 0)

    def test_valid_acknowledgement_deletes_contiguous_rows(self):
        for sequence in range(1, 4):
            self.queue.enqueue(BOOT_ID, event(sequence))
        envelope = self.queue.batch(GATEWAY_ID)
        response = acknowledgement(envelope["events"], through=2)
        self.queue.acknowledge(envelope, response)
        remaining = self.queue.connection.execute(
            "SELECT sequence FROM queued_event ORDER BY sequence"
        ).fetchall()
        self.assertEqual(remaining, [(3,)])

    def test_no_delete_on_bad_mismatched_or_lower_acknowledgement(self):
        for sequence in range(1, 3):
            self.queue.enqueue(BOOT_ID, event(sequence))
        envelope = self.queue.batch(GATEWAY_ID)
        failures = [
            {},
            acknowledgement(envelope["events"], boot_id="33333333-3333-4333-8333-333333333333"),
            acknowledgement(envelope["events"], through=3),
        ]
        failures[0] = {"unexpected": True}
        for response in failures:
            with self.assertRaises(gateway.UploadRejected):
                self.queue.acknowledge(envelope, response)
            self.assertEqual(self.queue.stats()["depth"], 2)

        valid = acknowledgement(envelope["events"], through=0)
        self.queue.acknowledge(envelope, valid)
        lower = acknowledgement(envelope["events"], through=0)
        self.queue.acknowledge(envelope, lower)
        higher = acknowledgement(envelope["events"], through=1)
        self.queue.acknowledge(envelope, higher)
        with self.assertRaises(gateway.UploadRejected):
            self.queue.acknowledge(envelope, valid)
        self.assertEqual(self.queue.stats()["depth"], 1)

    def test_no_delete_when_upload_times_out_or_response_is_invalid(self):
        self.queue.enqueue(BOOT_ID, event(1))
        envelope = self.queue.batch(GATEWAY_ID)
        with mock.patch.object(gateway, "upload", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                gateway.upload("https://example.test/api", "secret", envelope)
        self.assertEqual(self.queue.stats()["depth"], 1)
        with self.assertRaises(gateway.UploadRejected):
            self.queue.acknowledge(envelope, {"bad": "response"})
        self.assertEqual(self.queue.stats()["depth"], 1)

    def test_row_and_byte_limits_refuse_without_discarding(self):
        self.queue.close()
        self.queue = gateway.DurableQueue(self.path, max_rows=1, max_bytes=10_000)
        self.queue.enqueue(BOOT_ID, event(1))
        with self.assertRaises(gateway.QueueFull):
            self.queue.enqueue(BOOT_ID, event(2))
        self.assertEqual(self.queue.stats()["depth"], 1)
        self.assertEqual(self.queue.state, "full")

        self.queue.close()
        other_path = self.path.parent / "small.sqlite3"
        self.queue = gateway.DurableQueue(other_path, max_rows=10, max_bytes=1)
        with self.assertRaises(gateway.QueueFull):
            self.queue.enqueue(BOOT_ID, event(1))
        self.assertEqual(self.queue.stats()["depth"], 0)


class ContractTests(unittest.TestCase):
    def test_rejects_non_https_credentials_query_and_non_443_urls(self):
        rejected = [
            "http://example.test/api", "https://user@example.test/api",
            "https://example.test:8443/api", "https://example.test/api?secret=x",
        ]
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(ValueError):
                gateway.validate_https_url(value)
        self.assertEqual(
            gateway.validate_https_url("https://example.test:443/api/gateway/v1/events/"),
            "https://example.test:443/api/gateway/v1/events/",
        )

    def test_event_schema_is_exact_and_canonical(self):
        value = event(1)
        self.assertEqual(set(value), {
            "schema_version", "event_id", "event_type", "rack_number",
            "logical_node_id", "assignment_revision", "sequence", "occurred_at",
            "payload",
        })
        self.assertEqual(set(value["payload"]), {
            "agent_schema_version", "sensor_state", "sample_age_ms",
        })
        encoded = gateway.canonical_json(value)
        self.assertEqual(encoded, gateway.canonical_json(json.loads(encoded)))
        self.assertNotIn(b" ", encoded)

    def test_retry_is_bounded_exponential_full_jitter(self):
        self.assertEqual(gateway.retry_delay(0, lambda: 0.0), 0.0)
        self.assertEqual(gateway.retry_delay(0, lambda: 1.0), 1.0)
        self.assertEqual(gateway.retry_delay(3, lambda: 1.0), 8.0)
        self.assertEqual(gateway.retry_delay(100, lambda: 1.0), 60.0)
        for attempt in range(20):
            delay = gateway.retry_delay(attempt, lambda: 0.5)
            self.assertGreaterEqual(delay, 0)
            self.assertLessEqual(delay, gateway.MAX_RETRY_SECONDS)
        self.assertEqual(gateway.retry_after_delay({"Retry-After": "600"}), 300.0)
        self.assertEqual(gateway.retry_after_delay({"Retry-After": "12"}), 12.0)
        self.assertIsNone(gateway.retry_after_delay({"Retry-After": "invalid"}))

    def test_credential_is_loaded_from_file_and_gateway_id_is_derived(self):
        secret = "A" * 43
        credential = f"egw1.{GATEWAY_ID}.1.{secret}"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential"
            path.write_text(credential + "\n", encoding="ascii")
            os.chmod(path, 0o600)
            loaded, gateway_id = gateway.load_credential(path)
        self.assertEqual(loaded, credential)
        self.assertEqual(gateway_id, GATEWAY_ID)


if __name__ == "__main__":
    unittest.main()
