import base64
import logging
import unittest
import uuid

from edgeathlete_rack_helper.http_client import NetworkError, ResponseError
from edgeathlete_rack_helper.runtime import RackHelperRuntime, valid_credential, valid_pairing_code


PAIRING_ID = "11111111-1111-4111-8111-111111111111"
INSTALLATION_ID = "22222222-2222-4222-8222-222222222222"
INTENT_ID = "33333333-3333-4333-8333-333333333333"


class MemoryStore:
    def __init__(self, **values):
        self.values = dict(values)

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)

    def get_json(self, name):
        value = self.values.get(name)
        return dict(value) if value is not None else None

    def set_json(self, name, value):
        self.values[name] = dict(value)

    def clear_pending_pairing(self):
        for name in ("bootstrap", "pairing_id", "activation_request_id"):
            self.delete(name)

    def clear_identity(self):
        for name in ("credential", "bootstrap", "pairing_id", "activation_request_id", "installation_id", "dispatch"):
            self.delete(name)


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, path, body, credential=None):
        self.calls.append((path, dict(body), credential))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def credential():
    secret = base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")
    return f"earh1.{uuid.uuid4()}.{secret}"


def claim_response():
    return {
        "pairing_id": PAIRING_ID,
        "state": "claimed",
        "confirmation_phrase": ["amberanchor", "bluebrook", "calmcedar", "dawnfox", "goldhawk", "swiftwolf"],
        "expires_at": "2026-08-10T12:00:00Z",
        "poll_after_seconds": 2,
    }


def activation_response(bound=False):
    return {
        "installation_id": INSTALLATION_ID,
        "endpoint_revision": 1,
        "status_cursor": 4,
        "launch_intent_bound": bound,
    }


def consume_response():
    return {
        "intent_id": INTENT_ID,
        "acknowledged_at": "2026-08-10T12:00:00Z",
        "ack_cursor": 5,
        "next": "reconcile",
    }


def status_response():
    return {
        "status": "no_sensor",
        "status_at": "2026-08-10T12:00:01Z",
        "status_cursor": 6,
        "next_heartbeat_seconds": 15,
        "stale_after_seconds": 60,
    }


