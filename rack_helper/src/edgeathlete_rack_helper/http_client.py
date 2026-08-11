"""Small fixed-origin JSON client for the accepted helper operations."""

import json
import re
import ssl
from urllib import error, request
from urllib.parse import urlsplit

from .config import APPLICATION_ORIGIN, HTTP_TIMEOUT_SECONDS, MAX_RESPONSE_BYTES


ALLOWED_PATHS = frozenset({
    "/api/rack-helper/v1/pairings/claim/",
    "/api/rack-helper/v1/pairings/status/",
    "/api/rack-helper/v1/pairings/activate/",
    "/api/rack-helper/v1/launch-intents/consume/",
    "/api/rack-helper/v1/status/",
})
REMOTE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)


class TransportError(Exception):
    """A privacy-safe transport failure without arbitrary remote text."""


class NetworkError(TransportError):
    pass


class ResponseError(TransportError):
    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _strict_object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("invalid JSON number")


def strict_json(raw):
    try:
        value = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise TransportError("invalid_json_response") from exc
    if not isinstance(value, dict) or _json_depth(value) > 8:
        raise TransportError("invalid_json_response")
    return value


def _json_depth(value):
    if isinstance(value, dict):
        return 1 + max((_json_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_json_depth(item) for item in value), default=0)
    return 0


def validate_origin(origin):
    parsed = urlsplit(origin)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid application origin") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.isascii()
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid application origin")
    return origin.rstrip("/")


class JsonTransport:
    def __init__(self, *, opener=None, timeout=HTTP_TIMEOUT_SECONDS):
        self.origin = validate_origin(APPLICATION_ORIGIN)
        self.timeout = timeout
        self.opener = opener or request.build_opener(
            request.HTTPSHandler(context=ssl.create_default_context()), NoRedirect(),
        )

    def post(self, path, body, credential=None):
        if path not in ALLOWED_PATHS or not isinstance(body, dict):
            raise ValueError("operation is not allowed")
        encoded = json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        }
        if credential is not None:
            headers["Authorization"] = "RackHelper " + credential
        outgoing = request.Request(self.origin + path, data=encoded, headers=headers, method="POST")
        try:
            response = self.opener.open(outgoing, timeout=self.timeout)
        except error.HTTPError as exc:
            return self._raise_response_error(exc)
        except (OSError, TimeoutError, error.URLError):
            raise NetworkError("network_unavailable") from None
        with response:
            status = response.getcode()
            payload = self._read_response(response)
        if status < 200 or status >= 300:
            self._raise_parsed_error(status, payload)
        return payload

    def _read_response(self, response):
        content_type = response.headers.get_content_type()
        if content_type != "application/json":
            raise TransportError("invalid_content_type")
        length = response.headers.get("Content-Length")
        if length is not None:
            try:
                if int(length) > MAX_RESPONSE_BYTES:
                    raise TransportError("response_too_large")
            except ValueError:
                raise TransportError("invalid_content_length") from None
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise TransportError("response_too_large")
        return strict_json(raw)

    def _raise_response_error(self, response):
        try:
            payload = self._read_response(response)
        except TransportError:
            raise ResponseError(response.code, "invalid_error_response") from None
        self._raise_parsed_error(response.code, payload)

    @staticmethod
    def _raise_parsed_error(status, payload):
        code = payload.get("code")
        if not isinstance(code, str) or REMOTE_ERROR_CODE.fullmatch(code) is None:
            code = "invalid_error_response"
        raise ResponseError(status, code)
