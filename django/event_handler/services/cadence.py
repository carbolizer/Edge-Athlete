"""
cadence.py — which weekdays a block trains on, and the dates that fall out.

`TrainingBlock.cadence_days_of_week` is a short string like "Mon,Wed,Fri". The
coach UI is a row of seven checkboxes that always emits week-ordered tokens, and
the serializer re-validates and re-sorts on the way in, so by the time a value
reaches this module it is canonical.

Kept in its own module because three places need to agree on the vocabulary: the
serializer that validates it, the generator that reads it, and the tests. A
second list of day names that drifts from the first is the kind of bug that only
shows up on a Wednesday.
"""

from datetime import date, timedelta

# Week order, and the ONLY accepted tokens. Index matters: it lines up with
# Python's date.weekday(), where Monday is 0.
CADENCE_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_DURATION_WEEKS = 520

_WEEKDAY_BY_TOKEN = {token: index for index, token in enumerate(CADENCE_DAYS)}


def cadence_weekdays(cadence):
    """"Mon,Wed,Fri" -> [0, 2, 4], in week order.

    Unknown tokens are skipped rather than raising: the serializer is where a bad
    value gets refused, and a block written before that validation existed should
    still schedule the days it CAN rather than failing outright.
    """
    if not cadence:
        return []
    weekdays = {
        _WEEKDAY_BY_TOKEN[token]
        for raw in cadence.split(",")
        if (token := raw.strip().title()) in _WEEKDAY_BY_TOKEN
    }
    return sorted(weekdays)


def training_dates(start_date, cadence, duration_weeks):
    """Every date this block trains on, in order.

    Counts WEEKS FROM THE START DATE, not calendar weeks — a block starting on a
    Wednesday with a Mon/Wed/Fri cadence gets that Wednesday and Friday in its
    first week, then resumes on the Monday. Counting calendar weeks instead would
    silently hand the coach a short first week.

    Returns [] when there is nothing to go on. A block with no cadence or no
    duration is not an error — it is a template a coach has not finished
    describing, and the caller decides what to do about that.
    """
    weekdays = cadence_weekdays(cadence)
    if not start_date or not weekdays or not duration_weeks or duration_weeks < 1:
        return []
    if duration_weeks > MAX_DURATION_WEEKS:
        raise ValueError(f"duration_weeks cannot exceed {MAX_DURATION_WEEKS}")

    # ⚠️ A date can still arrive here as a STRING. Django coerces a date on its
    # way into the database but leaves the in-memory attribute exactly as it was
    # assigned, so a program created straight from request data holds
    # "2026-08-03" rather than a date — and the arithmetic below fails with
    # "can only concatenate str to str". The caller should parse first; this
    # accepts it anyway, because a calendar refusing to generate is a worse
    # outcome than being tolerant about one input.
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)

    # Inclusive of the start date, exclusive of the day the last week ends.
    last_date = start_date + timedelta(weeks=duration_weeks) - timedelta(days=1)

    dates = []
    day = start_date
    while day <= last_date:
        if day.weekday() in weekdays:
            dates.append(day)
        day += timedelta(days=1)
    return dates
