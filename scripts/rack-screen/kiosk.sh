#!/bin/bash
# kiosk.sh — launch Chromium full-screen as one Edge Athlete screen.
#
#   kiosk.sh [role] [host] [mode]
#
#   role   rack | coach | dashboard        (default: rack)
#   host   the base station's address      (default: basestation)
#   mode   kiosk | windowed                (default: kiosk)
#
#          On the base station ITSELF, pass `localhost` — see WHY LOCALHOST below.
#
#   kiosk.sh rack                          a rack tablet
#   kiosk.sh dashboard                     a wall display
#   kiosk.sh dashboard localhost           a wall display on the base station's own HDMI
#   kiosk.sh coach basestation windowed    a coach tablet — see WHY THERE IS A
#                                          WINDOWED MODE below
#
# It waits for the server to answer, stops the screen blanking, and runs Chromium,
# RELAUNCHING it if it ever exits so a screen is never left stuck on a dead page.
#
# ── WHY IT TAKES A ROLE INSTEAD OF A URL ────────────────────────────────────────
# It used to take a raw URL. But a role now decides THREE things that have to agree
# with each other — the URL, which browser profile to use, and which app gets
# installed — and passing a URL let those drift apart silently. Naming the role once
# and deriving the rest is what keeps them consistent.
#
# ── WHY EACH ROLE GETS ITS OWN PROFILE ──────────────────────────────────────────
# The app keeps its identity in localStorage: device_id, device_role, rack_number.
# localStorage is one bucket per (browser profile, origin). So two roles sharing a
# profile share one device_id and fight over one device_role — they are literally
# the same device as far as the server is concerned. A profile per role makes one
# machine look like several tablets, which is what a demo box needs.
#
# ── WHY --incognito IS GONE, AND MUST NOT COME BACK ─────────────────────────────
# This script used to pass --incognito. That wiped exactly the state the system is
# built on, every single launch:
#
#   • device_id lives in localStorage, which incognito discards when the last window
#     closes — and the relaunch loop at the bottom of this file starts a FRESH
#     process after every crash. So the screen came back as a brand-new unassigned
#     node, losing its rack assignment, forever, silently.
#   • repBuffer.js (the durability boundary — every rep is written there the instant
#     it arrives, so a WiFi drop mid-set loses nothing) is IndexedDB. Incognito
#     IndexedDB is memory-backed and dies with the process. That guarantee was void.
#   • Service workers do not register in incognito at all.
#
# A kiosk wants the OPPOSITE of incognito: one profile, on disk, that never forgets.
#
# ── WHY LOCALHOST MATTERS, AND THE FLAG FOR WHEN IT IS NOT AVAILABLE ────────────
# Service workers, Web Bluetooth, and PWA install are all gated on the page being a
# "secure context". Only https and localhost qualify. http://basestation does NOT —
# and note that this is judged on the ORIGIN TEXT, not the resolved address, so even
# on the base station itself the name `basestation` fails the test while `localhost`
# passes. That is the whole reason to pass `localhost` when the browser and the
# server are the same machine: everything just works, no flags, no certificates.
#
# From a different machine, localhost is not an option, so Chromium is told
# explicitly to trust the origin (see CHROME_ARGS). That flag is ignored unless a
# --user-data-dir is also set, which is one more reason the profile above is not
# optional. Serving real HTTPS was the alternative and is worse here: a self-signed
# cert warns on every phone, and an https page refuses the plain ws:// MQTT socket
# as mixed content. See react/src/polyfills.js, which fought the same battle.

set -u

ROLE="${1:-rack}"
HOST="${2:-basestation}"
MODE="${3:-kiosk}"          # kiosk | windowed

# Keep a log, but only when nobody is watching.
#
# Launched from autostart there is no terminal, so everything this script says —
# "waiting for basestation", the snap warning, the relaunch notices — went nowhere.
# That is exactly the situation where you need it: a screen that came up blank, and
# a person standing in front of it with no idea what it tried to do.
#
# Run by hand, output stays on the terminal, because redirecting it into a file you
# then have to go and read would be obnoxious. `-t 1` is the test for "is stdout a
# terminal", which is precisely the difference between those two cases.
EDGE_KIOSK_LOG="${EDGE_KIOSK_LOG:-/tmp/edgeathlete-kiosk.log}"
if [ ! -t 1 ]; then
    exec >>"$EDGE_KIOSK_LOG" 2>&1
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') launcher starting ==="
fi

# ── WHY THERE IS A WINDOWED MODE, AND WHO IT IS FOR ─────────────────────────────
# The coach tablet. Everything above about trusting the origin and keeping a real
# profile applies to it just as much — a coach needs the offline cache for the notes
# work that is coming, and the app cannot be INSTALLED at all without the browser
# treating the origin as secure. But --kiosk is wrong for a coach: it locks the
# window full-screen with no menu, and the menu is where "install this app" lives.
# A coach also navigates, logs in, and legitimately closes the thing.
#
# So windowed mode is the same launch with three differences: no --kiosk, no
# relaunch loop (a coach closing the window means it), and no cursor hiding.
#
# It is a ONE-TIME door in practice. Once the app is installed from that menu, the
# browser writes its own launcher icon and runs it standalone — no browser chrome,
# its own name, its own icon. After that the coach taps the installed app, not this.
case "$MODE" in
  kiosk|windowed) ;;
  *) echo "[kiosk] unknown mode '$MODE' — expected kiosk or windowed"; exit 1 ;;
esac

