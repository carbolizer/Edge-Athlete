export function buildTrainingDayPayload(label, athleteIds) {
  return {
    label: label.trim(),
    athletes: [...new Set(athleteIds.map(Number))],
  };
}

export function unfinishedRackNumbers(body) {
  const racks = body?.rack_numbers || body?.unfinished_racks || body?.racks || [];
  return racks.filter((rack) => Number.isInteger(Number(rack))).map(Number);
}

export function reportValue(value, suffix = "") {
  return value === null || value === undefined ? "--" : `${value}${suffix}`;
}

export function orderedReportPrescriptions(athlete) {
  const prescriptions = athlete?.prescriptions || athlete?.effective_prescriptions || (athlete?.prescription ? [athlete.prescription] : []);
  return [...prescriptions].sort((left, right) => (left.position || 0) - (right.position || 0));
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

// What to tell the coach after ending a day.
//
// This exists because the panel used to say a flat "Training day ended and
// report generated" while the screen redrew looking identical — several sessions
// were open at once, so ending one promoted the next and the button appeared
// broken. Naming the day that ended is the difference between a confusing screen
// and an explained one, and `still_open` is surfaced rather than swallowed
// because a silent second open day is exactly how that bug hid.
export function endedDayMessage(body) {
  const ended = body?.ended;
  if (!ended) return "Training day ended and report generated.";

  const label = ended.label ? `“${ended.label}”` : "The training day";
  const report = ended.report_generated
    ? "Its report is finalized."
    : "No report was generated.";
  const stillOpen = ended.still_open?.label
    ? ` ⚠️ Another day is still open: “${ended.still_open.label}”.`
    : "";

  return `${label} ended. ${report}${stillOpen}`;
}
