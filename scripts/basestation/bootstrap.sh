#!/usr/bin/env bash
# bootstrap.sh — get Edge Athlete onto a bare base station with one command.
#
# Run this on a fresh machine and it does everything: installs git, pulls the
# repo down to a fixed location, and hands off to setup.sh, which installs
# Docker and the boot service.
#
#   curl -fsSL https://raw.githubusercontent.com/carbolizer/Edge-Athlete/SprintBranch/scripts/basestation/bootstrap.sh | sudo bash
#
# Run it AGAIN any time you want to update the base station — it pulls the
# latest code and re-runs setup. Nothing here is one-shot.
#
# WHERE THINGS GO, AND WHY IT IS NOT YOUR HOME DIRECTORY.
# The install lives at /srv/edge-athlete/Edge-Athlete, owned by root. The old
# Pi script hardcoded /home/pi, which meant the whole system quietly depended on
# WHICH USER was logged in — rename the account, add a second admin, or log in
# as anyone else and the boot service pointed at a directory that no longer
# existed. /srv belongs to the machine, not to a person, so nothing below cares
# who is at the keyboard.
#
# Override either of these if you need to:
#   EDGE_HOME=/opt/edge-athlete  EDGE_BRANCH=main  curl ... | sudo bash

set -euo pipefail

REPO_URL="${EDGE_REPO_URL:-https://github.com/carbolizer/Edge-Athlete.git}"
EDGE_HOME="${EDGE_HOME:-/srv/edge-athlete}"

# ⚠️ PINNED TO SprintBranch ON PURPOSE — do not "fix" this to the default branch.
# GitHub's default for this repo is `main`, and main is a whole generation
# behind: different models (Session/Program instead of TrainingSession/
# TrainingProgram), no monitoring-publisher, no seed or simulator services. A
# base station built from main would come up looking fine and be running last
# season's app.
EDGE_BRANCH="${EDGE_BRANCH:-SprintBranch}"

PROJECT_DIR="$EDGE_HOME/Edge-Athlete"

if [ "$(id -u)" -ne 0 ]; then
    echo "[!] needs root — pipe it into 'sudo bash', not 'bash'"
    exit 1
fi

echo "[1] installing git..."
if ! command -v git >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq git ca-certificates
fi

echo "[2] fetching Edge Athlete into $PROJECT_DIR (branch: $EDGE_BRANCH)..."
mkdir -p "$EDGE_HOME"

if [ -d "$PROJECT_DIR/.git" ]; then
    # Already installed — update in place. Deliberately NOT `git pull`: the base
    # station is not a place anyone edits code, and a local change (or the old
    # setup script's habit of rewriting startup.sh in place) would turn a routine
    # update into a merge conflict on a machine with no one to resolve it.
    echo "    already installed, updating..."
    git -C "$PROJECT_DIR" remote set-url origin "$REPO_URL"
    git -C "$PROJECT_DIR" fetch --depth 1 origin "$EDGE_BRANCH"
    # `checkout -f`, and the -f is load-bearing. Plain `checkout -B` REFUSES when
    # a tracked file has been edited locally — so on a base station where anyone
    # once poked docker-compose.yml, the update aborted and the box silently sat
    # on old code. Forcing discards those edits, which is right: the install is a
    # deployment target, not a working copy. Untracked files are NOT touched, so
    # .env — the machine's own config — survives.
    git -C "$PROJECT_DIR" checkout -f -B "$EDGE_BRANCH" "origin/$EDGE_BRANCH"
else
    git clone --depth 1 --branch "$EDGE_BRANCH" "$REPO_URL" "$PROJECT_DIR"
fi

# The repo keeps its own name. The old script renamed Edge-Athlete to
# edge-athlete on arrival, which meant the directory you cloned was never the
# directory things ran from — a small thing that cost real time every time
# somebody went looking for it.
echo "[3] handing off to setup.sh..."
chmod +x "$PROJECT_DIR/scripts/basestation/setup.sh"
exec "$PROJECT_DIR/scripts/basestation/setup.sh"
