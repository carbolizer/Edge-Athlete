"""HTTP boundary for the thin hosted Rack control plane.

These routes expose identity and launch authority only; hardware and workout write
paths remain in the private-AP API.
"""
import secrets

from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .permissions import HasActiveOrganization, IsActiveStaff
from .services import rack_control_plane as control


def _response(body, status=200, error=None):
    response = Response(body, status=status)
    response["Cache-Control"] = "no-store"
    if error and error.retry_after:
        response["Retry-After"] = str(error.retry_after)
    return response


def _error(exc):
    body = {"code": exc.code, "detail": exc.detail}
    if exc.retry_after:
        body["retry_after_seconds"] = exc.retry_after
    return _response(body, exc.status, exc)


def _set_host_cookie(response, name, value, *, path, max_age, httponly):
    response.set_cookie(
        name, value, max_age=max_age, path=path, secure=True,
        httponly=httponly, samesite="Strict",
    )
    # Django synthesizes Expires from Max-Age; this protocol intentionally emits only Max-Age.
    response.cookies[name]["expires"] = ""


def _delete_host_cookie(response, name, *, path, httponly):
    _set_host_cookie(response, name, "", path=path, max_age=0, httponly=httponly)


def _endpoint_credential(request, *, touch=False):
    credential = control.authenticate_endpoint(request.COOKIES.get("ea_rack_endpoint"), touch=touch)
    if credential is None:
        raise control.ControlPlaneError(
            "endpoint_authentication_failed", "Endpoint authentication failed.", 401,
        )
    return credential


def _helper_credential(request, *, allow_pending=False, touch=False):
    credential = control.authenticate_helper(
        control.helper_authorization_token(request), allow_pending=allow_pending, touch=touch,
    )
    if credential is None:
        raise control.ControlPlaneError(
            "helper_authentication_failed", "Helper authentication failed.", 401,
        )
    return credential


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def rack_csrf(request):
    try:
        control.apply_limits([
            ("rack_csrf_source", control.source_key(request), 120, 60),
            ("rack_csrf_service", "service", 2000, 60),
        ])
    except control.ControlPlaneError as exc:
        return _error(exc)
    response = _response({})
    _set_host_cookie(
        response, "ea_rack_csrf", control.encode_secret(secrets.token_bytes(32)),
        path="/api/rack/v1/", max_age=control.ENDPOINT_COOKIE_AGE, httponly=False,
    )
    return response


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def endpoint_pairing_create(request):
    try:
        control.require_endpoint_mutation(request)
        control.require_exact_object(request.data, set())
        source = control.source_key(request)
        control.apply_limits([
            ("endpoint_pairing_create_source", source, 10, 15 * 60),
            ("endpoint_pairing_create_service", "service", 1000, 60),
        ])
        pairing, code, bootstrap = control.create_endpoint_pairing()
    except control.ControlPlaneError as exc:
        return _error(exc)
    response = _response({
        "pairing_id": str(pairing.id), "pairing_code": code,
        "expires_at": pairing.expires_at.isoformat(), "poll_after_seconds": 2,
    }, 201)
    _set_host_cookie(
        response, "ea_rack_endpoint_pairing", bootstrap,
        path="/api/rack/v1/endpoint-pairings/", max_age=control.PAIRING_COOKIE_AGE,
        httponly=True,
    )
    return response


