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
        const itemPath = typeof item === "object" && item !== null ? `${path}${path ? "." : ""}${index}` : path;
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

export function validationErrorPath(error, form) {
  if (error?.path) return error.path;
  const field = error?.field || "";
  const row = Number(error?.row);
  if (form === "workout") {
    if (field === "name" || field === "workout_name" || error?.code === "workout_name_conflict") return "name";
    if (field === "exercises" || field.startsWith("exercises.")) return field;
    if (Number.isInteger(row) && row > 0) return `exercises.${row - 1}${field ? `.${field}` : ""}`;
  }
  if (form === "program") {
    if (field === "name" || error?.code === "workout_program_name_conflict") return "name";
    if (field === "items" || field.startsWith("items.")) return field;
    if (Number.isInteger(row) && row > 0) return `items.${row - 1}${field ? `.${field}` : ""}`;
  }
  return "";
}

export function validationErrorsAt(errors, path, form, exact = true) {
  return errors.filter((error) => {
    const errorPath = validationErrorPath(error, form);
    return exact ? errorPath === path : errorPath === path || errorPath.startsWith(`${path}.`);
  });
}

export function unscopedValidationErrors(errors, form) {
  return errors.filter((error) => !validationErrorPath(error, form));
}

export function validateWorkoutDraft(name, exercises) {
  const errors = [];
  if (!name.trim()) errors.push({ path: "name", detail: "Workout name is required." });
  exercises.forEach((exercise, index) => {
    const base = `exercises.${index}`;
    if (!exercise.exercise.trim()) errors.push({ path: `${base}.exercise`, detail: "Movement is required." });
    for (const field of ["sets", "reps"]) {
      if (!/^\d+$/.test(String(exercise[field])) || Number(exercise[field]) < 1) errors.push({ path: `${base}.${field}`, detail: `${field === "sets" ? "Sets" : "Reps"} must be a positive whole number.` });
    }
    const weight = Number(exercise.default_weight_lbs);
    if (exercise.default_weight_lbs === "" || !Number.isFinite(weight) || weight < 0) errors.push({ path: `${base}.default_weight_lbs`, detail: "Weight must be zero or greater." });
    const hasMin = exercise.velocity_min !== "";
    const hasMax = exercise.velocity_max !== "";
    if (hasMin !== hasMax) {
      errors.push({ path: `${base}.${hasMin ? "velocity_max" : "velocity_min"}`, detail: "Enter both velocity bounds or leave both blank." });
    } else if (hasMin) {
      const minimum = Number(exercise.velocity_min);
      const maximum = Number(exercise.velocity_max);
      if (!Number.isFinite(minimum) || minimum < 0 || minimum > 10) errors.push({ path: `${base}.velocity_min`, detail: "Velocity minimum must be between 0 and 10." });
      if (!Number.isFinite(maximum) || maximum < minimum || maximum > 10) errors.push({ path: `${base}.velocity_max`, detail: "Velocity maximum must be between the minimum and 10." });
    }
  });
  return errors;
}

export function validateProgramDraft(name, selected) {
  const errors = [];
  if (!name.trim()) errors.push({ path: "name", detail: "Program name is required." });
  if (!selected.length) errors.push({ path: "items", detail: "Add at least one workout." });
  return errors;
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
