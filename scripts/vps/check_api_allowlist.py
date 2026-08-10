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
    return errors


def main():
    config_path = Path(sys.argv[1] if len(sys.argv) > 1 else "nginx/vps.conf.template")
    errors = validation_errors(config_path)
    for error in errors:
        print(error, file=sys.stderr)
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
