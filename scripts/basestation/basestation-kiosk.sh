#!/usr/bin/env bash
# basestation-kiosk.sh — run Edge Athlete screens on the base station itself.
#
#   basestation-kiosk.sh open <role>       a normal window, for INSTALLING the app
#   basestation-kiosk.sh run  <role>       full-screen kiosk, right now
#   basestation-kiosk.sh autostart <role>  launch that role on every boot
#
#   role   rack | coach | dashboard
#
# Two things this is for. One: driving a wall display off the base station's own
# HDMI output, which is `autostart dashboard`. Two: putting all three apps on one
# machine for a demo, so you can show the rack screen, the coach tablet, and the
# wall display without three pieces of hardware.
#
# ── WHY THIS IS A SEPARATE SCRIPT FROM rack-screen/kiosk.sh ─────────────────────
# It is mostly a thin wrapper around it, and deliberately so. What differs is the
# HOST: a rack tablet talks to `basestation` over WiFi, but here the browser and
# the server are the same machine, so it talks to `localhost` — and that one word
# changes what the browser will let the app do.
#
# Service workers, PWA install, and Web Bluetooth all require a "secure context",
# which means https or localhost and nothing else. `http://basestation` does not
# qualify, and — this is the part that surprises people — it still does not qualify
# ON the base station, even though the name resolves to a loopback address. The
# check is on the origin TEXT, not on where it resolves to. So `localhost` is a
# genuinely secure context here for free, with no certificate and no browser flags,
# and everything a rack tablet needs a flag for simply works.
#
# ── WHY EACH ROLE NEEDS ITS OWN PROFILE, ESPECIALLY HERE ────────────────────────
# The app's identity — device_id, device_role, rack_number — lives in localStorage,
# which is one bucket per (browser profile, origin). Same origin for all three roles
# here, so WITHOUT separate profiles the three apps would share one device_id and
# overwrite each other's role: not three demo screens, one confused one. kiosk.sh
# gives each role its own profile directory, which is what makes this work at all.
#
# ── INSTALLING (the `open` verb) ────────────────────────────────────────────────
# `run` uses --kiosk, which hides the menu — so there is no way to click Install.
# `open` is the same thing in a normal window: use ⋮ > Cast, save and share >
# Install page as app. Each role installs as its OWN app because each manifest now
# carries a distinct `id` (see react/public/manifest.rack.json for that story).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
KIOSK_SH="$REPO_DIR/scripts/rack-screen/kiosk.sh"
KIOSK_ROOT="${EDGE_KIOSK_ROOT:-/var/lib/edge-athlete/kiosk}"

usage() {
    cat <<'EOF'
basestation-kiosk.sh — run Edge Athlete screens on the base station itself.

  basestation-kiosk.sh open <role>       a normal window, for INSTALLING the app
  basestation-kiosk.sh run  <role>       full-screen kiosk, right now
  basestation-kiosk.sh autostart <role>  launch that role on every boot  (sudo)

  role   rack | coach | dashboard

Everything here talks to localhost, not basestation — that is what makes the
browser treat it as a secure context, so service workers and PWA install work
with no flags and no certificate. See the notes at the top of this file.
EOF
    exit "${1:-1}"
}

VERB="${1:-}"
ROLE="${2:-}"
[ -n "$VERB" ] || usage 1

# Help is answered BEFORE the role check — otherwise `--help` demanded a role,
# which is precisely the thing you are asking about.
case "$VERB" in -h|--help|help) usage 0 ;; esac

case "$ROLE" in
  rack|coach|dashboard) ;;
  *) echo "[!] need a role: rack, coach, or dashboard"; echo; usage 1 ;;
esac

case "$ROLE" in
  rack)      URL_PATH="/" ;;
  coach)     URL_PATH="/coach" ;;
  dashboard) URL_PATH="/dashboard" ;;
esac
URL="http://localhost${URL_PATH}"

# The profile directory has to exist and be writable by whoever is running this.
# 1777 (sticky, world-writable, like /tmp) is what lets any desktop user make their
# own without root, so this script never has to be run as a particular person.
ensure_profile_root() {
    if [ ! -d "$KIOSK_ROOT" ]; then
        echo "[*] creating $KIOSK_ROOT (needs sudo once)"
        sudo mkdir -p "$KIOSK_ROOT" && sudo chmod 1777 "$KIOSK_ROOT" || {
            echo "[!] could not create $KIOSK_ROOT"; exit 1
        }
    fi
}

case "$VERB" in
  run)
      ensure_profile_root
      # `normal` PASSED EXPLICITLY, and it has to be. kiosk.sh falls back to
      # /etc/edgeathlete/screen.conf when no rotation argument is given, and that
      # file exists on any box where a rack role was ever provisioned — which is
      # exactly what the base station is when it runs the demo screens. Without
      # this, giving rack tablets a portrait default would silently turn the base
      # station's own monitor on its side.
      exec "$KIOSK_SH" "$ROLE" localhost kiosk normal
      ;;

  open)
      ensure_profile_root
      PROFILE="$KIOSK_ROOT/$(id -un)-$ROLE"
      mkdir -p "$PROFILE"
      CHROME="$(command -v chromium-browser || command -v chromium || command -v google-chrome)"
      [ -n "$CHROME" ] || { echo "[!] no Chromium found — apt install chromium"; exit 1; }
      echo "[*] opening $URL  (profile: $PROFILE)"
      echo "    to install: ⋮ menu > Cast, save and share > Install page as app"
      # No --kiosk here on purpose: the menu has to be reachable to install.
      # --password-store=basic stops Chromium blocking on a system keyring prompt.
      exec "$CHROME" --user-data-dir="$PROFILE" --password-store=basic "$URL"
      ;;

  autostart)
      # System-wide, so it fires for whichever user the desktop logs in as — the
      # same reason rack-kiosk-setup.sh stopped writing into /home/pi.
      [ "$(id -u)" -eq 0 ] || { echo "[!] needs root: sudo $0 autostart $ROLE"; exit 1; }
      ensure_profile_root
      chmod +x "$KIOSK_SH"
      # May not exist on a base station that was never given a desktop.
      mkdir -p /etc/xdg/autostart
      cat > /etc/xdg/autostart/edgeathlete-kiosk.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Edge Athlete Kiosk ($ROLE)
Exec=$KIOSK_SH $ROLE localhost kiosk normal
X-GNOME-Autostart-enabled=true
EOF
      echo "[✔] $ROLE will launch at every desktop login (via localhost)"
      echo "    the base station must boot to a DESKTOP session for this to fire"
      ;;

  -h|--help|help) usage 0 ;;
  *) echo "[!] unknown command '$VERB'"; echo; usage 1 ;;
esac
