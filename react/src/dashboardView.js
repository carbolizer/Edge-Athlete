export function wallMovementView(roomState) {
  const movement = roomState?.movement;
  if (!movement) {
    return {
      waiting: true,
      name: "Waiting for a VBT movement",
      detail: "The leaderboard starts when an athlete signs into a velocity-targeted exercise.",
      rows: [],
    };
  }
  return {
    waiting: false,
    name: movement.name,
    detail: `${movement.participant_count} active athlete${movement.participant_count === 1 ? "" : "s"} · ${Number(movement.velocity_min).toFixed(2)}-${Number(movement.velocity_max).toFixed(2)} m/s target`,
    rows: roomState.leaderboard || [],
  };
}

export function wallDisplayState({ roomState, requestState, connectionState, lastError }) {
  if (!roomState && requestState === "loading") {
    return { status: "loading", roomState: null };
  }
  if (!roomState || requestState !== "ready") {
    return {
      status: "unavailable",
      roomState: null,
      message: lastError || "The latest room snapshot could not be loaded.",
    };
  }
  if (connectionState !== "live") {
    return {
      status: "unavailable",
      roomState: null,
      message: "Live scoreboard updates are unavailable while the room connection reconnects.",
    };
  }
  return { status: roomState.session ? "ready" : "empty", roomState };
}

// One rack, summarised for the coach's rack list and observation panel.
//
// A rack knows who is on it because that athlete CHECKED IN there — nobody is
// assigned to a rack in advance (canon D8). So the athlete lives on the rack
// itself, and what they are doing is read from their most recent set. There is
// no separate "training" block predicting what should happen next.
//
// Every field is optional on purpose: an idle rack with nobody on it is the
// normal state of most racks most of the time, not an error.
// What one set says about how the athlete is holding up, worked out from the
// reps themselves.
//
// His screen expected the server to send a `measured_insights` block. Ours
// doesn't — but it does send every rep, which is what those numbers were
// derived from, so they are computed here instead of adding a field.
//
// The one number that genuinely CANNOT be derived is the comparison against
// their previous set: that set isn't in this payload. It returns null and the
// panel shows "--" rather than inventing a trend, because a fabricated "you're
// 8% down" is the kind of thing a coach acts on.
export function measuredInsights(workoutSet) {
  const reps = (workoutSet?.reps || []).filter((r) => typeof r.mean_velocity === "number");
  const zone = workoutSet?.target_zone;
  const empty = {
    velocity_loss_percent: null, avg_velocity_change_percent: null,
    rep_velocity_range: null, mean_rep_duration_ms: null,
    reps_below_zone: 0, reps_in_zone: 0, reps_above_zone: 0,
  };
  if (!reps.length) return empty;

  const speeds = reps.map((r) => r.mean_velocity);
  const first = speeds[0];
  const last = speeds[speeds.length - 1];
  const durations = reps.map((r) => r.duration_ms).filter((d) => typeof d === "number");

  return {
    ...empty,
    // Positive means they slowed down over the set — the usual sign of fatigue.
    velocity_loss_percent: first ? ((first - last) / first) * 100 : null,
    rep_velocity_range: Math.max(...speeds) - Math.min(...speeds),
    mean_rep_duration_ms: durations.length
      ? durations.reduce((a, b) => a + b, 0) / durations.length : null,
    ...(zone ? {
      reps_below_zone: speeds.filter((v) => v < zone.min).length,
      reps_in_zone: speeds.filter((v) => v >= zone.min && v <= zone.max).length,
      reps_above_zone: speeds.filter((v) => v > zone.max).length,
    } : {}),
  };
}

export function coachRackView(rack) {
  const athlete = rack?.athlete;
  const latest = rack?.latest_set;
  if (!athlete) {
    return {
      athleteName: "No athlete signed in",
      movementName: "Waiting for check-in",
      progressLabel: "No active progress",
      latestResult: null,
    };
  }
  return {
    athleteName: athlete.name,
    movementName: latest?.exercise || "No movement yet",
    progressLabel: latest
      ? `Set ${latest.set_number}${latest.is_false_set ? " (false set)" : ""} · ${latest.reps_completed ?? 0} reps`
      : "Signed in, nothing lifted yet",
    latestResult: latest,
  };
}
