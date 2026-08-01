/* Proves day/workout grouping and rep comparisons without coupling tests to layout. */

import { describe, expect, it } from "vitest";
import { compareReps, groupHistorySets, localDayKey, summariseTrainingDays } from "./historyView.js";

describe("athlete history drill-down", () => {
  it("groups sets by calendar day and workout while preserving totals", () => {
    const sets = [
      { id: 3, ended_at: "2026-07-14T18:00:00Z", reps_completed: 3, session: { id: 2, label: "Evening lift" } },
      { id: 2, ended_at: "2026-07-14T16:00:00Z", reps_completed: 5, session: { id: 1, label: "Strength" } },
      { id: 1, ended_at: "2026-07-13T16:00:00Z", reps_completed: 4, session: { id: 1, label: "Strength" } },
    ];

    const days = groupHistorySets(sets);

    expect(days).toHaveLength(2);
    expect(days[0]).toMatchObject({ sets: 2, reps: 8 });
    expect(days[0].workouts.map((workout) => workout.label)).toEqual(["Evening lift", "Strength"]);
    expect(days[1]).toMatchObject({ sets: 1, reps: 4 });
  });

  it("computes each rep against the previous rep and set average", () => {
    const rows = compareReps({
      avg_velocity: 0.7,
      reps: [
        { rep_number: 1, mean_velocity: 0.8 },
        { rep_number: 2, mean_velocity: 0.7 },
        { rep_number: 3, mean_velocity: 0.6 },
      ],
    });

    expect(rows[0].changeFromPrevious).toBeNull();
    expect(rows[0].changeFromAverage).toBeCloseTo(0.1);
    expect(rows[1].changeFromPrevious).toBeCloseTo(-0.1);
    expect(rows[2].changeFromAverage).toBeCloseTo(-0.1);
  });

  it("uses local calendar boundaries and preserves newest set order", () => {
    const late = new Date(2026, 6, 14, 23, 30).toISOString();
    const nextMorning = new Date(2026, 6, 15, 8, 0).toISOString();
    expect(localDayKey(late)).not.toBe(localDayKey(nextMorning));

    const days = groupHistorySets([
      { id: 2, ended_at: nextMorning, reps_completed: 1, session: { id: 1, label: "Strength" } },
      { id: 1, ended_at: late, reps_completed: 1, session: { id: 1, label: "Strength" } },
    ]);
    expect(days.map((day) => day.workouts[0].sets[0].id)).toEqual([2, 1]);
  });
});

describe("summariseTrainingDays", () => {
  // groupHistorySets returns newest-first, which is the order this receives.
  const day = (key, endedAt, velocities) => ({
    key, endedAt, sets: velocities.length, reps: velocities.length * 3,
    workouts: [{ key: "w", label: "Day", sets: velocities.map((v) => ({ avg_velocity: v })) }],
  });

  it("averages every set in the day", () => {
    const [row] = summariseTrainingDays([day("d1", "2026-08-03T18:00:00Z", [0.6, 0.8])]);
    expect(row.avgVelocity).toBeCloseTo(0.7);
  });

  it("keeps the newest day first, the way a coach reads it", () => {
    const rows = summariseTrainingDays([
      day("newer", "2026-08-03T18:00:00Z", [0.9]),
      day("older", "2026-08-01T18:00:00Z", [0.6]),
    ]);
    expect(rows.map((r) => r.key)).toEqual(["newer", "older"]);
  });

  // Each day compares against the one BEFORE it in time, not after.
  it("trends up when the athlete moved faster than last time", () => {
    const [newer, older] = summariseTrainingDays([
      day("newer", "2026-08-03T18:00:00Z", [0.9]),
      day("older", "2026-08-01T18:00:00Z", [0.6]),
    ]);
    expect(newer.trend).toBe("up");
    expect(newer.change).toBeCloseTo(0.3);
    // The oldest row has nothing behind it, so it makes no claim.
    expect(older.trend).toBeNull();
    expect(older.change).toBeNull();
  });

  it("trends down when they moved slower", () => {
    const [newer] = summariseTrainingDays([
      day("newer", "2026-08-03T18:00:00Z", [0.5]),
      day("older", "2026-08-01T18:00:00Z", [0.8]),
    ]);
    expect(newer.trend).toBe("down");
  });

  // An arrow that is always on tells a coach nothing.
  it("calls a change inside the flat band flat, not a direction", () => {
    const [newer] = summariseTrainingDays([
      day("newer", "2026-08-03T18:00:00Z", [0.701]),
      day("older", "2026-08-01T18:00:00Z", [0.700]),
    ]);
    expect(newer.trend).toBe("flat");
  });

  it("makes no claim when a day has no measured velocity", () => {
    const [newer] = summariseTrainingDays([
      day("newer", "2026-08-03T18:00:00Z", [null, undefined]),
      day("older", "2026-08-01T18:00:00Z", [0.8]),
    ]);
    expect(newer.avgVelocity).toBeNull();
    expect(newer.trend).toBeNull();
  });

  it("survives an empty history", () => {
    expect(summariseTrainingDays([])).toEqual([]);
    expect(summariseTrainingDays(null)).toEqual([]);
  });
});
