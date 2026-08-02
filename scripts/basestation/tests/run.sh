#!/usr/bin/env bash
# run.sh — check the base-station scripts without a base station.
#
#   scripts/basestation/tests/run.sh
#
# Runs setup.sh, startup.sh and bootstrap.sh FOR REAL inside a throwaway Debian
# container, with the handful of commands that touch hardware (apt, docker,
# systemctl, nmcli) replaced by stubs. Needs Docker and nothing else.
#
# WHAT THIS CAN AND CANNOT TELL YOU.
# It covers the part that is actually script logic and has actually broken:
# where the install decides it lives, what gets written into the systemd unit
# and the config file, whether re-running is safe, and whether a failure is
# survived or fatal. Two real bugs were caught this way — a boot script that
# died before starting the app when the Wi-Fi adapter refused AP mode, and an
# update that silently did nothing if anyone had edited a tracked file.
#
# It CANNOT tell you the access point works. Nothing but real hardware can. Run
# these before you carry the box to the gym, not instead of.

set -euo pipefail

HERE="$(cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd -P)"
REPO="$(cd -- "$HERE/../../.." >/dev/null 2>&1 && pwd -P)"

if ! docker info >/dev/null 2>&1; then
    echo "[!] Docker isn't running — these tests need it."
    exit 1
fi

echo "repo: $REPO"
echo

failed=0

echo "############ provisioning: setup.sh + startup.sh ############"
docker run --rm -v "$REPO:/src:ro" debian:12 \
    bash /src/scripts/basestation/tests/provisioning.sh || failed=1

echo
echo "############ bootstrap: the one-command install ############"
docker run --rm -v "$REPO:/src:ro" debian:12 bash -c \
    'apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq git >/dev/null 2>&1 \
     && bash /src/scripts/basestation/tests/bootstrap.sh' || failed=1

echo
echo "############ wifi-apply: the host password-change agent ############"
docker run --rm -v "$REPO:/src:ro" debian:12 \
    bash /src/scripts/basestation/tests/wifi-apply.sh || failed=1

echo
if [ "$failed" -eq 0 ]; then
    echo "[✔] base-station scripts pass"
else
    echo "[✘] something failed — see above"
fi
exit "$failed"
