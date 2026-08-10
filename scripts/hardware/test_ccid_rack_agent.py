import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


PATH = Path(__file__).with_name("ccid_rack_agent.py")
SPEC = importlib.util.spec_from_file_location("ccid_rack_agent", PATH)
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


class FakeClock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now


class FakeReader:
    def __init__(self):
        self.tag = None

    def read_uid(self):
        return self.tag


class FakeUsbDevice:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def read(self, endpoint, size, timeout):
        self.calls.append((endpoint, size, timeout))
        if self.error is not None:
            raise self.error
        return self.result


class DirectCcidReaderTests(unittest.TestCase):
    def make_reader(self, device):
        reader = object.__new__(agent.DirectCcidReader)
        reader._reader = device
        return reader

    def test_waits_for_changed_slot_notification(self):
        device = FakeUsbDevice(b"\x50\x03")

        changed = self.make_reader(device).wait_for_change(0.2)

        self.assertTrue(changed)
        self.assertEqual(device.calls, [(agent.INTERRUPT_IN_ENDPOINT, 4, 200)])

    def test_removal_is_also_a_changed_slot_notification(self):
        device = FakeUsbDevice(b"\x50\x02")

        self.assertTrue(self.make_reader(device).wait_for_change(0.2))

    def test_ignores_interrupt_timeout(self):
        import usb.core

        device = FakeUsbDevice(error=usb.core.USBTimeoutError("no slot change"))

        self.assertFalse(self.make_reader(device).wait_for_change(0.2))

    def test_rejects_invalid_slot_notification(self):
        device = FakeUsbDevice(b"\x51\x03")

        with self.assertRaisesRegex(RuntimeError, "slot-change"):
            self.make_reader(device).wait_for_change(0.2)


class TapAgentTests(unittest.TestCase):
    def setUp(self):
        self.reader = FakeReader()
        self.clock = FakeClock()
        self.tap = agent.TapAgent(self.reader, clock=self.clock, tap_ttl_seconds=2)

    def test_normalizes_uid_without_preserving_separators(self):
        self.assertEqual(agent.normalize_tag_id("04:a1:b2:c3:d4:e5:f6"), "04A1B2C3D4E5F6")
        with self.assertRaises(ValueError):
            agent.normalize_tag_id("not-a-tag")

    def test_held_tag_is_consumed_once_until_removed(self):
        self.reader.tag = "04A1B2C3D4E5F6"
        self.tap.poll()
        self.assertEqual(self.tap.consume(1)["status"], "tap")
        self.tap.poll()
        self.assertEqual(self.tap.consume(1)["status"], "none")
        self.reader.tag = None
        self.tap.poll()
        self.reader.tag = "04A1B2C3D4E5F6"
        self.tap.poll()
        self.assertEqual(self.tap.consume(1)["status"], "tap")

    def test_pending_tap_expires_and_wrong_rack_is_hidden(self):
        self.reader.tag = "04A1B2C3D4E5F6"
        self.tap.poll()
        self.clock.now += 3
        self.assertEqual(self.tap.consume(1)["status"], "none")
        with self.assertRaisesRegex(agent.ApiError, "rack_reader_not_found"):
            self.tap.consume(2)

    def test_reader_failure_is_explicit_and_discards_pending_tap(self):
        self.reader.tag = "04A1B2C3D4E5F6"
        self.tap.poll()
        self.tap.reader_failed()
        with self.assertRaisesRegex(agent.ApiError, "reader_unavailable"):
            self.tap.consume(1)

    def test_replacing_reader_recovers_and_requires_a_fresh_tap(self):
        self.tap.reader_failed()
        replacement = FakeReader()
        self.tap.replace_reader(replacement)
        self.assertEqual(self.tap.consume(1)["status"], "none")
        replacement.tag = "04A1B2C3D4E5F6"
        self.tap.poll()
        self.assertEqual(self.tap.consume(1)["status"], "tap")


class PollCycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_immediate_notifications_are_rate_limited(self):
        reader = FakeReader()
        reader.tag = "04A1B2C3D4E5F6"
        reader.wait_for_change = lambda _timeout: True
        tap = agent.TapAgent(reader)
        delays = []

        async def record_sleep(delay):
            delays.append(delay)

        await agent.run_poll_cycle(
            tap,
            reader,
            0.2,
            clock=lambda: 10.0,
            sleep=record_sleep,
        )

        self.assertEqual(delays, [0.2])
        self.assertEqual(tap.consume(1)["status"], "tap")


class SocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.socket_path = os.path.join(self.directory.name, "nfc.sock")
        self.tap = agent.TapAgent(FakeReader())
        self.server = await agent.serve(self.tap, self.socket_path)

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        self.directory.cleanup()

    async def request(self, method="POST", path="/v1/taps/consume", body=None):
        body = {"rack_number": 1} if body is None else body
        encoded = json.dumps(body, separators=(",", ":")).encode()
        reader, writer = await asyncio.open_unix_connection(self.socket_path)
        writer.write(
            f"{method} {path} HTTP/1.1\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(encoded)}\r\n\r\n".encode() + encoded
        )
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
        return response.decode()

    async def test_socket_is_private_and_consumes_fixed_schema(self):
        self.assertEqual(os.stat(self.socket_path).st_mode & 0o777, 0o600)
        response = await self.request()
        self.assertIn("200 OK", response)
        self.assertIn('"status":"none"', response)

    async def test_rejects_wrong_method_path_and_body(self):
        self.assertIn("405 Method Not Allowed", await self.request(method="GET"))
        self.assertIn("404 Not Found", await self.request(path="/v1/other"))
        self.assertIn("400 Bad Request", await self.request(body={"rack_number": 1, "tag_id": "secret"}))

    async def test_partial_body_times_out(self):
        previous = agent.REQUEST_TIMEOUT_SECONDS
        agent.REQUEST_TIMEOUT_SECONDS = 0.02
        try:
            reader, writer = await asyncio.open_unix_connection(self.socket_path)
            writer.write(
                b"POST /v1/taps/consume HTTP/1.1\r\nContent-Type: application/json\r\n"
                b"Content-Length: 2\r\n\r\n{"
            )
            await writer.drain()
            response = await reader.read()
            writer.close()
            await writer.wait_closed()
        finally:
            agent.REQUEST_TIMEOUT_SECONDS = previous
        self.assertIn(b"400 Bad Request", response)


if __name__ == "__main__":
    unittest.main()
