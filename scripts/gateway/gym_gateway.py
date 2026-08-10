#!/usr/bin/env python3
"""Durably forward privacy-safe WT901 rack health to the hosted diagnostics API."""

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import random
import re
import signal
import socket
import sqlite3
import ssl
import stat
import time
from urllib import error, request
from urllib.parse import urlsplit
import uuid


VERSION = "1.0.0"
QUEUE_SCHEMA_VERSION = 1
MAX_AGENT_RESPONSE_BYTES = 64 * 1024
AGENT_TIMEOUT_SECONDS = 2.0
MAX_EVENTS_PER_BATCH = 100
MAX_BATCH_BYTES = 256 * 1024
MAX_QUEUE_ROWS = 50_000
MAX_QUEUE_BYTES = 64 * 1024 * 1024
MIN_RETRY_SECONDS = 1.0
MAX_RETRY_SECONDS = 60.0
MAX_RETRY_AFTER_SECONDS = 300.0
NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
RESULT_CODE_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
CREDENTIAL_PATTERN = re.compile(
    r"^egw1\.([0-9a-fA-F-]{36})\.([1-9][0-9]{0,9})\.([A-Za-z0-9_-]{43})$"
)
SENSOR_STATES = {"starting", "live", "stale", "reconnecting"}
TERMINAL_RESULTS = {"accepted", "duplicate", "rejected"}
RESPONSE_RESULTS = TERMINAL_RESULTS | {"retry"}
QUEUE_STATES = {"healthy", "unhealthy", "full", "corrupt", "read_only"}


class GatewayError(Exception):
    """Base class for expected, privacy-safe gateway failures."""


class AgentUnavailable(GatewayError):
    pass


class QueueUnavailable(GatewayError):
    pass


class QueueFull(QueueUnavailable):
    pass


class UploadRejected(GatewayError):
    pass


def canonical_json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc_timestamp(value):
    if not isinstance(value, str) or len(value) > 32 or not value.endswith("Z"):
        raise ValueError("timestamp must be bounded UTC RFC 3339")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError("timestamp must be UTC")
    return parsed


def strict_json(raw):
    return json.loads(
        raw.decode("utf-8"),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_https_without_redirect(upload_request, timeout, context):
    opener = request.build_opener(request.HTTPSHandler(context=context), NoRedirect())
    return opener.open(upload_request, timeout=timeout)


def validate_https_url(value):
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("upload URL is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or port not in (None, 443)
    ):
        raise ValueError("upload URL must be HTTPS on port 443 without credentials or query data")
    return value


def load_credential(path):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o077
            or metadata.st_size > 512
        ):
            raise ValueError("credential file is invalid")
        raw = os.read(fd, 513)
    finally:
        os.close(fd)
    try:
        credential = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("credential file is invalid") from exc
    match = CREDENTIAL_PATTERN.fullmatch(credential)
    if match is None:
        raise ValueError("credential file is invalid")
    gateway_id = str(uuid.UUID(match.group(1)))
    return credential, gateway_id


def _recv_bounded(client, limit):
    chunks = bytearray()
    while True:
        remaining = limit + 1 - len(chunks)
        if remaining <= 0:
            raise AgentUnavailable("agent response exceeded limit")
        chunk = client.recv(min(4096, remaining))
        if not chunk:
            return bytes(chunks)
        chunks.extend(chunk)
        if len(chunks) > limit:
            raise AgentUnavailable("agent response exceeded limit")


