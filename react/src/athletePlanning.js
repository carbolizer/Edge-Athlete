export function buildAthleteAssignmentPayload(workoutProgramId) {
  return { workout_program_id: Number(workoutProgramId) };
}

export function buildOverrideFields(draft) {
  const payload = {};
  for (const field of ["sets", "reps", "weight_lbs"]) {
    if (!Object.hasOwn(draft, field)) continue;
    payload[field] = draft[field] === "" ? null : Number(draft[field]);
  }
  return payload;
}

export function exerciseTargetView(exercise) {
  const template = exercise.template || exercise.template_targets || {};
  const effective = exercise.effective || exercise.effective_targets || {};
  const override = exercise.override || exercise.athlete_override || {};
  return {
    sets: {
      template: template.sets ?? exercise.sets,
      effective: effective.sets ?? exercise.effective_sets ?? override.sets ?? template.sets ?? exercise.sets,
    },
    reps: {
      template: template.reps ?? exercise.reps,
      effective: effective.reps ?? exercise.effective_reps ?? override.reps ?? template.reps ?? exercise.reps,
    },
    weight_lbs: {
      template: template.weight_lbs ?? template.default_weight_lbs ?? exercise.default_weight_lbs,
      effective: effective.weight_lbs ?? exercise.effective_weight_lbs ?? override.weight_lbs ?? template.weight_lbs ?? template.default_weight_lbs ?? exercise.default_weight_lbs,
    },
  };
}

export function effectiveAssignmentLabel(source, assignment) {
  const label = assignment?.workout?.name || assignment?.name || "Workout unavailable";
  if (source === "athlete" || source === "athlete_assignment" || source === "athlete_program") return `Athlete program · ${label}`;
  if (source === "rack" || source === "rack_assignment") return `Rack assignment · ${label}`;
  return `No effective assignment · ${label}`;
}

export function resolveRackPlanningState(rackState) {
  const roster = rackState?.active_athletes || [];
  const identityAvailable = rackState?.identity_available ?? Boolean(rackState?.active_session && !rackState?.active_program && roster.length);
  let source = rackState?.effective_assignment_source ?? null;
  if (!source && rackState?.effective_workout) source = rackState.assignment ? "rack" : "athlete";
  return { identityAvailable, source };
}

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function confirmedProgramSelection(currentId, nextId, dirty, confirmDiscard) {
  if (String(currentId) === String(nextId)) return { id: currentId, confirmed: false };
  if (dirty && !confirmDiscard()) return { id: currentId, confirmed: false };
  return { id: nextId, confirmed: true };
}

export function serverLocalDate(body) {
  const candidates = [
    body?.training_date,
    body?.effective?.training_date,
    body?.resolved?.training_date,
    body?.preview?.training_date,
  ];
  return candidates.find((value) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) || "";
}

export function materializeProgram(program, clientId = "main") {
  return {
    client_id: clientId,
    name: program?.name || "Athlete plan",
    workout_program_id: program?.id ?? null,
    workouts: (program?.items || []).map((item) => ({
      workout_id: item.workout.id,
      name: item.workout.name,
      exercises: (item.workout.exercises || []).map((exercise) => ({
        workout_exercise_id: exercise.id,
        exercise: exercise.exercise,
        sets: exercise.sets,
        reps: exercise.reps,
        weight_lbs: exercise.default_weight_lbs,
        velocity_min: exercise.velocity_min,
        velocity_max: exercise.velocity_max,
      })),
    })),
  };
}

export function normalizeSchedule(body) {
  if (!body) return { version: 0, training_date: "", plans: [], entries: [] };
  const planClientIds = new Map((body.plans || []).map((plan) => [Number(plan.id), String(plan.client_id || plan.position)]));
  return {
    version: body.version,
    training_date: serverLocalDate(body),
    plans: (body.plans || []).map((plan) => ({
      ...plan,
      client_id: String(plan.client_id || plan.position),
      workouts: (plan.workouts || []).map((workout) => ({
        ...workout,
        exercises: (workout.exercises || []).map((exercise) => ({ ...exercise, weight_lbs: exercise.weight_lbs })),
      })),
    })),
    entries: (body.entries || []).map((entry) => ({
      date: entry.date || "",
      weekday: entry.weekday ?? "",
      selector_type: entry.date ? "date" : "weekday",
      is_rest: entry.is_rest === true,
      plan_client_id: entry.is_rest ? null : planClientIds.get(Number(entry.plan_id)) || "main",
    })),
  };
}

