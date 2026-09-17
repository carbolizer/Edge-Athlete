/* Shapes the bounded athlete analytics response for the coach history hierarchy. */

export function localDayKey(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  return [date.getFullYear(), date.getMonth() + 1, date.getDate()]
    .map((part, index) => index === 0 ? String(part) : String(part).padStart(2, "0"))
    .join("-");
}

export function groupHistorySets(sets) {
  const days = new Map();
  for (const workoutSet of sets || []) {
    const dayKey = localDayKey(workoutSet.ended_at);
    if (!days.has(dayKey)) {
      days.set(dayKey, { key: dayKey, endedAt: workoutSet.ended_at, sets: 0, reps: 0, workouts: new Map() });
    }
    const day = days.get(dayKey);
    if (new Date(workoutSet.ended_at) > new Date(day.endedAt)) day.endedAt = workoutSet.ended_at;
    const workoutKey = String(workoutSet.session?.id ?? workoutSet.session?.label ?? "unknown");
    if (!day.workouts.has(workoutKey)) {
      day.workouts.set(workoutKey, {
        key: workoutKey,
        label: workoutSet.session?.label || "Unlabeled workout",
        sets: [],
        reps: 0,
      });
    }
    const workout = day.workouts.get(workoutKey);
    workout.sets.push(workoutSet);
    workout.reps += workoutSet.reps_completed || 0;
    day.sets += 1;
    day.reps += workoutSet.reps_completed || 0;
  }
  return [...days.values()]
    .map((day) => ({
      ...day,
      workouts: [...day.workouts.values()].map((workout) => ({
        ...workout,
        sets: [...workout.sets].sort((left, right) => new Date(right.ended_at) - new Date(left.ended_at)),
      })),
    }))
    .sort((left, right) => new Date(right.endedAt) - new Date(left.endedAt));
}

// A day-per-row summary for the top of the History tab: when they trained, how
// much, how fast, and which way it moved.
//
// ⚠️ THE AVERAGE POOLS EVERY MOVEMENT THAT DAY, and that is a real limitation,
// not a rounding detail. Velocity is only comparable within a lift — a squat
// day sits around 0.6 m/s and a bench day around 0.9 — so a day of benching
// after a day of squatting reads as a large jump when the athlete did nothing
// different. The screen says so next to the column rather than letting the
// arrow imply more than it knows.
//
// The honest alternative is a per-movement comparison: average each movement
// separately and compare it against the last day that movement was trained.
// It is about fifteen lines more and needs no new data — everything here comes
// from `sets`, which the athlete-context fetch already returns. Deliberate
// choice, recorded so the next person knows it was one.
//
// FLAT_BAND exists because two days are never numerically identical. Without it
// every row would show an arrow, including ones that moved by 0.001 m/s, and an
// arrow that is always on tells a coach nothing.
export const FLAT_BAND = 0.02;

export function summariseTrainingDays(days) {
  // Oldest first, so each day can look back at the one before it. Flipped back
  // at the end — a coach reads most-recent-first.
  const chronological = [...(days || [])].reverse();
  const summaries = chronological.map((day) => {
    const velocities = day.workouts
      .flatMap((workout) => workout.sets)
      .map((workoutSet) => workoutSet.avg_velocity)
      .filter((value) => value !== null && value !== undefined);
    const avgVelocity = velocities.length
      ? velocities.reduce((total, value) => total + value, 0) / velocities.length
      : null;
    return {
      key: day.key,
      endedAt: day.endedAt,
      sets: day.sets,
      reps: day.reps,
      workoutCount: day.workouts.length,
      avgVelocity,
      change: null,
      trend: null,
    };
  });

  for (let index = 1; index < summaries.length; index += 1) {
    const today = summaries[index];
    const before = summaries[index - 1];
    if (today.avgVelocity === null || before.avgVelocity === null) continue;
    today.change = today.avgVelocity - before.avgVelocity;
    today.trend = Math.abs(today.change) < FLAT_BAND
      ? "flat"
      : today.change > 0 ? "up" : "down";
  }

  return summaries.reverse();
}

export function compareReps(workoutSet) {
  const average = workoutSet.avg_velocity;
  return (workoutSet.reps || []).map((rep, index, reps) => ({
    ...rep,
    changeFromPrevious: index === 0 ? null : rep.mean_velocity - reps[index - 1].mean_velocity,
    changeFromAverage: average === null || average === undefined ? null : rep.mean_velocity - average,
  }));
}
