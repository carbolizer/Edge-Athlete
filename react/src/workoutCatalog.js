// workoutCatalog.js — payload shaping for the workout catalog screen.
//
// The vocabulary here is worth getting straight, because two different things
// are both loosely called "a program":
//
//   TrainingBlock  — the reusable TEMPLATE a coach designs once ("Fall Strength").
//                    Timeless: no group, no dates.
//   workout        — one DAY inside a block ("Day 1 — Lower"). A workout cannot
//                    exist on its own; it always belongs to a block.
//   exercise row   — one prescribed movement in a day.
//
// The single most important thing on this screen: a prescribed load is a
// PERCENTAGE OF THE ATHLETE'S OWN MAX, not a number of pounds. One line —
// "Back squat, 5x3 @ 80%" — serves a whole group, and everyone's actual bar
// weight is worked out from their own tested max when they walk up to the rack.
// That is why the field is `target_percent` and never a weight.

// Percent bounds match the CSV importer's, so a hand-typed row and an imported
// row are held to the same rule.
export const MIN_TARGET_PERCENT = 1;
export const MAX_TARGET_PERCENT = 150;

export function createExerciseDraft(position) {
  return {
    position,
    exercise: "",          // an Exercise id, chosen from the movement catalog
    sets: "",
    reps: "",
    target_percent: "",    // percent of the athlete's max, NOT pounds
    velocity_zone_min: "",
    velocity_zone_max: "",
  };
}

// A whole training day in one payload — its block, its name, its place in the
// block, and its movements in order. Sent as one call so a half-entered workout
// can never exist in the catalog.
export function buildWorkoutPayload(name, exercises, trainingBlockId, position) {
  return {
    training_block: Number(trainingBlockId),
    name: name.trim(),
    ...(position ? { position: Number(position) } : {}),
    exercises: exercises.map((exercise, index) => ({
      // An id from the movement catalog, never a typed-in name — the catalog
      // exists so "Back Squat" and "back squat" can't become two movements.
      exercise: Number(exercise.exercise),
      position: index + 1,
      sets: Number(exercise.sets),
      reps: Number(exercise.reps),
      target_percent: Number(exercise.target_percent),
      velocity_zone_min: exercise.velocity_zone_min === "" ? null : Number(exercise.velocity_zone_min),
      velocity_zone_max: exercise.velocity_zone_max === "" ? null : Number(exercise.velocity_zone_max),
    })),
  };
}

export function flattenApiErrors(body, fallback) {
  const errors = [];

  function visit(value, path = "") {
    if (typeof value === "string") {
      errors.push({ field: path, detail: value });
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((item, index) => {
        const itemPath = typeof item === "object" && item !== null ? `${path}${path ? "." : ""}${index + 1}` : path;
        visit(item, itemPath);
      });
      return;
    }
    if (!value || typeof value !== "object") return;
    if (value.errors && typeof value.errors === "object" && Object.keys(value.errors).length) {
      visit(value.errors, path);
      return;
    }
    if (typeof value.detail === "string") {
      errors.push({
        row: value.row,
        field: value.field || path,
        code: value.code,
        detail: value.detail,
      });
      return;
    }
    Object.entries(value).forEach(([key, item]) => {
      if (key !== "code") visit(item, path ? `${path}.${key}` : key);
    });
  }

  visit(body);
  return errors.length ? errors : [{ detail: fallback }];
}

export function errorLabel(error) {
  const location = [error.row ? `Row ${error.row}` : "", error.field ? String(error.field).replaceAll("_", " ") : ""].filter(Boolean).join(" · ");
  return `${location ? `${location}: ` : ""}${error.detail}`;
}

// ─────────────────────── the CSV repair loop (canon D17) ───────────────────────
//
// A misspelled name doesn't reject the file. The server hands back every row it
// understood PLUS an error per row it didn't, each carrying the text it choked
// on and the closest matches it knows. The coach picks the right one on screen
// and the same file is sent again with their answers attached — no editing the
// spreadsheet, no re-uploading.
//
// Corrections are grouped by what they name, because the server keys them that
// way: an answer about an athlete must never satisfy a movement lookup.

