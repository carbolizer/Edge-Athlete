"""Taking a coach's spreadsheet and turning it into real training data.

THE PROBLEM THIS SOLVES
Coaches already keep everything in spreadsheets. Making them retype it all into
a new app is how a new app gets abandoned. So they hand us the file they already
have — and the files they already have are not all the same kind of thing.

THE THREE KINDS OF SHEET
We work out which one it is by looking at the column names, then handle it:

  * A ROSTER      — just a list of people. Creates athletes.
  * A MAX SHEET   — what each person can lift. This is the most valuable one:
                    every prescribed weight in the whole system is a percentage
                    of these numbers, so without them nothing has a target.
  * A PLAN        — the workouts themselves, as percentages.

WHEN A WEIGHT'S MEANING IS UNCLEAR, WE SKIP IT
"225" in a spreadsheet could be a one-rep max, a set of five, or 80% of
something. If we guess wrong, the damage doesn't stay in that one cell: an
athlete's max is whatever was recorded most recently, so a wrong guess quietly
becomes their official number and drags down every other weight we prescribe
for them. Leaving it out is safe and visible — the coach gets told exactly who
is missing what, and the app already copes fine with an athlete who has no max
recorded yet. So: convert only when the sheet says plainly what the number
means, otherwise skip it and say so.

A TYPO SHOULDN'T THROW AWAY THE OTHER 199 ROWS
When a name doesn't match anything we know, we don't reject the file. We say
which row, offer the closest matches we can find, and hand back everything we
parsed so the coach can fix it on screen and try again. Nothing is ever written
until they do.

Nothing here creates people or movements behind the coach's back. A misspelling
turned into a new athlete would sit in the roster forever, shadowing the real
person — so creating is either the explicit point of the sheet (a roster) or an
explicit choice the coach makes.
"""

import difflib

from django.db import transaction

from ..models import (Athlete, AthleteReferenceMax, Exercise, TrainingBlockExercise,
                      TrainingBlockWorkout, TrainingGroup, TrainingProgramExercise,
                      TrainingProgramWorkout)
from .csv_parsing import (check_headers, flip_last_first, is_blank, normalize_name,
                          optional_number, positive_integer, read_csv, required_text,
                          validation_error)

# ───────────────────────────── sheet shapes ─────────────────────────────

SHEET_ROSTER = "roster"
SHEET_REFERENCE_MAX = "reference_max"
SHEET_PLAN = "plan"

# Which columns each kind of sheet uses. The "signature" column is the one that
# tells the three apart, so a coach never has to declare what they're uploading.
SHEET_COLUMNS = {
    SHEET_ROSTER: {
        "required": ("athlete_name",),
        "optional": ("nfc_tag_id", "notes", "training_group"),
    },
    SHEET_REFERENCE_MAX: {
        # One of max_lbs / weight_lbs must be present — checked separately below,
        # because "either of these two" isn't something a plain required list can
        # express. They mean different things; see _reference_from_row.
        "required": ("athlete_name", "exercise"),
        "optional": ("max_lbs", "weight_lbs", "reps", "target_percent", "nfc_tag_id"),
    },
    SHEET_PLAN: {
        "required": ("workout_name", "exercise", "position", "sets", "reps", "target_percent"),
        "optional": ("velocity_min", "velocity_max"),
    },
}

# A percent above 100 is real training (overload eccentrics), so it is allowed.
# Zero and negatives never are.
MIN_TARGET_PERCENT = 1.0
MAX_TARGET_PERCENT = 150.0

MAX_VELOCITY_MPS = 10.0


def detect_sheet_type(headers):
    """Work out which kind of sheet this is from its column names.

    Deliberately based on a single distinguishing column each, so the answer is
    obvious to a human reading the file and can't land on two types at once.
    """
    present = set(headers)
    if "workout_name" in present:
        return SHEET_PLAN
    if "athlete_name" in present:
        return SHEET_REFERENCE_MAX if "exercise" in present else SHEET_ROSTER
    return None


def _unrecognized_sheet_error():
    return validation_error(
        None, "headers", "unrecognized_sheet",
        "This file's columns don't match any sheet we recognise. A roster needs "
        "'athlete_name'; a max sheet needs 'athlete_name' and 'exercise'; a "
        "workout plan needs 'workout_name'.")


