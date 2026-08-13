#!/bin/bash
set -e

# rack-kiosk-setup.sh — one-time provisioner for an Edge Athlete SCREEN.
#
#   sudo scripts/rack-screen/rack-kiosk-setup.sh [role]
#
#   role   rack | coach | dashboard      (default: rack)
#
# You normally do NOT run this by hand. rack-bootstrap.sh is the one command that
# provisions a rack screen from nothing, and it calls this with `rack`. Run it
# directly only for a coach tablet, or to re-provision.
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
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

AGENT_CONF="/etc/edgeathlete/rack-agent.conf"
AGENT_SERVICE="/etc/systemd/system/edgeathlete-rack-agent.service"
# BLE address of this rack's WT901 sensor. Empty until you have run
# `python3 wt901_rack_agent.py --scan` and filled it in.
BLE_ADDRESS="${BLE_ADDRESS:-}"
NODE_ID="${NODE_ID:-}"
MQTT_HOST="${MQTT_HOST:-$KIOSK_HOST}"
MQTT_PORT="${MQTT_PORT:-1883}"
# WT901 output rate (samples/second). MUST match the sensor's configured rate:
# set it on the sensor with WitMotion's config tool, then mirror it here.
SENSOR_HZ="${SENSOR_HZ:-50}"
AGENT_VENV="/opt/edgeathlete/rack-agent-venv"

AUTOSTART_FILE=/etc/xdg/autostart/edgeathlete-kiosk.desktop
COACH_ICON=/usr/share/applications/edgeathlete-coach.desktop

# ── installing the launcher ─────────────────────────────────────────────────────
#
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
#
# EACH BRANCH DELETES THE OTHER'S ARTIFACT, and that is load-bearing on a RE-RUN.
# Provision a box as `rack`, later re-run it as `coach`, and without the deletes it
# would keep the old autostart entry alongside the new coach icon — a device acting
# as two roles at once, with a full-screen kiosk seizing the screen at every login
# on a tablet that is supposed to be hand-held.
install_launcher() {
    chmod +x "$SCRIPT_DIR/kiosk.sh"

    if [ "$ROLE" = "coach" ]; then
        echo "    installing the coach launcher icon..."
        rm -f "$AUTOSTART_FILE"
        mkdir -p "$(dirname "$COACH_ICON")"
        cat > "$COACH_ICON" <<EOF
[Desktop Entry]
Type=Application
Name=Edge Athlete — Coach
Comment=Open the coach console. Use the browser menu to install it as an app.
Exec=$SCRIPT_DIR/kiosk.sh coach $KIOSK_HOST once
Icon=$SCRIPT_DIR/../../react/public/icon-coach-192.png
Terminal=false
StartupWMClass=Chromium
Categories=Utility;
EOF
        command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database || true
        echo "    tap 'Edge Athlete — Coach' in the app list, then install it from the"
        echo "    browser's ⋮ menu to get a proper full-screen app icon."
    else
        echo "    installing the kiosk launcher to run at login..."
        rm -f "$COACH_ICON"
        # /etc/xdg/autostart is the SYSTEM-WIDE version of ~/.config/autostart: every
        # desktop session reads it, whoever is logged in. That is the whole point.
        # mkdir because a minimal desktop image may not have created it yet, and a bare
        # redirect into a missing directory fails at the last step.
        mkdir -p "$(dirname "$AUTOSTART_FILE")"
        cat > "$AUTOSTART_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Edge Athlete Kiosk ($ROLE)
Exec=$SCRIPT_DIR/kiosk.sh $ROLE $KIOSK_HOST kiosk
X-GNOME-Autostart-enabled=true
EOF
    fi
}

echo "[1] installing Chromium + kiosk helpers..."
apt update
# Package name differs by image: chromium-browser (older) vs chromium (newer).
# procps supplies pkill, which ea-restart and ea-kiosk-exit both depend on. Without
# it they print a cheerful message and do nothing, which is worse than failing.
apt install -y network-manager x11-xserver-utils unclutter curl procps
apt install -y chromium-browser || apt install -y chromium