def read_rack_health(socket_path, rack_number, expected_node_id):
    encoded_request = (
        f"GET /v1/racks/{rack_number}/health HTTP/1.1\r\n"
        "Host: ble-agent\r\nConnection: close\r\n\r\n"
    ).encode("ascii")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(AGENT_TIMEOUT_SECONDS)
            client.connect(socket_path)
            client.sendall(encoded_request)
            response = _recv_bounded(client, MAX_AGENT_RESPONSE_BYTES)
    except AgentUnavailable:
        raise
    except (OSError, TimeoutError) as exc:
        raise AgentUnavailable("agent unavailable") from exc

    try:
        raw_headers, raw_body = response.split(b"\r\n\r\n", 1)
        lines = raw_headers.decode("ascii").split("\r\n")
        version, status_text, _reason = lines[0].split(" ", 2)
        headers = {}
        for line in lines[1:]:
            key, value = line.split(":", 1)
            key = key.strip().lower()
            if not key or key in headers:
                raise ValueError("duplicate header")
            headers[key] = value.strip()
        content_length = int(headers["content-length"])
        payload = strict_json(raw_body)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentUnavailable("agent response invalid") from exc
    if (
        version != "HTTP/1.1"
        or status_text != "200"
        or content_length != len(raw_body)
        or not isinstance(payload, dict)
    ):
        raise AgentUnavailable("agent response invalid")

    allowed = {"schema_version", "node_id", "state", "sample_age_ms"}
    health = {key: payload[key] for key in allowed if key in payload}
    schema_version = health.get("schema_version")
    node_id = health.get("node_id")
    state = health.get("state")
    sample_age_ms = health.get("sample_age_ms")
    if (
        type(schema_version) is not int
        or not 1 <= schema_version <= 32767
        or node_id != expected_node_id
        or not isinstance(node_id, str)
        or NODE_ID_PATTERN.fullmatch(node_id) is None
        or state not in SENSOR_STATES
        or (
            sample_age_ms is not None
            and (type(sample_age_ms) is not int or not 0 <= sample_age_ms <= 600_000)
        )
    ):
        raise AgentUnavailable("agent health invalid")
    return health


def reconnecting_health(node_id):
    return {
        "schema_version": 1,
        "node_id": node_id,
        "state": "reconnecting",
        "sample_age_ms": None,
    }


