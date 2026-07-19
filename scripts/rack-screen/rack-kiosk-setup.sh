#!/bin/bash
set -e

# rack-kiosk-setup.sh — one-time provisioner for an Edge Athlete RACK SCREEN.
#
# Run this ONCE on a fresh Raspberry Pi that will be a rack tablet, from the repo
# root:  sudo scripts/rack-screen/rack-kiosk-setup.sh
#
# A rack screen is the OPPOSITE of the base station. The base station (setup.sh)
# turns its Pi into the Wi-Fi ACCESS POINT and runs the server. A rack screen is a
# CLIENT: it JOINS the base station's "EdgeAthlete" network and boots straight into
# a full-screen Chromium pointed at the rack screen. It runs NO server/Docker.
#
# Assumes Raspberry Pi OS WITH DESKTOP — kiosk mode needs a graphical session.
# It: installs Chromium + helpers, joins the Wi-Fi as a client, turns on desktop
# autologin, and installs kiosk.sh (this folder) to run at every boot.
#
# Ported in spirit from the base-station setup.sh. It can only be truly tested on
# real Pi hardware; read the per-step notes if something doesn't come up.

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo scripts/rack-screen/rack-kiosk-setup.sh"
    exit 1
fi

# ── settings — the Wi-Fi values MUST match the base station's startup.sh ──
AP_SSID="EdgeAthlete"                  # base station's Wi-Fi name (startup.sh AP_NAME)
AP_PASSWORD="ChangeMe123!"             # base station's Wi-Fi password (startup.sh AP_PASSWORD)
KIOSK_URL="http://basestation/"        # rack screen; a wall display would use http://basestation/dashboard
KIOSK_USER="pi"                        # the desktop user that auto-logs in
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[1] installing Chromium + kiosk helpers..."
apt update
# Package name differs by image: chromium-browser (older) vs chromium (newer).
apt install -y network-manager x11-xserver-utils unclutter curl
apt install -y chromium-browser || apt install -y chromium

echo "[2] joining the '$AP_SSID' Wi-Fi as a client..."
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
    echo "[!] raspi-config not found — enable 'Desktop autologin' yourself (raspi-config > System > Boot)"
fi

echo "[4] installing the kiosk launcher to run at login..."
chmod +x "$SCRIPT_DIR/kiosk.sh"
AUTOSTART_DIR="/home/$KIOSK_USER/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/edgeathlete-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Edge Athlete Kiosk
Exec=$SCRIPT_DIR/kiosk.sh $KIOSK_URL
X-GNOME-Autostart-enabled=true
EOF
chown -R "$KIOSK_USER":"$KIOSK_USER" "/home/$KIOSK_USER/.config"

echo "[✔] rack-screen kiosk setup complete."
echo "  Kiosk URL: $KIOSK_URL"
echo "  (For a WALL display, re-run with KIOSK_URL changed to http://basestation/dashboard.)"
echo ""
echo "  Reboot to launch. FIRST boot shows the role picker — tap 'Rack Tablet' once;"
echo "  after a coach assigns it a rack, every reboot goes straight to the live screen."
echo ""
echo "  Bookworm (Wayland) note: if the kiosk doesn't auto-start, the ~/.config/autostart"
echo "  entry may not run under labwc — see the Wayland note in kiosk.sh."