// Which lookup an error belongs to, from its code (unknown_athlete,
// ambiguous_exercise, ...). Anything else isn't a naming problem and can't be
// repaired by pointing at a record.
export function correctionKind(code) {
  if (!code) return null;
  const match = /^(?:unknown|ambiguous)_(athlete|exercise|training_group)$/.exec(code);
  return match ? match[1] : null;
}

// The errors a coach can actually fix here, paired with the raw text to fix.
// Errors without a `value` (a missing column, an unreadable file) are real but
// belong in the plain error list — there is nothing to point at.
export function repairableErrors(errors) {
  return (errors || []).filter((error) => correctionKind(error.code) && error.value);
}

// Every record the coach could mean, closest matches first so the likely answer
// is at the top, but never ONLY the guesses — difflib can miss, and a coach who
// knows the right answer shouldn't be stuck because the algorithm didn't.
export function repairChoices(error, records) {
  const suggested = error.suggestions || [];
  const byName = new Map((records || []).map((record) => [record.name, record]));
  const candidates = (error.candidates || []).map((candidate) => ({ id: candidate.id, name: candidate.name, suggested: true }));
  const fromSuggestions = suggested
    .map((name) => byName.get(name))
    .filter(Boolean)
    .map((record) => ({ id: record.id, name: record.name, suggested: true }));
  const top = candidates.length ? candidates : fromSuggestions;
  const topIds = new Set(top.map((choice) => choice.id));
  const rest = (records || [])
    .filter((record) => !topIds.has(record.id))
    .map((record) => ({ id: record.id, name: record.name, suggested: false }));
  return [...top, ...rest];
}

// Fold one answer into the map the import endpoint expects.
export function applyCorrection(corrections, kind, value, recordId) {
  const next = { ...corrections, [kind]: { ...(corrections[kind] || {}) } };
  if (recordId === "" || recordId === null || recordId === undefined) delete next[kind][value];
  else next[kind][value] = Number(recordId);
  if (!Object.keys(next[kind]).length) delete next[kind];
  return next;
}

export function countCorrections(corrections) {
  return Object.values(corrections || {}).reduce((total, group) => total + Object.keys(group).length, 0);
}

export function sameOriginPath(value, origin) {
  if (!value) return null;
  try {
    const url = new URL(value, origin);
    if (url.origin !== origin || url.username || url.password) return null;
    return `${url.pathname}${url.search}`;
  } catch {
    return null;
  }
}

// A block is the template itself: what it's called, how long it runs, and which
// days of the week it's meant to be trained on. Its workouts are added
// afterwards, each one choosing this block and its own position.
//
// Duration and cadence are the coach's design, not decoration — they describe
// how the block is meant to be run. Nothing generates a calendar from them yet,
// which is why both are optional rather than absent.
export function buildTrainingBlockPayload(name, durationWeeks, cadenceDays) {
  return {
    name: name.trim(),
    duration_weeks: durationWeeks === "" ? null : Number(durationWeeks),
    // Stored as a plain string like "Mon,Wed,Fri".
    cadence_days_of_week: (cadenceDays || []).join(","),
  };
}

export const CADENCE_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function toggleCadenceDay(selected, day) {
  return selected.includes(day)
    ? selected.filter((item) => item !== day)
    : CADENCE_DAYS.filter((item) => selected.includes(item) || item === day);
}

// Deploying is what turns a template into something athletes actually train:
// the block gets copied down for one group, starting on a real date. The copy is
// independent from that moment on, so editing it later never disturbs the
// template it came from.
//
// `training_block` is optional on purpose — a coach can write a one-off plan for
// a group with no template behind it, and promote it to a template later.
export function buildDeployPayload(name, trainingGroupId, trainingBlockId, startDate, endDate) {
  return {
    name: name.trim(),
    training_group: Number(trainingGroupId),
    ...(trainingBlockId ? { training_block: Number(trainingBlockId) } : {}),
    start_date: startDate,
    ...(endDate ? { end_date: endDate } : {}),
  };
}
