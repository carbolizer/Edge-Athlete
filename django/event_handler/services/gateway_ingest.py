import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from datetime import timedelta, timezone as datetime_timezone

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from event_handler.models import (
    EdgeGateway,
    GatewayBoot,
    GatewayCredential,
    GatewayEventReceipt,
    GatewayNodeGrant,
    GatewayNodeHealth,
    HostedGym,
    MonitoringEvent,
    Node,
)


logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 256 * 1024
MAX_BATCH_EVENTS = 100
MAX_QUEUE_DEPTH = 50_000
MAX_POSITIVE_BIGINT = 2**63 - 1
TIMESTAMP_FUTURE_LIMIT = timedelta(minutes=5)
TIMESTAMP_AGE_LIMIT = timedelta(days=7)
CREDENTIAL_PREFIX = "egw1"
CREDENTIAL_DOMAIN = b"edgeathlete-gateway-v1\0"
TOKEN_PATTERN = re.compile(
    r"^egw1\.([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.([1-9][0-9]{0,9})\.([A-Za-z0-9_-]{43})$"
)
NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,31}$")
UTC_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
OUTER_FIELDS = {"schema_version", "gateway_id", "gateway_boot_id", "gateway_status", "events"}
STATUS_FIELDS = {"queue_state", "queue_depth", "oldest_queued_at", "gateway_version"}
EVENT_FIELDS = {
    "schema_version", "event_id", "event_type", "rack_number", "logical_node_id",
    "assignment_revision", "sequence", "occurred_at", "payload",
}
PAYLOAD_FIELDS = {"agent_schema_version", "sensor_state", "sample_age_ms"}


class InvalidGatewayRequest(Exception):
    def __init__(self, code, detail, status=400):
        self.code = code
        self.detail = detail
        self.status = status


