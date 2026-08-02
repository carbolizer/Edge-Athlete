#!/usr/bin/env bash
# apply-wifi.sh — apply a Wi-Fi password change the coach app requested.
#
# This is the PRIVILEGED HALF of "change the Wi-Fi password from the app". The
# web container is deliberately not allowed to run nmcli (it is the most exposed
# service; it must not be able to reconfigure the host network), so instead it
# drops the new password into a spool file. A systemd path-unit watches that file
# and runs THIS, as root, on the host — where the network privilege already
# lives. See wifi_config.py for the other half.
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

# Apply live. modify persists the new key into the NetworkManager profile (so it
# survives a reboot); up re-applies it now, which is the moment every device
# drops and must rejoin with the new password.
log "applying new Wi-Fi password to '$CONNECTION_NAME'"
nmcli connection modify "$CONNECTION_NAME" 802-11-wireless-security.psk "$NEW_PW"
nmcli connection up "$CONNECTION_NAME"
log "done — every device must now reconnect with the new password"
