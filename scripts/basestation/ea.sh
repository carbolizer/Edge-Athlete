#!/usr/bin/env bash
# ea.sh — the base station's short commands. ONE file, run under several names.
#
#   ea-update [branch]   pull latest code and rebuild
#   ea-seed              load the demo session, athletes and coach
#   ea-sim [node_id]     start the fake rack sensor
#   ea-sim-log           follow the simulator's decisions
#   ea-sim-stop          stop it
#   ea-help              the list
#
# ── WHY THIS IS EXECUTED, NOT SOURCED (it used to be sourced, and that was wrong) ──
# These were shell FUNCTIONS in a file symlinked into /etc/profile.d. That directory
# is only read by LOGIN shells, which meant the commands existed in some places and
# silently did not in others:
#
#   ssh basestation           login shell     -> worked
#   a terminal on the desktop  NOT login      -> "command not found"
#   ssh basestation 'ea-update'  NOT login    -> "command not found"
#   after any reboot, in a session opened
#     before the symlink existed              -> "command not found"
#
# The workaround was to `source` the file by hand, every time. A command you have to
# install into your shell before each use is not a command, and the failure looked
# like the update mechanism was broken rather than the delivery of it.
#
# A real executable on PATH has none of that. It works in every shell, every login
# type, over ssh in one shot, and under sudo. The cost is that it cannot change the
# calling shell's environment — which none of these ever needed to do.
#
# ── HOW ONE FILE BECOMES SIX COMMANDS ─────────────────────────────────────────────
# setup.sh symlinks this into /usr/local/bin once per command name, and the script
# reads which name it was invoked as. Symlinks rather than copies, so `ea-update`
# also updates the commands themselves.
#
# ⚠️ There is a SECOND ea.sh, in scripts/rack-screen/, for screens. Both define
# `ea-update` and they resolve to different bootstraps. See that file's header.

set -uo pipefail

EDGE_DIR="${EDGE_DIR:-/srv/edge-athlete/Edge-Athlete}"
EDGE_REPO_RAW="https://raw.githubusercontent.com/carbolizer/Edge-Athlete"

# Which name were we invoked as? Called as plain `ea`, take the subcommand from the
# first argument instead, so `ea update` and `ea-update` both work.
CMD="$(basename "$0")"
case "$CMD" in
    ea|ea.sh) CMD="ea-${1:-help}"; [ $# -gt 0 ] && shift ;;
esac

usage() {
    cat <<EOF
Edge Athlete — base station commands

  ea-update [branch]   pull latest code and rebuild        (default: main)
  ea-seed              load demo session, athletes, coach
  ea-sim [node_id]     start the fake rack sensor          (default: rack_1)
  ea-sim-log           follow the simulator's decisions
  ea-sim-stop          stop it

The install lives at $EDGE_DIR
EOF
}

case "$CMD" in

ea-update)
    # Same command as a first-time install — bootstrap.sh is deliberately not
    # one-shot, so this is the ONLY update path. Takes a branch, defaulting to main.
    branch="${1:-main}"
    echo "==> updating from branch '$branch' (this rebuilds — several minutes)"
    curl -fsSL "${EDGE_REPO_RAW}/${branch}/scripts/basestation/bootstrap.sh" \
        | sudo EDGE_BRANCH="$branch" bash
    ;;

ea-seed)
    # Safe to run twice — the seeder is idempotent. Do NOT add --reset on a real
    # base station: it deletes by NAME, so it takes out any real group called
    # "Varsity" and any athlete sharing a name with the demo four.
    echo "==> seeding demo session + coach"
    cd "$EDGE_DIR" && sudo docker compose run --rm seed
    ;;

ea-sim)
    # Publishing pulses is what makes the node appear as an unassigned rack on the
    # tablet — that IS the registration. Assign it a rack there and reps follow.
    node="${1:-rack_1}"
    cd "$EDGE_DIR" || exit 1
    if [ "$node" = "rack_1" ]; then
        # The compose service is already defined as rack_1, so use it by name and
        # `ea-sim-stop` and `docker compose ps` can both see it.
        echo "==> starting simulator (rack_1)"
        sudo docker compose --profile demo up -d simulator
    else
        echo "==> starting simulator ($node)"
        sudo docker compose run -d --rm simulator \
            python manage.py simulate_node --node-id "$node"
    fi
    ;;

ea-sim-log)
    # Worth doing once: it says out loud why it is quiet, which is usually the
    # answer to "why no reps?".
    cd "$EDGE_DIR" && sudo docker compose logs -f simulator
    ;;

ea-sim-stop)
    echo "==> stopping simulator"
    cd "$EDGE_DIR" && sudo docker compose --profile demo stop simulator
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
