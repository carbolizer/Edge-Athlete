#!/bin/bash
set -e

# setup.sh — one-time Edge Athlete base-station provisioner.
# Run this ONCE on a fresh Pi (sudo ./setup.sh). It installs the tools the base
# station needs (NetworkManager, Docker), loads the Wi-Fi adapter firmware,
# auto-detects the Wi-Fi device, and installs the systemd service that runs
# startup.sh on every boot. After this, the Pi comes up as its own access point
# with the full stack running. Ported from Privacy-Dots-V2; names/paths changed.

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo ./setup.sh"
    exit 1
fi

echo "[1] normalizing repo name..."
cd /home/pi

if [ -d "Edge-Athlete" ] && [ ! -d "edge-athlete" ]; then
    mv Edge-Athlete edge-athlete
fi

PROJECT_DIR="/home/pi/edge-athlete"
cd "$PROJECT_DIR"

echo "[2] installing required tools..."
apt update
apt install -y \
  sudo \
  git \
  curl \
  network-manager \
  wpasupplicant \
  wireless-tools \
  net-tools \
  docker.io \
  docker-compose-plugin

echo "[3] enabling services..."
systemctl enable --now NetworkManager
systemctl enable --now docker

echo "[4] preparing firmware for Genbasic / MT7601U adapter..."
mkdir -p /lib/firmware

if [ -f "$PROJECT_DIR/mt7601u.bin" ]; then
    cp "$PROJECT_DIR/mt7601u.bin" /lib/firmware/mt7601u.bin
fi

if [ -f "$PROJECT_DIR/mt7601.bin" ]; then
    cp "$PROJECT_DIR/mt7601.bin" /lib/firmware/mt7601.bin
    cp "$PROJECT_DIR/mt7601.bin" /lib/firmware/mt7601u.bin
fi

modprobe mt7601u || true

echo "[5] preparing env file..."
if [ ! -f ".env" ]; then
    cp .env.example .env
fi

echo "[6] preparing startup script..."
chmod +x startup.sh

echo "[7] creating state flags..."
mkdir -p /var/lib/edgeathlete

echo "[8] creating systemd service..."
cat > /etc/systemd/system/edgeathlete.service <<EOF
[Unit]
Description=Edge Athlete Startup Service
After=network-online.target docker.service NetworkManager.service
Wants=network-online.target docker.service NetworkManager.service

[Service]
Type=oneshot
ExecStart=/home/pi/edge-athlete/startup.sh
RemainAfterExit=yes
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable edgeathlete.service

echo "[9] reducing docker log growth..."
mkdir -p /etc/docker

cat > /etc/docker/daemon.json <<EOF
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF

systemctl restart docker

echo "[10] checking wifi adapter..."
nmcli device status || true

WIFI_IFACE=$(nmcli -t -f DEVICE,TYPE device | grep ":wifi" | cut -d: -f1 | head -n 1)

if [ -z "$WIFI_IFACE" ]; then
    echo "[!] no wifi adapter detected by NetworkManager"
    echo "[!] check: lsusb, dmesg | grep mt7601, and /lib/firmware/mt7601u.bin"
    exit 1
fi

echo "[✔] wifi adapter detected: $WIFI_IFACE"

echo "[10.5] updating startup.sh wifi interface..."
sed -i "s/^WIFI_IFACE=.*/WIFI_IFACE=\"$WIFI_IFACE\"/" startup.sh

echo "[11] building docker stack..."
docker compose build

echo "[✔] setup complete"
echo " ===================== *****IMPORTANT**** ===================="
echo " MAKE SURE TO ADD .env FILE that FITS THE STRUCTURE OF .env.example "
echo "Next:"
echo "  1. update startup.sh WIFI_IFACE=\"$WIFI_IFACE\" if needed"
echo "  2. reboot"
echo "  3. service should run automatically"
echo ""
echo "Manual start command:"
echo "  systemctl start edgeathlete.service"
