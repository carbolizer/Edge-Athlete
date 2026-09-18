#!/bin/bash
# rotate.sh — turn this screen, and turn its touch input with it.
#
#   rotate.sh <normal|left|right|inverted>
#
# ── WHY THIS IS ITS OWN FILE ──────────────────────────────────────────────────
# Two callers need exactly this, and a copy in each would drift:
#
#   kiosk.sh   applies the saved rotation at every login, before the browser opens
#   ea.sh      `ea rotate-left` — change it now, on a screen already running
#
# ── THE HALF PEOPLE LEAVE OUT ─────────────────────────────────────────────────
# Rotating the picture WITHOUT rotating touch is worse than not rotating at all.
# X11 keeps delivering touch events in the panel's original coordinate space, so
# the display looks perfect and every tap lands somewhere else. An athlete presses
# "Start Set" and hits something two inches away, and nothing on screen hints why.
#
# So every pointer device gets a matching Coordinate Transformation Matrix — every
# one, not just the first: a rack tablet usually enumerates several (the touch
# panel, plus a stylus or mouse-emulation node).
#
# ── X11 ONLY ──────────────────────────────────────────────────────────────────
# Under Wayland (Raspberry Pi OS Bookworm defaults to labwc) xrandr is not the
# mechanism and this does nothing. It says so rather than pretending to work;
# rotation belongs in the compositor's config there.

set -u

ROTATE="${1:-normal}"

case "$ROTATE" in
    normal)   MATRIX="1 0 0 0 1 0 0 0 1" ;;
    left)     MATRIX="0 -1 1 1 0 0 0 0 1" ;;
    right)    MATRIX="0 1 0 -1 0 1 0 0 1" ;;
    inverted) MATRIX="-1 0 1 0 -1 1 0 0 1" ;;
    *)
        echo "unknown rotation '$ROTATE' — expected normal, left, right or inverted" >&2
        exit 1
        ;;
esac

if ! command -v xrandr >/dev/null 2>&1; then
    echo "[!] xrandr not found — nothing to rotate (Wayland? rotate in the compositor config)" >&2
    exit 0
fi

# Whichever output is actually plugged in. The name differs per device — HDMI-1,
# HDMI-A-1, DSI-1 for the official touch display — so asking is the only thing
# that works everywhere.
OUTPUT="$(xrandr --query 2>/dev/null | awk '/ connected/{print $1; exit}')"
if [ -z "$OUTPUT" ]; then
    echo "[!] no connected display found — skipping rotation" >&2
    exit 0
fi

echo "==> rotating $OUTPUT $ROTATE"
xrandr --output "$OUTPUT" --rotate "$ROTATE" 2>/dev/null \
    || { echo "[!] xrandr could not rotate $OUTPUT" >&2; exit 0; }

if command -v xinput >/dev/null 2>&1; then
    xinput list --name-only 2>/dev/null | while IFS= read -r DEV; do
        [ -n "$DEV" ] || continue
        # Most of these are keyboards and virtual devices that have no such
        # property; they fail harmlessly and are meant to.
        xinput set-prop "$DEV" 'Coordinate Transformation Matrix' $MATRIX 2>/dev/null || true
    done
    echo "    touch input remapped to match"
else
    echo "[!] xinput not found — the PICTURE rotated but TOUCH DID NOT." >&2
    echo "    taps will land in the wrong place. install xinput:" >&2
    echo "      sudo apt install -y xinput" >&2
fi
