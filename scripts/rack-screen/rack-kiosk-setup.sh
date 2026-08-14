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
  --agents-only) ROLE="rack" ;;
  *) echo "unknown role '$ROLE' — expected rack, coach, dashboard, or --agents-only"; exit 1 ;;
esac

# ── --agents-only mode ─────────────────────────────────────────────────────────
# Install ONLY the two hardware agents (the WT901 sensor agent and the NFC reader
# agent) as boot services, and stop — no Chromium, no Wi-Fi join, no kiosk, no
# desktop autologin. This is for a machine that is a general-purpose laptop (the
# rack screen runs in a normal browser) rather than a dedicated kiosk tablet.
#
# The agent block below expects to run as ROLE=rack, which we just forced. The
# deps + services logic is identical either way; only the steps AFTER the agent
# block are skipped.
AGENTS_ONLY=0
if [ "${1:-}" = "--agents-only" ]; then
  AGENTS_ONLY=1
  echo "==> agents-only: installing the WT901 + NFC reader boot services, then stopping"
fi

# ── settings — the WiFi values MUST match the base station's startup.sh ─────────
# Display rotation for THIS device: normal | left | right | inverted.
#
# A RACK tablet is bolted to its rack in PORTRAIT, so `rack` defaults to `right`.
# A coach's tablet is hand-held in landscape and is forced back to `normal`. The
# default is keyed on ROLE because this one script provisions both.
#
# `left` and `right` are both portrait — which one depends on the way the tablet
# is mounted. If the picture is upside down, flip it with `ea rotate-left`; no
# re-provisioning needed. Touch input is remapped to match, see rotate.sh.
#
# Override at install time with:  curl ... | sudo SCREEN_ROTATE=normal bash
#
# ── WHY RACK ONLY DEFAULTS ON A FIRST INSTALL ─────────────────────────────────
# If /etc/edgeathlete/screen.conf already exists, a rack install leaves it alone.
# Someone who turned a screen with `ea rotate-left` must not have it silently
# reset to `right` by the next `ea-update` — that is the same trap the autostart
# line had before rotation moved into this file.
#
# Coach and dashboard are the opposite: they FORCE normal, even over an existing
# file. Re-provisioning a rack tablet as a coach tablet has to undo the rack's
# portrait, or you get a sideways hand-held tablet. install_launcher() already
# treats a role change this way — each branch deletes the other's artifact — and
# rotation follows the same rule.
SCREEN_CONF="/etc/edgeathlete/screen.conf"
if [ -z "${SCREEN_ROTATE:-}" ]; then
    if [ "$ROLE" = "rack" ]; then
        [ -f "$SCREEN_CONF" ] || SCREEN_ROTATE="right"
    else
        SCREEN_ROTATE="normal"
    fi
fi

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

if [ "$AGENTS_ONLY" = 1 ]; then
    echo "[1] agents-only — skipping Chromium + kiosk helpers"
    # The package index still has to be refreshed. This mode skips the Chromium
    # block below, which is where `apt update` used to live — but it still runs
    # `apt install python3-venv` further down, and installing against a stale
    # index is how you get a 404 on a package that plainly exists.
    apt update
else
    echo "[1] installing Chromium + kiosk helpers..."
    apt update
    # Package name differs by image: chromium-browser (older) vs chromium (newer).
    # procps supplies pkill, which ea-restart and ea-kiosk-exit both depend on. Without
    # it they print a cheerful message and do nothing, which is worse than failing.
    apt install -y network-manager x11-xserver-utils unclutter curl procps
    apt install -y chromium-browser || apt install -y chromium
