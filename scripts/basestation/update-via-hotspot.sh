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
# SSID_MATCH is a distinctive PIECE of the hotspot name, not the whole thing —
# "iPhone" is usually enough. The exact name is then read off the live scan.
#
# WHY NOT JUST TYPE THE NAME: an iPhone hotspot is called "Devin's iPhone" with a
# CURLY apostrophe (U+2019), not the straight ' you get from a keyboard. They are
# different characters, so a hand-typed name silently never matches and the join
# fails for a reason nothing in the output would explain. Matching a substring and
# taking the SSID verbatim from the scan sidesteps that, and any other odd character.
SSID_MATCH="iPhone"
HOTSPOT_PASS="CHANGE_ME"
# ────────────────────────────────────────────────────────────────────────────

BRANCH="${EDGE_BRANCH:-main}"
AP_PROFILE="EdgeAthlete-AP"
RAW="https://raw.githubusercontent.com/carbolizer/Edge-Athlete/${BRANCH}/scripts/basestation/bootstrap.sh"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "needs root — run it with sudo"; exit 1
fi
if [ "$HOTSPOT_PASS" = "CHANGE_ME" ]; then
    echo "set SSID_MATCH and HOTSPOT_PASS at the top of this file first"; exit 1
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
log "leaving the gym network — your SSH session ends now"
nmcli connection down "$AP_PROFILE" >/dev/null 2>&1 || true
sleep 2

# Read the hotspot's REAL name off the scan rather than trusting a typed one.
log "scanning for a network matching '$SSID_MATCH'..."
HOTSPOT_SSID=""
for _ in 1 2 3; do
    HOTSPOT_SSID="$(nmcli -t -f SSID device wifi list --rescan yes 2>/dev/null \
                    | grep -F "$SSID_MATCH" | head -n1)"
    [ -n "$HOTSPOT_SSID" ] && break
    sleep 5
done
[ -n "$HOTSPOT_SSID" ] || { log "no network matching '$SSID_MATCH' — is the hotspot on?"; exit 1; }
log "found: '$HOTSPOT_SSID'"

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

# ── 4. reboot ───────────────────────────────────────────────────────────────
# A reboot is the cleanest finish AND a second safety net: the boot service runs
# startup.sh, which raises the access point and starts the stack from scratch. So even
# if the trap above somehow failed, coming back up fixes it.
#
# The trap stays armed deliberately — it restores the AP as this script exits, so the
# gym network is back even in the seconds before the machine actually goes down, and
# still back if the reboot never happens.
log "update finished (exit $rc) — rebooting in 5 seconds"
log "rejoin the gym Wi-Fi in ~2 minutes, then: ssh edgeathlete@basestation 'tail -40 /tmp/ea-update.log'"
sync
sleep 5
systemctl reboot || reboot || log "!! reboot failed — run 'sudo reboot' by hand"

exit "$rc"
