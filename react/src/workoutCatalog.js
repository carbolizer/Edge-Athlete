export function createExerciseDraft(position) {
  return {
    position,
    exercise: "",
    sets: "",
    reps: "",
    default_weight_lbs: "",
    velocity_min: "",
    velocity_max: "",
  };
}

export function buildWorkoutPayload(name, exercises) {
  return {
    name: name.trim(),
    exercises: exercises.map((exercise, index) => ({
      exercise: exercise.exercise.trim(),
      position: index + 1,
      sets: Number(exercise.sets),
      reps: Number(exercise.reps),
      default_weight_lbs: Number(exercise.default_weight_lbs),
      velocity_min: exercise.velocity_min === "" ? null : Number(exercise.velocity_min),
      velocity_max: exercise.velocity_max === "" ? null : Number(exercise.velocity_max),
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
