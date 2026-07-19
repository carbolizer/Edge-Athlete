#!/bin/bash
# kiosk.sh — launch Chromium full-screen for an Edge Athlete kiosk (rack or wall).
#
# The rack-kiosk-setup.sh installer wires this to run at desktop login. It waits
# for the base station to answer, stops the screen from blanking, and runs
# Chromium in --kiosk mode, RELAUNCHING it if it ever exits so a rack screen is
# never left stuck on a blank/crashed page.
#
# Usage: kiosk.sh [URL]      (default http://basestation/)
#   • rack screen  → http://basestation/         (the app dispatches to /rack/N)
#   • wall display → http://basestation/dashboard (Phase 12 — same script, different URL)
#
# Wayland note: Raspberry Pi OS Bookworm defaults to Wayland (labwc/wayfire), where
# the `xset` lines below are harmless no-ops — disable blanking in the compositor
# config instead (e.g. labwc's autostart, or `wlr-randr`). Chromium --kiosk itself
# works the same on X and Wayland.

set -u
URL="${1:-http://basestation/}"

# 1. Wait until the base station answers — Wi-Fi + the server stack may still be
#    coming up at boot. Try for ~60s, then launch anyway (the app will retry).
echo "[kiosk] waiting for $URL ..."
for _ in $(seq 1 30); do
  if curl -sf -o /dev/null "$URL"; then break; fi
  sleep 2
done

# 2. Stop the display from blanking or sleeping (X11; no-ops under Wayland).
xset s off      2>/dev/null || true
xset -dpms      2>/dev/null || true
xset s noblank  2>/dev/null || true
command -v unclutter >/dev/null 2>&1 && unclutter -idle 0.5 -root &  # hide the cursor

# 3. Chromium is packaged as `chromium-browser` on older images, `chromium` on newer.
CHROME="$(command -v chromium-browser || command -v chromium)"
if [ -z "$CHROME" ]; then echo "[kiosk] Chromium not found — run rack-kiosk-setup.sh"; exit 1; fi

# 4. Relaunch loop: if Chromium is closed or crashes, bring it right back.
while true; do
  "$CHROME" \
    --kiosk "$URL" \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-features=Translate \
    --incognito \
    --check-for-update-interval=31536000 \
    --overscroll-history-navigation=0
  echo "[kiosk] Chromium exited — restarting in 3s"
  sleep 3
done
