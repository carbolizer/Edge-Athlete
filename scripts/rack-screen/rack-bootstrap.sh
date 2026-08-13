#!/usr/bin/env bash
# rack-bootstrap.sh — turn a blank machine into a rack screen with one command.
#
#   curl -fsSL https://raw.githubusercontent.com/carbolizer/Edge-Athlete/main/scripts/rack-screen/rack-bootstrap.sh | sudo bash
#
# Run it AGAIN any time you want to update a rack screen. Like the base station's
# bootstrap.sh, nothing here is one-shot.
#
# ── WHY THIS EXISTS ─────────────────────────────────────────────────────────────
# The base station had a one-command install and a rack screen did not. Provisioning
# a rack meant "install git, clone the repo, cd into it, run this script with these
# arguments" — four chances to get it wrong, on the device you have the most of. This
# is the same shape as bootstrap.sh so the two are learned once, not twice.
#
# ── WHY IT TAKES NO ROLE ARGUMENT ───────────────────────────────────────────────
# A rack screen is a rack screen. It hardcodes the role deliberately: this is the
# path you run on a dozen identical devices, and a role argument on that path is a
# way to end up with a wall display bolted to a squat rack. The other roles are
# deliberate, one-off acts and go through rack-kiosk-setup.sh directly:
#
#   sudo scripts/rack-screen/rack-kiosk-setup.sh coach
#
# The base station is different again — it defaults to the wall display and can open
# any role for debugging. See scripts/basestation/basestation-kiosk.sh.
#
# ── WHAT IT DOES NOT INSTALL ────────────────────────────────────────────────────
# No Docker, no Python, no database, no server. A rack screen is a CLIENT: it joins
# the base station's WiFi and shows a web page. The repo is cloned only because the
# kiosk scripts live in it — nothing in it runs but two shell scripts.
#
# Override these if you need to. ⚠️ The assignments go AFTER `sudo`, not before
# `curl` — sudo scrubs the environment, so anything set before the pipe never
# reaches this script:
#   curl ... | sudo EDGE_BRANCH=SprintBranch AP_PASSWORD='hunter2' bash

set -euo pipefail

REPO_URL="${EDGE_REPO_URL:-https://github.com/carbolizer/Edge-Athlete.git}"
EDGE_HOME="${EDGE_HOME:-/srv/edge-athlete}"
EDGE_BRANCH="${EDGE_BRANCH:-main}"
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

# Same location as the base station, and for the same reason: /srv belongs to the
# machine, not to whoever is logged in. A rack screen that was set up by one account
# must keep working after that account is renamed or replaced.
if [ -d "$PROJECT_DIR/.git" ]; then
    echo "    already installed, updating..."
    git -C "$PROJECT_DIR" remote set-url origin "$REPO_URL"
    # The refspec is spelled out for the same reason bootstrap.sh spells it out: the
    # first clone is --single-branch, so the remote maps only that one branch and a
    # later `git fetch origin main` never creates refs/remotes/origin/main. Naming
    # the destination forces it into existence, so switching branches works.
    git -C "$PROJECT_DIR" fetch --depth 1 origin \
        "+refs/heads/$EDGE_BRANCH:refs/remotes/origin/$EDGE_BRANCH"
    # -f because a screen is a deployment target, not a working copy. Untracked
    # files are left alone.
    git -C "$PROJECT_DIR" checkout -f -B "$EDGE_BRANCH" "origin/$EDGE_BRANCH"
else
    git clone --depth 1 --branch "$EDGE_BRANCH" "$REPO_URL" "$PROJECT_DIR"
fi

echo "[3] handing off to rack-kiosk-setup.sh..."
chmod +x "$PROJECT_DIR/scripts/rack-screen/rack-kiosk-setup.sh"
exec "$PROJECT_DIR/scripts/rack-screen/rack-kiosk-setup.sh" rack
