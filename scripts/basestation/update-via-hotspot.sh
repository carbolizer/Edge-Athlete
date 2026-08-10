#!/usr/bin/env bash
#
# update-via-hotspot.sh — update a base station that has no wired internet.
#
# ⚠️ TRY USB TETHERING OR AN ETHERNET CABLE FIRST. Either gives the box internet on a
# SEPARATE interface, so the access point keeps running and your SSH session never
# drops. Then you can just run bootstrap.sh normally. This script exists only for when
# neither is available.
#
# WHAT IT DOES, AND WHY IT HAS TO BE RUN DETACHED
# The base station has ONE Wi-Fi adapter, and it is busy broadcasting the gym network.
# To reach GitHub it has to stop doing that and join your phone instead — which kills
# the very connection you are typing over. So this script:
#
#   1. joins your phone's hotspot   (your SSH session dies here)
#   2. pulls the latest code and rebuilds
#   3. puts the access point back and starts the stack
#
# Because step 1 disconnects you, it MUST be started detached or it dies halfway,
# leaving the box on your phone's hotspot with no gym Wi-Fi. See the run command below.
#
# THE SAFETY NET
# An EXIT trap restores the access point no matter how this script ends — success,
# failure, or kill. That is the difference between "the update failed" and "nobody can
# reach the base station any more".
#
# RUN IT:
#   sudo setsid nohup bash /tmp/ea-hotspot-update.sh > /tmp/ea-update.log 2>&1 &
#
# Then rejoin the gym Wi-Fi (give it ~2 minutes) and watch:
#   ssh edgeathlete@basestation 'tail -f /tmp/ea-update.log'
#
set -uo pipefail        # NOT -e: a failed step must still hit the trap and restore the AP

# ── EDIT THESE TWO LINES ────────────────────────────────────────────────────
HOTSPOT_SSID="CHANGE_ME"
HOTSPOT_PASS="CHANGE_ME"
# ────────────────────────────────────────────────────────────────────────────

BRANCH="${EDGE_BRANCH:-main}"
AP_PROFILE="EdgeAthlete-AP"
RAW="https://raw.githubusercontent.com/carbolizer/Edge-Athlete/${BRANCH}/scripts/basestation/bootstrap.sh"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "needs root — run it with sudo"; exit 1
fi
if [ "$HOTSPOT_SSID" = "CHANGE_ME" ]; then
    echo "edit HOTSPOT_SSID and HOTSPOT_PASS at the top of this file first"; exit 1
fi

WIFI_IFACE="$(nmcli -t -f DEVICE,TYPE device | grep ':wifi$' | cut -d: -f1 | head -n1)"
[ -n "$WIFI_IFACE" ] || { echo "no wifi adapter found"; exit 1; }
log "wifi adapter: $WIFI_IFACE"

# ── the safety net ──────────────────────────────────────────────────────────
# Runs on ANY exit. Puts the gym network back before anything else, so a failure
# costs you an update, not access to the machine.
restore_ap() {
    local code=$?
    log "restoring the access point..."
    nmcli connection down "$HOTSPOT_SSID" >/dev/null 2>&1 || true
    nmcli connection delete "$HOTSPOT_SSID" >/dev/null 2>&1 || true
    if nmcli connection up "$AP_PROFILE" >/dev/null 2>&1; then
        log "access point '$AP_PROFILE' is back up"
    else
        log "!! could not raise '$AP_PROFILE' directly — restarting the boot service"
        systemctl restart edgeathlete.service || true
        sleep 8
        nmcli connection up "$AP_PROFILE" >/dev/null 2>&1 || log "!! STILL DOWN — plug in a keyboard or ethernet"
    fi
    log "done (exit $code)"
}
trap restore_ap EXIT

# ── 1. join the phone ───────────────────────────────────────────────────────
log "leaving the gym network and joining '$HOTSPOT_SSID' — your SSH session ends now"
nmcli connection down "$AP_PROFILE" >/dev/null 2>&1 || true
sleep 2
nmcli device wifi rescan >/dev/null 2>&1 || true
sleep 5

joined=0
for attempt in 1 2 3; do
    if nmcli device wifi connect "$HOTSPOT_SSID" password "$HOTSPOT_PASS" ifname "$WIFI_IFACE" >/dev/null 2>&1; then
        joined=1; break
    fi
    log "join attempt $attempt failed, retrying..."
    sleep 5
done
[ "$joined" -eq 1 ] || { log "could not join '$HOTSPOT_SSID' — check the name and password"; exit 1; }

# ── 2. wait for real internet, not just an IP ───────────────────────────────
log "waiting for internet..."
online=0
for _ in $(seq 1 20); do
    if curl -fsS --max-time 5 -o /dev/null https://github.com; then online=1; break; fi
    sleep 3
done
[ "$online" -eq 1 ] || { log "joined the hotspot but cannot reach github — is mobile data on?"; exit 1; }
log "online"

# ── 3. update ───────────────────────────────────────────────────────────────
log "fetching bootstrap from branch '$BRANCH'..."
curl -fsSL "$RAW" -o /tmp/ea-bootstrap.sh || { log "download failed"; exit 1; }

log "running bootstrap (this rebuilds the stack — several minutes)..."
EDGE_BRANCH="$BRANCH" bash /tmp/ea-bootstrap.sh
rc=$?
[ "$rc" -eq 0 ] && log "bootstrap finished cleanly" || log "!! bootstrap exited $rc — the AP still comes back"

# ── 4. hand back to the boot service ────────────────────────────────────────
# The trap restores the AP; this brings the refreshed stack up with it.
log "starting the stack..."
systemctl restart edgeathlete.service || log "!! service restart failed — check: journalctl -u edgeathlete"

exit "$rc"