# ─────────────────────── matching names to real records ───────────────────────


class NameResolver:
    """Turns the names typed in a spreadsheet into the records they mean.

    Built once per import and reused for every row, so a roster of a few hundred
    is read from the database once rather than once per line.

    The order it tries things matters. An exact match inside the squad being
    imported for beats an exact match across the whole gym, because that is what
    narrows real ambiguity: two "Jordan Lee"s in a building is believable, two in
    the same thirty-person squad is not. Only when both of those are inconclusive
    do we stop and ask the coach.

    A COACH'S ANSWER OUTRANKS ALL OF IT
    Once the coach has told us who "Jordn Reyes" is, that answer is used for
    EVERY row spelled that way — which is the whole point of fixing it on screen
    instead of editing the file and uploading again. See `corrections`.
    """

    def __init__(self, records, scope_ids=None, corrections=None):
        # records: iterable of (id, display_name)
        self.display_by_id = {}
        self.ids_by_name = {}
        for record_id, display in records:
            self.display_by_id[record_id] = display
            self.ids_by_name.setdefault(normalize_name(display), []).append(record_id)
        self.scope_ids = set(scope_ids or ())
        # {misspelling -> id}, keyed the same way names are, so the coach's fix
        # matches every row with that spelling regardless of case or spacing.
        self.corrections = {normalize_name(text): record_id
                            for text, record_id in (corrections or {}).items()}

    def _candidates(self, raw):
        """Every record this text could mean, trying the surname-first spelling too."""
        for candidate_text in (raw, flip_last_first(raw)):
            found = self.ids_by_name.get(normalize_name(candidate_text))
            if found:
                return found
        return []

    def suggestions(self, raw, limit=3):
        """The closest names we do know, for "did you mean...?"."""
        close = difflib.get_close_matches(normalize_name(raw), self.ids_by_name.keys(),
                                          n=limit, cutoff=0.6)
        return [self.display_by_id[self.ids_by_name[name][0]] for name in close]

    def resolve(self, raw):
        """Return (record_id, problem_code). Exactly one of the two is set."""
        # The coach's own answer comes first — it is the only source here that
        # is a decision rather than a guess. An id we don't recognise is ignored
        # rather than trusted, so a stale or hand-edited correction falls back to
        # normal matching and re-reports the problem instead of silently writing
        # to whatever row that number happens to be.
        corrected = self.corrections.get(normalize_name(raw))
        if corrected is not None and corrected in self.display_by_id:
            return corrected, None

        candidates = self._candidates(raw)
        if not candidates:
            return None, "unknown"
        if len(candidates) == 1:
            return candidates[0], None

        in_scope = [c for c in candidates if c in self.scope_ids]
        if len(in_scope) == 1:
            return in_scope[0], None
        return None, "ambiguous"

    def candidate_labels(self, raw):
        """Who a duplicated name could be, labelled so a coach can tell them apart."""
        return [{"id": c, "name": self.display_by_id[c]} for c in self._candidates(raw)]


# Corrections arrive grouped by what they name, because the same text can mean
# two different things — "Jordan" could be an athlete a coach is fixing and, in
# another gym's sheet, nothing at all. Keying by kind keeps one fix from leaking
# into a lookup it was never meant for.
def _for(corrections, kind):
    return (corrections or {}).get(kind)


def _athlete_resolver(scope_group=None, corrections=None):
    scope_ids = ()
    if scope_group is not None:
        scope_ids = list(scope_group.athletes.values_list("id", flat=True))
    return NameResolver(Athlete.objects.values_list("id", "name"), scope_ids=scope_ids,
                        corrections=_for(corrections, "athlete"))


def _exercise_resolver(corrections=None):
    return NameResolver(Exercise.objects.values_list("id", "name"),
                        corrections=_for(corrections, "exercise"))


