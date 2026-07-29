import { describe, expect, it } from "vitest";
import { addProgramWorkout, buildWorkoutPayload, buildWorkoutProgramPayload, errorLabel, flattenApiErrors, moveProgramWorkout, sameOriginPath } from "./workoutCatalog.js";

describe("buildWorkoutPayload", () => {
  // A workout is one DAY inside a block, so the block id travels with it — a day
  // cannot exist unattached. Movements are catalog ids, never typed-in names, and
  // the load is a PERCENT of each athlete's own max rather than a weight in pounds.
  it("sends the block, catalog ids, and percent targets with contiguous positions", () => {
    expect(buildWorkoutPayload("  Day 1 — Lower  ", [
      { exercise: "3", sets: "4", reps: "5", target_percent: "80", velocity_zone_min: "0.55", velocity_zone_max: "0.75" },
      { exercise: "7", sets: "3", reps: "8", target_percent: "65", velocity_zone_min: "", velocity_zone_max: "" },
    ], 2, 1)).toEqual({
      training_block: 2,
      name: "Day 1 — Lower",
      position: 1,
      exercises: [
        { exercise: 3, position: 1, sets: 4, reps: 5, target_percent: 80, velocity_zone_min: 0.55, velocity_zone_max: 0.75 },
        { exercise: 7, position: 2, sets: 3, reps: 8, target_percent: 65, velocity_zone_min: null, velocity_zone_max: null },
      ],
    });
  });

  // Position is optional: the server appends the day to the end of the block when
  // the coach doesn't say where it goes.
  it("omits position entirely when none is given", () => {
    const payload = buildWorkoutPayload("Day 2", [
      { exercise: "3", sets: "5", reps: "3", target_percent: "75", velocity_zone_min: "", velocity_zone_max: "" },
    ], 2);
    expect(payload.position).toBeUndefined();
    expect(payload.training_block).toBe(2);
  });
});

describe("flattenApiErrors", () => {
  it("preserves CSV row and field details", () => {
    const errors = flattenApiErrors({ detail: "Workout data is invalid.", errors: [{ row: 7, field: "sets", code: "invalid", detail: "Enter a positive integer." }] }, "Failed");
    expect(errors).toEqual([{ row: 7, field: "sets", code: "invalid", detail: "Enter a positive integer." }]);
    expect(errorLabel(errors[0])).toBe("Row 7 · sets: Enter a positive integer.");
  });

  it("flattens serializer fields and supplies a fallback for an empty body", () => {
    expect(flattenApiErrors({ name: ["A workout with this name already exists."] }, "Failed"))
      .toEqual([{ field: "name", detail: "A workout with this name already exists." }]);
    expect(flattenApiErrors({}, "Failed")).toEqual([{ detail: "Failed" }]);
  });

  it("prefers structured field errors over an envelope detail", () => {
    expect(flattenApiErrors({ detail: "Override data is invalid.", errors: { sets: "sets must be positive." } }, "Failed"))
      .toEqual([{ field: "sets", detail: "sets must be positive." }]);
  });
});

describe("sameOriginPath", () => {
  const origin = "https://edge-athlete.local";

  it("normalizes relative and same-origin absolute pagination links", () => {
    expect(sameOriginPath("/api/workouts/?page=2", origin)).toBe("/api/workouts/?page=2");
    expect(sameOriginPath("https://edge-athlete.local/api/workouts/?page=3", origin)).toBe("/api/workouts/?page=3");
  });

  it("rejects cross-origin, credentialed, and malformed pagination links", () => {
    expect(sameOriginPath("https://example.com/api/workouts/?page=2", origin)).toBeNull();
    expect(sameOriginPath("https://user:pass@edge-athlete.local/api/workouts/?page=2", origin)).toBeNull();
    expect(sameOriginPath("http://[invalid", origin)).toBeNull();
    expect(sameOriginPath(null, origin)).toBeNull();
  });
});

describe("workout program draft helpers", () => {
  const squat = { id: 4, name: "Lower Strength", exercises: [] };
  const press = { id: 9, name: "Upper Strength", exercises: [] };

  it("stores only stable workout identity and prevents duplicate IDs", () => {
    const selected = addProgramWorkout([], squat);
    expect(selected).toEqual([{ id: 4, name: "Lower Strength" }]);
    expect(addProgramWorkout(selected, { id: "4", name: "Renamed" })).toBe(selected);
  });

  it("reorders within bounds without changing membership", () => {
    const selected = [squat, press];
    expect(moveProgramWorkout(selected, 1, -1)).toEqual([press, squat]);
    expect(moveProgramWorkout(selected, 0, -1)).toBe(selected);
  });

  it("builds a trimmed, contiguously ordered API payload", () => {
    expect(buildWorkoutProgramPayload("  Strength Week  ", [squat, press])).toEqual({
      name: "Strength Week",
      items: [
        { workout_id: 4, position: 1 },
        { workout_id: 9, position: 2 },
      ],
    });
  });
});
