import { describe, expect, it } from "vitest";
import { addProgramWorkout, buildWorkoutPayload, buildWorkoutProgramPayload, errorLabel, flattenApiErrors, moveProgramWorkout, sameOriginPath, unscopedValidationErrors, validateProgramDraft, validateWorkoutDraft, validationErrorPath, validationErrorsAt } from "./workoutCatalog.js";

describe("buildWorkoutPayload", () => {
  it("trims text, normalizes numbers, and assigns contiguous positions", () => {
    expect(buildWorkoutPayload("  Lower Strength  ", [
      { exercise: " Back squat ", sets: "4", reps: "5", default_weight_lbs: "225.5", velocity_min: "0.55", velocity_max: "0.75" },
      { exercise: "RDL", sets: "3", reps: "8", default_weight_lbs: "0", velocity_min: "", velocity_max: "" },
    ])).toEqual({
      name: "Lower Strength",
      exercises: [
        { exercise: "Back squat", position: 1, sets: 4, reps: 5, default_weight_lbs: 225.5, velocity_min: 0.55, velocity_max: 0.75 },
        { exercise: "RDL", position: 2, sets: 3, reps: 8, default_weight_lbs: 0, velocity_min: null, velocity_max: null },
      ],
    });
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

describe("workout validation render model", () => {
  it("maps API rows, structured paths, and conflicts to field-local targets", () => {
    const errors = [
      { row: 2, field: "sets", detail: "Invalid sets." },
      { field: "exercises.0.exercise", detail: "Invalid movement." },
      { code: "workout_name_conflict", detail: "Already exists." },
      { detail: "Request failed." },
    ];
    expect(validationErrorPath(errors[0], "workout")).toBe("exercises.1.sets");
    expect(validationErrorsAt(errors, "exercises.1", "workout", false)).toEqual([errors[0]]);
    expect(validationErrorsAt(errors, "name", "workout")).toEqual([errors[2]]);
    expect(unscopedValidationErrors(errors, "workout")).toEqual([errors[3]]);
  });

  it("returns client errors for each affected workout field", () => {
    const errors = validateWorkoutDraft("", [{ exercise: "", sets: "0", reps: "x", default_weight_lbs: "-1", velocity_min: "1", velocity_max: "" }]);
    expect(errors.map((error) => error.path)).toEqual([
      "name",
      "exercises.0.exercise",
      "exercises.0.sets",
      "exercises.0.reps",
      "exercises.0.default_weight_lbs",
      "exercises.0.velocity_max",
    ]);
  });

  it("keeps program name and item errors local", () => {
    expect(validateProgramDraft("", [])).toEqual([
      { path: "name", detail: "Program name is required." },
      { path: "items", detail: "Add at least one workout." },
    ]);
    expect(validationErrorPath({ row: 2, field: "workout_id" }, "program")).toBe("items.1.workout_id");
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
