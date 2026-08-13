"""Every number a coach or sports scientist might want to argue with, in one file.

WHAT BELONGS HERE
A knob someone could reasonably want turned without being told "no" — the 1RM
formula, how far below target counts as slowing down, how long "resting" lasts.
Change the value here and the whole system follows; nothing reads a second copy.

WHAT DOES NOT BELONG HERE
Operational guards — max upload size, page limits, how many rows an endpoint
returns. Those are not opinions about training, they are protections for one
specific piece of code, and they belong next to that code where you will
actually find them. Hoovering every constant in the repo into one file makes
things harder to find, not easier. This file is deliberately short.

HOW TO CHANGE A FORMULA
The numbers live here; the functions that use them live in lifting_math.py.
Swapping Epley for Brzycki is one edit in `one_rep_max()` there. Re-tuning what
counts as a slow rep is one edit here. Both are single-site changes on purpose —
that is the entire reason these two files exist.

⚠️ ONE KNOB IS NOT HERE, AND CANNOT BE — see VELOCITY_YELLOW_FRACTION below.
"""
from datetime import timedelta


# ─────────────────────────── estimating a one-rep max ───────────────────────────

# The window of rep counts an honest 1RM estimate can be made from. A single is
# already a max attempt, and a 30-rep set is conditioning, where every one of
# these formulas falls apart. Outside this range callers get None rather than a
# confident wrong number.
MIN_REPS_FOR_ESTIMATE = 1
MAX_REPS_FOR_ESTIMATE = 12

# Epley's divisor: 1RM = weight x (1 + reps / EPLEY_DIVISOR).
# Lower = more generous estimates. Brzycki and Lombardi are different shapes, not
# a different number here — swapping to one of those means editing the formula in
# lifting_math.one_rep_max(), which is the one place it is written.
EPLEY_DIVISOR = 30


# ─────────────────────────── putting weight on a bar ───────────────────────────

# Gyms load in 5 lb steps (2.5 lb plates in pairs), so a prescription of 198.3 is
# noise. Every resolved target is snapped to this. Set to 2.5 for a gym with
# fractional plates, or 1 to disable rounding entirely.
LOADING_INCREMENT_LBS = 5


# ─────────────────────────── reading the room ───────────────────────────

# How long after finishing a set an athlete still counts as "resting". Past this
# they fall through to "ready" or "not_started" — because a set that ended an hour
# ago means they moved on, not that they are still between sets.
RESTING_WINDOW = timedelta(minutes=20)

# A sensor that has not been heard from in this long is shown as stale rather than
# live. Nodes pulse every few seconds, so this is several missed beats, not one.
NODE_STALE_AFTER = timedelta(seconds=15)


# ─────────────────────── the one that got away ───────────────────────
#
# ⚠️ THE VELOCITY COLOUR THRESHOLD IS NOT IN THIS FILE.
#
# A rep is green at or above the target zone, yellow down to 85% of it, red below.
# That 0.85 lives in `react/src/rack/velocity.js` — a FROZEN file (SPEC §2.1). The
# tablet computes the colour and POSTs it; the server only ever stores and reads
# back what it was told, so there is no server-side copy to consolidate. That is
# why it is single-source today despite not living here.
#
# It is written down here so that someone re-tuning the training model finds out
# where it is instead of concluding it does not exist.
#
# To change it you must touch the frozen rack contract, which means: the whole
# rack loop gets re-verified on real hardware, and every stored `velocity_color`
# from before the change was computed under the old threshold. Old reps are not
# recoloured. Treat it as a schema change, not a tweak.
VELOCITY_YELLOW_FRACTION_SEE_FROZEN_RACK = 0.85
