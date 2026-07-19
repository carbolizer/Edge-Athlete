#!/bin/bash
set -e

# startup.sh — Edge Athlete base-station boot script.
# Runs automatically on Pi boot (via edgeathlete.service). It turns the Pi's
# Wi-Fi adapter into a private access point — the gym's own closed network that
# never touches the internet — then brings the whole Docker stack up. Tablets,
# the wall display, and the coach device all join THIS network and reach the
# base station at http://basestation. Ported from Privacy-Dots-V2; only the
# names, SSID, and paths changed.
#
# Install (done for you by setup.sh):
#   Service file:  /etc/systemd/system/edgeathlete.service
#   ExecStart:     /home/pi/edge-athlete/scripts/basestation/startup.sh
#   Enable:        sudo systemctl daemon-reload && sudo systemctl enable edgeathlete.service
#   Executable:    chmod +x scripts/basestation/startup.sh
#
# NOTE: PROJECT_DIR below is the REPO ROOT (where docker-compose.yml lives), not
# this script's folder — that's why the docker stack still comes up correctly
# even though this script now lives under scripts/basestation/.

##################################### BEGIN SCRIPT ###################################

# Define all system settings (Wi-Fi name, password, paths, etc.)
AP_NAME="EdgeAthlete"              # Wi-Fi name users will see
AP_PASSWORD="ChangeMe123!"         # Wi-Fi password (change before any real use)
WIFI_IFACE="wlan0"                 # Physical Wi-Fi device (setup.sh auto-detects and rewrites this)
CONNECTION_NAME="EdgeAthlete-AP"   # Internal name used by the system
AP_IP_CIDR="192.168.4.1/24"        # IP range for connected devices
AP_IP="${AP_IP_CIDR%%/*}"          # IP the AP maps the base-station domain to
PROJECT_DIR="/home/pi/edge-athlete"

# Create flags to track setup and default password state
STATE_DIR="/var/lib/edgeathlete"   # directory in linux var files to track which state sys is in
SETUP_COMPLETE_FLAG="$STATE_DIR/setup_complete.flag"
DEFAULT_FLAG="$STATE_DIR/default_ap_password.flag"

mkdir -p "$STATE_DIR"

# Run only once: mark that default password is active on first setup
if [ ! -f "$SETUP_COMPLETE_FLAG" ]; then         # Check if we completed init setup
    echo "[*] First boot detected"
    # Set the Linux hostname so users can access the base station with:
    # http://basestation
    hostnamectl set-hostname basestation

    # Tell connected devices that "basestation" points to the Pi AP IP
    mkdir -p /etc/NetworkManager/dnsmasq-shared.d

    cat > /etc/NetworkManager/dnsmasq-shared.d/basestation.conf <<EOF
address=/basestation/$AP_IP
EOF

    touch "$DEFAULT_FLAG"                       # Flag that default password is still being used
    touch "$SETUP_COMPLETE_FLAG"                # Flag that init setup has been completed (doesnt rerun)
fi

# Start NetworkManager to control network connections
echo "[1] Starting NetworkManager..."
systemctl restart NetworkManager
sleep 2

# Bring up existing Wi-Fi access point, or create it if missing
echo "[2] Bringing up AP mode..."
# nmcli - Network command line interface
nmcli connection up "$CONNECTION_NAME" || {
    echo "[!] AP profile not found. Creating it now..."

    # Create new Wi-Fi access point profile
    nmcli connection add type wifi ifname "$WIFI_IFACE" con-name "$CONNECTION_NAME" autoconnect yes ssid "$AP_NAME"

    # Configure Wi-Fi settings (mode, password, IP range, etc.)
    nmcli connection modify "$CONNECTION_NAME" \
      802-11-wireless.mode ap \
      802-11-wireless.band bg \
      802-11-wireless.channel 6 \
      802-11-wireless-security.key-mgmt wpa-psk \
      802-11-wireless-security.psk "$AP_PASSWORD" \
      ipv4.method shared \
      ipv4.addresses "$AP_IP_CIDR" \
      ipv6.method ignore \
      connection.autoconnect yes \
      connection.permissions ""

    # Activate the access point
    nmcli connection up "$CONNECTION_NAME"
}

# Give the network time to fully come online
echo "[3] Waiting for AP/network to fully initialize..."
sleep 5

# Start all backend services (Django, React, DB, etc.)
echo "[4] Starting Edge Athlete Docker stack..."
cd "$PROJECT_DIR" || {
    echo "[!] Project directory not found: $PROJECT_DIR"
    exit 1
}
# Support both old and new Docker Compose formats
if command -v docker-compose >/dev/null 2>&1; then
    docker-compose up -d
else
    docker compose up -d
fi

# Confirm system is running
echo "[✔] Edge Athlete base-station startup complete"
nmcli connection show --active
