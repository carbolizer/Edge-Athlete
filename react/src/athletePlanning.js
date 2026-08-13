// athletePlanning.js — shaping for the "what is this athlete training" panel.
//
// The thing to understand before reading this: an athlete is not assigned a plan
// directly. A plan belongs to a GROUP, and an athlete trains it by being in that
// group. So "assign this athlete to a program" really means "put them in the
// group that runs it", and one athlete can be in several groups at once and
// therefore carry more than one plan.
//
// That is why the assignment response is a LIST, not a single program.

// The id here is a deployed TrainingProgram — a plan a group is actually
// running — never a TrainingBlock. A block is just the template; nobody trains
// a template. Sending a block id here would either fail or, worse, match an
// unrelated program that happens to share the number.
export function buildAthleteAssignmentPayload(trainingProgramId) {
  return { training_program: Number(trainingProgramId) };
}

// An override is an exception for one athlete on one prescribed line. It moves
// the PERCENTAGE, never a fixed weight, so their target still tracks their own
// max instead of freezing at a number that ages badly.
//
// A blank field means "inherit the group's value", which is why "" becomes null
// rather than 0 — those mean very different things to a lifter.
export function buildOverrideFields(draft) {
  const payload = {};
  for (const field of ["target_percent", "sets", "reps"]) {
    if (!Object.hasOwn(draft, field)) continue;
    payload[field] = draft[field] === "" ? null : Number(draft[field]);
  }
  return payload;
}

// What the group prescribes vs what this athlete will actually do. Both are
// shown side by side so a coach can see at a glance whether someone is on the
// group's number or on their own.
export function exerciseTargetView(exercise) {
  const override = exercise.override || {};
  const pick = (field) => ({
    group: exercise[field],
    effective: override[field] ?? exercise[field],
  });
  return {
    sets: pick("sets"),
    reps: pick("reps"),
    target_percent: pick("target_percent"),
    // Resolved by the server from this athlete's own reference max. Null is a
    // real answer, not a failure: it means nobody has recorded a max for them
    // yet, and the rack will say so rather than inventing a weight.
    target_weight_lbs: exercise.target_weight_lbs ?? null,
  };
}

// Every workout across every plan that applies to this athlete, flattened for a
// picker and labelled with the group it comes from — because with two plans in
// play, "Day 1" alone is ambiguous.
export function assignedWorkoutOptions(assignment) {
  const options = [];
  for (const entry of assignment || []) {
    for (const workout of entry.workouts || []) {
      options.push({
        id: workout.id,
        label: `${entry.training_group?.name || "Group"} · ${workout.position}. ${workout.name}`,
        groupName: entry.training_group?.name || "",
        programName: entry.training_program?.name || "",
        exercises: workout.exercises || [],
      });
    }
  }
  return options;
}

// A plain sentence for the top of the panel. Silence is worse than a blunt "no
// plan" — a coach needs to know the difference between "not loaded" and
// "genuinely training nothing".
export function assignmentSummary(assignment) {
  const entries = assignment || [];
  if (!entries.length) return "No plan — this athlete is not in a group with a program.";
  return entries
    .map((entry) => `${entry.training_program?.name || "Plan"} (via ${entry.training_group?.name || "group"})`)
    .join(" · ");
}