def _resolve_into(resolver, raw, row_number, field, errors, kind):
    """Shared "look this name up, or explain why we couldn't" step.

    The `suggestions` list on the error is what lets the screen offer a fix
    instead of just refusing the file.
    """
    if raw is None:
        return None
    record_id, problem = resolver.resolve(raw)
    if problem == "unknown":
        errors.append(validation_error(
            row_number, field, f"unknown_{kind}",
            f"No {kind.replace('_', ' ')} named '{raw}'.",
            value=raw, suggestions=resolver.suggestions(raw)))
        return None
    if problem == "ambiguous":
        errors.append(validation_error(
            row_number, field, f"ambiguous_{kind}",
            f"More than one {kind.replace('_', ' ')} is named '{raw}'. Pick which one you mean.",
            value=raw, candidates=resolver.candidate_labels(raw)))
        return None
    return record_id


# ───────────────────────────── the max sheet ─────────────────────────────


def _reference_from_row(raw, row_number, errors, skipped, athlete_name, exercise_name):
    """Work out the anchor number and what rep count it was set at.

    Four situations, and only one of them is a guess we refuse to make:

      max_lbs given          -> that IS the anchor. reps, if given, is its basis.
      weight_lbs + percent   -> the anchor is what that weight is a percentage of.
      weight_lbs + reps      -> the anchor is that weight at that rep count; the
                                conversion to a single happens later, exactly.
      weight_lbs, nothing else -> unknowable. Skipped, and reported.

    Returns (reference_weight_lbs, rep_basis) or (None, None) when skipped.
    """
    reps = None
    if not is_blank(raw.get("reps")):
        reps = positive_integer(raw.get("reps"), row_number, "reps", errors)

    percent = optional_number(raw.get("target_percent"), row_number, "target_percent", errors,
                              minimum=MIN_TARGET_PERCENT, maximum=MAX_TARGET_PERCENT)

    if not is_blank(raw.get("max_lbs")):
        weight = optional_number(raw.get("max_lbs"), row_number, "max_lbs", errors, minimum=0.1)
        return (weight, reps or 1) if weight is not None else (None, None)

    weight = optional_number(raw.get("weight_lbs"), row_number, "weight_lbs", errors, minimum=0.1)
    if weight is None:
        return None, None

    if percent is not None:
        # The sheet says this weight is N% of something; that something is the anchor.
        return weight / (percent / 100.0), reps or 1
    if reps is not None:
        return weight, reps

    skipped.append({
        "row": row_number,
        "athlete_name": athlete_name,
        "exercise": exercise_name,
        "code": "weight_meaning_unknown",
        "detail": (f"Skipped: '{weight_column_label(raw)}' for {athlete_name} doesn't say whether "
                   "it's a max, a set of reps, or a percentage. Add a 'reps' or "
                   "'target_percent' column, or rename the column to 'max_lbs'."),
    })
    return None, None


def weight_column_label(raw):
    """The number we couldn't interpret, shown back exactly as the coach typed it."""
    value = raw.get("max_lbs") if not is_blank(raw.get("max_lbs")) else raw.get("weight_lbs")
    return str(value).strip() if value is not None else ""


def validate_reference_max_rows(rows, headers, *, scope_group=None, corrections=None):
    """Check a max sheet. Returns (entries, errors, skipped)."""
    errors = []
    skipped = []
    shape = SHEET_COLUMNS[SHEET_REFERENCE_MAX]
    check_headers(headers, shape["required"], shape["optional"], errors)

    if "max_lbs" not in headers and "weight_lbs" not in headers:
        errors.append(validation_error(
            None, "headers", "missing_headers",
            "A max sheet needs a 'max_lbs' column (the weight IS their max) or a "
            "'weight_lbs' column (with 'reps' or 'target_percent' to say what it means)."))
    if errors:
        return [], errors, skipped

    athletes = _athlete_resolver(scope_group, corrections)
    exercises = _exercise_resolver(corrections)

    entries = []
    for row_number, raw in rows:
        athlete_name = required_text(raw.get("athlete_name"), row_number, "athlete_name", errors)
        exercise_name = required_text(raw.get("exercise"), row_number, "exercise", errors)
        athlete_id = _resolve_into(athletes, athlete_name, row_number, "athlete_name",
                                   errors, "athlete")
        exercise_id = _resolve_into(exercises, exercise_name, row_number, "exercise",
                                    errors, "exercise")

        weight, rep_basis = _reference_from_row(raw, row_number, errors, skipped,
                                                athlete_name, exercise_name)
        if None in (athlete_id, exercise_id, weight):
            continue
        entries.append({
            "row": row_number,
            "athlete_id": athlete_id,
            "athlete_name": athletes.display_by_id[athlete_id],
            "exercise_id": exercise_id,
            "exercise": exercises.display_by_id[exercise_id],
            "reference_weight_lbs": round(weight, 1),
            "rep_basis": rep_basis,
        })
    return entries, errors, skipped


