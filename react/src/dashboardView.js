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

export function coachRackView(rack) {
  const training = rack?.training;
  if (!training) {
    return {
      athleteName: "No athlete signed in",
      movementName: "Waiting for athlete identity",
      progressLabel: "No active progress",
      latestResult: null,
    };
  }
  const exercise = training.exercise;
  const completed = training.progression?.completed_sets ?? 0;
  return {
    athleteName: training.athlete.name,
    movementName: exercise?.name || "Program complete",
    progressLabel: training.status === "complete"
      ? "Program complete"
      : `Set ${training.expected_set_number} of ${exercise?.sets ?? "--"} · ${completed} completed`,
    latestResult: training.latest_result,
  };
}
