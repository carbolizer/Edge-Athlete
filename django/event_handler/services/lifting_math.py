"""The lifting arithmetic, in one place on purpose.

There is exactly ONE formula in this system for moving between "lifted X for N
reps" and "could lift Y once", and it lives here. Two very different features
need it — deciding what to put on the bar today, and updating an athlete's
working max after a session — and they must never drift apart, so neither one
gets its own copy.

Swapping the formula (Epley for Brzycki, or a coach-tuned curve) is a one-line
change in this file. That is the whole reason the file exists.
"""

# A rep count outside this window can't support an honest estimate: a single is
# already a max attempt, and a 30-rep set is conditioning, where every one of
# these formulas falls apart. Callers get None rather than a confident wrong
# number.
MIN_REPS_FOR_ESTIMATE = 1
MAX_REPS_FOR_ESTIMATE = 12

# Gyms load in 5 lb steps (2.5 lb plates in pairs), so a prescription of 198.3
# is noise. Round to something an athlete can actually build on the bar.
LOADING_INCREMENT_LBS = 5


def one_rep_max(weight_lbs, reps):
    """"They lifted X for N reps" -> "their one-rep max is about Y".

    Epley: 1RM = weight x (1 + reps/30).

    Returns None when the inputs can't support an estimate (no weight, or a rep
    count outside the honest window), so callers can skip rather than special-case.
    """
    if not weight_lbs or reps is None:
        return None
    if reps < MIN_REPS_FOR_ESTIMATE or reps > MAX_REPS_FOR_ESTIMATE:
        return None
    return weight_lbs * (1 + reps / 30)


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