@transaction.atomic
def create_reference_maxes(entries):
    """Record every max. Adds rows, never edits — an athlete's current number is
    simply their newest row, so re-importing a corrected sheet supersedes the old
    values while the history stays graphable."""
    return AthleteReferenceMax.objects.bulk_create([
        AthleteReferenceMax(
            athlete_id=entry["athlete_id"],
            exercise_id=entry["exercise_id"],
            reference_weight_lbs=entry["reference_weight_lbs"],
            rep_basis=entry["rep_basis"],
            source=AthleteReferenceMax.SOURCE_MANUAL,
        ) for entry in entries
    ])


# ───────────────────────────── the roster sheet ─────────────────────────────


def validate_roster_rows(rows, headers, *, scope_group=None, corrections=None):
    """Check a roster. Returns (entries, errors, skipped).

    Someone already on the roster is SKIPPED, not an error: re-uploading last
    season's list with ten new names on the end should add ten people, not
    refuse the file or create ten duplicates.
    """
    errors = []
    skipped = []
    shape = SHEET_COLUMNS[SHEET_ROSTER]
    check_headers(headers, shape["required"], shape["optional"], errors)
    if errors:
        return [], errors, skipped

    existing = _athlete_resolver(corrections=corrections)
    groups = NameResolver(TrainingGroup.objects.values_list("id", "name"),
                          corrections=_for(corrections, "training_group"))
    taken_tags = set(Athlete.objects.exclude(nfc_tag_id=None).values_list("nfc_tag_id", flat=True))

    entries = []
    seen_in_file = {}
    for row_number, raw in rows:
        name = required_text(raw.get("athlete_name"), row_number, "athlete_name", errors)
        if name is None:
            continue

        if existing._candidates(name):
            skipped.append({"row": row_number, "athlete_name": name, "code": "already_on_roster",
                            "detail": f"Skipped: {name} is already on the roster."})
            continue

        normalized = normalize_name(name)
        if normalized in seen_in_file:
            skipped.append({"row": row_number, "athlete_name": name, "code": "duplicate_in_file",
                            "detail": f"Skipped: {name} appears more than once in this file "
                                      f"(first on line {seen_in_file[normalized]})."})
            continue
        seen_in_file[normalized] = row_number

        tag = raw.get("nfc_tag_id")
        tag = tag.strip() if isinstance(tag, str) and tag.strip() else None
        if tag is not None and tag in taken_tags:
            errors.append(validation_error(row_number, "nfc_tag_id", "nfc_tag_taken",
                                           f"NFC tag '{tag}' is already used by another athlete."))
            continue
        if tag is not None:
            taken_tags.add(tag)

        group_id = None
        if not is_blank(raw.get("training_group")):
            group_id = _resolve_into(groups, raw["training_group"].strip(), row_number,
                                     "training_group", errors, "training_group")
            if group_id is None:
                continue
        elif scope_group is not None:
            group_id = scope_group.id  # importing "into" a squad puts them in it

        notes = raw.get("notes")
        entries.append({
            "row": row_number,
            "name": name,
            "nfc_tag_id": tag,
            "notes": notes.strip() if isinstance(notes, str) else "",
            "training_group_id": group_id,
        })
    return entries, errors, skipped


@transaction.atomic
def create_athletes(entries):
    """Add everyone, and put them in their squad if the sheet said which."""
    created = []
    for entry in entries:
        athlete = Athlete.objects.create(
            name=entry["name"],
            nfc_tag_id=entry["nfc_tag_id"],
            notes=entry["notes"],
        )
        if entry["training_group_id"] is not None:
            athlete.training_groups.add(entry["training_group_id"])
        created.append(athlete)
    return created


