import { describe, expect, it } from "vitest";
import { coachRackView, wallDisplayState, wallMovementView } from "./dashboardView.js";

describe("wall snapshot availability", () => {
  const populated = {
    session: { label: "Training" },
    movement: { name: "Squat" },
    leaderboard: [{ athlete: { name: "Old leader" } }],
    insights: [{ athlete_name: "Old leader" }],
  };

  it("hides the prior movement, leaderboard, and insights after a REST refresh fails", () => {
    expect(wallDisplayState({
      roomState: populated,
      requestState: "stale",
      connectionState: "live",
      lastError: "Base station returned HTTP 503",
    })).toEqual({
      status: "unavailable",
      roomState: null,
      message: "Base station returned HTTP 503",
    });
  });

  it.each(["reconnecting", "stale"])("hides the snapshot when MQTT is %s", (connectionState) => {
    const display = wallDisplayState({ roomState: populated, requestState: "ready", connectionState });
    expect(display.status).toBe("unavailable");
    expect(display.roomState).toBeNull();
    expect(display.message).toContain("Live scoreboard updates are unavailable");
  });

  it("exposes the snapshot only when REST and MQTT are current", () => {
    expect(wallDisplayState({ roomState: populated, requestState: "ready", connectionState: "live" }))
      .toEqual({ status: "ready", roomState: populated });
  });
});

describe("wall movement presentation", () => {
  it("clears rows while waiting instead of retaining a previous movement", () => {
    const view = wallMovementView({ movement: null, leaderboard: [{ athlete: { name: "Stale" } }] });
    expect(view.waiting).toBe(true);
    expect(view.rows).toEqual([]);
  });

  it("presents the selected movement and its bounded rows", () => {
    const leaderboard = [{ athlete: { name: "Alex" }, best_avg_velocity: 0.81 }];
    const view = wallMovementView({
      movement: { name: "Back squat", participant_count: 2, velocity_min: 0.5, velocity_max: 0.8 },
      leaderboard,
    });
    expect(view).toMatchObject({ waiting: false, name: "Back squat", rows: leaderboard });
    expect(view.detail).toContain("2 active athletes");
  });
});

describe("coach rack observation", () => {
  it("derives signed-in progress and completion without assignment controls", () => {
    const view = coachRackView({ training: {
      athlete: { name: "Jordan" },
      status: "ready",
      expected_set_number: 2,
      exercise: { name: "Bench press", sets: 4 },
      progression: { completed_sets: 1 },
      latest_result: { avg_velocity: 0.75 },
    } });
    expect(view).toEqual({
      athleteName: "Jordan",
      movementName: "Bench press",
      progressLabel: "Set 2 of 4 · 1 completed",
      latestResult: { avg_velocity: 0.75 },
    });
  });
});
