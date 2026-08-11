"""Hosted Rack identity, pairing, status, launch, and retention services.

All authority is derived from a browser or helper credential. This module has no
dependency on physical sensors or training-write models.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone
from urllib.parse import urlsplit

from django.conf import settings
from django.db import IntegrityError, connection, models, transaction
from django.utils import timezone

from event_handler.models import (
    ApiThrottleBucket,
    BrowserEndpoint,
    EndpointCredential,
    EndpointPairing,
    OrganizationMembership,
    RackHelperCredential,
    RackHelperInstallation,
    RackHelperLaunchConsumeReceipt,
    RackHelperLaunchIntent,
    RackHelperPairing,
    TrainingGroup,
    TrainingGroupCoach,
)


PAIRING_LIFETIME = timedelta(minutes=5)
HELPER_INACTIVITY_LIMIT = timedelta(hours=24)
TERMINAL_RETENTION = timedelta(hours=24)
BACKLOG_GATE_AGE = timedelta(hours=23, minutes=55)
MAX_CONSUME_RECEIPTS_PER_INSTALLATION = 10_000
STATUS_STALE_AFTER = timedelta(seconds=60)
ENDPOINT_COOKIE_AGE = 365 * 24 * 60 * 60
PAIRING_COOKIE_AGE = 5 * 60
TOKEN_BYTES = 32
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PHRASE_PREFIXES = (
    "amber", "autumn", "blue", "bold", "bright", "calm", "cedar", "clear",
    "cloud", "coral", "crisp", "dawn", "deep", "eager", "fair", "fern",
    "gold", "green", "happy", "iron", "ivory", "jade", "keen", "light",
    "lunar", "maple", "navy", "quiet", "rapid", "silver", "steady", "swift",
)
PHRASE_SUFFIXES = (
    "anchor", "apple", "arrow", "badger", "beacon", "birch", "bison", "brook",
    "canyon", "cedar", "cliff", "cloud", "comet", "coral", "crane", "creek",
    "dawn", "eagle", "ember", "falcon", "field", "finch", "forest", "fox",
    "garden", "grove", "harbor", "hawk", "heron", "hill", "island", "lake",
    "lantern", "lark", "leaf", "maple", "meadow", "mesa", "moon", "oak",
    "ocean", "orbit", "otter", "peak", "pine", "planet", "pond", "quartz",
    "raven", "reef", "ridge", "river", "robin", "rock", "sparrow", "star",
    "stone", "storm", "sun", "trail", "valley", "willow", "wind", "wolf",
)
HELPER_POSTABLE_STATUSES = {
    "no_sensor", "scanning", "verifying", "ready", "active_online", "active_offline",
    "stopping", "draining", "credential_revoked", "authentication_blocked",
    "sensor_reconnecting", "queue_full", "queue_corrupt", "keychain_unavailable",
    "update_required", "queue_unsafe", "queue_read_only", "queue_write_failed",
    "endpoint_reassigned", "recovery_required",
}


class ControlPlaneError(Exception):
    def __init__(self, code, detail, status, retry_after=None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status
        self.retry_after = retry_after


def _secret_key():
    value = getattr(settings, "RACK_CONTROL_PLANE_KEY", settings.SECRET_KEY)
    return value.encode("utf-8")


def _hmac_digest(domain, value):
    return hmac.new(_secret_key(), domain + b"\0" + value, hashlib.sha256).hexdigest()


def _credential_digest(domain, secret):
    return hashlib.sha256(domain + b"\0" + secret).hexdigest()


def canonical_secret(value):
    if not isinstance(value, str) or len(value) != 43 or not value.isascii():
        return None
    try:
        decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        return None
    if len(decoded) != TOKEN_BYTES:
        return None
    if base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        return None
    return decoded


def encode_secret(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def parse_credential(value, prefix):
    if not isinstance(value, str) or len(value) > 100 or not value.isascii():
        return None
    parts = value.split(".")
    if len(parts) != 3 or parts[0] != prefix:
        return None
    try:
        credential_id = uuid.UUID(parts[1])
    except (ValueError, AttributeError):
        return None
    if str(credential_id) != parts[1]:
        return None
    secret = canonical_secret(parts[2])
    return (credential_id, secret) if secret is not None else None


def validate_origin(request):
    value = request.META.get("HTTP_ORIGIN")
    expected = getattr(settings, "RACK_PUBLIC_ORIGIN", "")
    if not value or "," in value or value != expected:
        return False
    try:
        parsed = urlsplit(value)
        expected_parsed = urlsplit(expected)
        port = parsed.port or (443 if parsed.scheme == "https" else None)
        expected_port = expected_parsed.port or 443
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and parsed.hostname
        and parsed.hostname.isascii()
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
        and parsed.hostname == expected_parsed.hostname
        and port == expected_port
    )


def validate_csrf(request):
    cookie = request.COOKIES.get("ea_rack_csrf")
    header = request.headers.get("X-CSRFToken")
    return bool(
        cookie and header and len(cookie) <= 128 and len(header) <= 128
        and canonical_secret(cookie) is not None
        and hmac.compare_digest(cookie, header)
    )


def require_endpoint_mutation(request):
    if not validate_origin(request) or not validate_csrf(request):
        raise ControlPlaneError("csrf_failed", "Request verification failed.", 403)


def require_coach_origin(request):
    if not validate_origin(request):
        raise ControlPlaneError("csrf_failed", "Request verification failed.", 403)


def require_exact_object(data, keys):
    if not isinstance(data, dict) or set(data) != set(keys):
        raise ControlPlaneError("invalid_request", "The request body is invalid.", 400)
    return data


def parse_uuid(value):
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None
    return parsed if str(parsed) == str(value) else None


def _now_floor(now, seconds):
    timestamp = int(now.timestamp())
    return datetime.fromtimestamp(timestamp - timestamp % seconds, tz=datetime_timezone.utc)


def throttle(scope, key, limit, seconds, now=None):
    now = now or timezone.now()
    window_start = _now_floor(now, seconds)
    digest = _hmac_digest(b"edgeathlete-throttle-v1", f"{scope}\0{key}".encode("utf-8"))
    expires_at = window_start + timedelta(seconds=seconds) + TERMINAL_RETENTION
    with transaction.atomic():
        table = connection.ops.quote_name(ApiThrottleBucket._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(
                f"""INSERT INTO {table}
                    (scope, key_digest, window_start, count, expires_at)
                    VALUES (%s, %s, %s, 1, %s)
                    ON CONFLICT (scope, key_digest, window_start)
                    DO UPDATE SET count = {table}.count + 1, expires_at = EXCLUDED.expires_at
                    RETURNING count""",
                [scope, digest, window_start, expires_at],
            )
            count = cursor.fetchone()[0]
    if count > limit:
        retry = max(1, int((window_start + timedelta(seconds=seconds) - now).total_seconds()) + 1)
        raise ControlPlaneError("rate_limited", "Too many requests.", 429, retry)


def apply_limits(limits, now=None):
    for scope, key, limit, seconds in limits:
        throttle(scope, key, limit, seconds, now)


def source_key(request):
    if settings.VPS_DEPLOYMENT:
        return request.META.get("HTTP_X_EDGE_CLIENT_ADDRESS") or "unknown"
    return request.META.get("REMOTE_ADDR") or "unknown"


def ensure_cleanup_capacity(now=None):
    now = now or timezone.now()
    cutoff = now - BACKLOG_GATE_AGE
    backlog = (
        EndpointPairing.objects.filter(terminal_at__lte=cutoff).exists()
        or RackHelperPairing.objects.filter(terminal_at__lte=cutoff).exists()
        or RackHelperLaunchIntent.objects.filter(terminal_at__lte=cutoff).exists()
        or RackHelperInstallation.objects.filter(terminal_at__lte=cutoff).exists()
        or ApiThrottleBucket.objects.filter(expires_at__lte=now - BACKLOG_GATE_AGE).exists()
    )
    if backlog:
        raise ControlPlaneError("service_unavailable", "The service is temporarily unavailable.", 503)


def random_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))


def code_digest(code, helper=False):
    domain = b"edgeathlete-helper-pairing-code-v1" if helper else b"edgeathlete-endpoint-pairing-code-v1"
    return _hmac_digest(domain, code.encode("ascii"))


def endpoint_summary(endpoint):
    return {
        "id": str(endpoint.id),
        "kind": endpoint.kind,
        "display_name": endpoint.display_name,
        "training_group": {
            "id": endpoint.training_group_id,
            "name": endpoint.training_group.name,
        },
        "endpoint_revision": endpoint.endpoint_revision,
    }


def authenticate_endpoint(raw_token, *, touch=False):
    parsed = parse_credential(raw_token, "eae1")
    if parsed is None:
        return None
    credential_id, secret = parsed
    try:
        credential = EndpointCredential.objects.select_related(
            "endpoint__training_group", "endpoint__organization",
        ).get(pk=credential_id, state=EndpointCredential.STATE_ACTIVE)
    except EndpointCredential.DoesNotExist:
        return None
    expected = _credential_digest(b"edgeathlete-endpoint-credential-v1", secret)
    if not hmac.compare_digest(credential.secret_digest, expected):
        return None
    if credential.endpoint.state != BrowserEndpoint.STATE_ACTIVE or credential.endpoint.training_group_id is None:
        return None
    if credential.endpoint.training_group.organization_id != credential.endpoint.organization_id:
        return None
    if touch:
        now = timezone.now()
        EndpointCredential.objects.filter(pk=credential.pk).update(last_used_at=now)
        BrowserEndpoint.objects.filter(pk=credential.endpoint_id).update(last_seen_at=now)
    return credential


def helper_authorization_token(request):
    value = request.headers.get("Authorization")
    if not value or not value.startswith("RackHelper ") or value.count(" ") != 1:
        return None
    return value[len("RackHelper "):]


def authenticate_helper(raw_token, *, allow_pending=False, touch=False, now=None):
    parsed = parse_credential(raw_token, "earh1")
    if parsed is None:
        return None
    credential_id, secret = parsed
    states = [RackHelperCredential.STATE_ACTIVE]
    if allow_pending:
        states.append(RackHelperCredential.STATE_PENDING)
    try:
        credential = RackHelperCredential.objects.select_related(
            "installation__endpoint__training_group", "installation__endpoint__organization",
            "installation__pairing",
        ).get(pk=credential_id, state__in=states)
    except RackHelperCredential.DoesNotExist:
        return None
    expected = _credential_digest(b"edgeathlete-helper-credential-v1", secret)
    if not hmac.compare_digest(credential.secret_digest, expected):
        return None
    installation = credential.installation
    endpoint = installation.endpoint
    now = now or timezone.now()
    if credential.state == RackHelperCredential.STATE_ACTIVE:
        if (
            installation.state != RackHelperInstallation.STATE_ACTIVE
            or endpoint.state != BrowserEndpoint.STATE_ACTIVE
            or endpoint.training_group_id is None
            or endpoint.training_group.organization_id != endpoint.organization_id
            or not installation.last_contact_at
            or installation.last_contact_at + HELPER_INACTIVITY_LIMIT <= now
        ):
            return None
    if touch:
        RackHelperCredential.objects.filter(pk=credential.pk).update(last_used_at=now)
        RackHelperInstallation.objects.filter(pk=installation.pk).update(last_contact_at=now)
    return credential


def _expire_endpoint_pairing(pairing, now):
    if pairing.state in [EndpointPairing.STATE_PENDING, EndpointPairing.STATE_CLAIMED] and pairing.expires_at <= now:
        pairing.state = EndpointPairing.STATE_EXPIRED
        pairing.code_digest = None
        pairing.bootstrap_digest = None
        pairing.terminal_at = now
        pairing.save(update_fields=["state", "code_digest", "bootstrap_digest", "terminal_at"])
        return True
    return False


def create_endpoint_pairing():
    now = timezone.now()
    ensure_cleanup_capacity(now)
    bootstrap = secrets.token_bytes(TOKEN_BYTES)
    for _attempt in range(5):
        code = random_code()
        try:
            pairing = EndpointPairing.objects.create(
                code_digest=code_digest(code),
                bootstrap_digest=_hmac_digest(b"edgeathlete-endpoint-bootstrap-v1", bootstrap),
                created_at=now, expires_at=now + PAIRING_LIFETIME,
            )
            return pairing, code, encode_secret(bootstrap)
        except IntegrityError:
            continue
    raise ControlPlaneError("pairing_unavailable", "Pairing is unavailable.", 503)


def coach_can_manage_group(user, organization, group):
    if OrganizationMembership.objects.filter(
        user=user, organization=organization, is_active=True, role=OrganizationMembership.OWNER,
    ).exists():
        return True
    return TrainingGroupCoach.objects.filter(training_group=group, coach=user).exists()


def manageable_training_groups(user, organization):
    # OrganizationMembership currently has one accepted role: owner. The
    # permission layer has already resolved exactly one active membership.
    return TrainingGroup.objects.filter(organization=organization).order_by(
        "name", "id",
    ).values("id", "name")


@transaction.atomic
def claim_endpoint_pairing(user, organization, pairing_code, group_id, display_name):
    now = timezone.now()
    if not isinstance(pairing_code, str) or len(pairing_code) != 8 or any(c not in CODE_ALPHABET for c in pairing_code):
        raise ControlPlaneError("not_found", "Not found.", 404)
    if not isinstance(display_name, str) or not (1 <= len(display_name.strip()) <= 80):
        raise ControlPlaneError("invalid_request", "The request body is invalid.", 400)
    try:
        group = TrainingGroup.objects.get(pk=group_id, organization=organization)
    except (TrainingGroup.DoesNotExist, ValueError, TypeError):
        raise ControlPlaneError("not_found", "Not found.", 404)
    if not coach_can_manage_group(user, organization, group):
        raise ControlPlaneError("not_found", "Not found.", 404)
    try:
        pairing = EndpointPairing.objects.select_for_update().get(code_digest=code_digest(pairing_code))
    except EndpointPairing.DoesNotExist:
        raise ControlPlaneError("not_found", "Not found.", 404)
    if _expire_endpoint_pairing(pairing, now) or pairing.state != EndpointPairing.STATE_PENDING:
        raise ControlPlaneError("not_found", "Not found.", 404)
    endpoint = BrowserEndpoint.objects.create(
        organization=organization, training_group=group, display_name=display_name.strip(),
    )
    pairing.endpoint = endpoint
    pairing.state = EndpointPairing.STATE_CLAIMED
    pairing.claimed_at = now
    pairing.code_digest = None
    pairing.save(update_fields=["endpoint", "state", "claimed_at", "code_digest"])
    return endpoint


def _derive_endpoint_secret(pairing, bootstrap):
    material = pairing.id.bytes + pairing.credential_id.bytes + bootstrap
    return hmac.new(_secret_key(), b"edgeathlete-endpoint-delivery-v1\0" + material, hashlib.sha256).digest()


@transaction.atomic
def endpoint_pairing_status(bootstrap_token):
    bootstrap = canonical_secret(bootstrap_token)
    if bootstrap is None:
        raise ControlPlaneError("endpoint_authentication_failed", "Endpoint authentication failed.", 401)
    digest = _hmac_digest(b"edgeathlete-endpoint-bootstrap-v1", bootstrap)
    try:
        pairing = EndpointPairing.objects.select_for_update().get(bootstrap_digest=digest)
    except EndpointPairing.DoesNotExist:
        raise ControlPlaneError("endpoint_authentication_failed", "Endpoint authentication failed.", 401)
    now = timezone.now()
    if _expire_endpoint_pairing(pairing, now):
        raise ControlPlaneError("pairing_expired", "The pairing session expired.", 410)
    if pairing.state == EndpointPairing.STATE_PENDING:
        return pairing, None
    if pairing.state not in [EndpointPairing.STATE_CLAIMED, EndpointPairing.STATE_DELIVERED]:
        raise ControlPlaneError("pairing_expired", "The pairing session expired.", 410)
    secret = _derive_endpoint_secret(pairing, bootstrap)
    credential, _created = EndpointCredential.objects.get_or_create(
        pk=pairing.credential_id,
        defaults={
            "endpoint": pairing.endpoint,
            "secret_digest": _credential_digest(b"edgeathlete-endpoint-credential-v1", secret),
        },
    )
    if credential.endpoint_id != pairing.endpoint_id:
        raise ControlPlaneError("endpoint_authentication_failed", "Endpoint authentication failed.", 401)
    if pairing.state == EndpointPairing.STATE_CLAIMED:
        pairing.state = EndpointPairing.STATE_DELIVERED
        pairing.delivered_at = now
        pairing.terminal_at = now
        pairing.save(update_fields=["state", "delivered_at", "terminal_at"])
    token = f"eae1.{credential.id}.{encode_secret(secret)}"
    return pairing, token


def helper_snapshot(endpoint, now=None):
    now = now or timezone.now()
    installation = endpoint.helper_installations.filter(
        state=RackHelperInstallation.STATE_ACTIVE,
    ).order_by("created_at").first()
    if installation is None:
        return {
            "installation_id": None, "status": "pairing_required", "status_at": None,
            "status_cursor": endpoint.helper_status_cursor, "freshness": "not_applicable",
            "stale_at": None, "heartbeat_interval_seconds": 15, "stale_after_seconds": 60,
        }
    status = endpoint.helper_status
    status_at = endpoint.helper_status_at
    stale_at = status_at + STATUS_STALE_AFTER if status_at and status not in ["released"] else None
    stale = bool(stale_at and now >= stale_at)
    return {
        "installation_id": str(installation.id),
        "status": "stale" if stale else status,
        "status_at": status_at.isoformat() if status_at else None,
        "status_cursor": endpoint.helper_status_cursor,
        "freshness": "stale" if stale else ("not_applicable" if status == "released" else "fresh"),
        "stale_at": stale_at.isoformat() if stale_at else None,
        "heartbeat_interval_seconds": 15,
        "stale_after_seconds": 60,
    }


@transaction.atomic
def create_helper_pairing(endpoint_id):
    endpoint = BrowserEndpoint.objects.select_for_update().get(pk=endpoint_id)
    now = timezone.now()
    ensure_cleanup_capacity(now)
    for pairing in endpoint.helper_pairings.select_for_update().filter(
        state__in=[RackHelperPairing.STATE_PENDING, RackHelperPairing.STATE_CLAIMED, RackHelperPairing.STATE_CONFIRMED],
    ):
        if pairing.expires_at <= now:
            expire_helper_pairing_locked(pairing, now)
        else:
            raise ControlPlaneError("helper_pairing_pending", "Helper pairing is already pending.", 409)
    if endpoint.helper_installations.filter(state=RackHelperInstallation.STATE_ACTIVE).exists():
        raise ControlPlaneError("helper_already_paired", "A Rack Helper is already paired.", 409)
    for _attempt in range(5):
        code = random_code()
        try:
            pairing = RackHelperPairing.objects.create(
                endpoint=endpoint, code_digest=code_digest(code, helper=True),
                server_nonce=secrets.token_bytes(32), created_at=now,
                expires_at=now + PAIRING_LIFETIME,
            )
            return pairing, code
        except IntegrityError:
            continue
    raise ControlPlaneError("pairing_unavailable", "Pairing is unavailable.", 503)


def confirmation_phrase(pairing):
    material = b"".join([
        pairing.id.bytes, pairing.endpoint_id.bytes, pairing.proposed_credential_id.bytes,
        bytes.fromhex(pairing.proposed_credential_digest), bytes.fromhex(pairing.bootstrap_digest),
        bytes(pairing.server_nonce),
    ])
    bits = int.from_bytes(hashlib.sha256(b"edgeathlete-confirmation-phrase-v1\0" + material).digest()[:9], "big") >> 6
    words = []
    for shift in (55, 44, 33, 22, 11, 0):
        index = (bits >> shift) & 0x7ff
        words.append(PHRASE_PREFIXES[index >> 6] + PHRASE_SUFFIXES[index & 0x3f])
    return words


@transaction.atomic
def claim_helper_pairing(data):
    now = timezone.now()
    code = data["pairing_code"]
    bootstrap = canonical_secret(data["bootstrap_token"])
    parsed_credential = parse_credential(data["credential"], "earh1")
    if (
        not isinstance(code, str) or len(code) != 8 or any(c not in CODE_ALPHABET for c in code)
        or bootstrap is None or parsed_credential is None
        or data["platform"] not in ["linux_x64", "windows_x64"]
        or data["contract_version"] != 1
    ):
        raise ControlPlaneError("not_found", "Not found.", 404)
    try:
        pairing = RackHelperPairing.objects.select_related("endpoint").get(code_digest=code_digest(code, helper=True))
        endpoint = BrowserEndpoint.objects.select_for_update().get(pk=pairing.endpoint_id)
        pairing = RackHelperPairing.objects.select_for_update().get(pk=pairing.pk)
    except RackHelperPairing.DoesNotExist:
        raise ControlPlaneError("not_found", "Not found.", 404)
    if pairing.expires_at <= now:
        expire_helper_pairing_locked(pairing, now)
        raise ControlPlaneError("not_found", "Not found.", 404)
    credential_id, credential_secret = parsed_credential
    bootstrap_digest = _hmac_digest(b"edgeathlete-helper-bootstrap-v1", bootstrap)
    credential_digest = _credential_digest(b"edgeathlete-helper-credential-v1", credential_secret)
    if pairing.state == RackHelperPairing.STATE_CLAIMED:
        same = (
            pairing.bootstrap_digest == bootstrap_digest
            and pairing.proposed_credential_id == credential_id
            and pairing.proposed_credential_digest == credential_digest
            and pairing.platform == data["platform"]
            and pairing.contract_version == data["contract_version"]
        )
        if same:
            return pairing
        raise ControlPlaneError("not_found", "Not found.", 404)
    if pairing.state != RackHelperPairing.STATE_PENDING:
        raise ControlPlaneError("not_found", "Not found.", 404)
    phrase = _confirmation_phrase_values(pairing, credential_id, credential_digest, bootstrap_digest)
    pairing.bootstrap_digest = bootstrap_digest
    pairing.proposed_credential_id = credential_id
    pairing.proposed_credential_digest = credential_digest
    pairing.platform = data["platform"]
    pairing.contract_version = data["contract_version"]
    pairing.confirmation_phrase_digest = _hmac_digest(
        b"edgeathlete-confirmation-phrase-digest-v1", "\0".join(phrase).encode("ascii"),
    )
    pairing.state = RackHelperPairing.STATE_CLAIMED
    pairing.claimed_at = now
    pairing.save()
    return pairing


def helper_claim_scope(code):
    if not isinstance(code, str) or len(code) != 8 or any(c not in CODE_ALPHABET for c in code):
        return None
    pairing = RackHelperPairing.objects.filter(
        code_digest=code_digest(code, helper=True),
    ).values_list("pk", "endpoint_id", "endpoint__organization_id").first()
    return tuple(str(value) for value in pairing) if pairing else None


def helper_confirm_scope(user, organization, code):
    if not isinstance(code, str) or len(code) != 8 or any(c not in CODE_ALPHABET for c in code):
        return None
    pairing = RackHelperPairing.objects.select_related("endpoint__training_group").filter(
        code_digest=code_digest(code, helper=True),
    ).first()
    if pairing is None:
        return None
    endpoint = pairing.endpoint
    group = endpoint.training_group
    if (
        endpoint.organization_id != organization.id or group is None
        or group.organization_id != organization.id
        or not coach_can_manage_group(user, organization, group)
    ):
        return None
    return str(pairing.pk), str(endpoint.pk)


def _confirmation_phrase_values(pairing, credential_id, credential_digest, bootstrap_digest):
    pairing.proposed_credential_id = credential_id
    pairing.proposed_credential_digest = credential_digest
    pairing.bootstrap_digest = bootstrap_digest
    return confirmation_phrase(pairing)


def expire_helper_pairing_locked(pairing, now):
    if pairing.state not in [RackHelperPairing.STATE_PENDING, RackHelperPairing.STATE_CLAIMED, RackHelperPairing.STATE_CONFIRMED]:
        return False
    pairing.state = RackHelperPairing.STATE_EXPIRED
    pairing.code_digest = None
    pairing.bootstrap_digest = None
    pairing.proposed_credential_digest = None
    pairing.confirmation_phrase_digest = ""
    pairing.server_nonce = None
    pairing.terminal_at = now
    pairing.save(update_fields=[
        "state", "code_digest", "bootstrap_digest", "proposed_credential_digest",
        "confirmation_phrase_digest", "server_nonce", "terminal_at",
    ])
    installation = RackHelperInstallation.objects.select_for_update().filter(
        pairing=pairing, state=RackHelperInstallation.STATE_PENDING,
    ).first()
    if installation:
        installation.state = RackHelperInstallation.STATE_EXPIRED
        installation.pairing = None
        installation.terminal_at = now
        installation.save(update_fields=["state", "pairing", "terminal_at"])
        RackHelperCredential.objects.filter(
            installation=installation, state=RackHelperCredential.STATE_PENDING,
        ).update(state=RackHelperCredential.STATE_REVOKED, secret_digest=None, revoked_at=now)
    return True


@transaction.atomic
def confirm_helper_pairing(user, organization, pairing_id):
    try:
        candidate = RackHelperPairing.objects.select_related("endpoint__training_group").get(pk=pairing_id)
        endpoint = BrowserEndpoint.objects.select_for_update().get(pk=candidate.endpoint_id)
        pairing = RackHelperPairing.objects.select_for_update().get(pk=pairing_id)
    except RackHelperPairing.DoesNotExist:
        raise ControlPlaneError("not_found", "Not found.", 404)
    now = timezone.now()
    group = endpoint.training_group
    if (
        endpoint.organization_id != organization.id or group is None
        or group.organization_id != organization.id
        or not coach_can_manage_group(user, organization, group)
    ):
        raise ControlPlaneError("not_found", "Not found.", 404)
    if pairing.expires_at <= now:
        expire_helper_pairing_locked(pairing, now)
        raise ControlPlaneError("not_found", "Not found.", 404)
    if pairing.state == RackHelperPairing.STATE_CONFIRMED:
        return pairing, pairing.installation
    if pairing.state != RackHelperPairing.STATE_CLAIMED:
        raise ControlPlaneError("not_found", "Not found.", 404)
    installation = RackHelperInstallation.objects.create(
        endpoint=endpoint, pairing=pairing, platform=pairing.platform,
        contract_version=pairing.contract_version, activation_expires_at=pairing.expires_at,
    )
    RackHelperCredential.objects.create(
        id=pairing.proposed_credential_id, installation=installation,
        secret_digest=pairing.proposed_credential_digest,
    )
    pairing.state = RackHelperPairing.STATE_CONFIRMED
    pairing.confirmed_at = now
    pairing.save(update_fields=["state", "confirmed_at"])
    return pairing, installation


def helper_pairing_status(pairing_id, bootstrap_token):
    pairing_uuid = parse_uuid(pairing_id)
    bootstrap = canonical_secret(bootstrap_token)
    if pairing_uuid is None or bootstrap is None:
        raise ControlPlaneError("not_found", "Not found.", 404)
    digest = _hmac_digest(b"edgeathlete-helper-bootstrap-v1", bootstrap)
    try:
        pairing = RackHelperPairing.objects.get(pk=pairing_uuid, bootstrap_digest=digest)
    except RackHelperPairing.DoesNotExist:
        raise ControlPlaneError("not_found", "Not found.", 404)
    if pairing.expires_at <= timezone.now() or pairing.state not in [
        RackHelperPairing.STATE_CLAIMED, RackHelperPairing.STATE_CONFIRMED, RackHelperPairing.STATE_ACTIVATED,
    ]:
        raise ControlPlaneError("not_found", "Not found.", 404)
    return pairing


@transaction.atomic
def activate_helper(credential, pairing_id, activation_request_id):
    installation_id = credential.installation_id
    endpoint_id = credential.installation.endpoint_id
    endpoint = BrowserEndpoint.objects.select_for_update().get(pk=endpoint_id)
    pairing = RackHelperPairing.objects.select_for_update().filter(pk=pairing_id, endpoint=endpoint).first()
    installation = RackHelperInstallation.objects.select_for_update().get(pk=installation_id)
    now = timezone.now()
    if pairing is None:
        raise ControlPlaneError("activation_unavailable", "Helper activation is unavailable.", 409)
    if pairing.activation_request_id:
        if pairing.activation_request_id == activation_request_id:
            return pairing.activation_response
        raise ControlPlaneError("activation_request_conflict", "The activation request cannot be reused.", 409)
    if (
        pairing.state != RackHelperPairing.STATE_CONFIRMED or installation.state != RackHelperInstallation.STATE_PENDING
        or credential.state != RackHelperCredential.STATE_PENDING or pairing.expires_at <= now
        or endpoint.state != BrowserEndpoint.STATE_ACTIVE or endpoint.training_group_id is None
    ):
        raise ControlPlaneError("activation_unavailable", "Helper activation is unavailable.", 409)
    current_intent = endpoint.launch_intents.select_for_update().filter(
        state=RackHelperLaunchIntent.STATE_PENDING,
    ).first()
    bound = False
    if current_intent:
        if current_intent.expires_at <= now:
            current_intent.state = RackHelperLaunchIntent.STATE_EXPIRED
            current_intent.terminal_at = now
            current_intent.save(update_fields=["state", "terminal_at"])
        elif current_intent.target_installation_id is None:
            current_intent.target_installation = installation
            current_intent.save(update_fields=["target_installation"])
            bound = True
    installation.state = RackHelperInstallation.STATE_ACTIVE
    installation.pairing = None
    installation.activated_at = now
    installation.last_contact_at = now
    installation.save(update_fields=["state", "pairing", "activated_at", "last_contact_at"])
    credential.state = RackHelperCredential.STATE_ACTIVE
    credential.activated_at = now
    credential.last_used_at = now
    credential.save(update_fields=["state", "activated_at", "last_used_at"])
    pairing.state = RackHelperPairing.STATE_ACTIVATED
    pairing.activated_at = now
    pairing.code_digest = None
    pairing.proposed_credential_digest = None
    pairing.confirmation_phrase_digest = ""
    pairing.server_nonce = None
    pairing.terminal_at = now
    endpoint.helper_status = "no_sensor"
    endpoint.helper_status_at = now
    endpoint.helper_status_boot_id = None
    endpoint.helper_status_cursor += 1
    endpoint.save(update_fields=[
        "helper_status", "helper_status_at", "helper_status_boot_id",
        "helper_status_cursor", "updated_at",
    ])
    response = {
        "installation_id": str(installation.id), "endpoint_revision": endpoint.endpoint_revision,
        "status_cursor": endpoint.helper_status_cursor, "launch_intent_bound": bound,
    }
    pairing.activation_request_id = activation_request_id
    pairing.activation_response = response
    pairing.save(update_fields=[
        "state", "activated_at", "activation_request_id", "activation_response",
        "code_digest", "proposed_credential_digest",
        "confirmation_phrase_digest", "server_nonce", "terminal_at",
    ])
    return response


@transaction.atomic
def create_launch_intent(endpoint_id):
    endpoint = BrowserEndpoint.objects.select_for_update().get(pk=endpoint_id)
    now = timezone.now()
    ensure_cleanup_capacity(now)
    if endpoint.state != BrowserEndpoint.STATE_ACTIVE or endpoint.training_group_id is None:
        raise ControlPlaneError("not_found", "Not found.", 404)
    pending = endpoint.launch_intents.select_for_update().filter(state=RackHelperLaunchIntent.STATE_PENDING)
    pending.filter(expires_at__lte=now).update(
        state=RackHelperLaunchIntent.STATE_EXPIRED, terminal_at=now,
    )
    pending.filter(expires_at__gt=now).update(
        state=RackHelperLaunchIntent.STATE_SUPERSEDED, superseded_at=now, terminal_at=now,
    )
    installation = endpoint.helper_installations.select_for_update().filter(
        state=RackHelperInstallation.STATE_ACTIVE,
    ).first()
    if installation and installation.launch_consume_receipts.count() >= MAX_CONSUME_RECEIPTS_PER_INSTALLATION:
        raise ControlPlaneError("service_unavailable", "The service is temporarily unavailable.", 503)
    intent = RackHelperLaunchIntent.objects.create(
        endpoint=endpoint, target_installation=installation, created_at=now,
        expires_at=now + PAIRING_LIFETIME,
    )
    endpoint.helper_status_cursor += 1
    endpoint.last_launch_intent = intent
    endpoint.save(update_fields=["helper_status_cursor", "last_launch_intent", "updated_at"])
    return intent, endpoint.helper_status_cursor


@transaction.atomic
def inspect_launch_intent(endpoint_id, intent_id):
    endpoint = BrowserEndpoint.objects.select_for_update().get(pk=endpoint_id)
    intent_uuid = parse_uuid(intent_id)
    if intent_uuid is None:
        raise ControlPlaneError("not_found", "Not found.", 404)
    intent = endpoint.launch_intents.select_for_update().filter(pk=intent_uuid).first()
    if intent is None:
        raise ControlPlaneError("not_found", "Not found.", 404)
    if intent.state == RackHelperLaunchIntent.STATE_PENDING and intent.expires_at <= timezone.now():
        intent.state = RackHelperLaunchIntent.STATE_EXPIRED
        intent.terminal_at = timezone.now()
        intent.save(update_fields=["state", "terminal_at"])
    endpoint.refresh_from_db()
    return endpoint, intent


@transaction.atomic
def consume_launch_intent(credential, helper_boot_id, consume_request_id):
    installation_id = credential.installation_id
    endpoint_id = credential.installation.endpoint_id
    endpoint = BrowserEndpoint.objects.select_for_update().get(pk=endpoint_id)
    installation = RackHelperInstallation.objects.select_for_update().get(pk=installation_id)
    receipt = RackHelperLaunchConsumeReceipt.objects.filter(
        installation=installation, consume_request_id=consume_request_id,
    ).first()
    if receipt:
        if receipt.helper_boot_id != helper_boot_id:
            raise ControlPlaneError("consume_request_conflict", "The consume request cannot be reused.", 409)
        return receipt
    now = timezone.now()
    intent = endpoint.launch_intents.select_for_update().filter(state=RackHelperLaunchIntent.STATE_PENDING).first()
    if intent and intent.expires_at <= now:
        intent.state = RackHelperLaunchIntent.STATE_EXPIRED
        intent.terminal_at = now
        intent.save(update_fields=["state", "terminal_at"])
        intent = None
    if intent is None or intent.target_installation_id != installation.id:
        raise ControlPlaneError("launch_intent_unavailable", "No launch request is available.", 409)
    endpoint.helper_status_cursor += 1
    endpoint.helper_status = "launching"
    endpoint.helper_status_at = now
    endpoint.helper_status_boot_id = helper_boot_id
    endpoint.last_launch_intent = intent
    endpoint.save(update_fields=[
        "helper_status_cursor", "helper_status", "helper_status_at", "helper_status_boot_id",
        "last_launch_intent", "updated_at",
    ])
    intent.state = RackHelperLaunchIntent.STATE_CONSUMED
    intent.consumed_at = now
    intent.consumer_boot_id = helper_boot_id
    intent.consume_request_id = consume_request_id
    intent.ack_cursor = endpoint.helper_status_cursor
    intent.terminal_at = now
    intent.save(update_fields=[
        "state", "consumed_at", "consumer_boot_id", "consume_request_id", "ack_cursor",
        "terminal_at",
    ])
    receipt = RackHelperLaunchConsumeReceipt.objects.create(
        installation=installation, consume_request_id=consume_request_id,
        helper_boot_id=helper_boot_id, intent_id=intent.id,
        acknowledged_at=now, ack_cursor=endpoint.helper_status_cursor,
    )
    installation.last_contact_at = now
    installation.save(update_fields=["last_contact_at"])
    RackHelperCredential.objects.filter(pk=credential.pk).update(last_used_at=now)
    return receipt


@transaction.atomic
def write_helper_status(credential, boot_id, request_id, status_value):
    endpoint = BrowserEndpoint.objects.select_for_update().get(pk=credential.installation.endpoint_id)
    installation = RackHelperInstallation.objects.select_for_update().get(pk=credential.installation_id)
    if installation.last_status_request_id == request_id:
        if installation.last_status_boot_id == boot_id and installation.last_status_value == status_value:
            return installation.last_status_response
        raise ControlPlaneError("status_request_conflict", "The status request cannot be reused.", 409)
    if status_value not in HELPER_POSTABLE_STATUSES:
        raise ControlPlaneError("invalid_status", "The helper status is invalid.", 400)
    if not RackHelperLaunchConsumeReceipt.objects.filter(
        installation=installation, helper_boot_id=boot_id,
    ).exists():
        raise ControlPlaneError("launch_required", "Launch authorization is required.", 409)
    now = timezone.now()
    endpoint.helper_status_cursor += 1
    endpoint.helper_status = status_value
    endpoint.helper_status_at = now
    endpoint.helper_status_boot_id = boot_id
    endpoint.save(update_fields=[
        "helper_status_cursor", "helper_status", "helper_status_at", "helper_status_boot_id", "updated_at",
    ])
    response = {
        "status": status_value, "status_at": now.isoformat(),
        "status_cursor": endpoint.helper_status_cursor,
        "next_heartbeat_seconds": 15, "stale_after_seconds": 60,
    }
    installation.last_contact_at = now
    installation.last_status_request_id = request_id
    installation.last_status_boot_id = boot_id
    installation.last_status_value = status_value
    installation.last_status_response = response
    installation.save(update_fields=[
        "last_contact_at", "last_status_request_id", "last_status_boot_id",
        "last_status_value", "last_status_response",
    ])
    RackHelperCredential.objects.filter(pk=credential.pk).update(last_used_at=now)
    return response


def cleanup_control_plane(*, now=None, batch_size=1000, max_transactions=10):
    now = now or timezone.now()
    batch_size = min(max(1, batch_size), 1000)
    max_transactions = min(max(1, max_transactions), 10)
    deadline = time.monotonic() + 45
    counts = {"expired": 0, "deleted": 0}
    for _transaction_number in range(max_transactions):
        if time.monotonic() >= deadline:
            break
        with transaction.atomic():
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = %s", [remaining_ms])
            changed = 0
            unclaimed_ids = list(EndpointPairing.objects.filter(
                endpoint__isnull=True, expires_at__lte=now,
                state=EndpointPairing.STATE_PENDING,
            ).order_by("pk").values_list("pk", flat=True)[:batch_size])
            if unclaimed_ids:
                changed += EndpointPairing.objects.filter(pk__in=unclaimed_ids).update(
                    state=EndpointPairing.STATE_EXPIRED, code_digest=None,
                    bootstrap_digest=None, terminal_at=now,
                )

            remaining = batch_size - changed
            endpoint_ids = list(
                BrowserEndpoint.objects.filter(
                    models.Q(
                        endpoint_pairings__expires_at__lte=now,
                        endpoint_pairings__state__in=["pending", "claimed"],
                    )
                    | models.Q(
                        helper_pairings__expires_at__lte=now,
                        helper_pairings__state__in=["pending", "claimed", "confirmed"],
                    )
                    | models.Q(
                        helper_installations__state=RackHelperInstallation.STATE_ACTIVE,
                        helper_installations__last_contact_at__lte=now - HELPER_INACTIVITY_LIMIT,
                    )
                ).values_list("pk", flat=True).distinct().order_by("pk")[:max(0, remaining // 5)]
            )
            endpoints = list(BrowserEndpoint.objects.select_for_update().filter(
                pk__in=endpoint_ids,
            ).order_by("pk"))
            for endpoint in endpoints:
                if changed >= batch_size:
                    break
                endpoint_pairings = endpoint.endpoint_pairings.select_for_update().filter(
                    expires_at__lte=now, state__in=[EndpointPairing.STATE_PENDING, EndpointPairing.STATE_CLAIMED],
                ).order_by("pk")[:batch_size - changed]
                for pairing in endpoint_pairings:
                    if _expire_endpoint_pairing(pairing, now):
                        changed += 1
                helper_pairings = endpoint.helper_pairings.select_for_update().filter(
                    expires_at__lte=now, state__in=[RackHelperPairing.STATE_PENDING, RackHelperPairing.STATE_CLAIMED, RackHelperPairing.STATE_CONFIRMED],
                ).order_by("pk")[:batch_size - changed]
                for pairing in helper_pairings:
                    if expire_helper_pairing_locked(pairing, now):
                        changed += 1
                installations = endpoint.helper_installations.select_for_update().filter(
                    state=RackHelperInstallation.STATE_ACTIVE,
                    last_contact_at__lte=now - HELPER_INACTIVITY_LIMIT,
                ).order_by("pk")[:batch_size - changed]
                for installation in installations:
                    installation.state = RackHelperInstallation.STATE_EXPIRED
                    installation.revoked_at = now
                    installation.terminal_at = now
                    installation.save(update_fields=["state", "revoked_at", "terminal_at"])
                    RackHelperCredential.objects.filter(
                        installation=installation, state=RackHelperCredential.STATE_ACTIVE,
                    ).update(state=RackHelperCredential.STATE_REVOKED, secret_digest=None, revoked_at=now)
                    endpoint.launch_intents.filter(state=RackHelperLaunchIntent.STATE_PENDING).update(
                        state=RackHelperLaunchIntent.STATE_CANCELLED, cancelled_at=now,
                        terminal_at=now,
                    )
                    changed += 1
            counts["expired"] += changed

            # Each endpoint can change a pairing, installation, credential, and intent.
            remaining = batch_size - len(unclaimed_ids) - (len(endpoints) * 5)
            deleted = 0
            cutoff = now - TERMINAL_RETENTION
            deletion_queries = [
                ApiThrottleBucket.objects.filter(expires_at__lte=now),
                RackHelperLaunchConsumeReceipt.objects.filter(
                    installation__terminal_at__lte=cutoff,
                ),
                RackHelperLaunchIntent.objects.filter(terminal_at__lte=cutoff),
                RackHelperCredential.objects.filter(
                    state=RackHelperCredential.STATE_REVOKED, revoked_at__lte=cutoff,
                ),
                RackHelperInstallation.objects.filter(
                    terminal_at__lte=cutoff, credentials__isnull=True,
                    launch_intents__isnull=True, launch_consume_receipts__isnull=True,
                ),
                RackHelperPairing.objects.filter(
                    terminal_at__lte=cutoff, installation__isnull=True,
                ),
                EndpointPairing.objects.filter(terminal_at__lte=cutoff),
                EndpointCredential.objects.filter(
                    state=EndpointCredential.STATE_REVOKED, revoked_at__lte=cutoff,
                ),
            ]
            for queryset in deletion_queries:
                if deleted >= remaining:
                    break
                ids = list(queryset.order_by("pk").values_list("pk", flat=True)[:remaining - deleted])
                if ids:
                    removed, _details = queryset.model.objects.filter(pk__in=ids).delete()
                    deleted += removed
            counts["deleted"] += deleted
        if changed + deleted == 0:
            break
    return counts
