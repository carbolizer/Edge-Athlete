"""Bounded client for the host BLE Agent's fixed Unix-socket API."""

import json
import socket

from django.conf import settings


MAX_RESPONSE_BYTES = 64 * 1024
# A physical scan takes five seconds and verification may include a BlueZ connect.
# Keep the request bounded above both Agent operations rather than timing them out early.
SOCKET_TIMEOUT_SECONDS = 25
SAFE_CONFLICTS = {
    "binding_reconciliation_required",
    "binding_not_found",
    "device_already_bound",
    "fresh_frames_unavailable",
    "movement_not_confirmed",
    "not_wt901_notify_device",
    "rack_already_bound",
    "rack_not_bound",
    "scan_handle_expired",
    "scan_unavailable",
    "verification_expired",
    "verification_unavailable",
}

SAFE_DETAILS = {
    "binding_reconciliation_required": "BLE binding changed; reconcile the rack and try again",
    "binding_not_found": "BLE binding no longer exists",
    "device_already_bound": "sensor is already assigned to another rack",
    "fresh_frames_unavailable": "sensor did not provide fresh WT901 frames",
    "movement_not_confirmed": "sensor movement was not confirmed; move the sensor and verify again",
    "not_wt901_notify_device": "device does not provide the WT901 notification service",
    "rack_already_bound": "rack already has a BLE sensor binding",
    "rack_not_bound": "rack has no BLE sensor binding",
    "scan_handle_expired": "scan result expired; scan again",
    "scan_unavailable": "Bluetooth scan is unavailable",
    "verification_expired": "sensor verification expired; scan again",
    "verification_unavailable": "sensor verification is unavailable",
}


class BLEAgentUnavailable(Exception):
    pass


class BLEAgentConflict(Exception):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _strict_json(raw):
    return json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def _call(method, path, body=None):
    encoded_body = b"" if body is None else json.dumps(
        body, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    headers = [
        f"{method} {path} HTTP/1.1", "Host: ble-agent", "Connection: close",
    ]
    if body is not None:
        headers.extend([
            "Content-Type: application/json", f"Content-Length: {len(encoded_body)}",
        ])
    encoded = ("\r\n".join(headers) + "\r\n\r\n").encode("ascii") + encoded_body
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(SOCKET_TIMEOUT_SECONDS)
            client.connect(settings.BLE_AGENT_SOCKET_PATH)
            client.sendall(encoded)
            chunks = bytearray()
            while True:
                chunk = client.recv(min(4096, MAX_RESPONSE_BYTES + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
                if len(chunks) > MAX_RESPONSE_BYTES:
                    raise BLEAgentUnavailable("BLE Agent response exceeded the limit")
    except BLEAgentUnavailable:
        raise
    except (OSError, TimeoutError) as exc:
        raise BLEAgentUnavailable("BLE Agent is unavailable") from exc

    try:
        raw_headers, raw_body = bytes(chunks).split(b"\r\n\r\n", 1)
        header_lines = raw_headers.decode("ascii").split("\r\n")
        version, status_text, _reason = header_lines[0].split(" ", 2)
        status = int(status_text)
        response_headers = {}
        for line in header_lines[1:]:
            key, value = line.split(":", 1)
            response_headers[key.lower()] = value.strip()
        content_length = int(response_headers["content-length"])
    except (ValueError, UnicodeDecodeError, KeyError) as exc:
        raise BLEAgentUnavailable("BLE Agent returned an invalid response") from exc
    if version != "HTTP/1.1" or content_length != len(raw_body):
        raise BLEAgentUnavailable("BLE Agent returned an invalid response")
    try:
        response = _strict_json(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise BLEAgentUnavailable("BLE Agent returned invalid JSON") from exc
    if not isinstance(response, dict):
        raise BLEAgentUnavailable("BLE Agent returned an invalid response")
    if 200 <= status < 300:
        return response
    code = response.get("code")
    if code in SAFE_CONFLICTS:
        raise BLEAgentConflict(code, SAFE_DETAILS[code])
    raise BLEAgentUnavailable("BLE Agent returned an invalid response")


def scan():
    return _call("POST", "/v1/scans", {})


def verify(device_handle):
    return _call("POST", "/v1/verifications", {"handle": device_handle})


def bind(verification_token, rack_number, expected_node_id):
    return _call("POST", "/v1/bindings", {
        "verification_token": verification_token,
        "rack_number": rack_number,
        "expected_node_id": expected_node_id,
    })


def rollback(binding_token):
    return _call("DELETE", f"/v1/bindings/{binding_token}")


def health(rack_number):
    return _call("GET", f"/v1/racks/{rack_number}/health")
