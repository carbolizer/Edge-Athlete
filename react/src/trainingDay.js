export function buildTrainingDayPayload(label, athleteIds) {
  if (typeof athleteIds === "string") return { label: label.trim(), preview_version: athleteIds };
  return {
    label: label.trim(),
    athletes: [...new Set(athleteIds.map(Number))],
  };
}

export function previewGroups(preview) {
  const groups = { eligible: [], rest: [], missing: [] };
  for (const row of preview?.athletes || []) {
    if (row.eligible) groups.eligible.push(row);
    else if (row.is_rest) groups.rest.push(row);
    else groups.missing.push(row);
  }
  return groups;
}

export function unfinishedRackNumbers(body) {
  const racks = body?.rack_numbers || body?.unfinished_racks || body?.racks || [];
  return racks.filter((rack) => Number.isInteger(Number(rack))).map(Number);
}

export function reportValue(value, suffix = "") {
  return value === null || value === undefined ? "--" : `${value}${suffix}`;
}

export function orderedReportPrescriptions(athlete) {
  const prescriptions = athlete?.frozen_plan?.workouts || athlete?.prescriptions || athlete?.effective_prescriptions || (athlete?.prescription ? [athlete.prescription] : []);
  return [...prescriptions].sort((left, right) => (left.position || 0) - (right.position || 0));
}

export function reportExerciseSets(athlete, prescription, exercise) {
  const occurrenceId = prescription.occurrence_id ?? prescription.id;
  return (athlete?.sets || []).filter((workoutSet) => {
    if (workoutSet.day_plan_exercise_id != null && exercise.id != null) return Number(workoutSet.day_plan_exercise_id) === Number(exercise.id);
    if (workoutSet.workout_exercise_id != null && exercise.id != null) return Number(workoutSet.workout_exercise_id) === Number(exercise.id);
    if (workoutSet.day_plan_workout_id != null && occurrenceId != null) return Number(workoutSet.day_plan_workout_id) === Number(occurrenceId) && workoutSet.exercise === exercise.exercise;
    return workoutSet.exercise === exercise.exercise;
  });
}

export function orderedReportExercises(prescription) {
  return [...(prescription?.exercises || [])].sort((left, right) => (left.position || 0) - (right.position || 0));
}

export function reportAthletes(report) {
  return report?.athletes || report?.participants || [];
}

export function reportSnapshot(report) {
  return report?.snapshot || report || {};
}

export function reportSummary(report) {
  if (report?.summary) return report.summary;
  const athletes = reportAthletes(report);
  const sets = qualifyingReportSets(athletes.flatMap((athlete) => athlete.sets || []));
  return {
    athlete_count: athletes.length,
    completed_sets: sets.length,
    completed_reps: sets.reduce((total, workoutSet) => total + (workoutSet.reps_completed || 0), 0),
  };
}

export function reportAthleteContext(entry) {
  const frozenPlan = entry?.frozen_plan;
  return {
    scheduleSource: entry?.schedule_source || frozenPlan?.schedule_source || "legacy",
    scheduleVersion: frozenPlan?.schedule_version ?? null,
    programName: frozenPlan?.name || entry?.assigned_program?.name || null,
    progressStatus: entry?.final_progress?.status || null,
    rackNumbers: entry?.rack_participation || [],
  };
}

export function qualifyingReportSets(sets) {
  return sets.filter((workoutSet) => workoutSet?.is_false_set !== true);
}

export function budgetReportRendering(athletes, limits = REPORT_RENDER_LIMITS) {
  const totalSets = athletes.reduce((total, athlete) => total + (athlete.sets || []).length, 0);
  const totalReps = athletes.reduce((total, athlete) => total + (athlete.sets || []).reduce((setTotal, workoutSet) => setTotal + (workoutSet.reps || []).length, 0), 0);
  let remainingSets = limits.sets;
  let remainingReps = limits.reps;
  let renderedSetCount = 0;
  let renderedRepCount = 0;

  const renderedAthletes = athletes.slice(0, limits.athletes).map((entry) => {
    const sourceSets = entry.sets || [];
    const renderedSets = [];
    for (const workoutSet of sourceSets) {
      if (remainingSets <= 0) break;
      const sourceReps = workoutSet.reps || [];
      const reps = sourceReps.slice(0, Math.max(0, remainingReps));
      renderedSets.push({ workoutSet, reps, totalReps: sourceReps.length });
      remainingSets -= 1;
      remainingReps -= reps.length;
      renderedSetCount += 1;
      renderedRepCount += reps.length;
    }
    return { entry, sets: renderedSets, totalSets: sourceSets.length };
  });

  return {
    athletes: renderedAthletes,
    counts: {
      athletes: { rendered: renderedAthletes.length, total: athletes.length },
      sets: { rendered: renderedSetCount, total: totalSets },
      reps: { rendered: renderedRepCount, total: totalReps },
    },
  };
}
export const REPORT_RENDER_LIMITS = Object.freeze({ athletes: 100, sets: 200, reps: 1000 });
