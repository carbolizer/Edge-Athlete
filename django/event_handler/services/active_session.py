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
    """Every session that is RUNNING — started and not yet ended, newest first.

    ⚠️ "Started" is the load-bearing word, and it arrived in P14. A session can
    now exist before it runs (`started_at` is null for a slot a coach set up for
    Thursday), so "not ended" is no longer the same question as "live". Without
    the started filter, next week's session would come back as the current one —
    and because Postgres sorts NULLs FIRST in a descending order, it would sort
    ahead of the day actually happening. That is the D18 failure with a calendar
    bolted on.

    Tie-break is newest `started_at` then highest id, so two sessions started in
    the same instant resolve deterministically rather than by whatever order the
    database happens to return.

    There should normally be at most ONE — `sessions_view` refuses to start a
    second (P12). This still returns a queryset, because the P12 guard needs to
    name what is already running, and because a database written before that
    guard existed can legitimately hold several.
    """
    return (TrainingSession.objects
            .filter(started_at__isnull=False, ended_at__isnull=True)
            .order_by("-started_at", "-id"))


def scheduled_but_not_started():
    """Sessions that exist but have not been started, soonest-created first.

    These are deliberately NOT active: they hold no racks and capture no
    check-ins. A coach sets one up ahead of time and starts it when the room
    fills.
    """
    return (TrainingSession.objects
            .filter(started_at__isnull=True, ended_at__isnull=True)
            .order_by("id"))


def active_session():
    """The live session, or None.

    ⚠️ THE SINGLE DEFINITION OF "ACTIVE". Every endpoint — coach, rack, and wall
    — comes through here, so they cannot disagree about which session athletes
    are checking into. Before P12 this query was hand-written FOUR times;
    consolidating it is what let P14 change the rule in one place.

    "Most recent RUNNING session" — started and not ended. Last-one-wins among
    those, which is exactly how a stray second open session used to silently
    capture check-ins (canon D18): athletes' sets attached to a day with no
    participants while every tablet looked normal. P12 stops a second being
    started; P14's nullable `started_at` stops a future one counting at all.
    This helper still tolerates finding several, because old data can contain
    them and crashing on it would be worse.
    """
    return open_sessions().first()