class RuntimeTests(unittest.TestCase):
    def test_pairing_code_is_exact(self):
        self.assertTrue(valid_pairing_code("ABCDEFGH"))
        for value in ("abcdefgh", "ABC", "ABCDEFGI", "ABCDEFGU", "ABCDEFGH ", None):
            self.assertFalse(valid_pairing_code(value))

    def test_credential_parser_matches_canonical_backend_form(self):
        token = credential()
        self.assertTrue(valid_credential(token))
        for value in (token + "=", token.upper(), "earh1.not-a-uuid.secret", "x\r\nHeader: value"):
            self.assertFalse(valid_credential(value))

    def test_manual_start_and_unpaired_launch_make_no_network_call(self):
        for mode in ("manual", "launch"):
            transport = FakeTransport()
            runtime = RackHelperRuntime(MemoryStore(), transport, platform="linux_x64")
            runtime.start(mode)
            self.assertEqual(transport.calls, [])
            self.assertIn(runtime.state, {"inert", "unpaired"})

    def test_pairing_stores_secrets_before_claim_and_displays_phrase(self):
        store = MemoryStore()
        transport = FakeTransport(claim_response())
        states = []
        runtime = RackHelperRuntime(
            store, transport, platform="linux_x64", on_state=lambda state, detail=None: states.append((state, detail)),
        )
        self.assertTrue(runtime.pair("ABCDEFGH"))
        body = transport.calls[0][1]
        self.assertEqual(body["credential"], store.get("credential"))
        self.assertEqual(body["bootstrap_token"], store.get("bootstrap"))
        self.assertEqual(body["platform"], "linux_x64")
        self.assertEqual(store.get("pairing_id"), PAIRING_ID)
        self.assertEqual(states[-1][0], "confirmation_required")
        self.assertNotIn("ABCDEFGH", states[-1][1])

    def test_active_identity_cannot_be_overwritten_by_pairing_ui(self):
        token = credential()
        store = MemoryStore(credential=token, installation_id=INSTALLATION_ID)
        transport = FakeTransport()
        runtime = RackHelperRuntime(store, transport, platform="linux_x64")
        self.assertFalse(runtime.pair("ABCDEFGH"))
        self.assertEqual(store.get("credential"), token)
        self.assertEqual(transport.calls, [])
        self.assertEqual(runtime.state, "paired_inert")

    def test_malformed_keyring_credential_is_deleted_without_network(self):
        store = MemoryStore(credential="bad\r\nHeader: injected", installation_id=INSTALLATION_ID)
        transport = FakeTransport()
        runtime = RackHelperRuntime(store, transport, platform="linux_x64")
        self.assertFalse(runtime.consume_launch())
        self.assertEqual(store.values, {})
        self.assertEqual(transport.calls, [])
        self.assertEqual(runtime.state, "authentication_blocked")

    def test_confirmation_activates_and_keeps_only_active_identity(self):
        token = credential()
        store = MemoryStore(credential=token, bootstrap="b" * 43, pairing_id=PAIRING_ID)
        transport = FakeTransport(
            {"pairing_id": PAIRING_ID, "state": "confirmed", "activation_expires_at": "2026-08-10T12:00:00Z", "poll_after_seconds": 2},
            activation_response(),
        )
        runtime = RackHelperRuntime(store, transport, platform="linux_x64")
        self.assertTrue(runtime.poll_and_activate())
        self.assertEqual(store.get("credential"), token)
        self.assertEqual(store.get("installation_id"), INSTALLATION_ID)
        self.assertIsNone(store.get("bootstrap"))
        self.assertIsNone(store.get("pairing_id"))
        self.assertIsNone(store.get("activation_request_id"))
        self.assertEqual(runtime.state, "paired_inert")

    def test_response_loss_retries_same_durable_consume_request(self):
        store = MemoryStore(credential=credential())
        transport = FakeTransport(NetworkError("lost"), consume_response(), status_response())
        runtime = RackHelperRuntime(store, transport, platform="linux_x64")
        runtime.start_heartbeat = lambda: None
        self.assertTrue(runtime.consume_launch())
        first, second = transport.calls[:2]
        self.assertEqual(first[1], second[1])
        self.assertEqual(first[2], second[2])
        self.assertIsNone(store.get("dispatch"))
        self.assertEqual(runtime.boot_id, first[1]["helper_boot_id"])
        self.assertEqual(runtime.state, "no_sensor")

    def test_existing_dispatch_is_retried_after_process_restart(self):
        dispatch = {
            "helper_boot_id": "44444444-4444-4444-8444-444444444444",
            "consume_request_id": "55555555-5555-4555-8555-555555555555",
        }
        store = MemoryStore(credential=credential(), dispatch=dispatch)
        transport = FakeTransport(consume_response())
        runtime = RackHelperRuntime(store, transport, platform="linux_x64")
        runtime.start_heartbeat = lambda: None
        self.assertTrue(runtime.consume_launch())
        self.assertEqual(transport.calls[0][1], dispatch)
        self.assertEqual(runtime.boot_id, dispatch["helper_boot_id"])

    def test_missing_intent_is_inert_and_clears_completed_dispatch_attempt(self):
        store = MemoryStore(credential=credential())
        transport = FakeTransport(ResponseError(409, "launch_intent_unavailable"))
        runtime = RackHelperRuntime(store, transport, platform="linux_x64")
        self.assertFalse(runtime.consume_launch())
        self.assertEqual(runtime.state, "inert")
        self.assertIsNone(store.get("dispatch"))

    def test_backend_credential_rejection_deletes_identity(self):
        store = MemoryStore(credential=credential(), installation_id=INSTALLATION_ID)
        transport = FakeTransport(ResponseError(401, "helper_authentication_failed"))
        runtime = RackHelperRuntime(store, transport, platform="linux_x64")
        self.assertFalse(runtime.consume_launch())
        self.assertEqual(store.values, {})
        self.assertEqual(runtime.state, "authentication_blocked")

    def test_terminal_pairing_rejection_deletes_pending_credential(self):
        store = MemoryStore(credential=credential(), bootstrap="b" * 43, pairing_id=PAIRING_ID)
        transport = FakeTransport(ResponseError(404, "not_found"))
        runtime = RackHelperRuntime(store, transport, platform="linux_x64")
        self.assertFalse(runtime.poll_and_activate())
        self.assertEqual(store.values, {})
        self.assertEqual(runtime.state, "pairing_rejected")

    def test_heartbeat_posts_only_no_sensor_with_new_request_id(self):
        store = MemoryStore(credential=credential())
        transport = FakeTransport(status_response(), status_response())
        runtime = RackHelperRuntime(store, transport, platform="linux_x64")
        self.assertTrue(runtime.send_heartbeat())
        self.assertTrue(runtime.send_heartbeat())
        first, second = transport.calls
        self.assertEqual(first[0], "/api/rack-helper/v1/status/")
        self.assertEqual(first[1]["status"], "no_sensor")
        self.assertEqual(first[1]["helper_boot_id"], runtime.boot_id)
        self.assertNotEqual(first[1]["status_request_id"], second[1]["status_request_id"])

    def test_heartbeat_response_loss_reuses_status_request_id(self):
        store = MemoryStore(credential=credential())
        transport = FakeTransport(NetworkError("lost"), status_response())
        runtime = RackHelperRuntime(store, transport, platform="linux_x64")
        self.assertTrue(runtime.send_heartbeat())
        self.assertEqual(transport.calls[0][1], transport.calls[1][1])

    def test_quit_stops_loop_without_network_mutation(self):
        transport = FakeTransport()
        runtime = RackHelperRuntime(MemoryStore(), transport, platform="linux_x64")
        runtime.quit()
        self.assertTrue(runtime.stop_event.is_set())
        self.assertEqual(runtime.state, "disconnected")
        self.assertEqual(transport.calls, [])

    def test_logs_contain_no_protocol_credentials_or_request_ids(self):
        token = credential()
        store = MemoryStore(credential=token)
        transport = FakeTransport(ResponseError(409, "launch_intent_unavailable"))
        runtime = RackHelperRuntime(store, transport, platform="linux_x64")
        with self.assertLogs("edgeathlete_rack_helper", logging.INFO) as captured:
            runtime.consume_launch()
        logs = "\n".join(captured.output)
        self.assertNotIn(token, logs)
        self.assertNotIn("edgeathlete-rack:launch", logs)
        dispatch = transport.calls[0][1]
        self.assertNotIn(dispatch["helper_boot_id"], logs)
        self.assertNotIn(dispatch["consume_request_id"], logs)


if __name__ == "__main__":
    unittest.main()
