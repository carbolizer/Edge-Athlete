"""Desktop regressions using fake Bluetooth; no adapter or sensor required."""
import asyncio
from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "wt901_desktop_agent", Path(__file__).with_name("wt901_rack_agent.py"),
)
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


class DesktopTests(unittest.IsolatedAsyncioTestCase):
    async def test_windows_event_loop_can_scan_without_unix_signals(self):
        scan = mock.AsyncMock()
        loop = asyncio.get_running_loop()
        with mock.patch.object(agent, "run_scan", scan), mock.patch.object(
            loop, "add_signal_handler", side_effect=NotImplementedError,
        ):
            options = agent.parse_args(["--scan"])
            await agent.run_until_stopped(options)
        scan.assert_awaited_once_with(options)

    async def test_scan_uses_advertised_name_and_rssi_with_mac_uuid(self):
        device = SimpleNamespace(name=None, address="host-local-uuid")
        advertisement = SimpleNamespace(local_name="WT901BLECL5.0", rssi=-48)
        scanner = SimpleNamespace(discover=mock.AsyncMock(return_value={
            device.address: (device, advertisement),
        }))
        output = io.StringIO()
        with mock.patch.dict("sys.modules", {"bleak": SimpleNamespace(BleakScanner=scanner)}), redirect_stdout(output):
            await agent.run_scan(SimpleNamespace(scan_seconds=5))
        self.assertIn("address=host-local-uuid  rssi=-48", output.getvalue())
        scanner.discover.assert_awaited_once_with(timeout=5, return_adv=True)

    def test_windows_central_mode_fails_with_actionable_message(self):
        with mock.patch.object(agent.sys, "platform", "win32"), self.assertRaises(SystemExit):
            agent.parse_args(["--socket-path", "agent.sock"])


class DesktopLauncherTests(unittest.TestCase):
    def test_setup_rejects_extra_args(self):
        import wt901_desktop
        with self.assertRaises(SystemExit):
            wt901_desktop.main(["setup", "--scan"])

    def test_run_invokes_rack_agent_with_arguments(self):
        import wt901_desktop
        with mock.patch("subprocess.call", return_value=0) as call_mock, mock.patch(
            "pathlib.Path.is_file", return_value=True,
        ):
            code = wt901_desktop.main(["run", "--scan"])
            self.assertEqual(code, 0)
            self.assertTrue(call_mock.called)
            args = call_mock.call_args[0][0]
            self.assertTrue(any("wt901_rack_agent.py" in arg for arg in args))
            self.assertIn("--scan", args)

    def test_gui_invokes_gui_script_with_arguments(self):
        import wt901_desktop
        with mock.patch("subprocess.call", return_value=0) as call_mock, mock.patch(
            "pathlib.Path.is_file", return_value=True,
        ):
            code = wt901_desktop.main(["gui", "--address", "my-sensor-addr"])
            self.assertEqual(code, 0)
            self.assertTrue(call_mock.called)
            args = call_mock.call_args[0][0]
            self.assertTrue(any("wt901_gui.py" in arg for arg in args))
            self.assertIn("my-sensor-addr", args)


if __name__ == "__main__":
    unittest.main()
