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

export function compareReps(workoutSet) {
  const average = workoutSet.avg_velocity;
  return (workoutSet.reps || []).map((rep, index, reps) => ({
    ...rep,
    changeFromPrevious: index === 0 ? null : rep.mean_velocity - reps[index - 1].mean_velocity,
    changeFromAverage: average === null || average === undefined ? null : rep.mean_velocity - average,
  }));
}
