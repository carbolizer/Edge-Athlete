#!/usr/bin/env bash
# aliases.sh — short commands for a SCREEN: a rack tablet, a coach tablet, or a
# wall display. NOT the base station.
#
# ⚠️ THERE ARE TWO FILES CALLED aliases.sh AND THEY ARE NOT INTERCHANGEABLE.
# scripts/basestation/aliases.sh is the other one. Both define `ea-update`, and on
# each machine it means "update this device" — but they resolve to different
# bootstraps, because the two devices are not the same kind of thing:
#
#   base station  ->  bootstrap.sh       installs Docker, the server stack, the
#                                        access point. Minutes. Rebuilds containers.
#   a screen      ->  rack-bootstrap.sh  installs a browser and a launcher. Seconds.
#                                        No Docker, no server, nothing to rebuild.
#
# Running the base station's version on a screen would install a server it has no use
# for AND try to turn it into a second WiFi access point, competing with the real
# base station for the air the gym runs on. That is why a screen gets its own file
# rather than a shared one with conditionals: the wrong branch of a conditional is a
# silent disaster, two separate files are just two separate files.
#
# THIS FILE IS SOURCED, NOT RUN. rack-kiosk-setup.sh symlinks it into /etc/profile.d,
# so `ea-update` also updates these commands. Never `exit` or `set -e` here — a
# sourced file that exits closes the login shell it was sourced into.

EDGE_DIR="${EDGE_DIR:-/srv/edge-athlete/Edge-Athlete}"
EDGE_REPO_RAW="https://raw.githubusercontent.com/carbolizer/Edge-Athlete"
EDGE_KIOSK_LOG="${EDGE_KIOSK_LOG:-/tmp/edgeathlete-kiosk.log}"

# Pull the latest code and re-provision this screen. Same command as a first-time
# install — rack-bootstrap.sh is deliberately not one-shot.
#
#   ea-update              -> main
#   ea-update SprintBranch -> that branch instead
ea-update() {
    local branch="${1:-main}"
    echo "==> updating this screen from branch '$branch'"
    curl -fsSL "${EDGE_REPO_RAW}/${branch}/scripts/rack-screen/rack-bootstrap.sh" \
        | sudo EDGE_BRANCH="$branch" bash
}

# Restart the browser without rebooting the screen.
#
# Killing Chromium is enough: the launcher runs it in a relaunch loop, so it comes
# straight back — on the same profile, so the screen keeps its identity and its rack
# assignment. This is the fix for a screen stuck on a stale or broken page, and it
# beats pulling the power, which risks the on-device rep buffer mid-set.
ea-restart() {
    echo "==> restarting the browser (the launcher brings it back in ~3s)"
    pkill -f 'chromium.*--user-data-dir' || echo "    nothing running to restart"
}

# What the launcher printed. This is where "waiting for basestation" and the snap
# warning end up — the two things worth reading when a screen comes up blank.
ea-kiosk-log() {
    if [ -f "$EDGE_KIOSK_LOG" ]; then
        tail -n "${1:-40}" "$EDGE_KIOSK_LOG"
    else
        echo "no log at $EDGE_KIOSK_LOG — the launcher may not have run yet"
    fi
}

ea-help() {
    cat <<EOF
Edge Athlete — screen commands (this is a SCREEN, not the base station)

  ea-update [branch]   pull latest code and re-provision   (default: main)
  ea-restart           restart the browser, keep the identity
  ea-kiosk-log [n]     last n lines the launcher printed   (default: 40)

The install lives at $EDGE_DIR
EOF
}
