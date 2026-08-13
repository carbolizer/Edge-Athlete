"""Bounded client for the host NFC Agent's private Unix-socket API."""

import json
import re
import socket

from django.conf import settings


MAX_RESPONSE_BYTES = 4096
SOCKET_TIMEOUT_SECONDS = 1
TAG_PATTERN = re.compile(r"^[0-9A-F]{8,32}$")


class NFCAgentUnavailable(Exception):
    pass


def consume(rack_number):
    body = json.dumps({"rack_number": rack_number}, separators=(",", ":")).encode()
    request = (
        b"POST /v1/taps/consume HTTP/1.1\r\nHost: nfc-agent\r\n"
        b"Content-Type: application/json\r\nConnection: close\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode()
        + body
    )
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(SOCKET_TIMEOUT_SECONDS)
            client.connect(settings.NFC_AGENT_SOCKET_PATH)
            client.sendall(request)
            response = bytearray()
            while True:
                chunk = client.recv(min(1024, MAX_RESPONSE_BYTES + 1 - len(response)))
                if not chunk:
                    break
                response.extend(chunk)
                if len(response) > MAX_RESPONSE_BYTES:
                    raise NFCAgentUnavailable()
    except NFCAgentUnavailable:
        raise
    except (OSError, TimeoutError) as error:
        raise NFCAgentUnavailable() from error
    try:
        raw_headers, raw_body = bytes(response).split(b"\r\n\r\n", 1)
        status = int(raw_headers.split(b"\r\n", 1)[0].split(b" ")[1])
        payload = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NFCAgentUnavailable() from error
    if status != 200 or not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise NFCAgentUnavailable()
    if payload == {"schema_version": 1, "status": "none"}:
        return payload
    if (
        set(payload) == {"schema_version", "status", "tag_id"}
        and payload["status"] == "tap"
        and isinstance(payload["tag_id"], str)
        and TAG_PATTERN.fullmatch(payload["tag_id"])
    ):
        return payload
    raise NFCAgentUnavailable()