class DurableQueue:
    def __init__(self, path, max_rows=MAX_QUEUE_ROWS, max_bytes=MAX_QUEUE_BYTES):
        self.path = Path(path)
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.state = "healthy"
        self._open()

    def _open(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        if self.path.is_symlink():
            self.state = "read_only"
            raise QueueUnavailable("queue path is unsafe")
        existed = self.path.exists()
        try:
            self.connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS queue_meta (
                    schema_version INTEGER NOT NULL,
                    last_ack_json BLOB,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS queued_event (
                    local_order INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    boot_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    occurred_at TEXT NOT NULL,
                    canonical_json BLOB NOT NULL,
                    byte_length INTEGER NOT NULL,
                    enqueued_at TEXT NOT NULL
                );
                """
            )
            os.chmod(self.path, 0o600)
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                row = self.connection.execute("SELECT COUNT(*) FROM queue_meta").fetchone()[0]
                if row == 0:
                    self.connection.execute(
                        "INSERT INTO queue_meta VALUES (?, NULL, ?)",
                        (QUEUE_SCHEMA_VERSION, utc_now()),
                    )
                elif row != 1:
                    raise QueueUnavailable("queue metadata invalid")
                schema = self.connection.execute(
                    "SELECT schema_version FROM queue_meta"
                ).fetchone()[0]
                if schema != QUEUE_SCHEMA_VERSION:
                    raise QueueUnavailable("queue schema unsupported")
                integrity = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise QueueUnavailable("queue integrity check failed")
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
        except sqlite3.DatabaseError as exc:
            self.state = "corrupt"
            if hasattr(self, "connection"):
                self.connection.close()
            raise QueueUnavailable("queue unavailable") from exc
        except OSError as exc:
            self.state = "read_only"
            raise QueueUnavailable("queue unavailable") from exc

    def close(self):
        self.connection.close()

    def stats(self):
        row = self.connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(byte_length), 0), MIN(enqueued_at) FROM queued_event"
        ).fetchone()
        return {"depth": row[0], "bytes": row[1], "oldest_queued_at": row[2]}

    def enqueue(self, boot_id, event):
        validate_event(event)
        try:
            uuid.UUID(boot_id)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("boot ID is invalid") from exc
        encoded = canonical_json(event)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            count, byte_count = self.connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(byte_length), 0) FROM queued_event"
            ).fetchone()
            if count >= self.max_rows or byte_count + len(encoded) > self.max_bytes:
                self.connection.rollback()
                self.state = "full"
                raise QueueFull("queue full")
            self.connection.execute(
                """INSERT INTO queued_event
                   (event_id, boot_id, sequence, occurred_at, canonical_json, byte_length, enqueued_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["event_id"], boot_id, event["sequence"],
                    event["occurred_at"], encoded, len(encoded), utc_now(),
                ),
            )
            self.connection.commit()
            self.state = (
                "full"
                if count + 1 >= self.max_rows or byte_count + len(encoded) >= self.max_bytes
                else "healthy"
            )
        except QueueFull:
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            self.state = "unhealthy"
            raise QueueUnavailable("queue write failed") from exc
        return encoded

    def batch(self, gateway_id):
        rows = self.connection.execute(
            """SELECT local_order, boot_id, sequence, canonical_json
               FROM queued_event ORDER BY local_order LIMIT ?""",
            (MAX_EVENTS_PER_BATCH,),
        ).fetchall()
        if not rows:
            return None
        first_boot = rows[0][1]
        events = []
        selected = []
        for row in rows:
            if row[1] != first_boot:
                break
            event = strict_json(row[3])
            proposed_events = events + [event]
            stats = self.stats()
            envelope = make_envelope(gateway_id, first_boot, self.state, stats, proposed_events)
            if len(canonical_json(envelope)) > MAX_BATCH_BYTES:
                break
            events = proposed_events
            selected.append(row)
        if not selected:
            raise QueueUnavailable("oldest queued event exceeds upload limit")
        stats = self.stats()
        return make_envelope(gateway_id, first_boot, self.state, stats, events)

    def acknowledge(self, envelope, response):
        events = envelope["events"]
        boot_id = envelope["gateway_boot_id"]
        acknowledged = validate_acknowledgement(response, boot_id, events)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            previous_raw = self.connection.execute(
                "SELECT last_ack_json FROM queue_meta"
            ).fetchone()[0]
            previous_acknowledged = 0
            if previous_raw:
                previous = strict_json(previous_raw)
                if previous["gateway_boot_id"] == boot_id and acknowledged < previous["acknowledged_through"]:
                    raise UploadRejected("acknowledgement cursor decreased")
                if previous["gateway_boot_id"] == boot_id:
                    previous_acknowledged = previous["acknowledged_through"]
            sequences = [
                row[0] for row in self.connection.execute(
                    "SELECT sequence FROM queued_event WHERE boot_id = ? AND sequence <= ? ORDER BY sequence",
                    (boot_id, acknowledged),
                )
            ]
            if sequences and sequences != list(range(previous_acknowledged + 1, acknowledged + 1)):
                raise UploadRejected("acknowledgement is not contiguous")
            rejection_codes = sorted(
                item["code"] for item in response["results"] if item["result"] == "rejected"
            )[:10]
            ack_record = canonical_json({
                "acknowledged_through": acknowledged,
                "gateway_boot_id": boot_id,
                "rejection_codes": rejection_codes,
            })
            self.connection.execute("UPDATE queue_meta SET last_ack_json = ?", (ack_record,))
            self.connection.execute(
                "DELETE FROM queued_event WHERE boot_id = ? AND sequence <= ?",
                (boot_id, acknowledged),
            )
            self.connection.commit()
        except UploadRejected:
            self.connection.rollback()
            raise
        except (sqlite3.DatabaseError, ValueError, json.JSONDecodeError) as exc:
            self.connection.rollback()
            raise QueueUnavailable("acknowledgement transaction failed") from exc
        return acknowledged


def make_event(sequence, rack_number, node_id, assignment_revision, health, now=utc_now):
    return {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "event_type": "sensor_health",
        "rack_number": rack_number,
        "logical_node_id": node_id,
        "assignment_revision": assignment_revision,
        "sequence": sequence,
        "occurred_at": now(),
        "payload": {
            "agent_schema_version": health["schema_version"],
            "sensor_state": health["state"],
            "sample_age_ms": health["sample_age_ms"],
        },
    }


def validate_event(event):
    expected_keys = {
        "schema_version", "event_id", "event_type", "rack_number", "logical_node_id",
        "assignment_revision", "sequence", "occurred_at", "payload",
    }
    if not isinstance(event, dict) or set(event) != expected_keys:
        raise ValueError("event schema is invalid")
    try:
        uuid.UUID(event["event_id"])
        parse_utc_timestamp(event["occurred_at"])
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("event identity is invalid") from exc
    payload = event["payload"]
    if (
        event["schema_version"] != 1
        or event["event_type"] != "sensor_health"
        or type(event["rack_number"]) is not int
        or not 1 <= event["rack_number"] <= 8
        or not isinstance(event["logical_node_id"], str)
        or NODE_ID_PATTERN.fullmatch(event["logical_node_id"]) is None
        or type(event["assignment_revision"]) is not int
        or event["assignment_revision"] < 1
        or type(event["sequence"]) is not int
        or event["sequence"] < 1
        or not isinstance(payload, dict)
        or set(payload) != {"agent_schema_version", "sensor_state", "sample_age_ms"}
        or type(payload["agent_schema_version"]) is not int
        or not 1 <= payload["agent_schema_version"] <= 32767
        or payload["sensor_state"] not in SENSOR_STATES
        or (
            payload["sample_age_ms"] is not None
            and (
                type(payload["sample_age_ms"]) is not int
                or not 0 <= payload["sample_age_ms"] <= 600_000
            )
        )
    ):
        raise ValueError("event schema is invalid")


def make_envelope(gateway_id, boot_id, queue_state, stats, events):
    state = queue_state if queue_state in QUEUE_STATES else "unhealthy"
    return {
        "schema_version": 1,
        "gateway_id": gateway_id,
        "gateway_boot_id": boot_id,
        "gateway_status": {
            "queue_state": state,
            "queue_depth": stats["depth"],
            "oldest_queued_at": stats["oldest_queued_at"],
            "gateway_version": VERSION,
        },
        "events": events,
    }


def validate_acknowledgement(response, boot_id, events):
    if not isinstance(response, dict) or set(response) != {
        "schema_version", "gateway_boot_id", "results", "acknowledged_through", "server_time",
    }:
        raise UploadRejected("invalid acknowledgement schema")
    acknowledged = response["acknowledged_through"]
    if (
        response["schema_version"] != 1
        or response["gateway_boot_id"] != boot_id
        or type(acknowledged) is not int
        or acknowledged < 0
        or not isinstance(response["results"], list)
        or len(response["results"]) != len(events)
    ):
        raise UploadRejected("invalid acknowledgement")
    try:
        parse_utc_timestamp(response["server_time"])
    except (TypeError, ValueError) as exc:
        raise UploadRejected("invalid acknowledgement") from exc
    expected = {(event["event_id"], event["sequence"]): event for event in events}
    seen = set()
    for item in response["results"]:
        if not isinstance(item, dict) or set(item) != {"event_id", "sequence", "result", "code"}:
            raise UploadRejected("invalid acknowledgement result")
        if type(item["sequence"]) is not int or not isinstance(item["event_id"], str):
            raise UploadRejected("invalid acknowledgement result")
        identity = (item["event_id"], item["sequence"])
        if (
            identity not in expected
            or identity in seen
            or item["result"] not in RESPONSE_RESULTS
            or not isinstance(item["code"], str)
            or RESULT_CODE_PATTERN.fullmatch(item["code"]) is None
        ):
            raise UploadRejected("invalid acknowledgement result")
        if item["sequence"] <= acknowledged and item["result"] not in TERMINAL_RESULTS:
            raise UploadRejected("non-terminal event was acknowledged")
        seen.add(identity)
    if events and acknowledged > events[-1]["sequence"]:
        raise UploadRejected("acknowledgement exceeds batch")
    return acknowledged


def upload(url, credential, envelope, timeout=10.0, opener=open_https_without_redirect):
    encoded = canonical_json(envelope)
    if len(encoded) > MAX_BATCH_BYTES:
        raise UploadRejected("batch exceeds limit")
    upload_request = request.Request(
        url,
        data=encoded,
        method="POST",
        headers={
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
            "X-Request-ID": str(uuid.uuid4()),
        },
    )
    context = ssl.create_default_context()
    with opener(upload_request, timeout=timeout, context=context) as response:
        if response.status != 200:
            raise UploadRejected(f"upload retry {response.status}")
        raw = response.read(MAX_AGENT_RESPONSE_BYTES + 1)
        if len(raw) > MAX_AGENT_RESPONSE_BYTES:
            raise UploadRejected("upload response exceeded limit")
    try:
        return strict_json(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UploadRejected("upload response invalid") from exc


def retry_delay(attempt, random_source=random.random):
    cap = min(MAX_RETRY_SECONDS, MIN_RETRY_SECONDS * (2 ** min(attempt, 16)))
    return random_source() * cap


def retry_after_delay(headers):
    try:
        value = float(headers.get("Retry-After", ""))
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return min(value, MAX_RETRY_AFTER_SECONDS)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default="/run/edgeathlete/ble-agent.sock")
    parser.add_argument("--rack", type=int, required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--url", type=validate_https_url, required=True)
    parser.add_argument("--credential", required=True)
    parser.add_argument("--queue", default="/var/lib/edgeathlete-gateway/queue.sqlite3")
    parser.add_argument("--poll", type=float, default=10.0)
    options = parser.parse_args(argv)
    if not 1 <= options.rack <= 8:
        parser.error("--rack must be between 1 and 8")
    if NODE_ID_PATTERN.fullmatch(options.node) is None:
        parser.error("--node is invalid")
    if options.revision < 1 or options.poll < 1:
        parser.error("--revision and --poll must be positive")
    return options


def run(options):
    credential, gateway_id = load_credential(options.credential)
    queue = DurableQueue(options.queue)
    boot_id = str(uuid.uuid4())
    sequence = 1
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    next_poll = 0.0
    retry_at = 0.0
    retry_attempt = 0
    last_agent_state = None
    while not stopping:
        now = time.monotonic()
        if now >= next_poll:
            try:
                health = read_rack_health(options.socket, options.rack, options.node)
                agent_state = health["state"]
            except AgentUnavailable:
                health = reconnecting_health(options.node)
                agent_state = "reconnecting"
            if agent_state != last_agent_state:
                logging.info("sensor state %s", agent_state)
                last_agent_state = agent_state
            try:
                queue.enqueue(boot_id, make_event(
                    sequence, options.rack, options.node, options.revision, health,
                ))
                sequence += 1
            except QueueFull:
                logging.error("queue full")
            except QueueUnavailable:
                logging.error("queue unhealthy")
            next_poll = now + options.poll

        if now >= retry_at:
            envelope = queue.batch(gateway_id)
            if envelope is not None:
                try:
                    response = upload(options.url, credential, envelope)
                    queue.acknowledge(envelope, response)
                    logging.info("upload acknowledged %d events", len(envelope["events"]))
                    retry_attempt = 0
                    retry_at = now
                except error.HTTPError as exc:
                    logging.warning("upload retry %d", exc.code)
                    server_delay = retry_after_delay(exc.headers) if exc.code in (429, 503) else None
                    retry_at = now + (
                        server_delay if server_delay is not None else retry_delay(retry_attempt)
                    )
                    retry_attempt += 1
                except (error.URLError, TimeoutError, OSError, ssl.SSLError, UploadRejected, QueueUnavailable):
                    logging.warning("upload retry")
                    retry_at = now + retry_delay(retry_attempt)
                    retry_attempt += 1
        time.sleep(min(0.25, max(0.01, min(next_poll, retry_at or next_poll) - time.monotonic())))
    queue.close()


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    options = parse_args(argv)
    run(options)


if __name__ == "__main__":
    main()
