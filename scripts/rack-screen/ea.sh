#!/usr/bin/env bash
# ea.sh — short commands for a SCREEN: a rack tablet, a coach tablet, or a wall
# display. NOT the base station.
#
#   ea-update [branch]   pull latest code and re-provision this screen
#   ea-restart           restart the browser, keeping this screen's identity
#   ea-rotate-<dir>      turn the screen (left|right|normal|inverted), now and at boot
#   ea-kiosk-log [n]     the last n lines the launcher printed
#   ea-help              the list
#
# ⚠️ THERE ARE TWO FILES CALLED ea.sh AND THEY ARE NOT INTERCHANGEABLE.
# scripts/basestation/ea.sh is the other one. Both provide `ea-update`, and on each
# machine it means "update this device" — but they resolve to different bootstraps,
# because the two devices are not the same kind of thing:
#
#   base station  ->  bootstrap.sh       Docker, the server stack, the access point.
#                                        Minutes. Rebuilds containers.
#   a screen      ->  rack-bootstrap.sh  a browser and a launcher. Seconds.
#                                        No Docker, no server, nothing to rebuild.
#
# Installing the base station's version on a screen would give it a server it has no
# use for AND stand up a second WiFi access point, competing with the real one for
# the air the gym runs on. That is why these are two files rather than one with a
# check for which device it is: the wrong branch of a conditional is a silent
# disaster, two separate files are just two separate files.
#
# ── EXECUTED, NOT SOURCED ─────────────────────────────────────────────────────────
# These used to be shell functions in /etc/profile.d, which only LOGIN shells read —
# so they worked over plain ssh and were missing from a desktop terminal, from
# `ssh host 'ea-update'`, and from any session opened before the file existed. A real
# executable on PATH works everywhere. See the base station's ea.sh for the longer
# version of that story.

set -uo pipefail

EDGE_DIR="${EDGE_DIR:-/srv/edge-athlete/Edge-Athlete}"
EDGE_REPO_RAW="https://raw.githubusercontent.com/carbolizer/Edge-Athlete"
EDGE_KIOSK_LOG="${EDGE_KIOSK_LOG:-/tmp/edgeathlete-kiosk.log}"

CMD="$(basename "$0")"
case "$CMD" in
    ea|ea.sh) CMD="ea-${1:-help}"; [ $# -gt 0 ] && shift ;;
esac

usage() {
    cat <<EOF
Edge Athlete — screen commands (this is a SCREEN, not the base station)

  ea-update [branch]   pull latest code and re-provision   (default: main)
  ea-restart           restart the browser, keep the identity
  ea-rotate-<dir>      turn the screen: left|right|normal|inverted
  ea-kiosk-log [n]     last n lines the launcher printed   (default: 40)
  ea-kiosk-exit        leave the kiosk for the desktop (Ctrl+Alt+K)

ea-rotate takes effect now AND survives a reboot. left and right are both
portrait; which one depends on how the tablet is mounted.

The install lives at $EDGE_DIR
EOF
}

case "$CMD" in

ea-update)
    branch="${1:-main}"
    echo "==> updating this screen from branch '$branch'"
    curl -fsSL "${EDGE_REPO_RAW}/${branch}/scripts/rack-screen/rack-bootstrap.sh" \
        | sudo EDGE_BRANCH="$branch" bash
    ;;

ea-restart)
    # Killing Chromium is enough: the launcher runs it in a relaunch loop, so it
    # comes straight back on the SAME profile — the screen keeps its identity and
    # its rack assignment. This is the fix for a screen stuck on a stale page, and
    # it beats pulling the power, which risks the on-device rep buffer mid-set.
    echo "==> restarting the browser (the launcher brings it back in ~3s)"
    pkill -f 'chromium.*--user-data-dir' || echo "    nothing running to restart"
    ;;

ea-kiosk-exit)
    # Leave the kiosk and land on the plain desktop, so you can open the app menu or
    # a different role. Sets the flag FIRST: kill the browser first and the relaunch
    # loop would win the race and reopen it before the flag existed.
    #
    # Nothing is uninstalled and nothing is disabled — the next login starts the
    # kiosk again, because kiosk.sh clears this flag when it launches.
    echo "==> leaving the kiosk"
    touch "${EDGE_KIOSK_STOP:-/tmp/edgeathlete-kiosk.stop}"
    pkill -f 'chromium.*--user-data-dir' || echo "    nothing running"
    ;;

ea-rotate|ea-rotate-*)
    # `ea rotate-left`, `ea rotate-right`, `ea rotate-normal`, `ea rotate-inverted`.
    # `ea-rotate left` works too — same thing, whichever you type first.
    #
    # Does BOTH halves, because doing one is a trap either way: rotating only the
    # live screen looks fixed until the next reboot, and only writing the file
    # leaves you staring at a screen that did not move wondering if it worked.
    DIR="${CMD#ea-rotate}"; DIR="${DIR#-}"     # ea-rotate-left -> left
    [ -n "$DIR" ] || DIR="${1:-}"              # ea-rotate left -> left
    case "$DIR" in
        normal|left|right|inverted) ;;
        *)
            echo "usage: ea rotate-left | rotate-right | rotate-normal | rotate-inverted"
            echo
            echo "  left and right are both PORTRAIT — which one depends on how the"
            echo "  tablet is mounted. try one, and use the other if it is upside down."
            exit 1
            ;;
    esac

    # Save first, apply second. The save is what survives a reboot, and it is the
    # half that can fail (it needs root); doing it first means a screen that turns
    # is a screen that will still be turned tomorrow, rather than one that looks
    # right until the next power cycle.
    #
    # ⚠️ The two halves run as DIFFERENT USERS on purpose. Writing to /etc needs
    # root; talking to the display needs the desktop session's own user and its
    # DISPLAY. Running the xrandr half under sudo would rotate root's non-existent
    # screen and report success.
    echo "==> saving rotation '$DIR' for the next boot"
    sudo mkdir -p /etc/edgeathlete
    printf 'SCREEN_ROTATE=%s\n' "$DIR" | sudo tee /etc/edgeathlete/screen.conf >/dev/null

    "$(dirname "$(readlink -f "$0")")/rotate.sh" "$DIR"
    ;;

ea-kiosk-log)
    # Where "waiting for basestation" and the snap warning end up — the two things
    # worth reading when a screen comes up blank.
    if [ -f "$EDGE_KIOSK_LOG" ]; then
        tail -n "${1:-40}" "$EDGE_KIOSK_LOG"
    else
        echo "no log at $EDGE_KIOSK_LOG — the launcher may not have run yet"
    fi
    ;;

ea-help|ea--help|ea-h)
    usage
    ;;

*)
    echo "unknown command '$CMD'"; echo
    usage
    exit 1
    ;;

esac
