import { describe, expect, it } from "vitest";
import { buildAthleteAssignmentPayload, buildOverrideFields, effectiveAssignmentLabel, exerciseTargetView, resolveRackPlanningState } from "./athletePlanning.js";

describe("athlete planning payloads", () => {
  it("builds a whole-program assignment without selecting a workout item", () => {
    expect(buildAthleteAssignmentPayload("8")).toEqual({ workout_program_id: 8 });
  });

  it("omits untouched fields, sends blanks as inheritance nulls, and preserves zero weight", () => {
    expect(buildOverrideFields({ sets: "", weight_lbs: "0" })).toEqual({ sets: null, weight_lbs: 0 });
    expect(buildOverrideFields({ reps: "6" })).toEqual({ reps: 6 });
  });

});

describe("effective target presentation", () => {
  it("uses final effective values while retaining template fallbacks and zero", () => {
    expect(exerciseTargetView({ sets: 4, reps: 5, default_weight_lbs: 225, effective_targets: { sets: 3, reps: 6, weight_lbs: 0 } })).toEqual({
      sets: { template: 4, effective: 3 },
      reps: { template: 5, effective: 6 },
      weight_lbs: { template: 225, effective: 0 },
    });
  });

  it("labels athlete, rack, and unavailable assignment sources", () => {
    const assignment = { workout: { name: "Lower Strength" } };
    expect(effectiveAssignmentLabel("athlete_program", assignment)).toBe("Athlete program · Lower Strength");
    expect(effectiveAssignmentLabel("rack", assignment)).toBe("Rack assignment · Lower Strength");
    expect(effectiveAssignmentLabel(null, null)).toBe("No effective assignment · Workout unavailable");
  });

  it("prefers explicit rack flags and safely falls back to roster and assignment state", () => {
    expect(resolveRackPlanningState({ identity_available: false, active_session: {}, active_athletes: [{ id: 1 }], effective_assignment_source: "athlete" })).toEqual({ identityAvailable: false, source: "athlete" });
    expect(resolveRackPlanningState({ active_session: {}, active_athletes: [{ id: 1 }], effective_workout: {}, assignment: {} })).toEqual({ identityAvailable: true, source: "rack" });
    expect(resolveRackPlanningState({ active_session: {}, active_athletes: [{ id: 1 }], effective_workout: {} })).toEqual({ identityAvailable: true, source: "athlete" });
  });
});