fi

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

    # A venv keeps the hardware deps off the system Python.
    #
    # ── WHY THE TWO AGENTS INSTALL SEPARATELY, AND WHY NEITHER IS FATAL ─────────
    # These used to be one `pip install -r requirements.txt`, unguarded, under
    # `set -e`. On Raspberry Pi OS Bullseye (Python 3.9) the bleak pin needs 3.10+,
    # so pip exited non-zero and took the ENTIRE provisioning run with it: no
    # Chromium, no kiosk launcher, no autostart — and no NFC reader either, even
    # though that agent talks to USB through pyusb and never imports bleak.
    #
    # A rack screen's first job is to be a screen. Losing a sensor it may not even
    # have attached must not cost you the browser. And the script already treats
    # the WT901 as optional further down (the service stays disabled without a
    # BLE_ADDRESS), so making its dependencies mandatory was inconsistent anyway.
    #
    # Each install now records its own outcome and only gates its own service.
    BLE_DEPS_OK=1
    NFC_DEPS_OK=1

    if [ ! -x "$AGENT_VENV/bin/python" ]; then
        # Unguarded, this line dies under `set -e` and takes the whole run with
        # it, printing nothing about why — the same failure mode the pip installs
        # below were split up to avoid. Say what happened and let the venv attempt
        # be the thing that decides whether the agents are possible.
        apt install -y python3 python3-venv \
            || echo "[!] could not install python3/python3-venv — trying the venv anyway"
        # If the venv itself cannot be built, neither agent is possible — but the
        # kiosk still is, so record it and carry on rather than aborting.
        python3 -m venv "$AGENT_VENV" || { BLE_DEPS_OK=0; NFC_DEPS_OK=0; }
    fi

    if [ -x "$AGENT_VENV/bin/python" ]; then
        PYVER="$("$AGENT_VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo unknown)"
        # A failed pip self-upgrade (usually no route to PyPI) is not a reason to
        # stop; the pinned installs below will report the real problem.
        "$AGENT_VENV/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 || true

        "$AGENT_VENV/bin/pip" install --quiet -r "$PROJECT_DIR/scripts/hardware/requirements-nfc.txt" \
            || NFC_DEPS_OK=0
        "$AGENT_VENV/bin/pip" install --quiet -r "$PROJECT_DIR/scripts/hardware/requirements-ble.txt" \
            || BLE_DEPS_OK=0

        [ "$NFC_DEPS_OK" = 1 ] || echo "[!] NFC reader dependencies failed to install — the reader will be skipped"
        if [ "$BLE_DEPS_OK" != 1 ]; then
            echo "[!] WT901 sensor dependencies failed to install — the BLE agent will be skipped"
            echo "    this machine runs Python $PYVER; bleak needs 3.10 or newer."
            echo "    Raspberry Pi OS Bullseye ships 3.9 — reimage to Bookworm for BLE."
            echo "    everything else (kiosk, NFC, MQTT nodes) still works on this machine."
        fi
    fi

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
    --hz \$SENSOR_HZ
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

    # Two independent reasons not to start it: no sensor address yet, or no bleak.
    # Starting it without either just produces a crash loop that reads like broken
    # hardware, so say which one it is instead.
    if [ "$BLE_DEPS_OK" != 1 ]; then
        systemctl disable "$(basename "$AGENT_SERVICE")" >/dev/null 2>&1 || true
        echo "    rack sensor agent NOT enabled — bleak is not installed on this machine"
        echo "    the unit was still written, so it will start once the deps are available"
    elif [ -n "${BLE_ADDRESS:-}" ]; then
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
# Creates /run/edgeathlete before the agent starts, and again after every reboot.
#
# WITHOUT THIS THE AGENT CANNOT START AT ALL. It binds a Unix socket at
# \$NFC_SOCKET_PATH, and asyncio.start_unix_server() raises FileNotFoundError when
# the parent directory is missing. /run is a tmpfs, so the directory does not
# survive a reboot and creating it by hand fixes nothing past the next power cycle.
#
# The failure is quiet and looks like a hardware fault. serve() runs BEFORE
# serve_http(), so the crash happens before the HTTP endpoint the rack browser
# polls ever opens — and with Restart=always below, the agent simply respawns
# every 5 seconds while the screen shows "Card reader unavailable". Check
# \`journalctl -u edgeathlete-nfc-agent\` before suspecting the reader.
#
# The manual instructions in guides/base-station.md do this with
# \`install -d /run/edgeathlete\`, which is why running the agent by hand works
# and provisioning it did not.
#
# Preserve=yes so the directory outlives a restart of this unit, and is still
# there if the WT901 agent is later given a socket in the same place.
RuntimeDirectory=edgeathlete
RuntimeDirectoryMode=0750
RuntimeDirectoryPreserve=yes
ExecStart=$AGENT_VENV/bin/python $PROJECT_DIR/scripts/hardware/ccid_rack_agent.py \\
    --socket-path \$NFC_SOCKET_PATH \\
    --rack-number \$RACK_NUMBER \\
    --http-port 8766 \\
    --allowed-origins http://basestation,http://192.168.4.1,http://localhost,http://127.0.0.1
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF
    # Gated on ITS OWN dependencies only. pyusb has no Python floor, so this
    # normally succeeds even where the BLE agent above could not be installed —
    # which is the whole reason the two requirement files are separate.
    if [ "$NFC_DEPS_OK" = 1 ]; then
        systemctl enable --now "$(basename "$NFC_AGENT_SERVICE")"
        echo "    NFC reader agent enabled"
    else
        systemctl disable "$(basename "$NFC_AGENT_SERVICE")" >/dev/null 2>&1 || true
        echo "    NFC reader agent NOT enabled — pyusb is not installed on this machine"
    fi
fi

