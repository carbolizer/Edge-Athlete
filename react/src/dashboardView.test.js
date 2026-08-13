import { describe, expect, it } from "vitest";
import { coachRackView, measuredInsights, rackMetrics, wallDisplayState, wallMovementView } from "./dashboardView.js";

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

describe("measuredInsights", () => {
  const zone = { min: 0.5, max: 0.8 };
  const set = (means, target_zone = zone) => ({
    target_zone,
    reps: means.map((mean_velocity, i) => ({ rep_number: i + 1, mean_velocity, duration_ms: 900 })),
  });

  it("reads fatigue as the drop from the first rep to the last", () => {
    const i = measuredInsights(set([1.0, 0.9, 0.8]));
    expect(i.velocity_loss_percent).toBeCloseTo(20, 5);
    expect(i.rep_velocity_range).toBeCloseTo(0.2, 5);
    expect(i.mean_rep_duration_ms).toBe(900);
  });

  it("counts reps against the target zone", () => {
    const i = measuredInsights(set([0.4, 0.6, 0.75, 0.95]));
    expect([i.reps_below_zone, i.reps_in_zone, i.reps_above_zone]).toEqual([1, 2, 1]);
  });

  // The previous set is not in this payload. A fabricated "you're 8% down" is
  // exactly the kind of number a coach would act on, so it stays null.
  it("never invents a comparison against the previous set", () => {
    expect(measuredInsights(set([1.0, 0.9])).avg_velocity_change_percent).toBeNull();
  });

  it("survives a set with no reps, and one with no velocity zone", () => {
    expect(measuredInsights({ reps: [] }).velocity_loss_percent).toBeNull();
    expect(measuredInsights(undefined).reps_in_zone).toBe(0);
    const noZone = measuredInsights(set([0.6, 0.7], null));
    expect(noZone.reps_in_zone).toBe(0);
    expect(noZone.rep_velocity_range).toBeCloseTo(0.1, 5);
  });
});

describe("coach rack observation", () => {
  // These fixtures are the SHAPE /api/room-state/?details=true actually returns.
  // The previous version of this test invented a `training` block with a
  // predicted next set — nothing on our side has ever produced that, so the test
  // stayed green while the real screen crashed on `rack.nodes.length`. Fixtures
  // that agree with the server are the whole point of this file.
  const signedInRack = {
    rack_number: 1,
    status: "lifting",
    status_color: "green",
    athlete: { id: 7, name: "Jordan Lee" },
    node: { node_id: "rack_1", battery_level: 88, signal_strength: -50, is_stale: false },
    latest_set: {
      id: 12, exercise: "Bench Press", set_number: 2, weight_lbs: 185,
      reps_completed: 5, avg_velocity: 0.75, peak_velocity: 0.9,
      is_false_set: false, target_zone: null, reps: [],
    },
  };

  it("reads the athlete from the RACK and the movement from their latest set", () => {
    expect(coachRackView(signedInRack)).toEqual({
      athleteName: "Jordan Lee",
      movementName: "Bench Press",
      progressLabel: "Set 2 · 5 reps",
      latestResult: signedInRack.latest_set,
      metrics: { isLive: false, reps: 5, mean: 0.75, peak: 0.9 },
    });
  });

  // Most racks, most of the time. An empty rack is the normal state, not a
  // failure, and it must not read as though someone is on it.
  it("says plainly when nobody has checked in", () => {
    const idle = { rack_number: 3, status: "idle", athlete: null, latest_set: null, node: null };
    expect(coachRackView(idle)).toEqual({
      athleteName: "No athlete signed in",
      movementName: "Waiting for check-in",
      progressLabel: "No active progress",
      latestResult: null,
      metrics: { isLive: false, reps: 0, mean: undefined, peak: undefined },
    });
    expect(coachRackView(undefined).athleteName).toBe("No athlete signed in");
  });

  // Checked in but nothing lifted yet is a third state, distinct from both.
  it("distinguishes signed in with no set from an empty rack", () => {
    const view = coachRackView({ ...signedInRack, latest_set: null });
    expect(view.athleteName).toBe("Jordan Lee");
    expect(view.progressLabel).toBe("Signed in, nothing lifted yet");
  });

  // A mis-tracked set stays visible and labelled rather than silently counting.
  it("marks a false set instead of hiding it", () => {
    const view = coachRackView({ ...signedInRack, latest_set: { ...signedInRack.latest_set, is_false_set: true } });
    expect(view.progressLabel).toBe("Set 2 (false set) · 5 reps");
  });

  it("prefers active runtime metrics without replacing the saved set", () => {
    const rack = {
      ...signedInRack,
      live: {
        rep_count: 3,
        latest_mean_velocity: 0.71,
        latest_peak_velocity: 0.93,
        latest_color: "green",
      },
    };
    expect(rackMetrics(rack)).toEqual({
      isLive: true, reps: 3, mean: 0.71, peak: 0.93,
    });
    expect(coachRackView(rack).progressLabel).toBe("Set 2 · 3 reps");
    expect(coachRackView(rack).latestResult).toBe(signedInRack.latest_set);
  });
});
