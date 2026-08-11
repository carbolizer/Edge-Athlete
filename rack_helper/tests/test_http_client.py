import io
import json
from email.message import Message
import unittest
from urllib import error

from edgeathlete_rack_helper.http_client import (
    JsonTransport,
    NoRedirect,
    ResponseError,
    TransportError,
    strict_json,
    validate_origin,
)


class FakeResponse:
    def __init__(self, body, status=200, content_type="application/json", length=True):
        self.body = io.BytesIO(body)
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if length:
            self.headers["Content-Length"] = str(len(body))

    def read(self, size=-1):
        return self.body.read(size)

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def open(self, outgoing, timeout):
        self.requests.append((outgoing, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class HttpClientTests(unittest.TestCase):
    def test_fixed_origin_path_and_authorization_header(self):
        opener = FakeOpener(FakeResponse(b'{"ok":true}'))
        transport = JsonTransport(opener=opener)
        self.assertEqual(
            transport.post("/api/rack-helper/v1/status/", {}, "earh1.test.secret"),
            {"ok": True},
        )
        outgoing, timeout = opener.requests[0]
        self.assertEqual(outgoing.full_url, "https://app.edgeathlete.online/api/rack-helper/v1/status/")
        self.assertEqual(outgoing.get_header("Authorization"), "RackHelper earh1.test.secret")
        self.assertEqual(timeout, 5)

    def test_disallows_unknown_paths(self):
        transport = JsonTransport(opener=FakeOpener(FakeResponse(b"{}")))
        with self.assertRaises(ValueError):
            transport.post("/api/sets/", {})

    def test_runtime_cannot_override_build_time_origin(self):
        with self.assertRaises(TypeError):
            JsonTransport(origin="https://other.example")

    def test_origin_must_be_https_port_443_without_url_data(self):
        self.assertEqual(validate_origin("https://edgeathlete.example:443/"), "https://edgeathlete.example:443")
        for value in (
            "http://edgeathlete.example", "https://user@edgeathlete.example",
            "https://edgeathlete.example:444", "https://edgeathlete.example/path",
            "https://edgeathlete.example/?query=1", "https://edgeathlete.example/#fragment",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_origin(value)

    def test_strict_json_rejects_duplicates_constants_nonobjects_and_depth(self):
        malformed = [
            b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'\xff', b'{',
            json.dumps({"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": 1}}}}}}}}}).encode(),
        ]
        for raw in malformed:
            with self.subTest(raw=raw[:30]), self.assertRaises(TransportError):
                strict_json(raw)

    def test_bounds_content_type_and_response_bytes(self):
        with self.assertRaises(TransportError):
            JsonTransport(opener=FakeOpener(FakeResponse(b"{}", content_type="text/html"))).post(
                "/api/rack-helper/v1/status/", {},
            )
        oversized = b"{" + b" " * (16 * 1024) + b"}"
        with self.assertRaises(TransportError):
            JsonTransport(opener=FakeOpener(FakeResponse(oversized, length=False))).post(
                "/api/rack-helper/v1/status/", {},
            )

    def test_redirect_handler_never_constructs_followup(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://other.example"))

    def test_http_error_returns_only_stable_code(self):
        body = b'{"code":"launch_intent_unavailable","detail":"private arbitrary text"}'
        headers = Message()
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
        failure = error.HTTPError("https://edgeathlete.example", 409, "Conflict", headers, io.BytesIO(body))
        transport = JsonTransport(opener=FakeOpener(failure))
        with self.assertRaises(ResponseError) as caught:
            transport.post("/api/rack-helper/v1/launch-intents/consume/", {})
        self.assertEqual((caught.exception.status, caught.exception.code), (409, "launch_intent_unavailable"))
        self.assertNotIn("private", str(caught.exception))

    def test_http_error_code_requires_strict_lowercase_snake_case(self):
        invalid_codes = (
            "", "Uppercase", "dash-code", " leading", "trailing ", "line\nfeed",
            "_leading", "a" * 65, "café", 4, None,
        )
        for code in invalid_codes:
            with self.subTest(code=repr(code)):
                with self.assertRaises(ResponseError) as caught:
                    JsonTransport._raise_parsed_error(400, {"code": code})
                self.assertEqual(caught.exception.code, "invalid_error_response")


if __name__ == "__main__":
    unittest.main()