case "$ROLE" in
  rack)      PATH_PART="/" ;;          # '/' dispatches to /rack/N from stored state
  coach)     PATH_PART="/coach" ;;
  dashboard) PATH_PART="/dashboard" ;;
  *) echo "[kiosk] unknown role '$ROLE' — expected rack, coach, or dashboard"; exit 1 ;;
esac

URL="http://${HOST}${PATH_PART}"

# ── the browser profile ─────────────────────────────────────────────────────────
# Under /var/lib, not a home directory. A kiosk profile is state that belongs to the
# MACHINE, not to whoever happens to be logged in — the same reasoning that put the
# install under /srv instead of /home/pi. The old script hardcoded /home/pi, so the
# whole thing quietly depended on which user was at the keyboard.
#
# Namespaced by user as well as role so any user can run this without colliding with
# another's profile (the parent directory is world-writable and sticky, like /tmp).
KIOSK_ROOT="${EDGE_KIOSK_ROOT:-/var/lib/edge-athlete/kiosk}"
PROFILE="$KIOSK_ROOT/$(id -un)-$ROLE"
mkdir -p "$PROFILE" 2>/dev/null || {
    echo "[kiosk] cannot create $PROFILE — run rack-kiosk-setup.sh once to make $KIOSK_ROOT"
    exit 1
}

echo "[kiosk] role=$ROLE mode=$MODE url=$URL profile=$PROFILE"

# 1. Wait until the server answers — WiFi and the stack may still be coming up at
#    boot. Try for ~60s, then launch anyway (the app retries on its own).
echo "[kiosk] waiting for $URL ..."
for _ in $(seq 1 30); do
  if curl -sf -o /dev/null "$URL"; then break; fi
  sleep 2
done

# 2. Stop the display from blanking or sleeping.
#    X11 only. Under Wayland (Raspberry Pi OS Bookworm defaults to labwc) these are
#    harmless no-ops and the screen WILL still blank — that has to be set in the
#    compositor config instead. rack-kiosk-setup.sh handles it where it can.
xset s off      2>/dev/null || true
xset -dpms      2>/dev/null || true
xset s noblank  2>/dev/null || true
# The cursor is hidden only on unattended screens. A coach is holding a pointer and
# needs to see it.
if [ "$MODE" = "kiosk" ]; then
  command -v unclutter >/dev/null 2>&1 && unclutter -idle 0.5 -root &
fi

# 3. Chromium is `chromium-browser` on older images, `chromium` on newer.
CHROME="$(command -v chromium-browser || command -v chromium)"
if [ -z "$CHROME" ]; then echo "[kiosk] Chromium not found — run rack-kiosk-setup.sh"; exit 1; fi

# ⚠️ SNAP TRAP. On Ubuntu, `chromium` is a snap, and a snap is confined: it can read
# home directories and very little else. A --user-data-dir under /var/lib is OUTSIDE
# that confinement, so the browser fails to start — with a permissions error that
# looks like the directory is missing rather than forbidden, which is a bad hour.
#
# Debian and Raspberry Pi OS ship a normal .deb and are unaffected. Rather than move
# the profile back into a home directory (the exact user-dependence this whole script
# exists to remove), say so and fall back for this run only.
if readlink -f "$CHROME" 2>/dev/null | grep -q '/snap/'; then
    echo "[kiosk] !! this Chromium is a snap, which cannot read $KIOSK_ROOT."
    echo "[kiosk]    falling back to a profile under \$HOME for this run."
    echo "[kiosk]    For a permanent fix install a non-snap build:"
    echo "[kiosk]      sudo apt install -y chromium-browser  # Debian/RPi OS"
    echo "[kiosk]      or install Google Chrome's .deb on Ubuntu"
    PROFILE="$HOME/.edgeathlete-kiosk/$ROLE"
    mkdir -p "$PROFILE"
fi

CHROME_ARGS=(
  --user-data-dir="$PROFILE"
  --noerrdialogs
  --disable-session-crashed-bubble
  --disable-features=Translate
  --check-for-update-interval=31536000
  # Without this Chromium tries to unlock a system keyring on Linux and can sit
  # waiting for a password dialog nobody is there to answer.
  --password-store=basic
)

if [ "$MODE" = "kiosk" ]; then
  CHROME_ARGS+=(
    --kiosk
    --disable-infobars
    # Stops a swipe from the screen edge navigating back — fine on an unattended
    # screen, actively wrong on a coach's tablet where back is a real gesture.
    --overscroll-history-navigation=0
  )
else
  CHROME_ARGS+=( --start-maximized )
fi
CHROME_ARGS+=( "$URL" )

# Only needed when the origin is not already trusted. localhost always is, and
# adding the flag there would be noise that implies otherwise.
if [ "$HOST" != "localhost" ] && [ "$HOST" != "127.0.0.1" ]; then
  CHROME_ARGS+=( --unsafely-treat-insecure-origin-as-secure="http://${HOST}" )
fi

# 4. Kiosk mode relaunches forever: an unattended screen that closed itself is a dead
#    screen, and nobody is there to restart it. The profile is on disk, so it comes
#    back as the SAME device rather than a new one.
#
#    Windowed mode does NOT relaunch. A coach closing the window means it, and a loop
#    that reopens it would be a bug they cannot escape.
if [ "$MODE" = "windowed" ]; then
  exec "$CHROME" "${CHROME_ARGS[@]}"
fi

while true; do
  "$CHROME" "${CHROME_ARGS[@]}"
  echo "[kiosk] Chromium exited — restarting in 3s"
  sleep 3
done
