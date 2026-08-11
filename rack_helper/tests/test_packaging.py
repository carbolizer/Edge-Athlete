from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_linux_handler_has_one_final_uri_substitution_and_no_shell(self):
        text = (ROOT / "packaging/linux/register-development-handler.sh").read_text()
        exec_line = next(line for line in text.splitlines() if '"Exec=' in line)
        self.assertEqual(exec_line.count("%u"), 1)
        self.assertNotIn("%U", exec_line)
        self.assertNotIn("sh -c", text)

    def test_windows_handler_quotes_two_paths_and_one_final_argument(self):
        text = (ROOT / "packaging/windows/Register-DevelopmentHandler.ps1").read_text()
        command_line = next(line for line in text.splitlines() if "$command =" in line)
        self.assertIn("'\"{0}\" \"{1}\" \"%1\"'", command_line)
        self.assertEqual(command_line.count("%1"), 1)
        self.assertIn("HKCU:", text)
        self.assertNotIn("cmd.exe", text)

    def test_build_is_one_folder_and_development_labeled(self):
        spec = (ROOT / "EdgeAthleteRackHelperDevelopment.spec").read_text()
        self.assertIn("COLLECT(", spec)
        self.assertNotIn("onefile", spec.lower())
        self.assertIn('name="EdgeAthleteRackHelperDevelopment"', spec)

    def test_package_is_development_only_and_has_no_ble_dependency(self):
        project = (ROOT / "pyproject.toml").read_text()
        runtime = (ROOT / "requirements.txt").read_text()
        spec = (ROOT / "EdgeAthleteRackHelperDevelopment.spec").read_text()
        self.assertIn('name = "edgeathlete-rack-helper-development"', project)
        self.assertIn('"Development Status :: 2 - Pre-Alpha"', project)
        for text in (project, runtime, spec):
            self.assertNotIn("bleak", text.lower())

    def test_registrations_are_hidden_user_scoped_development_handlers(self):
        linux = (ROOT / "packaging/linux/register-development-handler.sh").read_text()
        windows = (ROOT / "packaging/windows/Register-DevelopmentHandler.ps1").read_text()
        self.assertIn("NoDisplay=true", linux)
        self.assertIn("development.desktop", linux)
        self.assertIn('update-desktop-database "$applications_dir"', linux)
        self.assertIn("HKCU:", windows)
        self.assertNotIn("HKLM:", windows)
        self.assertNotIn("MSIX", windows.upper())

    def test_platform_builds_require_hashes_audit_and_emit_sbom(self):
        linux = (ROOT / "scripts/build-linux-development.sh").read_text()
        windows = (ROOT / "packaging/windows/Build-Development.ps1").read_text()
        for text in (linux, windows):
            self.assertIn("--require-hashes", text)
            self.assertIn("pip_audit", text)
            self.assertIn("cyclonedx_py", text)
            self.assertIn("EdgeAthleteRackHelperDevelopment.cdx.json", text)
        self.assertTrue((ROOT / "requirements-linux-x64.lock").is_file())
        lock = (ROOT / "requirements-linux-x64.lock").read_text()
        self.assertIn("--hash=sha256:", lock)

    def test_runtime_has_no_ble_mqtt_listener_or_shell_import(self):
        source = "\n".join(
            path.read_text() for path in (ROOT / "src/edgeathlete_rack_helper").glob("*.py")
        )
        for forbidden in ("import bleak", "import paho", "import socket", "import subprocess", "os.system"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
