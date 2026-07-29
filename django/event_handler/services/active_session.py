"""
active_session.py — the one answer to "which training day is live right now?"

Every screen in the building has to agree on this. The rack tablet decides where
a set gets filed, the wall display decides what the room sees, and the coach
tablet decides what "End training day" ends. If any two of them resolve it
differently, sets land on the wrong day and nobody gets an error.

⚠️ WHY THIS FILE EXISTS. It used to be one helper in views.py with a docstring
claiming it was "deliberately the single place every endpoint agrees on which
session is active". It was not: the same query was hand-written FOUR times — in
views.py, twice more inside the rack endpoints, and again privately inside
room_state.py. Four copies of one rule is four places to forget when the rule
changes, and the rule is about to change: P14 makes a session creatable ahead of
time, so "active" will have to mean STARTED rather than merely existing. That is
a one-line change here and nowhere else, which is the entire point.
"""

from ..models import TrainingSession


def open_sessions():
    """Every session not yet ended, newest first.

    Tie-break is newest `started_at` then highest id, so two sessions created in
    the same instant resolve deterministically rather than by whatever order the
    database happens to return.

    There should normally be at most ONE — `sessions_view` refuses to open a
    second (P12). This still returns a queryset, because the P12 guard needs to
    name what is already open, and because a database written before that guard
    existed can legitimately hold several.
    """
    return TrainingSession.objects.filter(ended_at__isnull=True).order_by("-started_at", "-id")


def active_session():
    """The live session, or None.

    "Most recent unended session" is last-one-wins, which is exactly how a stray
    second open session used to silently capture check-ins (canon D18): athletes'
    sets attached to a day with no participants while every tablet looked normal.
    P12 stops a second one being opened. This helper still tolerates finding one,
    because old data can contain one and crashing on it would be worse.
    """
    return open_sessions().first()
