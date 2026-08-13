"""The lifting arithmetic, in one place on purpose.

There is exactly ONE formula in this system for moving between "lifted X for N
reps" and "could lift Y once", and it lives here. Two very different features
need it — deciding what to put on the bar today, and updating an athlete's
working max after a session — and they must never drift apart, so neither one
gets its own copy.

Swapping the formula (Epley for Brzycki, or a coach-tuned curve) is a one-line
change in this file. That is the whole reason the file exists.

The NUMBERS these functions use live in tuning.py, alongside every other knob
someone might want to turn. The shapes live here. Re-tuning is one edit there;
changing the formula itself is one edit here.
"""
from .tuning import (EPLEY_DIVISOR, LOADING_INCREMENT_LBS,
                     MAX_REPS_FOR_ESTIMATE, MIN_REPS_FOR_ESTIMATE)


def one_rep_max(weight_lbs, reps):
    """"They lifted X for N reps" -> "their one-rep max is about Y".

    Epley: 1RM = weight x (1 + reps / EPLEY_DIVISOR), divisor 30 by default.

    Returns None when the inputs can't support an estimate (no weight, or a rep
    count outside the honest window), so callers can skip rather than special-case.
    """
    if not weight_lbs or reps is None:
        return None
    if reps < MIN_REPS_FOR_ESTIMATE or reps > MAX_REPS_FOR_ESTIMATE:
        return None
    return weight_lbs * (1 + reps / EPLEY_DIVISOR)


def normalize_to_single(reference_weight_lbs, rep_basis):
    """Convert a recorded reference to a 1-rep basis.

    A "315 for 3" and a "315 for 1" are not the same athlete, so a stored
    reference carries the rep count it was set at. Percentages are always taken
    against a single, so anything else gets converted first.
    """
    if rep_basis is None or rep_basis <= 1:
        return reference_weight_lbs
    converted = one_rep_max(reference_weight_lbs, rep_basis)
    # A reference recorded at an absurd rep count is better used as-is than
    # thrown away — the coach entered it deliberately.
    return converted if converted is not None else reference_weight_lbs


def round_to_loadable(weight_lbs):
    """Snap a computed weight to something you can actually load on a bar."""
    if weight_lbs is None:
        return None
    return round(weight_lbs / LOADING_INCREMENT_LBS) * float(LOADING_INCREMENT_LBS)
