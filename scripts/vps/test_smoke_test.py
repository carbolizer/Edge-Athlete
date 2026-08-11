import importlib.util
import unittest
from email.message import Message
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("smoke_test.py")
SPEC = importlib.util.spec_from_file_location("smoke_test", SCRIPT_PATH)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def headers(**values):
    result = Message()
    for name, value in values.items():
        result[name.replace("_", "-")] = value
    return result


SECURITY_HEADERS = {
    "Strict_Transport_Security": "max-age=31536000; includeSubDomains",
    "X_Content_Type_Options": "nosniff",
    "X_Frame_Options": "DENY",
    "Referrer_Policy": "no-referrer",
    "Permissions_Policy": "bluetooth=(), camera=(), geolocation=(), microphone=()",
    "Content_Security_Policy": (
        "default-src 'self'; base-uri 'none'; connect-src 'self'; frame-ancestors 'none'; "
        "img-src 'self' data:; object-src 'none'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; worker-src 'self'"
    ),
}


class VpsSmokeValidationTests(unittest.TestCase):
    def valid_observations(self):
        secure = headers(**SECURITY_HEADERS)
        csrf_headers = headers(
            **SECURITY_HEADERS,
            Cache_Control="no-store",
            Set_Cookie="ea_rack_csrf=value; Path=/api/rack/v1/; SameSite=Strict; Secure",
        )
        redirect_headers = headers(Location="https://edge.example.com/rack")
        return {
            "health": SMOKE.Observation(200, secure, b'{"status":"ok","database":"ok"}'),
            "rack": SMOKE.Observation(200, secure, b'<div id="root"></div>'),
            "csrf": SMOKE.Observation(200, csrf_headers, b"{}"),
            "rack_status": SMOKE.Observation(
                401, secure,
                b'{"code":"endpoint_authentication_failed","detail":"Endpoint authentication failed."}',
            ),
            "coach_groups": SMOKE.Observation(401, secure, b""),
            "private_api": SMOKE.Observation(404, secure, b""),
            "admin": SMOKE.Observation(404, secure, b""),
            "http_redirect": SMOKE.Observation(308, redirect_headers, b""),
            "http_post": SMOKE.Observation(405, Message(), b""),
        }

    def test_valid_boundary_passes(self):
        self.assertEqual(
            SMOKE.validate_observations("edge.example.com", self.valid_observations()),
            [],
        )

    def test_exposed_private_api_fails(self):
        observations = self.valid_observations()
        observations["private_api"] = SMOKE.Observation(200, headers(**SECURITY_HEADERS), b"[]")
        self.assertIn(
            "private_api returned 200, expected 404",
            SMOKE.validate_observations("edge.example.com", observations),
        )

    def test_insecure_csrf_cookie_fails(self):
        observations = self.valid_observations()
        observations["csrf"] = SMOKE.Observation(
            200,
            headers(**SECURITY_HEADERS, Cache_Control="no-store", Set_Cookie="ea_rack_csrf=value"),
            b"{}",
        )
        errors = SMOKE.validate_observations("edge.example.com", observations)
        self.assertTrue(any("Rack CSRF cookie is missing Secure" == error for error in errors))

    def test_missing_security_header_fails(self):
        observations = self.valid_observations()
        observations["rack"] = SMOKE.Observation(200, Message(), b'<div id="root"></div>')
        self.assertTrue(any(
            error.startswith("rack: missing or invalid")
            for error in SMOKE.validate_observations("edge.example.com", observations)
        ))


if __name__ == "__main__":
    unittest.main()
