"""Reading a coach's spreadsheet safely, before anything about lifting matters.

WHAT THIS FILE IS FOR
A coach uploads a file. It could be anything — a huge file, a file that isn't
really a CSV, a file saved out of Excel with a weird invisible character at the
front. This file's whole job is to turn that upload into plain rows of text, or
to say clearly what's wrong with it. It knows nothing about athletes, weights,
or workouts; that lives in csv_import.py.

WHY IT IS SPLIT OUT
Two reasons. The checking here is fiddly and easy to get subtly wrong, so it
should be written once and shared by every kind of sheet we accept. And keeping
it separate means the lifting rules next door read as lifting rules, not as a
pile of file handling.

WHY THE ERRORS LOOK THE WAY THEY DO
Every problem is reported as one small record: which row, which column, a short
code, and a sentence a coach can read. That shape lets the screen put a mark on
the exact cell that's wrong instead of showing one useless "upload failed", and
it's the shape the coach app already knows how to display.

Most of this was written on the other branch and kept nearly as-is, because it
was already careful and already matched what the screen expects.
"""

from collections import Counter
from collections.abc import Mapping
import csv
import io
import math
import re

# A coach's spreadsheet is a few hundred lines. These caps exist so a truck-sized
# or endless file gets a clear answer instead of tying up the base station, which
# is also running a live gym at the time.
MAX_CSV_BYTES = 1024 * 1024
MAX_CSV_ROWS = 1000

# Postgres' limit for the integer columns these rows land in. Checked before the
# database sees the number so an absurd value comes back as a readable row error
# rather than a 500.
POSITIVE_INTEGER_MAX = 2147483647

_POSITIVE_INTEGER = re.compile(r"^[0-9]+$")
_WHITESPACE_RUN = re.compile(r"\s+")


def validation_error(row, field, code, detail, **extra):
    """One problem, in the shape every screen already knows how to display.

    `row` is the line number in the coach's file (None for a whole-file problem),
    `field` the column, `code` something the frontend can branch on, and `detail`
    a sentence written for a coach rather than a developer. `extra` carries
    optional extras like `suggestions` (see csv_import) without every caller
    needing to know about them.
    """
    return {"row": row, "field": field, "code": code, "detail": detail, **extra}


def normalize_name(value):
    """Squash the harmless ways the same name gets typed differently.

    Lowercase, trim the ends, and collapse runs of spaces, so "  Back  Squat "
    and "back squat" stop being two different movements. This is for COMPARING
    only — whatever the coach actually typed is what we store and show back.
    """
    if not isinstance(value, str):
        return ""
    return _WHITESPACE_RUN.sub(" ", value.strip()).casefold()


def flip_last_first(value):
    """Turn "Lee, Jordan" into "Jordan Lee".

    Exported rosters love the surname-first format. Only a single comma is
    treated this way — "Lee, Jordan, Jr" is left alone, because guessing at
    that one would do more harm than good.
    """
    if not isinstance(value, str) or value.count(",") != 1:
        return value
    last, first = (part.strip() for part in value.split(","))
    return f"{first} {last}" if last and first else value


def required_text(value, row, field, errors):
    """A column that must be filled in."""
    if not isinstance(value, str) or not value.strip():
        errors.append(validation_error(row, field, "required", f"{field} is required."))
        return None
    value = value.strip()
    if len(value) > 255:
        errors.append(validation_error(row, field, "too_long",
                                       f"{field} must be at most 255 characters."))
        return None
    return value


def positive_integer(value, row, field, errors):
    """A whole counting number — sets, reps, position. Never zero or negative."""
    digits = None
    if isinstance(value, bool):
        parsed = None
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        digits = value.strip()
        parsed = None
        if _POSITIVE_INTEGER.fullmatch(digits):
            normalized = digits.lstrip("0") or "0"
            maximum = str(POSITIVE_INTEGER_MAX)
            if len(normalized) < len(maximum) or (
                len(normalized) == len(maximum) and normalized <= maximum
            ):
                parsed = int(normalized)
    else:
        parsed = None

    too_big = (isinstance(value, int) and not isinstance(value, bool)
               and value > POSITIVE_INTEGER_MAX)
    overflowed = digits is not None and _POSITIVE_INTEGER.fullmatch(digits) and parsed is None
    if too_big or overflowed:
        errors.append(validation_error(row, field, "out_of_range",
                                       f"{field} must be at most {POSITIVE_INTEGER_MAX}."))
        return None
    if parsed is None or parsed < 1:
        errors.append(validation_error(row, field, "invalid_integer",
                                       f"{field} must be a positive whole number."))
        return None
    return parsed


