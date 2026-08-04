import { describe, expect, it } from "vitest";
import { addWorkoutOccurrence, buildAthleteAssignmentPayload, buildOverrideFields, buildSchedulePayload, confirmedProgramSelection, effectiveAssignmentLabel, exerciseTargetView, materializeProgram, moveOccurrence, normalizeSchedule, resolveRackPlanningState, scheduleValidation, serverLocalDate, validationErrorsAt } from "./athletePlanning.js";

describe("athlete planning payloads", () => {
  it("builds a whole-program assignment without selecting a workout item", () => {
    expect(buildAthleteAssignmentPayload("8")).toEqual({ workout_program_id: 8 });
  });

  it("omits untouched fields, sends blanks as inheritance nulls, and preserves zero weight", () => {
    expect(buildOverrideFields({ sets: "", weight_lbs: "0" })).toEqual({ sets: null, weight_lbs: 0 });
    expect(buildOverrideFields({ reps: "6" })).toEqual({ reps: 6 });
  });

});

describe("versioned athlete schedules", () => {
  const workout = { id: 3, name: "Lower", exercises: [{ id: 8, exercise: "Squat", sets: 3, reps: 5, default_weight_lbs: 100, velocity_min: 0.4, velocity_max: 0.8 }] };
  const program = { id: 2, name: "Strength", items: [{ workout }] };

  it("materializes programs and permits duplicate independently ordered occurrences", () => {
    const plan = addWorkoutOccurrence(materializeProgram(program), workout);
    expect(plan.workouts.map((row) => row.workout_id)).toEqual([3, 3]);
    plan.workouts[1].exercises[0].weight_lbs = 125;
    expect(plan.workouts[0].exercises[0].weight_lbs).toBe(100);
    expect(moveOccurrence(plan.workouts, 1, -1)[0].exercises[0].weight_lbs).toBe(125);
  });

  it("normalizes server plan IDs and builds an atomic expected-version payload", () => {
    const draft = normalizeSchedule({ version: 4, plans: [{ id: 11, client_id: "1", position: 1, name: "Local", workout_program_id: 2, workouts: [{ workout_id: 3, name: "Lower", exercises: [{ workout_exercise_id: 8, exercise: "Squat", sets: 2, reps: 4, weight_lbs: 0, velocity_min: null, velocity_max: null }] }] }], entries: [{ weekday: 1, is_rest: false, plan_id: 11 }, { date: "2026-07-22", is_rest: true, plan_id: null }] });
    expect(buildSchedulePayload(draft)).toMatchObject({ expected_version: 4, entries: [{ weekday: 1, is_rest: false, plan_client_id: "1" }, { date: "2026-07-22", is_rest: true }] });
    expect(draft.training_date).toBe("");
    expect(scheduleValidation(draft)).toEqual([]);
  });

  it("rejects duplicate selectors and invalid occurrence targets before save", () => {
    const draft = { version: 0, plans: [{ ...materializeProgram(program), workouts: [{ ...workout, workout_id: 3, exercises: [{ workout_exercise_id: 8, exercise: "Squat", sets: 0, reps: 5, weight_lbs: 0 }] }] }], entries: [{ weekday: 2 }, { weekday: 2 }] };
    const errors = scheduleValidation(draft);
    expect(validationErrorsAt(errors, "entries.1")).toEqual([{ path: "entries.1.selector", detail: "Duplicate weekday entry." }]);
    expect(validationErrorsAt(errors, "plan.workouts.0.exercises.0.sets")).toEqual([{ path: "plan.workouts.0.exercises.0.sets", detail: "Sets must be a positive whole number." }]);
  });

  it("uses only server-provided local dates and leaves unavailable exact dates blank", () => {
    expect(serverLocalDate({ training_date: "2026-07-22" })).toBe("2026-07-22");
    expect(serverLocalDate({ effective: { training_date: "2026-07-23" } })).toBe("2026-07-23");
    expect(serverLocalDate({ preview: { training_date: "2026-07-24" } })).toBe("2026-07-24");
    expect(normalizeSchedule({ version: 1, plans: [], entries: [] }).training_date).toBe("");
  });

  it("changes a dirty program source only after discard confirmation succeeds", () => {
    const cancelled = confirmedProgramSelection("2", "7", true, () => false);
    expect(cancelled).toEqual({ id: "2", confirmed: false });
    expect(confirmedProgramSelection(cancelled.id, "7", true, () => true)).toEqual({ id: "7", confirmed: true });
    expect(confirmedProgramSelection("2", "7", false, () => { throw new Error("confirmation should not run"); })).toEqual({ id: "7", confirmed: true });
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
