#!/usr/bin/env bash
# wait-and-launch-kiosk.sh — what actually makes the Pi boot into the wall display.
# On boot the Docker stack takes a while to come up (Postgres migrate, Django,
# nginx). Launching Chromium immediately would just show a connection error and
# sit there. So this script first POLLS the dashboard URL until nginx answers
# with the real page, THEN opens Chromium locked in kiosk mode against it. The
# manifest's "fullscreen" alone does NOT do this — a browser has to be told to
# launch. Run by edgeathlete-kiosk.service after the stack service.
set -euo pipefail

URL="${DASHBOARD_URL:-http://localhost/dashboard}"
MAX_WAIT="${MAX_WAIT_SECONDS:-180}"

echo "[kiosk] waiting for dashboard at ${URL} (up to ${MAX_WAIT}s)…"
deadline=$(( $(date +%s) + MAX_WAIT ))
until curl -fsS --max-time 3 "${URL}" >/dev/null 2>&1; do
  if [ "$(date +%s)" -ge "${deadline}" ]; then
    echo "[kiosk] dashboard did not come up within ${MAX_WAIT}s — giving up." >&2
    exit 1
  fi
  sleep 2
done
echo "[kiosk] dashboard is up — launching Chromium in kiosk mode."

# Chromium's binary is named chromium-browser on Raspberry Pi OS, chromium on some
# distros. Pick whichever exists.
BROWSER="$(command -v chromium-browser || command -v chromium || true)"
if [ -z "${BROWSER}" ]; then
  echo "[kiosk] no chromium binary found (install chromium-browser)." >&2
  exit 1
fi

exec "${BROWSER}" \
  --kiosk \
  --app="${URL}" \
  --noerrdialogs \
  --disable-infobars \
  --incognito \
  --check-for-update-interval=31536000
