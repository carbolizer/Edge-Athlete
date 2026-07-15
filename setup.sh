#!/bin/bash
set -e

# setup.sh — one-time Edge Athlete base-station provisioner.
# Run this ONCE on a fresh Pi (sudo ./setup.sh). It installs the tools the base
# station needs (NetworkManager, Docker), loads the Wi-Fi adapter firmware,
# auto-detects the Wi-Fi device, and installs the systemd service that runs
# startup.sh on every boot. After this, the Pi comes up as its own access point
# with the complete Edge Athlete stack running.

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
  python3 \
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
umask 077
if [ -L ".env" ] || { [ -e ".env" ] && [ ! -f ".env" ]; }; then
    echo "[!] .env must be a regular file"
    exit 1
fi
if [ ! -f ".env" ]; then
    cp .env.example .env
fi

# Generate Pi credentials without exposing them in process arguments. The atomic
# replace prevents a partial configuration if provisioning is interrupted.
python3 - <<'PY'
from pathlib import Path
import os
import secrets
import tempfile

path = Path('.env')
if path.is_symlink() or not path.is_file():
    raise SystemExit('.env must be a regular file')
path.chmod(0o600)
values = {}
order = []
for line in path.read_text().splitlines():
    if line and not line.startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        values[key] = value
        order.append(key)

if values.get('SECRET_KEY') in {None, '', 'change-me-local-only'}:
    values['SECRET_KEY'] = secrets.token_hex(32)
if values.get('POSTGRES_PASSWORD') in {None, '', 'change-me-local-only'}:
    values['POSTGRES_PASSWORD'] = secrets.token_hex(24)
    values['DATABASE_URL'] = (
        f"postgresql://edgeathlete:{values['POSTGRES_PASSWORD']}@postgres:5432/edgeathlete"
    )
values['DEBUG'] = 'False'
values['EDGEATHLETE_BIND_ADDRESS'] = '192.168.4.1'
for key in ('SECRET_KEY', 'POSTGRES_PASSWORD', 'DATABASE_URL', 'DEBUG', 'EDGEATHLETE_BIND_ADDRESS'):
    if key not in order:
        order.append(key)

with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.env.', delete=False) as output:
    os.fchmod(output.fileno(), 0o600)
    output.write('\n'.join(f'{key}={values[key]}' for key in order) + '\n')
    output.flush()
    os.fsync(output.fileno())
    temporary = output.name
os.replace(temporary, path)
path.chmod(0o600)

config_dir = Path('/etc/edgeathlete')
if config_dir.is_symlink() or (config_dir.exists() and not config_dir.is_dir()):
    raise SystemExit('/etc/edgeathlete must be a real directory')
config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
config_dir.chmod(0o700)
ap_path = config_dir / 'ap.env'
if ap_path.is_symlink() or (ap_path.exists() and not ap_path.is_file()):
    raise SystemExit('/etc/edgeathlete/ap.env must be a regular file')
if not ap_path.exists():
    with tempfile.NamedTemporaryFile('w', dir=config_dir, prefix='ap.', delete=False) as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(f'AP_PASSWORD={secrets.token_hex(16)}\n')
        output.flush()
        os.fsync(output.fileno())
        temporary = output.name
    os.replace(temporary, ap_path)
ap_path.chmod(0o600)
PY

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

echo "[10.5] writing root-only NetworkManager AP profile..."
nmcli connection delete EdgeAthlete-AP >/dev/null 2>&1 || true
WIFI_IFACE="$WIFI_IFACE" python3 - <<'PY'
from pathlib import Path
import os
import tempfile
import uuid

secret_path = Path('/etc/edgeathlete/ap.env')
password = secret_path.read_text().strip().removeprefix('AP_PASSWORD=')
if not 8 <= len(password) <= 63:
    raise SystemExit('AP_PASSWORD must contain 8-63 characters')

profile_dir = Path('/etc/NetworkManager/system-connections')
profile = profile_dir / 'EdgeAthlete-AP.nmconnection'
if profile.is_symlink() or (profile.exists() and not profile.is_file()):
    raise SystemExit('NetworkManager AP profile must be a regular file')
body = f'''[connection]
id=EdgeAthlete-AP
uuid={uuid.uuid4()}
type=wifi
interface-name={os.environ["WIFI_IFACE"]}
autoconnect=true

[wifi]
band=bg
channel=6
mode=ap
ssid=EdgeAthlete

[wifi-security]
key-mgmt=wpa-psk
psk={password}

[ipv4]
address1=192.168.4.1/24
method=shared

[ipv6]
method=disabled
'''
with tempfile.NamedTemporaryFile('w', dir=profile_dir, prefix='.edgeathlete.', delete=False) as output:
    os.fchmod(output.fileno(), 0o600)
    output.write(body)
    output.flush()
    os.fsync(output.fileno())
    temporary = output.name
os.replace(temporary, profile)
profile.chmod(0o600)
PY
nmcli connection reload

echo "[11] building docker stack..."
docker compose build

echo "[✔] setup complete"
echo "Next:"
echo "  1. reboot"
echo "  2. service should run automatically"
echo "  3. retrieve the AP password locally with: sudo cat /etc/edgeathlete/ap.env"
echo ""
echo "Manual start command:"
echo "  systemctl start edgeathlete.service"