# ── the rack sensor agent ──────────────────────────────────────────────────────
# A rack screen owns the WT901 sensor bolted to its rack. The agent reads the
# sensor over BLE, detects reps, and publishes them (plus a heartbeat) to the
# base station's Mosquitto. It runs as a systemd service so it survives the
# browser, reboots, and Wi-Fi drops.
#
# NODE_ID defaults to the rack's role suffix when we are provisioning a rack.
# The BLE address has to come from a live scan (`wt901_rack_agent.py --scan`),
# so it is never guessable here; leave BLE_ADDRESS empty and the service stays
# disabled until you fill in /etc/edgeathlete/rack-agent.conf.
if [ "$ROLE" = "rack" ]; then
    echo "[1b] installing the WT901 rack sensor agent..."

    if [ -z "${NODE_ID:-}" ]; then
        echo "    NODE_ID not set — using 'rack_1' (override with NODE_ID=rack_N)"
        NODE_ID="rack_1"
    fi

    # A venv keeps the hardware deps (bleak, paho-mqtt) off the system Python.
    if [ ! -x "$AGENT_VENV/bin/python" ]; then
        apt install -y python3 python3-venv
        python3 -m venv "$AGENT_VENV"
    fi
    "$AGENT_VENV/bin/pip" install --quiet --upgrade pip
    "$AGENT_VENV/bin/pip" install --quiet -r "$PROJECT_DIR/scripts/hardware/requirements.txt"

    # Machine-owned config, outside git, written once and never overwritten —
    # the same pattern as basestation.conf. BLE_ADDRESS is the part only a
    # physical scan can fill in.
    mkdir -p /etc/edgeathlete
    if [ ! -f "$AGENT_CONF" ]; then
        cat > "$AGENT_CONF" <<EOF
NODE_ID=$NODE_ID
BLE_ADDRESS=$BLE_ADDRESS
MQTT_HOST=$MQTT_HOST
MQTT_PORT=$MQTT_PORT
SENSOR_HZ=$SENSOR_HZ
EOF
        chmod 600 "$AGENT_CONF"
        echo "    wrote $AGENT_CONF"
    else
        echo "    $AGENT_CONF already exists — left alone"
        # shellcheck source=/dev/null
        . "$AGENT_CONF"
    fi

    cat > "$AGENT_SERVICE" <<EOF
[Unit]
Description=Edge Athlete WT901 rack sensor agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$AGENT_CONF
ExecStart=$AGENT_VENV/bin/python $PROJECT_DIR/scripts/hardware/wt901_rack_agent.py \\
    --address \$BLE_ADDRESS --node-id \$NODE_ID \\
    --mqtt-host \$MQTT_HOST --mqtt-port \$MQTT_PORT \\
    --base-url http://\$MQTT_HOST \\
    --hz \${SENSOR_HZ:-50}
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

    if [ -n "${BLE_ADDRESS:-}" ]; then
        systemctl enable --now "$(basename "$AGENT_SERVICE")"
        echo "    rack sensor agent enabled (BLE_ADDRESS set)"
    else
        systemctl disable "$(basename "$AGENT_SERVICE")" >/dev/null 2>&1 || true
        echo "    rack sensor agent NOT enabled — run"
        echo "      python3 $PROJECT_DIR/scripts/hardware/wt901_rack_agent.py --scan"
        echo "    then set BLE_ADDRESS in $AGENT_CONF and: systemctl enable --now edgeathlete-rack-agent"
    fi

    # ── the NFC reader agent ───────────────────────────────────────────────────
    # Reads the rack's NFC wristband reader and exposes one-time taps on the same
    # /run/edgeathlete socket Django talks to. Needs the pyusb dep already
    # installed above and the reader plugged in at boot; without the reader the
    # service stays alive and retries.
    echo "    installing the NFC reader agent..."
    NFC_RACK_NUMBER="$(printf '%s' "$NODE_ID" | sed 's/.*[^0-9]\([0-9]*\)$/\1/')"
    [ -n "$NFC_RACK_NUMBER" ] || NFC_RACK_NUMBER=1
    NFC_AGENT_CONF="/etc/edgeathlete/nfc-agent.conf"
    NFC_AGENT_SERVICE="/etc/systemd/system/edgeathlete-nfc-agent.service"
    if [ ! -f "$NFC_AGENT_CONF" ]; then
        cat > "$NFC_AGENT_CONF" <<EOF
