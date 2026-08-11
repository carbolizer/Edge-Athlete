#!/usr/bin/env python3
"""Fail when the VPS Nginx template exposes an unreviewed API location."""
import re
import sys
from pathlib import Path


EXPECTED_API_LOCATIONS = {
    "= /api/gateway/v1/events/",
    "= /api/health/",
    "= /api/gateways/diagnostics/",
    "~ ^/api/auth/(login|refresh)/$",
    "~ ^/api/rack/v1/(csrf|status)/$",
    "~ ^/api/rack/v1/(endpoint-pairings(?:/status)?|helper-pairings(?:/status)?|helper-launch-intents(?:/inspect)?)/$",
    "~ ^/api/coach/v1/(rack-endpoint-pairings/claim|rack-helper-pairings/confirm)/$",
    "= /api/coach/v1/training-groups/",
    "~ ^/api/rack-helper/v1/(pairings/(claim|status|activate)|status|launch-intents/consume)/$",
    "/api/",
}


def validation_errors(config_path):
    config = config_path.read_text(encoding="utf-8")
    errors = []
    api_locations = {
        match.strip()
        for match in re.findall(r"^\s*location\s+([^{}]*?/api/[^{}]*?)\s*\{", config, re.MULTILINE)
    }
    if api_locations != EXPECTED_API_LOCATIONS:
        missing = sorted(EXPECTED_API_LOCATIONS - api_locations)
        unexpected = sorted(api_locations - EXPECTED_API_LOCATIONS)
        errors.append(f"VPS API allowlist mismatch; missing={missing}, unexpected={unexpected}")
    fallback = re.search(r"^\s*location\s+/api/\s*\{(?P<body>.*?)^\s*\}", config, re.MULTILINE | re.DOTALL)
    if fallback is None or re.fullmatch(r"\s*return\s+404;\s*", fallback.group("body")) is None:
        errors.append("VPS API fallback must contain only 'return 404;'")
    if not re.search(r"^\s*location\s+\^~\s+/admin/\s*\{\s*return\s+404;", config, re.MULTILINE):
        errors.append("VPS admin denial is missing")
    required_method_guards = {
        "~ ^/api/rack/v1/(csrf|status)/$": "GET",
        "~ ^/api/rack/v1/(endpoint-pairings(?:/status)?|helper-pairings(?:/status)?|helper-launch-intents(?:/inspect)?)/$": "POST",
        "~ ^/api/coach/v1/(rack-endpoint-pairings/claim|rack-helper-pairings/confirm)/$": "POST",
        "= /api/coach/v1/training-groups/": "GET",
        "~ ^/api/rack-helper/v1/(pairings/(claim|status|activate)|status|launch-intents/consume)/$": "POST",
    }
    for location, method in required_method_guards.items():
        block = re.search(
            rf"^\s*location\s+{re.escape(location)}\s*\{{(?P<body>.*?)^\s*\}}",
            config, re.MULTILINE | re.DOTALL,
        )
        if block is None or f"if ($request_method != {method})" not in block.group("body"):
            errors.append(f"VPS hosted Rack location lacks exact {method} method guard: {location}")
        if block is None or "limit_req zone=hosted_control_plane" not in block.group("body"):
            errors.append(f"VPS hosted Rack location lacks per-IP limiting: {location}")
    main_csp = (
        "add_header Content-Security-Policy \"default-src 'self'; base-uri 'none'; "
        "connect-src 'self'; frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; "
        "script-src 'self'; style-src 'self' 'unsafe-inline'; worker-src 'self'\" always;"
    )
    # The named 429 location defines Retry-After, so Nginx no longer inherits
    # server-level add_header directives there. Require the CSP in both scopes.
    if config.count(main_csp) < 2:
        errors.append("VPS main application CSP is missing")
    rate_limit_response = (
        "add_header Cache-Control \"no-store\" always;\n"
        "        add_header Retry-After 12 always;\n"
        "        return 429 '{\"code\":\"rate_limited\",\"detail\":\"Too many requests.\","
        "\"retry_after_seconds\":12}';"
    )
    if "error_page 429 = @rate_limited;" not in config or rate_limit_response not in config:
        errors.append("VPS proxy rate-limit response contract is missing")
    for header in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"):
        if f"proxy_hide_header {header};" not in config:
            errors.append(f"VPS must suppress the upstream {header} header")
    return errors


def main():
    config_path = Path(sys.argv[1] if len(sys.argv) > 1 else "nginx/vps.conf.template")
    errors = validation_errors(config_path)
    for error in errors:
        print(error, file=sys.stderr)
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