def _is_integer(value, minimum=0, maximum=MAX_POSITIVE_BIGINT):
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def _canonical_uuid(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return None
    return parsed if str(parsed) == value else None


def _utc_timestamp(value):
    if not isinstance(value, str) or UTC_TIMESTAMP_PATTERN.fullmatch(value) is None:
        return None
    parsed = parse_datetime(value)
    if parsed is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(datetime_timezone.utc)


def _without_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def parse_request_body(body):
    if len(body) > MAX_BODY_BYTES:
        raise InvalidGatewayRequest("batch_too_large", "gateway batch exceeds 256 KiB", 413)
    try:
        value = json.loads(
            body.decode("utf-8"), object_pairs_hook=_without_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non-finite number")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise InvalidGatewayRequest("invalid_batch", "request body must be strict JSON")
    return validate_envelope(value)


def validate_envelope(value):
    if not isinstance(value, dict) or set(value) != OUTER_FIELDS:
        raise InvalidGatewayRequest("invalid_batch", "gateway batch has an invalid envelope")
    if value["schema_version"] != 1 or isinstance(value["schema_version"], bool):
        raise InvalidGatewayRequest("invalid_batch", "unsupported batch schema version")
    gateway_id = _canonical_uuid(value["gateway_id"])
    boot_id = _canonical_uuid(value["gateway_boot_id"])
    if gateway_id is None or boot_id is None:
        raise InvalidGatewayRequest("invalid_batch", "gateway and boot IDs must be canonical UUIDs")

    status = value["gateway_status"]
    if not isinstance(status, dict) or set(status) != STATUS_FIELDS:
        raise InvalidGatewayRequest("invalid_batch", "gateway status has an invalid schema")
    if status["queue_state"] not in dict(EdgeGateway.QUEUE_STATE_CHOICES):
        raise InvalidGatewayRequest("invalid_batch", "gateway queue state is invalid")
    if not _is_integer(status["queue_depth"], 0, MAX_QUEUE_DEPTH):
        raise InvalidGatewayRequest("invalid_batch", "gateway queue depth is invalid")
    if not isinstance(status["gateway_version"], str) or VERSION_PATTERN.fullmatch(status["gateway_version"]) is None:
        raise InvalidGatewayRequest("invalid_batch", "gateway version is invalid")
    oldest = status["oldest_queued_at"]
    parsed_oldest = _utc_timestamp(oldest) if oldest is not None else None
    if oldest is not None:
        now = timezone.now()
        if (
            parsed_oldest is None
            or parsed_oldest > now + TIMESTAMP_FUTURE_LIMIT
            or parsed_oldest < now - TIMESTAMP_AGE_LIMIT
        ):
            raise InvalidGatewayRequest("invalid_batch", "oldest queued timestamp is invalid")
    if status["queue_depth"] == 0 and oldest is not None:
        raise InvalidGatewayRequest("invalid_batch", "an empty queue cannot have an oldest timestamp")
    if status["queue_depth"] > 0 and oldest is None:
        raise InvalidGatewayRequest("invalid_batch", "a non-empty queue requires an oldest timestamp")

    events = value["events"]
    if not isinstance(events, list) or len(events) > MAX_BATCH_EVENTS:
        raise InvalidGatewayRequest("invalid_batch", "events must be a list of at most 100 items")
    if not events and status["queue_state"] not in {
        EdgeGateway.QUEUE_UNHEALTHY, EdgeGateway.QUEUE_FULL, EdgeGateway.QUEUE_CORRUPT,
        EdgeGateway.QUEUE_READ_ONLY,
    }:
        raise InvalidGatewayRequest("invalid_batch", "an empty batch requires an unhealthy queue state")

    normalized_events = []
    for event in events:
        if not isinstance(event, dict):
            raise InvalidGatewayRequest("invalid_batch", "every event must be an object")
        event_id = _canonical_uuid(event.get("event_id"))
        sequence = event.get("sequence")
        if event_id is None or not _is_integer(sequence, 1):
            raise InvalidGatewayRequest("invalid_batch", "every event requires an addressable event ID and sequence")
        normalized_events.append((event, event_id, sequence))

    return {
        "gateway_id": gateway_id,
        "boot_id": boot_id,
        "status": {
            **status,
            "oldest_queued_at": parsed_oldest,
        },
        "events": normalized_events,
    }


def gateway_secret_digest(secret):
    return hashlib.sha256(CREDENTIAL_DOMAIN + secret.encode("ascii")).hexdigest()


def issue_gateway_credential(gateway, sponsor, now=None):
    now = now or timezone.now()
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    version = (gateway.credentials.order_by("-version").values_list("version", flat=True).first() or 0) + 1
    credential = GatewayCredential.objects.create(
        gateway=gateway,
        version=version,
        secret_digest=gateway_secret_digest(secret),
        not_before=now,
        created_by=sponsor,
    )
    return credential, f"{CREDENTIAL_PREFIX}.{gateway.id}.{version}.{secret}"


def authenticate_gateway(authorization, request_id=""):
    match = TOKEN_PATTERN.fullmatch(authorization.removeprefix("Bearer ")) if isinstance(authorization, str) and authorization.startswith("Bearer ") else None
    if match is None:
        logger.warning("gateway_auth action=ingest result=gateway_auth_invalid request_id=%s", request_id)
        return None
    gateway_id, version, secret = match.groups()
    credential = GatewayCredential.objects.select_related("gateway").filter(
        gateway_id=gateway_id, version=int(version),
    ).first()
    now = timezone.now()
    valid = bool(
        credential
        and credential.gateway.revoked_at is None
        and credential.revoked_at is None
        and credential.not_before <= now
        and (credential.expires_at is None or credential.expires_at > now)
        and hmac.compare_digest(credential.secret_digest, gateway_secret_digest(secret))
    )
    if not valid:
        logger.warning("gateway_auth action=ingest result=gateway_auth_invalid request_id=%s", request_id)
        return None
    return credential


def _credential_is_valid(credential, gateway, now):
    return bool(
        gateway.revoked_at is None
        and credential.gateway_id == gateway.id
        and credential.revoked_at is None
        and credential.not_before <= now
        and (credential.expires_at is None or credential.expires_at > now)
    )


def _event_rejection(event, now, stale_boot, gateway_identity_matches, gateway, boot):
    if stale_boot:
        return "stale_gateway_boot", now
    if not gateway_identity_matches:
        return "gateway_identity_mismatch", now
    if set(event) != EVENT_FIELDS or event.get("schema_version") != 1 or isinstance(event.get("schema_version"), bool):
        return "invalid_event_schema", now
    if event.get("event_type") != GatewayEventReceipt.EVENT_SENSOR_HEALTH:
        return "invalid_event_schema", now
    rack_number = event.get("rack_number")
    node_id = event.get("logical_node_id")
    revision = event.get("assignment_revision")
    if (
        not _is_integer(rack_number, 1, 10_000)
        or not isinstance(node_id, str)
        or NODE_ID_PATTERN.fullmatch(node_id) is None
        or not _is_integer(revision, 1)
    ):
        return "invalid_event_schema", now
    occurred_at = _utc_timestamp(event.get("occurred_at"))
    if occurred_at is None:
        return "invalid_event_schema", now
    if occurred_at > now + TIMESTAMP_FUTURE_LIMIT:
        return "event_in_future", occurred_at
    if occurred_at < now - TIMESTAMP_AGE_LIMIT:
        return "event_too_old", occurred_at
    payload = event.get("payload")
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_FIELDS:
        return "invalid_event_schema", occurred_at
    if (
        not _is_integer(payload.get("agent_schema_version"), 1, 65_535)
        or payload.get("sensor_state") not in dict(GatewayNodeHealth.SENSOR_STATE_CHOICES)
        or (
            payload.get("sample_age_ms") is not None
            and not _is_integer(payload.get("sample_age_ms"), 0, 600_000)
        )
    ):
        return "invalid_health_value", occurred_at

    node = Node.objects.select_for_update().filter(node_id=node_id).first()
    if node is None or node.rack_number != rack_number:
        return "unknown_node", occurred_at
    grant = GatewayNodeGrant.objects.select_for_update().filter(node=node).first()
    if grant is None or grant.gateway_id != gateway.id or grant.revoked_at is not None:
        return "gateway_node_not_granted", occurred_at
    if grant.assignment_revision != node.assignment_revision or revision != node.assignment_revision:
        return "stale_assignment_revision", occurred_at

    health = GatewayNodeHealth.objects.select_for_update().filter(grant=grant).first()
    materially_changed = health is None or (
        health.sensor_state != payload["sensor_state"]
        or health.agent_schema_version != payload["agent_schema_version"]
    )
    if health is None:
        health = GatewayNodeHealth(grant=grant)
    health.sensor_state = payload["sensor_state"]
    health.sample_age_ms = payload["sample_age_ms"]
    health.agent_schema_version = payload["agent_schema_version"]
    health.gateway_occurred_at = occurred_at
    health.server_received_at = now
    health.boot = boot
    health.sequence = event["sequence"]
    health.save()
    return None, occurred_at, materially_changed


@transaction.atomic
def ingest_batch(credential, envelope):
    now = timezone.now()
    gateway = EdgeGateway.objects.select_for_update().filter(pk=credential.gateway_id).first()
    credential = GatewayCredential.objects.select_for_update().filter(pk=credential.pk).first()
    if gateway is None or credential is None or not _credential_is_valid(credential, gateway, now):
        raise InvalidGatewayRequest("gateway_auth_invalid", "gateway authentication failed", 401)
    if HostedGym.objects.count() != 1:
        raise InvalidGatewayRequest("gateway_ingest_unavailable", "gateway ingestion is unavailable", 503)

    status = envelope["status"]
    material_change = gateway.queue_state != status["queue_state"]
    credential.last_used_at = now
    credential.save(update_fields=["last_used_at"])

    if not envelope["events"]:
        gateway.last_contact_at = now
        gateway.queue_state = status["queue_state"]
        gateway.queue_depth = status["queue_depth"]
        gateway.oldest_queued_at = status["oldest_queued_at"]
        gateway.save(update_fields=[
            "last_contact_at", "queue_state", "queue_depth", "oldest_queued_at", "updated_at",
        ])
        if material_change:
            MonitoringEvent.objects.create(reason="gateway_health_changed")
        return [], 0

    ordered = sorted(enumerate(envelope["events"]), key=lambda item: item[1][2])
    first_sequence = ordered[0][1][2]
    boot = GatewayBoot.objects.select_for_update().filter(
        gateway=gateway, boot_id=envelope["boot_id"],
    ).first()
    if boot is None:
        if first_sequence != 1:
            raise InvalidGatewayRequest(
                "gateway_boot_conflict", "a new gateway boot must begin at sequence 1", 409,
            )
        epoch = 1
        if gateway.current_boot_id:
            current = GatewayBoot.objects.select_for_update().get(pk=gateway.current_boot_id)
            current.superseded_at = now
            current.save(update_fields=["superseded_at"])
            epoch = current.server_epoch + 1
        boot = GatewayBoot.objects.create(
            gateway=gateway, boot_id=envelope["boot_id"], server_epoch=epoch,
        )
        gateway.current_boot = boot
    stale_boot = gateway.current_boot_id != boot.id
    gateway_identity_matches = envelope["gateway_id"] == gateway.id
    expected = boot.acknowledged_through + 1
    gap_seen = False
    results = [None] * len(envelope["events"])

    for original_index, (event, event_id, sequence) in ordered:
        if gap_seen:
            results[original_index] = {
                "event_id": str(event_id), "sequence": sequence,
                "result": "retry", "code": "blocked_by_sequence_gap",
            }
            continue
        by_event = GatewayEventReceipt.objects.filter(gateway=gateway, event_id=event_id).first()
        by_sequence = GatewayEventReceipt.objects.filter(boot=boot, sequence=sequence).first()
        if by_event is not None or by_sequence is not None:
            if by_event is not None and by_sequence is not None and by_event.pk == by_sequence.pk:
                results[original_index] = {
                    "event_id": str(event_id), "sequence": sequence,
                    "result": "duplicate", "code": by_event.result_code,
                }
                if sequence == expected:
                    expected += 1
                continue
            results[original_index] = {
                "event_id": str(event_id), "sequence": sequence,
                "result": "rejected", "code": "event_identity_conflict",
            }
            if sequence == expected:
                expected += 1
            continue
        if sequence != expected:
            results[original_index] = {
                "event_id": str(event_id), "sequence": sequence,
                "result": "retry", "code": "sequence_gap",
            }
            gap_seen = True
            continue

        outcome = _event_rejection(
            event, now, stale_boot, gateway_identity_matches, gateway, boot,
        )
        rejection_code, occurred_at = outcome[0], outcome[1]
        accepted = rejection_code is None
        if accepted:
            material_change = material_change or outcome[2]
            code = "health_recorded"
            if gateway.last_event_at is None or occurred_at > gateway.last_event_at:
                gateway.last_event_at = occurred_at
        else:
            code = rejection_code
        GatewayEventReceipt.objects.create(
            gateway=gateway,
            boot=boot,
            event_id=event_id,
            sequence=sequence,
            event_type=GatewayEventReceipt.EVENT_SENSOR_HEALTH,
            result=(GatewayEventReceipt.RESULT_ACCEPTED if accepted else GatewayEventReceipt.RESULT_REJECTED),
            result_code=code,
            occurred_at=occurred_at,
        )
        results[original_index] = {
            "event_id": str(event_id), "sequence": sequence,
            "result": "accepted" if accepted else "rejected", "code": code,
        }
        expected += 1

    boot.acknowledged_through = expected - 1
    boot.last_received_at = now
    boot.save(update_fields=["acknowledged_through", "last_received_at"])
    gateway.last_contact_at = now
    gateway.queue_state = status["queue_state"]
    gateway.queue_depth = status["queue_depth"]
    gateway.oldest_queued_at = status["oldest_queued_at"]
    gateway.save(update_fields=[
        "current_boot", "last_contact_at", "last_event_at", "queue_state", "queue_depth",
        "oldest_queued_at", "updated_at",
    ])
    if material_change:
        MonitoringEvent.objects.create(reason="gateway_health_changed")
    return results, boot.acknowledged_through


def diagnostics_snapshot(now=None):
    now = now or timezone.now()
    gateway = EdgeGateway.objects.select_related("current_boot").order_by(
        F("revoked_at").asc(nulls_first=True), "-created_at",
    ).first()
    if gateway is None:
        return {"schema_version": 1, "gateway": None, "sensors": [], "server_time": now.isoformat()}

    active_credentials = gateway.credentials.filter(
        revoked_at=None, not_before__lte=now,
    ).filter(Q(expires_at=None) | Q(expires_at__gt=now))
    credential_active = active_credentials.exists()
    if gateway.revoked_at is not None or not credential_active:
        state = "revoked"
    elif gateway.last_contact_at and gateway.last_contact_at >= now - timedelta(seconds=30):
        state = "online"
    else:
        state = "stale"
    rotation_cutoff = now + timedelta(hours=24)
    rotation_required = not active_credentials.filter(
        Q(expires_at=None) | Q(expires_at__gt=rotation_cutoff),
    ).exists()
    oldest_age = None
    if gateway.oldest_queued_at is not None:
        oldest_age = max(0, int((now - gateway.oldest_queued_at).total_seconds()))

    sensors = []
    grants = GatewayNodeGrant.objects.filter(
        gateway=gateway, revoked_at=None,
    ).select_related("node", "health", "health__boot")
    for grant in grants.order_by("node__rack_number"):
        if (
            grant.node.rack_number is None
            or grant.assignment_revision != grant.node.assignment_revision
        ):
            continue
        try:
            health = grant.health
        except GatewayNodeHealth.DoesNotExist:
            sensor_state = "stale"
            received_at = None
        else:
            live = bool(
                health.sensor_state == GatewayNodeHealth.SENSOR_LIVE
                and health.sample_age_ms is not None
                and health.sample_age_ms <= 1000
                and health.server_received_at >= now - timedelta(seconds=15)
                and health.boot_id == gateway.current_boot_id
            )
            sensor_state = "live" if live else (
                "stale" if health.sensor_state == GatewayNodeHealth.SENSOR_LIVE else health.sensor_state
            )
            received_at = health.server_received_at.isoformat()
        sensors.append({
            "rack_number": grant.node.rack_number,
            "state": sensor_state,
            "last_received_at": received_at,
        })

    return {
        "schema_version": 1,
        "gateway": {
            "label": gateway.label,
            "state": state,
            "last_contact_at": gateway.last_contact_at.isoformat() if gateway.last_contact_at else None,
            "last_accepted_epoch": gateway.current_boot.server_epoch if gateway.current_boot else None,
            "last_accepted_sequence": gateway.current_boot.acknowledged_through if gateway.current_boot else 0,
            "queue_state": gateway.queue_state,
            "queue_depth": gateway.queue_depth,
            "oldest_queue_age_seconds": oldest_age,
            "rotation_required": rotation_required,
        },
        "sensors": sensors,
        "server_time": now.isoformat(),
    }