@api_view(["POST"])
@permission_classes([IsActiveStaff, HasActiveOrganization])
def endpoint_pairing_claim(request):
    try:
        control.require_coach_origin(request)
        data = control.require_exact_object(
            request.data, {"pairing_code", "training_group", "display_name"},
        )
        control.apply_limits([
            ("endpoint_claim_code", str(data["pairing_code"]), 5, 5 * 60),
            ("endpoint_claim_coach", str(request.user.pk), 20, 60 * 60),
            ("endpoint_claim_organization", str(request.organization.pk), 50, 60 * 60),
            ("endpoint_claim_service", "service", 1000, 60),
        ])
        endpoint = control.claim_endpoint_pairing(
            request.user, request.organization, data["pairing_code"],
            data["training_group"], data["display_name"],
        )
    except control.ControlPlaneError as exc:
        return _error(exc)
    return _response({"endpoint": control.endpoint_summary(endpoint), "state": "claimed"})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def endpoint_pairing_status(request):
    try:
        control.require_endpoint_mutation(request)
        control.require_exact_object(request.data, set())
        control.apply_limits([
            ("endpoint_pairing_status_source", control.source_key(request), 120, 60),
            ("endpoint_pairing_status_service", "service", 2000, 60),
        ])
        pairing, token = control.endpoint_pairing_status(
            request.COOKIES.get("ea_rack_endpoint_pairing"),
        )
    except control.ControlPlaneError as exc:
        response = _error(exc)
        if exc.code == "pairing_expired":
            _delete_host_cookie(
                response, "ea_rack_endpoint_pairing",
                path="/api/rack/v1/endpoint-pairings/", httponly=True,
            )
        return response
    if token is None:
        return _response({
            "state": "pending", "expires_at": pairing.expires_at.isoformat(),
            "poll_after_seconds": 2,
        })
    response = _response({
        "state": "paired", "endpoint": control.endpoint_summary(pairing.endpoint),
    })
    _set_host_cookie(
        response, "ea_rack_endpoint", token, path="/api/rack/v1/",
        max_age=control.ENDPOINT_COOKIE_AGE, httponly=True,
    )
    _delete_host_cookie(
        response, "ea_rack_endpoint_pairing",
        path="/api/rack/v1/endpoint-pairings/", httponly=True,
    )
    return response


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def endpoint_status(request):
    try:
        control.apply_limits([("endpoint_status_service", "service", 2000, 60)])
        credential = _endpoint_credential(request)
        endpoint = credential.endpoint
        control.apply_limits([
            ("endpoint_status_endpoint", str(endpoint.pk), 120, 60),
        ])
        credential = _endpoint_credential(request, touch=True)
    except control.ControlPlaneError as exc:
        return _error(exc)
    now = timezone.now()
    response = _response({
        "endpoint": control.endpoint_summary(endpoint),
        "helper": control.helper_snapshot(endpoint, now),
        "server_time": now.isoformat(),
    })
    _set_host_cookie(
        response, "ea_rack_endpoint", request.COOKIES["ea_rack_endpoint"],
        path="/api/rack/v1/", max_age=control.ENDPOINT_COOKIE_AGE, httponly=True,
    )
    return response


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def helper_pairing_create(request):
    try:
        control.require_endpoint_mutation(request)
        control.require_exact_object(request.data, set())
        control.apply_limits([
            ("helper_pairing_create_source", control.source_key(request), 20, 15 * 60),
            ("helper_pairing_create_service", "service", 1000, 60),
        ])
        credential = _endpoint_credential(request)
        endpoint = credential.endpoint
        control.apply_limits([
            ("helper_pairing_create_endpoint", str(endpoint.pk), 20, 60 * 60),
            ("helper_pairing_create_organization", str(endpoint.organization_id), 50, 60 * 60),
        ])
        pairing, code = control.create_helper_pairing(endpoint.pk)
    except control.ControlPlaneError as exc:
        return _error(exc)
    return _response({
        "pairing_id": str(pairing.id), "pairing_code": code,
        "expires_at": pairing.expires_at.isoformat(),
    }, 201)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def helper_pairing_claim(request):
    try:
        data = control.require_exact_object(request.data, {
            "pairing_code", "bootstrap_token", "credential", "platform", "contract_version",
        })
        control.apply_limits([
            ("helper_claim_source", control.source_key(request), 10, 15 * 60),
            ("helper_claim_service", "service", 1000, 60),
        ])
        claim_scope = control.helper_claim_scope(data["pairing_code"])
        if claim_scope:
            pairing_id, endpoint_id, organization_id = claim_scope
            control.apply_limits([
                ("helper_claim_pairing", pairing_id, 5, 5 * 60),
                ("helper_claim_endpoint", endpoint_id, 20, 60 * 60),
                ("helper_claim_organization", organization_id, 50, 60 * 60),
            ])
        pairing = control.claim_helper_pairing(data)
    except control.ControlPlaneError as exc:
        return _error(exc)
    return _response({
        "pairing_id": str(pairing.id), "state": "claimed",
        "confirmation_phrase": control.confirmation_phrase(pairing),
        "expires_at": pairing.expires_at.isoformat(), "poll_after_seconds": 2,
    })


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def endpoint_helper_pairing_status(request):
    try:
        control.require_endpoint_mutation(request)
        data = control.require_exact_object(request.data, {"pairing_id"})
        control.apply_limits([
            ("endpoint_helper_pairing_status_service", "service", 2000, 60),
        ])
        credential = _endpoint_credential(request)
        control.apply_limits([
            ("endpoint_helper_pairing_status_endpoint", str(credential.endpoint_id), 120, 60),
        ])
        pairing_id = control.parse_uuid(data["pairing_id"])
        if pairing_id is None:
            raise control.ControlPlaneError("not_found", "Not found.", 404)
        pairing = credential.endpoint.helper_pairings.filter(pk=pairing_id).first()
        if pairing is None:
            raise control.ControlPlaneError("not_found", "Not found.", 404)
        if pairing.expires_at <= timezone.now() and pairing.state != "activated":
            raise control.ControlPlaneError("pairing_expired", "The pairing session expired.", 410)
    except control.ControlPlaneError as exc:
        return _error(exc)
    return _response({
        "pairing_id": str(pairing.id), "state": pairing.state,
        "confirmation_phrase": (
            control.confirmation_phrase(pairing) if pairing.state != "pending" else None
        ),
        "expires_at": pairing.expires_at.isoformat(),
    })


