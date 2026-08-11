import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("check_api_allowlist.py")
SPEC = importlib.util.spec_from_file_location("check_api_allowlist", SCRIPT_PATH)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)
REPO_ROOT = Path(__file__).resolve().parents[2]


class ApiAllowlistTests(unittest.TestCase):
    def test_checked_in_template_passes(self):
        config_path = REPO_ROOT / "nginx" / "vps.conf.template"
        self.assertEqual(CHECKER.validation_errors(config_path), [])

    def test_proxying_fallback_fails(self):
        config = (REPO_ROOT / "nginx" / "vps.conf.template").read_text(encoding="utf-8")
        unsafe = config.replace(
            "location /api/ {\n        return 404;\n    }",
            "location /api/ {\n        proxy_pass http://vps_django;\n    }",
        )
        self.assertNotEqual(unsafe, config)
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "vps.conf.template"
            config_path.write_text(unsafe, encoding="utf-8")
            self.assertIn(
                "VPS API fallback must contain only 'return 404;'",
                CHECKER.validation_errors(config_path),
            )

    def test_hosted_allowlist_is_anchored_away_from_legacy_racks(self):
        config = (REPO_ROOT / "nginx" / "vps.conf.template").read_text(encoding="utf-8")
        hosted_locations = [
            value for value in CHECKER.EXPECTED_API_LOCATIONS
            if "rack" in value and value.startswith("~ ")
        ]
        self.assertTrue(hosted_locations)
        self.assertNotIn("/api/racks/", "\n".join(hosted_locations))
        self.assertTrue(all(value.endswith("$") for value in hosted_locations))

    def test_missing_method_guard_fails(self):
        config = (REPO_ROOT / "nginx" / "vps.conf.template").read_text(encoding="utf-8")
        unsafe = config.replace("if ($request_method != GET)", "if ($request_method != POST)", 1)
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "vps.conf.template"
            config_path.write_text(unsafe, encoding="utf-8")
            self.assertTrue(any("method guard" in error for error in CHECKER.validation_errors(config_path)))

    def test_main_application_csp_is_required(self):
        config = (REPO_ROOT / "nginx" / "vps.conf.template").read_text(encoding="utf-8")
        unsafe = config.replace(
            "    add_header Content-Security-Policy \"default-src 'self'; base-uri 'none'; connect-src 'self'; frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; worker-src 'self'\" always;\n",
            "",
            1,
        )
        self.assertNotEqual(unsafe, config)
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "vps.conf.template"
            config_path.write_text(unsafe, encoding="utf-8")
            self.assertIn("VPS main application CSP is missing", CHECKER.validation_errors(config_path))

    def test_hosted_routes_require_per_ip_limits(self):
        config = (REPO_ROOT / "nginx" / "vps.conf.template").read_text(encoding="utf-8")
        unsafe = config.replace("limit_req zone=hosted_control_plane burst=20 nodelay;", "", 1)
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "vps.conf.template"
            config_path.write_text(unsafe, encoding="utf-8")
            self.assertTrue(any("per-IP limiting" in error for error in CHECKER.validation_errors(config_path)))

    def test_upstream_security_headers_are_suppressed(self):
        config = (REPO_ROOT / "nginx" / "vps.conf.template").read_text(encoding="utf-8")
        unsafe = config.replace("    proxy_hide_header Referrer-Policy;\n", "", 1)
        self.assertNotEqual(unsafe, config)
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "vps.conf.template"
            config_path.write_text(unsafe, encoding="utf-8")
            self.assertIn(
                "VPS must suppress the upstream Referrer-Policy header",
                CHECKER.validation_errors(config_path),
            )


if __name__ == "__main__":
    unittest.main()
