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

// ── choosing when a day ended ────────────────────────────────────────────────
//
// Normally nobody chooses: you press End and it ends now. This exists for the
// power-cut case — the base station restarts with the day still open, and the
// honest end time is when the room actually emptied, not when someone next
// managed to log in.
//
// It is a DROPDOWN of computed options rather than a free-text time, because
// every impossible answer should be unreachable instead of merely rejected. A
// day cannot end before it started, and it cannot end in the future; if those
// times are never on the menu, nobody has to be told off for picking one. The
// server validates too — it has to, since it is also the API's contract — but a
// coach on a tablet should never meet that error.

const HOUR_MS = 60 * 60 * 1000;

function atTopOfHour(date) {
  const hour = new Date(date);
  hour.setMinutes(0, 0, 0);
  return hour;
}

function clockLabel(date) {
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function dayLabel(date, now) {
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) return clockLabel(date);
  const yesterday = new Date(now.getTime() - 24 * HOUR_MS);
  const prefix = date.toDateString() === yesterday.toDateString()
    ? "Yesterday"
    : date.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  return `${prefix}, ${clockLabel(date)}`;
}

// Options are always: "now", then each top-of-hour going backwards, stopping at
// the hour the session started. The start itself is offered last so a day opened
// by mistake can be closed to zero length rather than left running.
export function endTimeChoices(startedAt, now = new Date(), limit = 24) {
  const start = new Date(startedAt);
  const end = new Date(now);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return [{ value: "", label: "Now" }];
  }

  const choices = [{ value: "", label: "Now" }];
  let mark = atTopOfHour(end);
  while (choices.length <= limit) {
    // Strictly inside (start, now) — the endpoints are covered by "Now" and by
    // the explicit start option below, so an hour mark equal to either would be
    // a duplicate rather than a new choice.
    if (mark <= start) break;
    if (mark < end) {
      choices.push({ value: mark.toISOString(), label: dayLabel(mark, end) });
    }
    mark = new Date(mark.getTime() - HOUR_MS);
  }

  choices.push({
    value: start.toISOString(),
    label: `When it started (${dayLabel(start, end)}) — zero-length day`,
  });
  return choices;
}

// The PATCH body. An empty choice means "end it now", which is the shorthand the
// endpoint has always understood, so we send nothing rather than a timestamp we
// computed ourselves — the base station's clock is the one that should decide.
export function buildEndDayPayload(endedAtChoice) {
  return endedAtChoice ? { ended_at: endedAtChoice } : {};
}
