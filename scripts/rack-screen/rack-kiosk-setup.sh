#!/bin/bash
set -e

# rack-kiosk-setup.sh — one-time provisioner for an Edge Athlete SCREEN.
#
#   sudo scripts/rack-screen/rack-kiosk-setup.sh [role]
#
#   role   rack | coach | dashboard      (default: rack)
#
# A screen is the OPPOSITE of the base station. The base station (setup.sh) turns
# its machine into the WiFi ACCESS POINT and runs the server. A screen is a CLIENT:
# it JOINS the "EdgeAthlete" network and boots straight into full-screen Chromium.
# It runs no server and no Docker.
#
# Assumes an OS WITH A DESKTOP — kiosk mode needs a graphical session.
# It installs Chromium and helpers, joins the WiFi, turns on desktop autologin,
# and installs kiosk.sh to run at every login.
#
# ── NOTHING HERE DEPENDS ON WHICH USER IS LOGGED IN ─────────────────────────────
# This script used to hardcode the user `pi`: it wrote the autostart entry into
# /home/pi/.config and pointed the browser profile at that same home directory. So
# renaming the account, adding a second admin, or logging in as anyone else left a
# screen that autostarted nothing. Both of those now live in machine-owned paths —
# /etc/xdg/autostart for the launcher, /var/lib for the profile — which is the same
# correction bootstrap.sh already made when it moved the install to /srv.

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo scripts/rack-screen/rack-kiosk-setup.sh"
    exit 1
fi

ROLE="${1:-rack}"
case "$ROLE" in
  rack|coach|dashboard) ;;
  *) echo "unknown role '$ROLE' — expected rack, coach, or dashboard"; exit 1 ;;
esac

# ── settings — the WiFi values MUST match the base station's startup.sh ─────────
AP_SSID="${AP_SSID:-EdgeAthlete}"          # base station's WiFi name (startup.sh AP_NAME)
AP_PASSWORD="${AP_PASSWORD:-ChangeMe123!}" # base station's WiFi password
KIOSK_HOST="${KIOSK_HOST:-basestation}"    # `localhost` if this IS the base station
KIOSK_ROOT="/var/lib/edge-athlete/kiosk"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[1] installing Chromium + kiosk helpers..."
apt update
# Package name differs by image: chromium-browser (older) vs chromium (newer).
apt install -y network-manager x11-xserver-utils unclutter curl
apt install -y chromium-browser || apt install -y chromium

echo "[2] joining the '$AP_SSID' WiFi as a client..."
systemctl enable --now NetworkManager
if ! nmcli connection up "EdgeAthlete-client" 2>/dev/null; then
    nmcli device wifi connect "$AP_SSID" password "$AP_PASSWORD" name "EdgeAthlete-client" \
      || echo "[!] couldn't join '$AP_SSID' right now (is the base station powered on?) — NetworkManager will keep retrying"
fi
nmcli connection modify "EdgeAthlete-client" connection.autoconnect yes 2>/dev/null || true

echo "[3] enabling boot-to-desktop with autologin..."
if command -v raspi-config >/dev/null 2>&1; then
    raspi-config nonint do_boot_behaviour B4   # B4 = desktop, autologin
else
    echo "[!] raspi-config not found — enable desktop autologin yourself"
    echo "    (GNOME: /etc/gdm3/custom.conf, LightDM: /etc/lightdm/lightdm.conf)"
fi

echo "[4] making the browser profile directory..."
# 1777 = sticky and world-writable, exactly like /tmp. Any desktop user can create
# their own profile subdirectory without root, but cannot delete anyone else's.
# That is what lets the autostart entry below work for whoever actually logs in.
mkdir -p "$KIOSK_ROOT"
chmod 1777 "$KIOSK_ROOT"

chmod +x "$SCRIPT_DIR/kiosk.sh"

# A COACH TABLET IS NOT A KIOSK, and gets a different treatment.
# A rack screen and a wall display are unattended: they should boot straight into a
# locked full-screen browser and never be closed. A coach logs in, navigates, and
# legitimately puts the tablet down — auto-launching a menu-less full-screen window
# at every login would be a trap, not a feature.
#
# So a coach gets a tappable ICON instead of an autostart entry, opening a normal
# window. It still carries the trusted origin and the on-disk profile, which is what
# lets the app be installed and keep an offline copy. Once the coach installs it from
# the browser menu, Chromium writes its OWN launcher and runs the app standalone —
# full-screen, own icon, no browser chrome — so this icon is a one-time door.
if [ "$ROLE" = "coach" ]; then
    echo "[5] installing the coach launcher icon..."
    mkdir -p /usr/share/applications
    cat > /usr/share/applications/edgeathlete-coach.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Edge Athlete — Coach
Comment=Open the coach console. Use the browser menu to install it as an app.
Exec=$SCRIPT_DIR/kiosk.sh coach $KIOSK_HOST windowed
Terminal=false
Categories=Utility;
EOF
    echo "    tap 'Edge Athlete — Coach' in the app list, then install it from the"
    echo "    browser's ⋮ menu to get a proper full-screen app icon."
else
    echo "[5] installing the kiosk launcher to run at login..."
    # /etc/xdg/autostart is the SYSTEM-WIDE version of ~/.config/autostart: every
    # desktop session reads it, whoever is logged in. That is the whole point.
    # mkdir because a minimal desktop image may not have created it yet, and a bare
    # redirect into a missing directory fails the whole script at the last step.
    mkdir -p /etc/xdg/autostart
    cat > /etc/xdg/autostart/edgeathlete-kiosk.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Edge Athlete Kiosk ($ROLE)
Exec=$SCRIPT_DIR/kiosk.sh $ROLE $KIOSK_HOST
X-GNOME-Autostart-enabled=true
EOF
fi

echo "[6] keeping the screen awake..."
# The xset calls inside kiosk.sh only work under X11. Under Wayland (Raspberry Pi
# OS Bookworm defaults to labwc) they are silent no-ops and the screen blanks
# mid-set, which looks exactly like a crashed tablet. labwc reads this config.
if [ -d /etc/xdg/labwc ] || command -v labwc >/dev/null 2>&1; then
    mkdir -p /etc/xdg/labwc
    if ! grep -q "IdleExit" /etc/xdg/labwc/rc.xml 2>/dev/null; then
        echo "    labwc detected — disable screen blanking in /etc/xdg/labwc/rc.xml"
        echo "    (or: sudo raspi-config > Display Options > Screen Blanking > No)"
    fi
else
    echo "    X11 — kiosk.sh handles it with xset"
fi

echo ""
echo "[✔] kiosk setup complete."
echo "  role     $ROLE"
echo "  url      http://$KIOSK_HOST"
echo "  profile  $KIOSK_ROOT/<user>-$ROLE"
echo ""
echo "  Reboot to launch. FIRST boot on a rack shows the role picker — tap once;"
echo "  after a coach assigns it a rack, every reboot goes straight to the live screen."
echo "  That now actually holds: the profile is on disk, so the device keeps its id."
