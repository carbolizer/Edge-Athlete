import { describe, expect, it } from "vitest";
import { assignedWorkoutOptions, assignmentSummary, buildAthleteAssignmentPayload, buildOverrideFields, exerciseTargetView } from "./athletePlanning.js";

describe("athlete planning payloads", () => {
  // The id must be a DEPLOYED program, never a template. Sending a block id
  // here is the bug this rewrite fixed: it would either 404 or silently match
  // an unrelated program that happened to share the number.
  it("assigns by deployed training program", () => {
    expect(buildAthleteAssignmentPayload("8")).toEqual({ training_program: 8 });
  });

  it("omits untouched fields and sends a blank as an inheritance null", () => {
    expect(buildOverrideFields({ sets: "", target_percent: "72.5" })).toEqual({ sets: null, target_percent: 72.5 });
    expect(buildOverrideFields({ reps: "6" })).toEqual({ reps: 6 });
  });

  // An override of 0% is meaningless, but 0 must still survive the "" check
  // rather than being swallowed as blank — "" and 0 mean different things.
  it("keeps an explicit zero distinct from a blank", () => {
    expect(buildOverrideFields({ sets: "0" })).toEqual({ sets: 0 });
  });
});

describe("exerciseTargetView", () => {
  const row = { sets: 5, reps: 3, target_percent: 80, target_weight_lbs: 225 };

  it("shows the group's value when there is no override", () => {
    expect(exerciseTargetView(row)).toEqual({
      sets: { group: 5, effective: 5 },
      reps: { group: 3, effective: 3 },
      target_percent: { group: 80, effective: 80 },
      target_weight_lbs: 225,
    });
  });

  it("lets an override win field by field, leaving the rest inherited", () => {
    const view = exerciseTargetView({ ...row, override: { target_percent: 65 } });
    expect(view.target_percent).toEqual({ group: 80, effective: 65 });
    expect(view.sets).toEqual({ group: 5, effective: 5 });
  });

  // No reference max on file is a real state, not an error — the rack shows a
  // blank rather than inventing a weight, and so does this panel.
  it("reports a missing resolved weight as null rather than guessing", () => {
    expect(exerciseTargetView({ sets: 5, reps: 3, target_percent: 80 }).target_weight_lbs).toBeNull();
  });
});

describe("assignment across several groups", () => {
  const assignment = [
    {
      training_program: { id: 1, name: "Fall Strength" },
      training_group: { id: 10, name: "Varsity" },
      workouts: [{ id: 100, name: "Lower", position: 1, exercises: [{ id: 1000 }] }],
    },
    {
      training_program: { id: 2, name: "Return to Play" },
      training_group: { id: 11, name: "Rehab" },
      workouts: [{ id: 200, name: "Upper", position: 1, exercises: [] }],
    },
  ];

  // With two plans in play, "Day 1" alone is ambiguous — the group has to be
  // part of the label or a coach cannot tell the two apart.
  it("flattens every plan's days and labels each with its group", () => {
    const options = assignedWorkoutOptions(assignment);
    expect(options).toHaveLength(2);
    expect(options[0].label).toBe("Varsity · 1. Lower");
    expect(options[1].label).toBe("Rehab · 1. Upper");
  });

  it("summarizes every plan and says which group each comes from", () => {
    expect(assignmentSummary(assignment)).toBe("Fall Strength (via Varsity) · Return to Play (via Rehab)");
  });

  // "Not loaded" and "genuinely training nothing" must not look the same.
  it("states plainly when an athlete is on no plan at all", () => {
    expect(assignmentSummary([])).toBe("No plan — this athlete is not in a group with a program.");
    expect(assignedWorkoutOptions(undefined)).toEqual([]);
  });
});