export function addWorkoutOccurrence(plan, workout) {
  return {
    ...plan,
    workouts: [...(plan.workouts || []), {
      workout_id: workout.id,
      name: workout.name,
      exercises: (workout.exercises || []).map((exercise) => ({
        workout_exercise_id: exercise.id,
        exercise: exercise.exercise,
        sets: exercise.sets,
        reps: exercise.reps,
        weight_lbs: exercise.default_weight_lbs,
        velocity_min: exercise.velocity_min,
        velocity_max: exercise.velocity_max,
      })),
    }],
  };
}

export function moveOccurrence(items, index, direction) {
  const target = index + direction;
  if (target < 0 || target >= items.length) return items;
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function scheduleValidation(draft) {
  const errors = [];
  const add = (path, detail) => errors.push({ path, detail });
  if (!draft.plans.length || !draft.plans[0]?.workouts?.length) add("plan.workouts", "Add at least one workout to the athlete plan.");
  if (!draft.entries.length) add("entries", "Add at least one weekday or exact-date schedule entry.");
  const selectors = new Set();
  for (const [entryIndex, entry] of draft.entries.entries()) {
    const isDate = entry.selector_type === "date" || Boolean(entry.date);
    const selector = isDate ? entry.date : entry.weekday;
    const key = `${isDate ? "date" : "weekday"}:${selector}`;
    if (isDate && !/^\d{4}-\d{2}-\d{2}$/.test(entry.date || "")) add(`entries.${entryIndex}.date`, "Choose an exact date using the server-local calendar.");
    if (!isDate && entry.weekday === "") add(`entries.${entryIndex}.weekday`, "Choose a recurring weekday.");
    if (selectors.has(key)) add(`entries.${entryIndex}.selector`, `Duplicate ${isDate ? "exact date" : "weekday"} entry.`);
    else if (selector !== "") selectors.add(key);
  }
  for (const [workoutIndex, workout] of (draft.plans[0]?.workouts || []).entries()) {
    if (!workout.workout_id || !workout.exercises?.length) add(`plan.workouts.${workoutIndex}`, `${workout.name || "Workout"} needs at least one exercise.`);
    for (const [exerciseIndex, exercise] of (workout.exercises || []).entries()) {
      const base = `plan.workouts.${workoutIndex}.exercises.${exerciseIndex}`;
      if (!Number.isInteger(Number(exercise.sets)) || Number(exercise.sets) < 1) add(`${base}.sets`, "Sets must be a positive whole number.");
      if (!Number.isInteger(Number(exercise.reps)) || Number(exercise.reps) < 1) add(`${base}.reps`, "Reps must be a positive whole number.");
      if (!Number.isFinite(Number(exercise.weight_lbs)) || Number(exercise.weight_lbs) < 0 || exercise.weight_lbs === "") add(`${base}.weight_lbs`, "Weight must be zero or greater.");
    }
  }
  return errors;
}

export function validationErrorsAt(errors, path) {
  return errors.filter((error) => error?.path === path || error?.path?.startsWith(`${path}.`));
}

export function buildSchedulePayload(draft) {
  return {
    expected_version: draft.version,
    plans: draft.plans.map((plan) => ({
      client_id: String(plan.client_id),
      name: plan.name.trim(),
      workout_program_id: plan.workout_program_id || null,
      workouts: plan.workouts.map((workout) => ({
        workout_id: Number(workout.workout_id),
        exercises: workout.exercises.map((exercise) => ({
          workout_exercise_id: Number(exercise.workout_exercise_id),
          sets: Number(exercise.sets),
          reps: Number(exercise.reps),
          weight_lbs: Number(exercise.weight_lbs),
          velocity_min: exercise.velocity_min,
          velocity_max: exercise.velocity_max,
        })),
      })),
    })),
    entries: draft.entries.map((entry) => ({
      ...((entry.selector_type === "date" || entry.date) ? { date: entry.date } : { weekday: Number(entry.weekday) }),
      is_rest: entry.is_rest,
      ...(!entry.is_rest ? { plan_client_id: entry.plan_client_id || draft.plans[0]?.client_id } : {}),
    })),
  };
}
