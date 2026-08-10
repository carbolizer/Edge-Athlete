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


if __name__ == "__main__":
    unittest.main()
