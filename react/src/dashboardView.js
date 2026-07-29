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
