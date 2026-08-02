#!/usr/bin/env bash
# startup.sh — Edge Athlete base-station boot script.
#
# Runs on every boot, via edgeathlete.service (installed by setup.sh). It turns
# the machine's Wi-Fi adapter into a private access point — the gym's own closed
# network, which never touches the internet — and then brings the Docker stack
# up. Tablets, the wall display and the coach device all join THIS network and
# reach the base station at http://basestation.
#
# You can also run it by hand to restart everything:
#   sudo systemctl restart edgeathlete.service
#
# TWO THINGS IT DOES NOT DO ANY MORE:
#
#  1. It does not hardcode /home/pi. The repo root is resolved from this
#     script's own location, so the install works from wherever it was cloned
#     and does not care which user is logged in.
#
#  2. It does not carry this machine's settings. The Wi-Fi name, password and
#     interface live in /etc/edgeathlete/basestation.conf, outside the repo.
#     setup.sh used to `sed -i` the interface name into this file, which left
#     the repo dirty and made the next update conflict — and put the gym's Wi-Fi
#     password in git.

set -euo pipefail

# ── where am I? ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/../.." >/dev/null 2>&1 && pwd -P)"

# ── settings ────────────────────────────────────────────────────────────────
# Defaults first, so this still runs on a machine where setup.sh has not written
# a config yet. The file wins wherever it says something.
AP_NAME="EdgeAthlete"
AP_PASSWORD="ChangeMe123!"
WIFI_IFACE="wlan0"
CONNECTION_NAME="EdgeAthlete-AP"
AP_IP_CIDR="192.168.4.1/24"

CONFIG_FILE="/etc/edgeathlete/basestation.conf"
if [ -f "$CONFIG_FILE" ]; then
    # shellcheck source=/dev/null
    . "$CONFIG_FILE"
    echo "[*] settings from $CONFIG_FILE"
else
    echo "[!] no $CONFIG_FILE — using built-in defaults (run setup.sh to create one)"
fi

AP_IP="${AP_IP_CIDR%%/*}"          # the address the base-station name resolves to

STATE_DIR="/var/lib/edgeathlete"
SETUP_COMPLETE_FLAG="$STATE_DIR/setup_complete.flag"
DEFAULT_FLAG="$STATE_DIR/default_ap_password.flag"

mkdir -p "$STATE_DIR"

# ── first boot only ─────────────────────────────────────────────────────────
if [ ! -f "$SETUP_COMPLETE_FLAG" ]; then
    echo "[*] first boot"

    # So everything on the network can use http://basestation instead of an IP.
    hostnamectl set-hostname basestation

    # Tell connected devices that "basestation" means this machine. NetworkManager
    # runs dnsmasq for a shared connection, and this drops an answer into it.
    mkdir -p /etc/NetworkManager/dnsmasq-shared.d
    cat > /etc/NetworkManager/dnsmasq-shared.d/basestation.conf <<EOF
address=/basestation/$AP_IP
EOF

    touch "$SETUP_COMPLETE_FLAG"
fi

# Track whether the Wi-Fi password is still the shipped default, so it can be
# surfaced rather than silently left in place for a season.
if [ "$AP_PASSWORD" = "ChangeMe123!" ]; then
    touch "$DEFAULT_FLAG"
else
    rm -f "$DEFAULT_FLAG"
fi

# ── the access point ────────────────────────────────────────────────────────
echo "[1] starting NetworkManager..."
systemctl restart NetworkManager
sleep 2

# ⚠️ A FAILING ACCESS POINT MUST NOT STOP THE STACK.
#
# This used to be a bare `nmcli ... || { ...create... }` under `set -e`, so any
# failure in here killed the boot script on the spot and the Docker stack never
# started. That is the worst of both outcomes: a base station with no gym Wi-Fi
# AND no application, which cannot even be reached over a cable to find out why.
#
# So the AP is attempted, and a failure is shouted about and carried — the app
# still comes up, still answers on the wired network, and the log says plainly
# what went wrong.
bring_up_ap() {
    # Existing profile? Just raise it.
    nmcli connection up "$CONNECTION_NAME" 2>/dev/null && return 0

    echo "    no AP profile yet — creating it"
    nmcli connection add type wifi ifname "$WIFI_IFACE" con-name "$CONNECTION_NAME" \
      autoconnect yes ssid "$AP_NAME" || return 1

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
      connection.permissions "" || return 1

    nmcli connection up "$CONNECTION_NAME" || return 1
}

echo "[2] bringing up the access point on $WIFI_IFACE..."
AP_UP=1
if bring_up_ap; then
    echo "    access point '$AP_NAME' is up"
else
    AP_UP=0
    echo "[!] ------------------------------------------------------------"
    echo "[!] COULD NOT START THE ACCESS POINT on $WIFI_IFACE."
    echo "[!] Tablets will not be able to join the gym network."
    echo "[!] Most likely: this adapter does not support AP mode."
    echo "[!]   check:  iw list | grep -A5 'Supported interface modes'"
    echo "[!]           nmcli device status"
    echo "[!] Carrying on so the app still comes up on the wired network."
    echo "[!] ------------------------------------------------------------"
fi

echo "[3] waiting for the network to settle..."
sleep 5

# ── the stack ───────────────────────────────────────────────────────────────
echo "[4] starting the Docker stack from $PROJECT_DIR..."
cd "$PROJECT_DIR" || {
    echo "[!] project directory not found: $PROJECT_DIR"
    exit 1
}

# Pass the Wi-Fi password through to the containers for the coach page's
# "still on the default password" warning. AP_PASSWORD was set above by sourcing
# the config file; exporting it lets docker compose substitute it into the django
# service. The value is only ever compared to the default and reported as a
# boolean — it is never sent anywhere.
export AP_PASSWORD

# The base-station overlay is added on top of the base compose file. It grants the
# django container the one host mount it needs so a Wi-Fi-password change from the
# app reaches the host agent. It lives only in startup.sh (i.e. only on a real
# base station) — a plain `docker compose up` on a dev box never includes it.
BASE_OVERLAY="$PROJECT_DIR/docker-compose.basestation.yml"
COMPOSE_ARGS=(-f "$PROJECT_DIR/docker-compose.yml")
[ -f "$BASE_OVERLAY" ] && COMPOSE_ARGS+=(-f "$BASE_OVERLAY")

# `docker compose` (v2, a plugin) is what setup.sh installs. The old
# docker-compose fallback is kept for a box provisioned before that, and because
# a boot script failing over a hyphen is a bad way to lose a gym's morning.
if docker compose version >/dev/null 2>&1; then
    docker compose "${COMPOSE_ARGS[@]}" up -d
elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "${COMPOSE_ARGS[@]}" up -d
else
    echo "[!] no docker compose available — run setup.sh"
    exit 1
fi

if [ "$AP_UP" -eq 1 ]; then
    echo "[✔] base station up — join '$AP_NAME' and open http://basestation"
else
    echo "[✔] app is up, but there is NO GYM WI-FI — see the access point error above"
fi
if [ -f "$DEFAULT_FLAG" ]; then
    echo "[!] the Wi-Fi password is STILL THE DEFAULT — change AP_PASSWORD in $CONFIG_FILE"
fi
nmcli connection show --active || true
