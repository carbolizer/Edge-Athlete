"""USB transport contract tests: fragmented frames, failure, and cancellation."""
import asyncio
import struct
import unittest
from types import SimpleNamespace
from unittest import mock

import wt901_rack_agent as agent
from wt901_serial import open_sensor_stream, list_serial_ports


class SerialTests(unittest.IsolatedAsyncioTestCase):
    async def test_usb_fragments_reuse_ble_decoder_and_close(self):
        frame = b'\x55\x61' + struct.pack('<9h', 0, 0, 2048, 0, 0, 0, 0, 0, 0)
        chunks = iter([frame[:7], frame[7:], b''])
        port = mock.Mock(in_waiting=20)
        port.read.side_effect = lambda size: next(chunks, b'')
        serial = SimpleNamespace(Serial=mock.Mock(return_value=port))
        decoder = agent.WT901FrameDecoder()
        samples = []
        ready = asyncio.Event()

        def receive(_, chunk):
            samples.extend(decoder.feed(chunk))
            if samples:
                ready.set()

        with mock.patch.dict('sys.modules', {'serial': serial}):
            async with open_sensor_stream(SimpleNamespace(serial_port='COM3', baud=115200), receive, mock.Mock(), '', ''):
                await asyncio.wait_for(ready.wait(), 1)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].acceleration_g, (0, 0, 1))
        port.close.assert_called_once()
        port.write.assert_not_called()
        serial.Serial.assert_called_once_with(port='COM3', baudrate=115200, timeout=0.2, write_timeout=0.2)

    async def test_usb_disconnect_propagates_and_closes(self):
        port = mock.Mock(in_waiting=1)
        port.read.side_effect = OSError('device removed')
        disconnected = asyncio.Event()
        with mock.patch.dict('sys.modules', {'serial': SimpleNamespace(Serial=mock.Mock(return_value=port))}):
            with self.assertRaises(OSError):
                async with open_sensor_stream(SimpleNamespace(serial_port='COM3', baud=115200), mock.Mock(), lambda _: disconnected.set(), '', ''):
                    await asyncio.wait_for(disconnected.wait(), 1)
        port.close.assert_called_once()

    def test_serial_mode_requires_identity_and_excludes_ble(self):
        options = agent.parse_args(['--serial-port', 'COM3', '--node-id', 'rack_usb'])
        self.assertEqual(options.baud, 115200)
        for args in (['--serial-port', 'COM3'], ['--serial-port', 'COM3', '--address', 'uuid', '--node-id', 'rack'], ['--list-ports', '--scan']):
            with self.assertRaises(SystemExit):
                agent.parse_args(args)

    def test_port_list_exposes_cross_platform_device_names(self):
        ports = SimpleNamespace(comports=lambda: [SimpleNamespace(device='COM3', description='USB-SERIAL CH340', vid=0x1a86, pid=0x7523)])
        with mock.patch.dict('sys.modules', {'serial.tools': SimpleNamespace(list_ports=ports)}):
            self.assertEqual(list_serial_ports()[0]['port'], 'COM3')


if __name__ == '__main__':
    unittest.main()