if [ "$AGENTS_ONLY" = 1 ]; then
    # This summary used to list both agents unconditionally. On a Bullseye Pi
    # that meant printing "bleak could not be installed, skipping the BLE agent"
    # and then, three lines later, a green tick listing that same agent as
    # installed. A person might catch the contradiction; a script reading the
    # output just sees success. Report what was actually enabled — the same two
    # conditions the services themselves were gated on above.
    echo ""
    ENABLED=""
    if [ "$BLE_DEPS_OK" = 1 ] && [ -n "${BLE_ADDRESS:-}" ]; then
        ENABLED="$ENABLED  WT901 sensor agent  edgeathlete-rack-agent\n"
    fi
    if [ "$NFC_DEPS_OK" = 1 ]; then
        ENABLED="$ENABLED  NFC reader agent    edgeathlete-nfc-agent\n"
    fi

    if [ -n "$ENABLED" ]; then
        echo "[✔] agents-only setup complete. Enabled and starting on every boot:"
        printf "%b" "$ENABLED"
        echo ""
        echo "  Check: systemctl status edgeathlete-nfc-agent edgeathlete-rack-agent"
        echo "  Logs:  journalctl -u edgeathlete-nfc-agent"
    else
        echo "[!] agents-only setup finished, but NO agent was enabled."
        echo "    The unit files were written, so fixing the cause above and"
        echo "    re-running this is all it takes. Nothing else was changed."
    fi

    # Say the quiet part out loud rather than leaving it to be inferred from a
    # missing line in a list nobody reads closely.
    [ "$NFC_DEPS_OK" = 1 ] || echo "    NFC reader:  NOT enabled (pyusb missing)"
    if [ "$BLE_DEPS_OK" != 1 ]; then
        echo "    WT901 agent: NOT enabled (bleak missing — needs Python 3.10+)"
    elif [ -z "${BLE_ADDRESS:-}" ]; then
        echo "    WT901 agent: NOT enabled (no BLE_ADDRESS yet — scan for it, then re-run)"
    fi
    exit 0
fi

echo "[2] joining the '$AP_SSID' WiFi as a client..."
systemctl enable --now NetworkManager
if ! nmcli connection up "EdgeAthlete-client" 2>/dev/null; then
    nmcli device wifi connect "$AP_SSID" password "$AP_PASSWORD" name "EdgeAthlete-client" \
      || echo "[!] couldn't join '$AP_SSID' right now (is the base station powered on?) — NetworkManager will keep retrying"
fi
nmcli connection modify "EdgeAthlete-client" connection.autoconnect yes 2>/dev/null || true
# ⚠️ PRIORITY, not just autoconnect. Every NetworkManager connection defaults to
# priority 0, so "autoconnect yes" only means "this is eligible" — it does not mean
# "prefer this". A tablet that has ever joined a home or campus network has that
# saved too, equally eligible, and NetworkManager will cheerfully pick it instead.
# The screen then boots, looks connected, and cannot reach the base station at all.
#
# 100 is far above the default, so EdgeAthlete wins whenever it is in range.
#
# The other networks are deliberately LEFT ENABLED as a fallback. Disabling them
# would guarantee the right network in the gym and strand the tablet anywhere else
# — including on the bench where you need to ssh in and fix it.
nmcli connection modify "EdgeAthlete-client" connection.autoconnect-priority 100 2>/dev/null || true

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

# The device's saved orientation, read by kiosk.sh at every login and rewritten by
# `ea rotate-left`.
#
# ⚠️ AN EXISTING FILE IS LEFT ALONE unless SCREEN_ROTATE was explicitly passed.
# That is the whole reason this is a file and not a value baked into the autostart
# line: someone who turns a screen with `ea rotate-left` must not have it silently
# revert on the next `ea-update`. Same rule as rack-agent.conf — machine-owned
# config, outside git, provisioning does not stomp it.
mkdir -p /etc/edgeathlete
if [ -n "$SCREEN_ROTATE" ]; then
    printf 'SCREEN_ROTATE=%s\n' "$SCREEN_ROTATE" > "$SCREEN_CONF"
    echo "    rotation set to '$SCREEN_ROTATE'"
elif [ ! -f "$SCREEN_CONF" ]; then
    printf 'SCREEN_ROTATE=normal\n' > "$SCREEN_CONF"
else
    echo "    $SCREEN_CONF already exists — left alone (change it with: ea rotate-<dir>)"
fi

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
# ea-rotate is here as the bare name; the DIRECTION is a subcommand rather than a
# symlink per direction, so `ea rotate-left` and `ea-rotate left` both work without
# four more links in /usr/local/bin.
for cmd in ea ea-update ea-restart ea-rotate ea-kiosk-log ea-kiosk-exit ea-help; do
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
