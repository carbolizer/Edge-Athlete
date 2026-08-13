#!/usr/bin/env bash
#
# netmon.sh — one screen that shows WHY the WiFi feels slow, live.
#
# When a demo bogs down with a handful of tablets connected, the only question
# that matters is: "is the APP slow, or is the RADIO just full?" You cannot
# answer that from a single number. This opens three live views at once, on one
# screen, so you can read them together in a single glance:
#
#   top          — how many bytes each connected device is pulling right now
#   bottom-left  — each device's radio health (link speed, signal, dropped/retried packets)
#   bottom-right — how busy the WiFi channel itself is (is the air saturated?)
#
# Bytes alone can't tell "the app is slow" apart from "the radio can't push the
# bits" — that's the whole reason all three have to be visible at the same time.
# This is a LOOK-ONLY tool: it changes nothing on the machine, it only watches.
#
# Run it:   ./netmon.sh            # finds the WiFi-broadcasting card by itself
#           ./netmon.sh wlp2s0     # or name the card yourself
#           ./netmon.sh -r 2       # slow the refresh to every 2 seconds
#
# Leave it running:  Ctrl-b then d      Come back:  ./netmon.sh
# Shut it down:      sudo tmux kill-session -t netmon
#
set -euo pipefail

SESSION="netmon"
REFRESH=1
IFACE_ARG=""

usage() {
  cat <<'EOF'
netmon.sh — live AP monitor (iftop + iw station/survey) on one tmux screen

Usage: netmon.sh [-r seconds] [interface]
  -r seconds   refresh interval for the radio panes (default 1)
  interface    force the WiFi interface (default: auto-detect AP, else wlp2s0)
EOF
}

# --- args: an optional "-r <sec>" and an optional interface, in any order ---
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    -r) REFRESH="${2:-}"; shift 2 2>/dev/null || shift ;;
    -r*) REFRESH="${1#-r}"; shift ;;
    -*) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    *) IFACE_ARG="$1"; shift ;;
  esac
done

# refresh has to be a plain positive number that `watch -n` will accept
case "$REFRESH" in
  ''|*[!0-9.]*) echo "Refresh (-r) must be a number, got: '$REFRESH'" >&2; exit 1 ;;
esac

# --- the tools we lean on must already be here (never auto-install: box may be offline) ---
missing=""
for c in tmux iftop iw; do
  command -v "$c" >/dev/null 2>&1 || missing="$missing $c"
done
if [ -n "$missing" ]; then
  echo "Missing tools:$missing"
  echo "Install them with:  sudo apt install$missing"
  echo "(tmux and iftop are apt packages; iw is the 'iw' package.)"
  exit 1
fi

# --- find the card that is actually broadcasting the WiFi (the one in AP mode) ---
detect_ap_iface() {
  iw dev 2>/dev/null | awk '
    $1=="Interface"{iface=$2}
    $1=="type" && $2=="AP"{print iface; exit}'
}
IFACE="$IFACE_ARG"
[ -n "$IFACE" ] || IFACE="$(detect_ap_iface || true)"
[ -n "$IFACE" ] || IFACE="wlp2s0"

# soft sanity check — warn but keep going, since the user can force any name
if ! iw dev "$IFACE" info >/dev/null 2>&1; then
  echo "[!] '$IFACE' doesn't look like a WiFi interface on this box."
  echo "    Using it anyway; override with:  ./netmon.sh <iface>"
fi
echo "Monitoring interface: $IFACE  (refresh ${REFRESH}s)"

# --- one password prompt, up front -------------------------------------------
# iftop and the iw dumps need root. sudo remembers "you're allowed" PER TERMINAL,
# and every tmux pane is its own terminal — so priming sudo in this shell would
# NOT carry into the panes, and each pane would prompt again (2-3 times, mid-
# layout). So we prime sudo once here and then run the whole tmux session itself
# as root: one prompt, and no pane ever has to ask again.
sudo -v

# every tmux call goes through the primed root ticket
t() { sudo tmux "$@"; }

# --- already running? just reconnect to it, don't build a duplicate ---
if t has-session -t "$SESSION" 2>/dev/null; then
  echo "Session '$SESSION' already running — attaching."
  exec sudo tmux attach -t "$SESSION"
fi

# --- build the 3-pane screen (session runs as root, so no per-pane sudo) ---
# pane 0 (top, full width): per-device bandwidth
t new-session -d -s "$SESSION" -n monitor
t send-keys -t "$SESSION" "iftop -i $IFACE" C-m

# pane 1 (bottom-left): per-device radio health — link speed, signal, retries
t split-window -v -t "$SESSION"
t send-keys -t "$SESSION" "watch -n${REFRESH} 'iw dev ${IFACE} station dump'" C-m

# pane 2 (bottom-right): how busy the in-use channel is (airtime saturation).
# awk keeps only the channel block marked "[in use]" plus the indented lines
# under it, which is sturdier than a fixed -A line count if the output shifts.
t split-window -h -t "$SESSION"
t send-keys -t "$SESSION" "watch -n${REFRESH} \"iw dev ${IFACE} survey dump | awk '/\[in use\]/{p=1;print;next} /^Survey data/{p=0} p'\"" C-m

# big pane on top, the two radio panes in a row beneath it
t select-layout -t "$SESSION" main-horizontal
# let the mouse switch/scroll panes too, not just the Ctrl-b keys
t set-option -t "$SESSION" mouse on >/dev/null 2>&1 || true

cat <<EOF
Panes:  top = bytes per device  |  bottom-left = radio health  |  bottom-right = channel busy
Switch panes:  Ctrl-b then an arrow key   (or click a pane)
Detach (leave it running):  Ctrl-b then d      Reattach:  ./netmon.sh
Kill it:  sudo tmux kill-session -t $SESSION
EOF

exec sudo tmux attach -t "$SESSION"
