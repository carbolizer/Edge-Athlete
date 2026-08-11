#!/usr/bin/env python3
"""Verify the public VPS boundary without using application credentials."""
import argparse
import json
import ssl
import sys
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener


@dataclass(frozen=True)
class Observation:
    status: int
    headers: object
    body: bytes


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def request_once(opener, url, method="GET", body=None):
    request = Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with opener.open(request, timeout=10) as response:
            return Observation(response.status, response.headers, response.read(64 * 1024))
    except HTTPError as exc:
        return Observation(exc.code, exc.headers, exc.read(64 * 1024))


def security_header_errors(headers):
    expected = {
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "bluetooth=(), camera=(), geolocation=(), microphone=()",
        "Content-Security-Policy": (
            "default-src 'self'; base-uri 'none'; connect-src 'self'; frame-ancestors 'none'; "
            "img-src 'self' data:; object-src 'none'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; worker-src 'self'"
        ),
    }
    return [
        f"missing or invalid {name}"
        for name, value in expected.items()
        if headers.get(name) != value
    ]


def validate_observations(domain, observations):
    errors = []

    health = observations["health"]
    if health.status != 200:
        errors.append(f"health returned {health.status}, expected 200")
    else:
        try:
            payload = json.loads(health.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            errors.append("health did not return JSON")
        else:
            if payload != {"status": "ok", "database": "ok"}:
                errors.append("health response did not report application and database ready")

    rack = observations["rack"]
    if rack.status != 200 or b'<div id="root"></div>' not in rack.body:
        errors.append("/rack did not return the React application shell")

    csrf = observations["csrf"]
    cookie = csrf.headers.get("Set-Cookie", "")
    if csrf.status != 200 or csrf.headers.get("Cache-Control") != "no-store":
        errors.append("Rack CSRF bootstrap was not a no-store 200 response")
    for attribute in ("ea_rack_csrf=", "Secure", "SameSite=Strict", "Path=/api/rack/v1/"):
        if attribute not in cookie:
            errors.append(f"Rack CSRF cookie is missing {attribute}")

    status = observations["rack_status"]
    try:
        status_payload = json.loads(status.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        status_payload = None
    if status.status != 401 or status_payload != {
        "code": "endpoint_authentication_failed",
        "detail": "Endpoint authentication failed.",
    }:
        errors.append("unauthenticated Rack status did not fail with the generic 401 contract")

    if observations["coach_groups"].status != 401:
        errors.append("hosted coach TrainingGroup route did not require authentication")

    for label in ("private_api", "admin"):
        if observations[label].status != 404:
            errors.append(f"{label} returned {observations[label].status}, expected 404")

    redirect = observations["http_redirect"]
    if redirect.status != 308 or redirect.headers.get("Location") != f"https://{domain}/rack":
        errors.append("HTTP Rack GET did not redirect exactly to HTTPS")
    if observations["http_post"].status != 405:
        errors.append("credential-bearing HTTP POST was not rejected with 405")

    for label in ("health", "rack", "csrf", "rack_status", "coach_groups", "private_api", "admin"):
        errors.extend(f"{label}: {error}" for error in security_header_errors(observations[label].headers))
    return errors


def run(base_url, ca_file=None):
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.port not in (None, 443)
        or parsed.username or parsed.password
        or parsed.path not in ("", "/") or parsed.query or parsed.fragment
    ):
        raise ValueError("base URL must be an HTTPS origin without credentials, path, query, or fragment")
    domain = parsed.hostname
    https_origin = f"https://{parsed.netloc}"
    http_origin = f"http://{domain}"
    context = ssl.create_default_context(cafile=ca_file)
    opener = build_opener(NoRedirect(), HTTPSHandler(context=context))
    observations = {
        "health": request_once(opener, https_origin + "/api/health/"),
        "rack": request_once(opener, https_origin + "/rack"),
        "csrf": request_once(opener, https_origin + "/api/rack/v1/csrf/"),
        "rack_status": request_once(opener, https_origin + "/api/rack/v1/status/"),
        "coach_groups": request_once(opener, https_origin + "/api/coach/v1/training-groups/"),
        "private_api": request_once(opener, https_origin + "/api/athletes/"),
        "admin": request_once(opener, https_origin + "/admin/"),
        "http_redirect": request_once(opener, http_origin + "/rack"),
        "http_post": request_once(
            opener, http_origin + "/api/rack/v1/endpoint-pairings/", method="POST", body=b"{}",
        ),
    }
    return validate_observations(domain, observations)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="Public HTTPS origin, for example https://edge.example.com")
    parser.add_argument("--ca-file", help="Optional CA file for a private release-candidate environment")
    args = parser.parse_args()
    try:
        errors = run(args.base_url, args.ca_file)
    except (ValueError, OSError, URLError) as exc:
        print(f"VPS smoke test could not run: {exc}", file=sys.stderr)
        return 1
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print("VPS public-boundary smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