RACK_NUMBER=$NFC_RACK_NUMBER
NFC_SOCKET_PATH=/run/edgeathlete/nfc-agent.sock
EOF
        chmod 600 "$NFC_AGENT_CONF"
        echo "    wrote $NFC_AGENT_CONF"
    fi

    cat > "$NFC_AGENT_SERVICE" <<EOF
[Unit]
Description=Edge Athlete NFC rack reader agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$NFC_AGENT_CONF
ExecStart=$AGENT_VENV/bin/python $PROJECT_DIR/scripts/hardware/ccid_rack_agent.py \\
    --socket-path \$NFC_SOCKET_PATH \\
    --rack-number \${RACK_NUMBER:-1} \\
    --http-port 8766 \\
    --allowed-origins http://basestation,http://192.168.4.1,http://localhost,http://127.0.0.1
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF
    systemctl enable --now "$(basename "$NFC_AGENT_SERVICE")"
    echo "    NFC reader agent enabled"
fi

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

echo "[5] installing the launcher..."
install_launcher

echo "[5b] installing the short commands..."
# Real executables on PATH, one symlink per name. NOT sourced from /etc/profile.d,
# which only login shells read — that version was missing from desktop terminals,
# from `ssh host 'ea-update'`, and from any already-open session. See the header of
# scripts/basestation/ea.sh for the full story.
#
# ⚠️ THIS IS THE SCREEN'S ea.sh, NOT THE BASE STATION'S. They both provide
# `ea-update` and they point at different bootstraps — see either file's header.
# Linking the wrong one here would give a rack tablet a command that installs Docker
# and stands up a competing WiFi access point.
mkdir -p /usr/local/bin
for cmd in ea ea-update ea-restart ea-kiosk-log ea-kiosk-exit ea-help; do
    ln -sfn "$SCRIPT_DIR/ea.sh" "/usr/local/bin/$cmd"
done
chmod +x "$SCRIPT_DIR/ea.sh"
# The old sourced version would shadow these with stale functions in login shells.
rm -f /etc/profile.d/edge-athlete.sh

echo "[6] keeping the screen awake..."
# A screen that suspends mid-set looks identical to one that crashed, and unlike a
# blanked screen it does not come back on a tap — someone has to find a keyboard.
# Masked outright: there is no moment when a rack screen should suspend itself.
#
# This is the same fix the base station got, for the same reason. The base station's
# version was written first, after a monitor was plugged in and the machine put
# itself to sleep. Rack screens have the identical exposure and nobody had checked.
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target \
    >/dev/null 2>&1 || true
echo "    suspend/hibernate masked"

# The screen LOCK is handled in kiosk.sh instead, not here, because those settings
# are per-user and only exist inside a running session — see the gsettings block
# there. Worth knowing this screen is NOT exposed to the trap the base station hit:
# it autologins an ordinary account whose password someone actually knows, rather
# than a locked-password kiosk account that no password can unlock.

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
echo ""
echo "  SHORT COMMANDS (available right now — no re-login, no sourcing)"
echo "    ea-update      pull latest code and re-provision this screen"
echo "    ea-restart     restart the browser, keeping this screen's identity"
echo "    ea-kiosk-log   what the launcher printed — read this if it comes up blank"
echo "    ea-help        the full list"