# ───────────────────────────── the plan sheet ─────────────────────────────


def validate_plan_rows(rows, headers, *, corrections=None):
    """Check a workout plan. Returns (workouts, errors, skipped).

    Rows are grouped into workouts by 'workout_name'. The ORDER of the workouts
    is the order their names first appear in the file, because a spreadsheet's
    row order is what a coach means by "day 1, day 2" — there is no separate
    column for it and asking for one would be a chore.
    """
    errors = []
    shape = SHEET_COLUMNS[SHEET_PLAN]
    check_headers(headers, shape["required"], shape["optional"], errors)
    if errors:
        return [], errors, []

    exercises = _exercise_resolver(corrections)
    grouped = {}

    for row_number, raw in rows:
        workout_name = required_text(raw.get("workout_name"), row_number, "workout_name", errors)
        exercise_name = required_text(raw.get("exercise"), row_number, "exercise", errors)
        position = positive_integer(raw.get("position"), row_number, "position", errors)
        sets = positive_integer(raw.get("sets"), row_number, "sets", errors)
        reps = positive_integer(raw.get("reps"), row_number, "reps", errors)
        percent = optional_number(raw.get("target_percent"), row_number, "target_percent", errors,
                                  minimum=MIN_TARGET_PERCENT, maximum=MAX_TARGET_PERCENT)
        if percent is None and is_blank(raw.get("target_percent")):
            errors.append(validation_error(row_number, "target_percent", "required",
                                           "target_percent is required — plans are written as a "
                                           "percentage of the athlete's max, not a fixed weight."))

        velocity_min = optional_number(raw.get("velocity_min"), row_number, "velocity_min", errors,
                                       minimum=0, maximum=MAX_VELOCITY_MPS)
        velocity_max = optional_number(raw.get("velocity_max"), row_number, "velocity_max", errors,
                                       minimum=0, maximum=MAX_VELOCITY_MPS)
        if is_blank(raw.get("velocity_min")) != is_blank(raw.get("velocity_max")):
            errors.append(validation_error(
                row_number, "velocity_min", "velocity_pair_required",
                "Fill in both velocity_min and velocity_max, or leave both empty."))
            velocity_min = velocity_max = None
        elif None not in (velocity_min, velocity_max) and velocity_max < velocity_min:
            errors.append(validation_error(row_number, "velocity_max", "invalid_velocity_range",
                                           "velocity_max must be at least velocity_min."))

        exercise_id = _resolve_into(exercises, exercise_name, row_number, "exercise",
                                    errors, "exercise")

        if workout_name is None:
            continue
        workout = grouped.setdefault(normalize_name(workout_name), {
            "name": workout_name,
            "exercises": [],
        })
        if None in (exercise_id, position, sets, reps, percent):
            continue
        workout["exercises"].append({
            "row": row_number,
            "exercise_id": exercise_id,
            "exercise": exercises.display_by_id[exercise_id],
            "position": position,
            "sets": sets,
            "reps": reps,
            "target_percent": percent,
            "velocity_zone_min": velocity_min,
            "velocity_zone_max": velocity_max,
        })

    for workout in grouped.values():
        _check_positions(workout, errors)
        workout["exercises"].sort(key=lambda row: row["position"])

    return list(grouped.values()), errors, []


def _check_positions(workout, errors):
    """A workout's exercise order must be 1, 2, 3... with no gaps or repeats.

    A gap or a repeat means the coach's spreadsheet lost a row or has one pasted
    twice, and either way the order they intended is no longer recoverable — so
    it is worth stopping for rather than quietly picking one.
    """
    positions = [row["position"] for row in workout["exercises"]]
    if not positions:
        return
    seen = set()
    for row in workout["exercises"]:
        if row["position"] in seen:
            errors.append(validation_error(
                row["row"], "position", "duplicate_position",
                f"'{workout['name']}' uses position {row['position']} more than once."))
        seen.add(row["position"])
    if sorted(seen) != list(range(1, len(seen) + 1)):
        errors.append(validation_error(
            workout["exercises"][0]["row"], "position", "non_contiguous_positions",
            f"'{workout['name']}' must number its exercises 1, 2, 3... with no gaps."))


