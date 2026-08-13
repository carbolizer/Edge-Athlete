#!/usr/bin/env bash
# apply-wifi.sh — apply a Wi-Fi password change the coach app requested.
#
# THE "WORK-ORDER SLIP" HANDSHAKE (this file is one of six that share it).
# Picture the base station as a building. The coach app is a front-desk clerk
# with no keys to the electrical panel (the network); changing the Wi-Fi means
# flipping a switch on that panel, which is a root-only job. So the clerk just
# writes the new password on a work-order slip (a spool file) and drops it in an
# inbox tray.
#
# THIS SCRIPT IS THE MAINTENANCE WORKER. It is the one with the keys. A systemd
# path-unit keeps it watching the inbox tray; when a slip appears it picks it up,
# checks the slip is sane, flips the switch (runs nmcli, as root, on the host),
# and bins the slip. Keeping the keys here — out of the exposed web container —
# is the whole point. See wifi_config.py for the clerk's side.
#
# Triggered by edgeathlete-wifi-apply.path (installed by setup.sh). Not run by
# hand normally, but safe to: with no request file it does nothing.
#
# ORDER OF OPERATIONS, and why:
#   1. read the request, then DELETE it immediately. A malformed request must
#      never sit there re-triggering the path-unit in a loop. Consume first.
#   2. validate. Django already did, but a file on disk is not a trusted caller.
#   3. update basestation.conf — the documented source of truth — so a later
#      profile recreation uses the new password too.
#   4. apply live via nmcli. This is what actually changes the AP and drops every
#      connected device; it runs LAST so a validation failure never touches a
#      working AP.
# If power is lost between 1 and 4 the change is simply lost and the old password
# still works — a safe failure. The coach can retry from the app.

set -euo pipefail

# Paths are overridable so the test harness can point them at temp files instead
# of the real /etc and /var/lib. Same pattern as WIFI_APPLY_SPOOL on the Django
# side.
CONFIG_FILE="${EDGE_CONFIG:-/etc/edgeathlete/basestation.conf}"
STATE_DIR="${EDGE_STATE:-/var/lib/edgeathlete}"
REQUEST="$STATE_DIR/wifi-apply.request"

# Default, then let the config override it — the applier needs the connection name
# to tell nmcli which profile to change.
CONNECTION_NAME="EdgeAthlete-AP"
if [ -f "$CONFIG_FILE" ]; then
    # shellcheck source=/dev/null
    . "$CONFIG_FILE"
fi

log() { echo "[apply-wifi] $*"; }

# No request is not an error — the path-unit can fire a touch late, after an
# earlier run already consumed the file.
if [ ! -f "$REQUEST" ]; then
    log "no request pending, nothing to do"
    exit 0
fi

NEW_PW="$(head -n1 "$REQUEST" | tr -d '\r\n')"

# Consume it NOW, before doing anything that can fail, so a bad request cannot
# loop forever.
rm -f "$REQUEST"

# Validate (defense in depth). WPA2-PSK is 8..63 printable ASCII.
length=${#NEW_PW}
if [ "$length" -lt 8 ] || [ "$length" -gt 63 ]; then
    log "REJECTED: password length $length is outside 8..63 — AP left unchanged"
    exit 1
fi
if printf '%s' "$NEW_PW" | LC_ALL=C grep -q '[^ -~]'; then
    log "REJECTED: password has non-printable or non-ASCII characters — AP left unchanged"
    exit 1
fi

# Update the source-of-truth config. Strip + re-append rather than sed-replace:
# a password can contain characters sed treats specially. Same trick setup.sh
# uses for SECRET_KEY.
if [ -f "$CONFIG_FILE" ]; then
    grep -v '^AP_PASSWORD=' "$CONFIG_FILE" > "$CONFIG_FILE.tmp"
    echo "AP_PASSWORD=\"$NEW_PW\"" >> "$CONFIG_FILE.tmp"
    mv "$CONFIG_FILE.tmp" "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"       # it holds the Wi-Fi password
    log "updated $CONFIG_FILE"
fi

# Give the screens their heads-up before we pull the rug. Django already
# broadcast the new password over MQTT when the request came in; this short pause
# makes sure every connected screen has actually received and shown it before the
# AP restarts and drops them. Without it, a fast apply could beat the broadcast.
# Overridable so the test harness can set it to 0 instead of waiting for real.
sleep "${EDGE_APPLY_DELAY:-3}"

# Apply live. modify persists the new key into the NetworkManager profile (so it
# survives a reboot); up re-applies it now, which is the moment every device
# drops and must rejoin with the new password.
log "applying new Wi-Fi password to '$CONNECTION_NAME'"
nmcli connection modify "$CONNECTION_NAME" 802-11-wireless-security.psk "$NEW_PW"
nmcli connection up "$CONNECTION_NAME"
log "done — every device must now reconnect with the new password"
