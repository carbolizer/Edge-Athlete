#!/usr/bin/env bash
# aliases.sh — the handful of commands you actually run on a base station,
# given short names so nobody has to remember a URL or a compose incantation.
#
# WHAT THIS IS FOR
# Three things get done on this machine over and over: update it, fill it with
# demo data, and turn on the fake rack sensor. Each of those is a long command
# that is easy to get subtly wrong — the wrong branch, a missing --profile, the
# wrong directory. Typing them by hand is how a demo ends up running old code
# and nobody notices until it matters.
#
# THIS FILE IS SOURCED, NOT RUN.
# setup.sh symlinks it into /etc/profile.d/, so every SSH login picks it up.
# Because it is a symlink into the repo, `ea-update` also updates these very
# aliases — change this file, push, run ea-update, and the new commands are
# there on the next login. Nothing to copy around.
#
# It defines FUNCTIONS rather than `alias` lines on purpose: a real alias cannot
# take arguments or hold a pipe into sudo cleanly, and these need both.
#
# Never `exit` or `set -e` in here. A sourced file that exits closes the login
# shell it was sourced into, which would lock you out over SSH.

# Where the install lives. Overridable for the rare non-standard box, but the
# default is the same path bootstrap.sh has always used.
EDGE_DIR="${EDGE_DIR:-/srv/edge-athlete/Edge-Athlete}"
EDGE_REPO_RAW="https://raw.githubusercontent.com/carbolizer/Edge-Athlete"

# Pull the latest code and rebuild. Same command as a first-time install —
# bootstrap.sh is deliberately not one-shot, so this is the ONLY update path.
#
# Takes a branch as an optional argument, defaulting to main:
#   ea-update              -> main
#   ea-update SprintBranch -> that branch instead
ea-update() {
    local branch="${1:-main}"
    echo "==> updating from branch '$branch' (this rebuilds — several minutes)"
    curl -fsSL "${EDGE_REPO_RAW}/${branch}/scripts/basestation/bootstrap.sh" \
        | sudo EDGE_BRANCH="$branch" bash
}

# Fill the database with the demo session: a group, four athletes, an open
# session, and the demo coach login.
#
# Safe to run twice — the seeder is idempotent and will not duplicate rows. It
# is NOT safe to add --reset on a real base station: that deletes by NAME, so it
# takes out any real group called "Varsity" and any athlete sharing a name with
# the demo four. Left off here on purpose.
ea-seed() {
    echo "==> seeding demo session + coach"
    ( cd "$EDGE_DIR" && sudo docker compose run --rm seed )
}

# Start the fake rack sensor. It publishes pulses forever, which is what makes
# the node show up as an unassigned rack on the tablet — that IS the
# registration. Assign it a rack there and it starts sending reps.
#
# Takes a node id, defaulting to rack_1. A second node is just a second call:
#   ea-sim          -> rack_1, running detached
#   ea-sim rack_2   -> a second sensor alongside it
ea-sim() {
    local node="${1:-rack_1}"
    if [ "$node" = "rack_1" ]; then
        # The compose service is already defined as rack_1, so use it directly —
        # that way `ea-sim-stop` and `docker compose ps` both see it by name.
        echo "==> starting simulator (rack_1)"
        ( cd "$EDGE_DIR" && sudo docker compose --profile demo up -d simulator )
    else
        echo "==> starting simulator ($node)"
        ( cd "$EDGE_DIR" && sudo docker compose run -d --rm simulator \
            python manage.py simulate_node --node-id "$node" )
    fi
}

# Watch the simulator decide whether to publish. Worth doing once: it explains
# out loud why it is quiet, which is usually the answer to "why no reps?".
ea-sim-log() {
    ( cd "$EDGE_DIR" && sudo docker compose logs -f simulator )
}

ea-sim-stop() {
    echo "==> stopping simulator"
    ( cd "$EDGE_DIR" && sudo docker compose --profile demo stop simulator )
}

ea-help() {
    # Unquoted heredoc so the install path is shown for real, not as $EDGE_DIR.
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
