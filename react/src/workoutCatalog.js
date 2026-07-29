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

export function addProgramWorkout(selected, workout) {
  if (selected.some((item) => Number(item.id) === Number(workout.id))) return selected;
  return [...selected, { id: workout.id, name: workout.name }];
}

export function moveProgramWorkout(selected, index, direction) {
  const target = index + direction;
  if (target < 0 || target >= selected.length) return selected;
  const reordered = [...selected];
  [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
  return reordered;
}

export function buildWorkoutProgramPayload(name, selected) {
  return {
    name: name.trim(),
    items: selected.map((workout, index) => ({
      workout_id: Number(workout.id),
      position: index + 1,
    })),
  };
}
