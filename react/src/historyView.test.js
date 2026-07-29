/* Proves day/workout grouping and rep comparisons without coupling tests to layout. */

import { describe, expect, it } from "vitest";
import { compareReps, groupHistorySets, localDayKey } from "./historyView.js";

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