# A template and a squad's live plan hold identical rows in two parallel pairs of
# tables (see models.py — a program is a snapshot copy of a block, so editing one
# season's plan can't rewrite last season's history). Importing into either is the
# same work against different names, so the names are looked up here rather than
# writing the loop below twice.
_PLAN_TARGETS = {
    "block": {
        "workout_model": TrainingBlockWorkout,
        "exercise_model": TrainingBlockExercise,
        "parent_field": "training_block",
        "workout_field": "training_block_workout",
    },
    "program": {
        "workout_model": TrainingProgramWorkout,
        "exercise_model": TrainingProgramExercise,
        "parent_field": "training_program",
        "workout_field": "training_program_workout",
    },
}


@transaction.atomic
def create_plan_workouts(workouts, target, kind):
    """Add these workouts to a template ("block") or to a squad's plan ("program").

    New workouts are APPENDED after whatever the target already has, so importing
    into a template that already holds two days adds days three and four instead
    of colliding with them.
    """
    tables = _PLAN_TARGETS[kind]
    workout_model = tables["workout_model"]
    exercise_model = tables["exercise_model"]

    last_position = (workout_model.objects
                     .filter(**{tables["parent_field"]: target})
                     .order_by("-position")
                     .values_list("position", flat=True)
                     .first()) or 0

    created = []
    for offset, workout_data in enumerate(workouts, start=1):
        workout = workout_model.objects.create(**{
            tables["parent_field"]: target,
            "name": workout_data["name"],
            "position": last_position + offset,
        })
        exercise_model.objects.bulk_create([
            exercise_model(**{
                tables["workout_field"]: workout,
                "exercise_id": row["exercise_id"],
                "position": row["position"],
                "sets": row["sets"],
                "reps": row["reps"],
                "target_percent": row["target_percent"],
                "velocity_zone_min": row["velocity_zone_min"],
                "velocity_zone_max": row["velocity_zone_max"],
            }) for row in workout_data["exercises"]
        ])
        created.append(workout)
    return created


# ───────────────────────────── the front door ─────────────────────────────

VALIDATORS = {
    SHEET_ROSTER: validate_roster_rows,
    SHEET_REFERENCE_MAX: validate_reference_max_rows,
    SHEET_PLAN: validate_plan_rows,
}


def validate_upload(uploaded_file, *, scope_group=None, corrections=None):
    """Read a file and check it, writing nothing.

    Returns (sheet_type, payload, errors, skipped). `payload` comes back even
    when there are errors, so the screen can show the coach their own rows with
    the bad cells marked instead of an empty page and a refusal.

    `corrections` is how a coach's on-screen fix survives the round trip. The
    file is deliberately re-read from scratch every time — we never trust a
    previous preview — so without this the app would forget the answer it just
    asked for and report the same problem again. Shape:

        {"athlete": {"Jordn Reyes": 42}, "exercise": {"Bnch Press": 7}}

    A correction applies to EVERY row with that spelling, which is why a sheet
    with one name misspelled forty times is one fix and not forty.
    """
    headers, rows, errors = read_csv(uploaded_file)
    if errors:
        return None, [], errors, []

    sheet_type = detect_sheet_type(headers)
    if sheet_type is None:
        return None, [], [_unrecognized_sheet_error()], []

    validator = VALIDATORS[sheet_type]
    if sheet_type == SHEET_PLAN:
        payload, errors, skipped = validator(rows, headers, corrections=corrections)
    else:
        payload, errors, skipped = validator(rows, headers, scope_group=scope_group,
                                             corrections=corrections)
    return sheet_type, payload, errors, skipped


def commit_upload(sheet_type, payload, target=None, kind=None):
    """Write a payload that has already been checked. Returns how many rows landed."""
    if sheet_type == SHEET_ROSTER:
        return len(create_athletes(payload))
    if sheet_type == SHEET_REFERENCE_MAX:
        return len(create_reference_maxes(payload))
    return len(create_plan_workouts(payload, target, kind))