def finite_number(value, row, field, errors, *, minimum=None, maximum=None):
    """A decimal number — a weight, a percent, a velocity.

    Rejects the values that look like numbers to Python but aren't usable ones
    (infinity, not-a-number), because those sail through arithmetic and only
    surface much later as a nonsense weight on somebody's bar.
    """
    if isinstance(value, bool) or value is None or (isinstance(value, str) and not value.strip()):
        parsed = None
    else:
        if isinstance(value, str):
            value = value.strip().rstrip("%").strip()
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            parsed = None

    if parsed is None or not math.isfinite(parsed):
        errors.append(validation_error(row, field, "invalid_number",
                                       f"{field} must be a number."))
        return None
    if minimum is not None and parsed < minimum:
        errors.append(validation_error(row, field, "out_of_range",
                                       f"{field} must be at least {minimum}."))
        return None
    if maximum is not None and parsed > maximum:
        errors.append(validation_error(row, field, "out_of_range",
                                       f"{field} must be at most {maximum}."))
        return None
    return parsed


def is_blank(value):
    """True when the coach left the cell empty."""
    return value is None or (isinstance(value, str) and not value.strip())


def optional_number(value, row, field, errors, *, minimum=None, maximum=None):
    """A column a coach may legitimately leave empty. Blank means blank, not zero."""
    if is_blank(value):
        return None
    return finite_number(value, row, field, errors, minimum=minimum, maximum=maximum)


def read_csv(uploaded_file):
    """Turn an upload into (headers, rows, errors).

    `rows` come back as (line_number, {column: text}) so any later complaint can
    point at the coach's actual line number, which is the only row number they
    can see in their spreadsheet.

    Header names are NOT checked here — which columns are required depends on
    what kind of sheet this is, and that isn't known until the headers have been
    read. csv_import decides. Returning early with an empty header list on a
    fatal problem keeps the caller from having to re-check.
    """
    if uploaded_file is None:
        return [], [], [validation_error(None, "file", "file_required", "Please choose a CSV file.")]

    uploaded_file.seek(0)
    body = uploaded_file.read(MAX_CSV_BYTES + 1)
    if len(body) > MAX_CSV_BYTES:
        return [], [], [validation_error(None, "file", "file_too_large",
                                        "The file must be smaller than 1 MB.")]
    if not body:
        return [], [], [validation_error(None, "file", "empty_file", "The file is empty.")]

    try:
        # utf-8-sig strips the invisible marker Excel writes at the start of a
        # saved CSV; without it the first column name silently stops matching.
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], [], [validation_error(None, "file", "invalid_encoding",
                                        "The file must be saved as UTF-8 CSV.")]
    if "\x00" in text:
        return [], [], [validation_error(None, "file", "malformed_csv",
                                        "The file doesn't look like a CSV.")]

    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        headers = next(reader, None)
        if headers is None:
            return [], [], [validation_error(None, "file", "empty_file", "The file is empty.")]
        headers = [normalize_name(h) for h in headers]

        duplicates = sorted(h for h, count in Counter(headers).items() if count > 1)
        if duplicates:
            return headers, [], [validation_error(
                None, "headers", "duplicate_headers",
                f"The same column appears more than once: {', '.join(duplicates)}.")]

        rows = []
        for csv_row in reader:
            if not csv_row or all(not cell.strip() for cell in csv_row):
                continue  # a trailing blank line is not an error
            if len(rows) >= MAX_CSV_ROWS:
                return headers, [], [validation_error(
                    None, "file", "row_limit_exceeded",
                    f"The file must have at most {MAX_CSV_ROWS} rows.")]
            if len(csv_row) != len(headers):
                return headers, [], [validation_error(
                    reader.line_num, None, "malformed_csv",
                    "This row has a different number of columns than the header.")]
            rows.append((reader.line_num, dict(zip(headers, csv_row))))
    except (csv.Error, UnicodeError):
        return [], [], [validation_error(None, "file", "malformed_csv",
                                        "The file doesn't look like a CSV.")]

    if not rows:
        return headers, [], [validation_error(None, "file", "empty_csv",
                                             "The file has column names but no rows.")]
    return headers, rows, []


def check_headers(headers, required, optional, errors):
    """Complain about missing and unexpected columns, once the sheet type is known."""
    present = set(headers)
    missing = sorted(set(required) - present)
    unknown = sorted(present - set(required) - set(optional))
    if missing:
        errors.append(validation_error(None, "headers", "missing_headers",
                                       f"Missing column(s): {', '.join(missing)}."))
    if unknown:
        errors.append(validation_error(None, "headers", "unknown_headers",
                                       f"Unexpected column(s): {', '.join(unknown)}."))
    return not missing and not unknown


def as_mapping(raw, row_number, errors):
    """Guard for the hand-built (non-CSV) path, where a caller may pass junk."""
    if not isinstance(raw, Mapping):
        errors.append(validation_error(row_number, None, "invalid_row", "Each row must be an object."))
        return None
    return raw
