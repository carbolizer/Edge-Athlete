#!/usr/bin/env bash
# setup.sh — one-time Edge Athlete base-station provisioner.
#
# Installs everything the base station needs (NetworkManager, Docker), writes
# the machine's own config file, and installs the systemd service that runs
# startup.sh on every boot. After this the box comes up as its own Wi-Fi access
# point with the whole stack running.
#
# Normally you never call this directly — bootstrap.sh does, right after it
# clones the repo. Run it by hand only to re-provision an existing install:
#
#   sudo /srv/edge-athlete/Edge-Athlete/scripts/basestation/setup.sh
#
# IT WORKS FROM WHEREVER THE REPO IS. Nothing below hardcodes a path; the script
# finds the repo root from its own location. Clone to /srv, /opt, or a home
# directory while testing — it provisions whatever it is sitting in. The old Pi
# version hardcoded /home/pi/edge-athlete, so the base station depended on which
# user was logged in and on the repo being renamed after cloning.
#
# HARDWARE: this targets an ordinary x86 mini PC (a Dell OptiPlex) running
# Debian or Ubuntu. The Raspberry Pi's MT7601U USB Wi-Fi firmware step is gone —
# it only ever existed for the dongle on the Pi, and copying firmware for a
# chipset that isn't present did nothing but confuse the log.

set -euo pipefail

# ── where am I? ─────────────────────────────────────────────────────────────
# Resolve the repo root from this script's own path (scripts/basestation/ -> up
# two). `pwd -P` resolves symlinks, so a symlinked install still lands on the
# real directory rather than one that vanishes on the next boot.
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/../.." >/dev/null 2>&1 && pwd -P)"

CONFIG_DIR="/etc/edgeathlete"
CONFIG_FILE="$CONFIG_DIR/basestation.conf"
STATE_DIR="/var/lib/edgeathlete"
SERVICE_FILE="/etc/systemd/system/edgeathlete.service"

if [ "$(id -u)" -ne 0 ]; then
    echo "[!] please run as root: sudo $0"
    exit 1
fi

# Prove we actually found the repo before touching the machine. A wrong
# PROJECT_DIR would otherwise surface much later, as a boot service that fails
# every reboot for no visible reason.
if [ ! -f "$PROJECT_DIR/docker-compose.yml" ]; then
    echo "[!] no docker-compose.yml at $PROJECT_DIR"
    echo "[!] this script must stay inside the repo, at scripts/basestation/setup.sh"
    exit 1
fi

echo "[1] found the repo at $PROJECT_DIR"
cd "$PROJECT_DIR"

echo "[2] installing required tools..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  ca-certificates \
  curl \
  git \
  network-manager \
  wireless-tools \
  iw \
  net-tools

echo "[3] installing Docker..."
# Docker's own installer, not the distro's docker.io. The distro packages split
# Docker and Compose across releases and lag badly — on some Ubuntu versions
# `docker compose` simply isn't there — and this stack is nothing without
# Compose v2. Skipped entirely when Docker is already present, so re-running
# setup never reinstalls it.
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "    already present, skipping"
else
    curl -fsSL https://get.docker.com | sh
fi

echo "[4] enabling services..."
systemctl enable --now NetworkManager
systemctl enable --now docker

echo "[5] preparing env file..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "    created .env from .env.example"
else
    echo "    .env already exists, left alone"
fi

echo "[6] detecting the Wi-Fi adapter..."
# The base station BROADCASTS its own network, so it needs a Wi-Fi device that
# can run in AP mode. A wired-only OptiPlex will fail here, which is the correct
# outcome: better a clear error now than a box that boots with no gym network.
WIFI_IFACE="$(nmcli -t -f DEVICE,TYPE device 2>/dev/null | grep ':wifi$' | cut -d: -f1 | head -n 1 || true)"

if [ -z "$WIFI_IFACE" ]; then
    echo "[!] NetworkManager sees no Wi-Fi adapter."
    echo "[!] The base station has to broadcast the gym's network, so it needs one."
    echo "[!] Check:  nmcli device status   /   lsusb   /   lspci | grep -i net"
    echo "[!] If this box is wired-only, add a USB Wi-Fi adapter that supports AP mode."
    exit 1
fi
echo "    found: $WIFI_IFACE"

echo "[7] writing $CONFIG_FILE..."
# THE MACHINE'S SETTINGS LIVE OUTSIDE THE REPO, and that is the point.
#
# The old setup.sh ran `sed -i` on startup.sh to bake the interface name into a
# TRACKED FILE. That left the repo permanently dirty, so the next `git pull` on
# the base station hit a conflict on a machine with nobody around to resolve it
# — and the Wi-Fi password sat in git besides.
#
# Written once and never overwritten: change the AP name or password here and
# re-running setup (or updating the code) will not stamp on it.
mkdir -p "$CONFIG_DIR"
if [ -f "$CONFIG_FILE" ]; then
    echo "    already exists, left alone (delete it to regenerate)"
else
    cat > "$CONFIG_FILE" <<EOF
# Edge Athlete base station — this machine's settings.
# Not in git. Edit freely; setup.sh will not overwrite it.
# Applied on the next boot, or: sudo systemctl restart edgeathlete.service

AP_NAME="EdgeAthlete"              # the Wi-Fi name people see
AP_PASSWORD="ChangeMe123!"         # ⚠️ CHANGE THIS before the gym uses it
WIFI_IFACE="$WIFI_IFACE"           # detected by setup.sh
CONNECTION_NAME="EdgeAthlete-AP"   # NetworkManager profile name
AP_IP_CIDR="192.168.4.1/24"        # the base station's address + the range it hands out
EOF
    chmod 600 "$CONFIG_FILE"       # it holds the Wi-Fi password
    echo "    written (Wi-Fi password is in here — chmod 600)"
fi

echo "[8] creating state directory..."
mkdir -p "$STATE_DIR"

echo "[9] installing the boot service..."
chmod +x "$PROJECT_DIR/scripts/basestation/startup.sh"
# ExecStart is written with the RESOLVED path, so the unit always points at
# wherever this install actually is. Regenerated on every run, which is what
# makes moving the install a matter of re-running setup from its new home.
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Edge Athlete Base Station
After=network-online.target docker.service NetworkManager.service
Wants=network-online.target docker.service NetworkManager.service

[Service]
Type=oneshot
ExecStart=$PROJECT_DIR/scripts/basestation/startup.sh
RemainAfterExit=yes
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable edgeathlete.service

echo "[10] capping docker log growth..."
# Without this the JSON logs grow until the disk fills. A gym runs this box for
# months without anyone looking at it.
mkdir -p /etc/docker
if [ ! -f /etc/docker/daemon.json ]; then
    cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
    systemctl restart docker
else
    echo "    /etc/docker/daemon.json already exists, left alone"
fi

echo "[11] building the stack (this takes a while the first time)..."
docker compose build

cat <<EOF

[✔] setup complete

  install     $PROJECT_DIR
  config      $CONFIG_FILE
  Wi-Fi       $WIFI_IFACE
  service     edgeathlete.service (starts on every boot)

NEXT:
  1. change AP_PASSWORD in $CONFIG_FILE  — it is still the default
  2. reboot, or: sudo systemctl start edgeathlete.service
  3. join the "EdgeAthlete" Wi-Fi and open http://basestation

Then fill it with demo data if you want one:
  cd $PROJECT_DIR && docker compose run --rm seed
EOF
