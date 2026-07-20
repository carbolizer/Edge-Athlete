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