@api_view(["POST"])
@permission_classes([IsActiveStaff, HasActiveOrganization])
def helper_pairing_confirm(request):
    try:
        control.require_coach_origin(request)
        data = control.require_exact_object(request.data, {"pairing_id"})
        pairing_id = control.parse_uuid(data["pairing_id"])
        if pairing_id is None:
            raise control.ControlPlaneError("not_found", "Not found.", 404)
        control.apply_limits([
            ("helper_confirm_pairing", str(pairing_id), 10, 5 * 60),
            ("helper_confirm_service", "service", 1000, 60),
        ])
        confirm_scope = control.helper_confirm_scope(pairing_id)
        if confirm_scope:
            control.apply_limits([
                ("helper_confirm_endpoint", confirm_scope, 20, 60 * 60),
            ])
        pairing, installation = control.confirm_helper_pairing(
            request.user, request.organization, pairing_id,
        )
    except control.ControlPlaneError as exc:
        return _error(exc)
    return _response({
        "pairing_id": str(pairing.id), "state": "confirmed",
        "activation_expires_at": installation.activation_expires_at.isoformat(),
    })


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def helper_pairing_status(request):
    try:
        data = control.require_exact_object(request.data, {"pairing_id", "bootstrap_token"})
        control.apply_limits([
            ("helper_pairing_status_source", control.source_key(request), 120, 60),
            ("helper_pairing_status_service", "service", 2000, 60),
        ])
        pairing = control.helper_pairing_status(data["pairing_id"], data["bootstrap_token"])
    except control.ControlPlaneError as exc:
        return _error(exc)
    activation_expires = pairing.installation.activation_expires_at if hasattr(pairing, "installation") else None
    return _response({
        "pairing_id": str(pairing.id), "state": pairing.state,
        "activation_expires_at": activation_expires.isoformat() if activation_expires else None,
        "poll_after_seconds": 2,
    })


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def helper_pairing_activate(request):
    try:
        data = control.require_exact_object(request.data, {"pairing_id", "activation_request_id"})
        pairing_id = control.parse_uuid(data["pairing_id"])
        request_id = control.parse_uuid(data["activation_request_id"])
        if pairing_id is None or request_id is None:
            raise control.ControlPlaneError("activation_unavailable", "Helper activation is unavailable.", 409)
        control.apply_limits([
            ("helper_activate_source", control.source_key(request), 20, 15 * 60),
            ("helper_activate_service", "service", 1000, 60),
        ])
        credential = _helper_credential(request, allow_pending=True)
        control.apply_limits([
            ("helper_activate_pairing", str(pairing_id), 10, 5 * 60),
            ("helper_activate_endpoint", str(credential.installation.endpoint_id), 20, 60 * 60),
        ])
        result = control.activate_helper(credential, pairing_id, request_id)
    except control.ControlPlaneError as exc:
        return _error(exc)
    return _response(result)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def helper_status(request):
    try:
        data = control.require_exact_object(
            request.data, {"helper_boot_id", "status_request_id", "status"},
        )
        boot_id = control.parse_uuid(data["helper_boot_id"])
        request_id = control.parse_uuid(data["status_request_id"])
        if boot_id is None or request_id is None:
            raise control.ControlPlaneError("invalid_request", "The request body is invalid.", 400)
        control.apply_limits([
            ("helper_status_source", control.source_key(request), 120, 60),
            ("helper_status_service", "service", 2000, 60),
        ])
        credential = _helper_credential(request)
        control.apply_limits([
            ("helper_status_installation", str(credential.installation_id), 20, 60),
        ])
        result = control.write_helper_status(credential, boot_id, request_id, data["status"])
    except control.ControlPlaneError as exc:
        return _error(exc)
    return _response(result)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def launch_intent_create(request):
    try:
        control.require_endpoint_mutation(request)
        control.require_exact_object(request.data, set())
        control.apply_limits([
            ("launch_create_source", control.source_key(request), 20, 15 * 60),
            ("launch_create_service", "service", 1000, 60),
        ])
        credential = _endpoint_credential(request)
        endpoint = credential.endpoint
        control.apply_limits([
            ("launch_create_endpoint", str(endpoint.pk), 10, 60),
            ("launch_create_organization", str(endpoint.organization_id), 50, 60 * 60),
        ])
        intent, cursor = control.create_launch_intent(endpoint.pk)
    except control.ControlPlaneError as exc:
        return _error(exc)
    return _response({
        "intent_id": str(intent.id), "expires_at": intent.expires_at.isoformat(),
        "launch_uri": "edgeathlete-rack:launch", "create_status_cursor": cursor,
    }, 201)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def launch_intent_inspect(request):
    try:
        control.require_endpoint_mutation(request)
        data = control.require_exact_object(request.data, {"intent_id"})
        control.apply_limits([
            ("launch_inspect_source", control.source_key(request), 120, 60),
            ("launch_inspect_service", "service", 2000, 60),
        ])
        credential = _endpoint_credential(request)
        control.apply_limits([
            ("launch_inspect_endpoint", str(credential.endpoint_id), 120, 60),
        ])
        endpoint, intent = control.inspect_launch_intent(credential.endpoint_id, data["intent_id"])
    except control.ControlPlaneError as exc:
        return _error(exc)
    return _response({
        "intent_id": str(intent.id), "state": intent.state,
        "expires_at": intent.expires_at.isoformat(),
        "acknowledged_at": intent.consumed_at.isoformat() if intent.consumed_at else None,
        "ack_cursor": intent.ack_cursor,
        "current_status_cursor": endpoint.helper_status_cursor,
        "helper_status": control.helper_snapshot(endpoint)["status"],
    })


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def launch_intent_consume(request):
    try:
        data = control.require_exact_object(request.data, {"helper_boot_id", "consume_request_id"})
        boot_id = control.parse_uuid(data["helper_boot_id"])
        request_id = control.parse_uuid(data["consume_request_id"])
        if boot_id is None or request_id is None:
            raise control.ControlPlaneError("invalid_request", "The request body is invalid.", 400)
        control.apply_limits([
            ("launch_consume_source", control.source_key(request), 20, 60),
            ("launch_consume_service", "service", 1000, 60),
        ])
        credential = _helper_credential(request)
        control.apply_limits([
            ("launch_consume_installation", str(credential.installation_id), 20, 60),
        ])
        receipt = control.consume_launch_intent(credential, boot_id, request_id)
    except control.ControlPlaneError as exc:
        return _error(exc)
    return _response({
        "intent_id": str(receipt.intent_id),
        "acknowledged_at": receipt.acknowledged_at.isoformat(),
        "ack_cursor": receipt.ack_cursor, "next": "reconcile",
    })
