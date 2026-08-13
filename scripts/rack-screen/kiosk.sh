#!/bin/bash
# kiosk.sh — launch Chromium full-screen as one Edge Athlete screen.
#
#   kiosk.sh [role] [host] [mode]
#
#   role   rack | coach | dashboard        (default: rack)
#   host   the base station's address      (default: basestation)
#   mode   kiosk | once | windowed         (default: kiosk)
#
#          MODE IS TWO INDEPENDENT QUESTIONS, and they were tangled together at first:
#          "full-screen or a window?" and "reopen itself if it closes?"
#
#            kiosk     LOCKED full-screen, reopens itself   a gym screen, unattended
#            once      full-screen window, stays closed     the base station at boot
#            windowed  a maximised window, stays closed     when you want the toolbar
#
#          `kiosk` is a cage on purpose: no toolbar, no window buttons, no F11. An
#          athlete must not be able to leave the rack screen. `once` looks identical
#          on arrival but is an ordinary window — hover the top edge for the toolbar,
#          F11 to leave, minimise like anything else.
#
#          Reopening is right for a rack screen nobody is standing at: one that closed
#          itself and stayed closed is a dead screen with no one to notice. It is
#          wrong for the base station, where a person is sitting in front of it and
#          closing a window has to mean closing it.
#
#          On the base station ITSELF, pass `localhost` — see WHY LOCALHOST below.
#
#   kiosk.sh rack                          a rack tablet
#   kiosk.sh dashboard                     a wall display
#   kiosk.sh dashboard localhost           a wall display on the base station's own HDMI
#   kiosk.sh coach basestation once        a coach tablet — full-screen, but the
#                                          toolbar is one hover away
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
MODE="${3:-kiosk}"          # kiosk | once | windowed
# normal | left | right | inverted. DEFAULTS TO normal, and that default matters:
# this same launcher drives a rack tablet bolted vertically to a rack, a coach's
# tablet, AND the base station's own three desktop launchers. Rotating for one of
# them would turn the others sideways, so rotation is opt-in per device and never
# assumed from the role.
ROTATE="${4:-${EDGE_SCREEN_ROTATE:-normal}}"

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
# Touched by `ea-kiosk-exit` to tell the relaunch loop at the bottom of this file to
# stop rather than reopen the browser. See the comment there.
STOP_FLAG="${EDGE_KIOSK_STOP:-/tmp/edgeathlete-kiosk.stop}"
if [ ! -t 1 ]; then
    exec >>"$EDGE_KIOSK_LOG" 2>&1
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') launcher starting ==="
fi

# ── WHY ANYTHING EXCEPT `kiosk` EXISTS ──────────────────────────────────────────
# The coach tablet forced it. Everything above about trusting the origin and keeping
# a real profile applies to a coach just as much — they need the offline cache for
# the notes work that is coming, and the app cannot be INSTALLED at all without the
# browser treating the origin as secure. But --kiosk locks the window with no menu,
# and the menu is the only place "install this app" lives. So the mode that was
# supposed to deliver the fix also blocked the reason for it.
#
# `once` is the answer for every screen a PERSON uses: full-screen on arrival, but an
# ordinary window underneath, so the menu is one hover away and closing means closing.
# `windowed` is the same without the full-screen start, for when you want the toolbar
# visible from the first second.
#
# Both are a ONE-TIME door in practice. Once the app is installed from that menu, the
# browser writes its own launcher icon and runs it standalone — no browser chrome,
# its own name, its own icon. After that the coach taps the installed app, not this.
case "$MODE" in
  kiosk|once|windowed) ;;
  *) echo "[kiosk] unknown mode '$MODE' — expected kiosk, once, or windowed"; exit 1 ;;
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

# 2b. Rotate the display, if this device asked to be rotated.
#
#     A rack tablet is bolted to the rack in PORTRAIT; a coach's tablet and the
#     base station's monitor are landscape. Same launcher, same script, so this is
#     opt-in (see ROTATE at the top) and does nothing at all by default.
#
#     ⚠️ ROTATING THE PICTURE WITHOUT ROTATING TOUCH IS WORSE THAN NOT ROTATING.
#     X11 keeps sending touch events in the panel's original coordinate space, so
#     the display looks right and every tap lands somewhere else — a screen that
#     appears fine and responds to the wrong button. The matrices below remap each
#     touch device to match, which is the half people leave out.
#
#     X11 only. Under Wayland (Bookworm's labwc) xrandr is not the mechanism and
#     this quietly does nothing — rotate in the compositor's config there instead.
if [ "$ROTATE" != "normal" ]; then
    case "$ROTATE" in
        left)     MATRIX="0 -1 1 1 0 0 0 0 1" ;;
        right)    MATRIX="0 1 0 -1 0 1 0 0 1" ;;
        inverted) MATRIX="-1 0 1 0 -1 1 0 0 1" ;;
        *)        echo "[!] unknown rotation '$ROTATE' — expected normal|left|right|inverted"
                  MATRIX="" ;;
    esac

    if [ -n "$MATRIX" ] && command -v xrandr >/dev/null 2>&1; then
        # Whichever output is actually plugged in — the name differs per device
        # (HDMI-1, HDMI-A-1, DSI-1 for the official touch display), so asking is
        # the only thing that works across all of them.
        OUTPUT="$(xrandr --query 2>/dev/null | awk '/ connected/{print $1; exit}')"
        if [ -n "$OUTPUT" ]; then
            echo "==> rotating $OUTPUT $ROTATE"
            xrandr --output "$OUTPUT" --rotate "$ROTATE" 2>/dev/null || true
            # Every pointer/touch device, not just the first: a rack tablet often
            # shows up as several (touch, plus a stylus or a mouse emulation node).
            if command -v xinput >/dev/null 2>&1; then
                xinput list --name-only 2>/dev/null | while IFS= read -r DEV; do
                    xinput set-prop "$DEV" 'Coordinate Transformation Matrix' \
                        $MATRIX 2>/dev/null || true
                done
            fi
        else
            echo "[!] no connected display found — skipping rotation"
        fi
    fi
fi

# The xset calls above are X11-only, and modern desktops ignore them — so on
# GNOME/Wayland the screen still blanked and then LOCKED, which on the base station
# meant a lock screen sitting where the wall display should be, demanding a password
# for an account whose password is deliberately locked. Unopenable by design.
#
# These settings are per-user and only exist inside a running session, which is why
# they live here in the launcher rather than in the provisioning script: this is the
# one piece of code that runs as the right user, in the right session, every time.
#
# idle-delay 0 means "never consider this session idle" — it is the setting that
# actually stops the blanking; the two screensaver keys stop the lock that follows.
if command -v gsettings >/dev/null 2>&1; then
    gsettings set org.gnome.desktop.session idle-delay 0                     2>/dev/null || true
    gsettings set org.gnome.desktop.screensaver lock-enabled false           2>/dev/null || true
    gsettings set org.gnome.desktop.screensaver idle-activation-enabled false 2>/dev/null || true
    # Laptops and small-form-factor desktops suspend on idle by default, which takes
    # the whole server down, not just the screen.
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type nothing 2>/dev/null || true

    # Ctrl+Alt+K = leave the kiosk. This is the piece that makes the exit REACHABLE:
    # `ea-kiosk-exit` exists as a command, but you cannot get to a terminal or an app
    # menu from inside a full-screen browser — which is the whole problem. A desktop
    # keybinding is handled by the desktop, not by the browser, so it still fires.
    #
    # GNOME only, and best-effort. Elsewhere the way out is Ctrl+Alt+F3 to a text
    # console, then `ea-kiosk-exit`. That always works and is worth knowing anyway.
    KB=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/edgeathlete-exit/
    KBS="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$KB"
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "['$KB']" 2>/dev/null || true
    gsettings set "$KBS" name    'Exit Edge Athlete kiosk'                    2>/dev/null || true
    gsettings set "$KBS" command 'ea-kiosk-exit'                              2>/dev/null || true
    gsettings set "$KBS" binding '<Control><Alt>k'                            2>/dev/null || true
fi
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

# ── full-screen has two flavours, and only one of them is a cage ────────────────
# --kiosk is a LOCK: no toolbar, no window buttons, no F11, no way out. That is
# correct for a rack screen an athlete uses and must not be able to escape, and
# wrong everywhere else — it also hides the browser menu, which is the only place
# "install this app" lives, so a screen launched that way cannot be installed.
#
# --start-fullscreen fills the screen the same way but the window stays an ordinary
# window: hover the top edge and the toolbar returns, F11 leaves full-screen, and it
# can be minimised like anything else. That is what you want on a machine someone is
# sitting at — full-screen by default, not full-screen by force.
case "$MODE" in
  kiosk)
    CHROME_ARGS+=(
      --kiosk
      --disable-infobars
      # Stops a swipe from the screen edge navigating back — fine on an unattended
      # screen, actively wrong on a coach's tablet where back is a real gesture.
      --overscroll-history-navigation=0
    )
    ;;
  once)
    CHROME_ARGS+=( --start-fullscreen )
    ;;
  windowed)
    CHROME_ARGS+=( --start-maximized )
    ;;
esac
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
#    `once` and `windowed` do NOT relaunch. Closing has to mean closing when there is
#    a person at the keyboard — a window that reopens itself is a bug they cannot
#    escape, and on the base station it also means you can never get to the desktop
#    to demo anything else.
if [ "$MODE" != "kiosk" ]; then
  exec "$CHROME" "${CHROME_ARGS[@]}"
fi

# THE WAY OUT OF THE KIOSK. A relaunch loop is right for an unattended screen and
# wrong for the base station, where somebody sitting at the machine wants to open a
# different role, or just reach the app menu. Closing the browser could not do it:
# the loop brought it straight back, so the kiosk user was sealed inside the wall
# display with launchers installed that it had no way to reach.
#
# So the loop checks for a stop file. `ea-kiosk-exit` (or Ctrl+Alt+K, bound below on
# GNOME) drops that file and closes the browser, and the loop lets the session fall
# through to a plain desktop. Nothing is uninstalled and nothing is disabled — the
# next login starts the kiosk again, because the file is cleared at launch.
#
# Deliberately NOT an exit built into the browser: a rack tablet in a gym must not
# have a "leave the app" affordance an athlete can find by accident.
rm -f "$STOP_FLAG"

while true; do
  "$CHROME" "${CHROME_ARGS[@]}"
  if [ -f "$STOP_FLAG" ]; then
    rm -f "$STOP_FLAG"
    echo "[kiosk] stop requested — leaving you on the desktop"
    echo "[kiosk] log out and back in, or run: $0 $ROLE $HOST $MODE"
    exit 0
  fi
  echo "[kiosk] Chromium exited — restarting in 3s"
  sleep 3
done
