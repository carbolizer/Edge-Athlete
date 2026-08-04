import { describe, expect, it } from "vitest";
import { budgetReportRendering, buildTrainingDayPayload, orderedReportExercises, orderedReportPrescriptions, previewGroups, qualifyingReportSets, reportAthleteContext, reportAthletes, reportExerciseSets, reportSnapshot, reportSummary, reportValue, unfinishedRackNumbers } from "./trainingDay.js";

describe("training day payloads", () => {
  it("trims the label and deduplicates numeric athlete IDs", () => {
    expect(buildTrainingDayPayload("  Friday Training  ", ["4", 9, "4"])).toEqual({ label: "Friday Training", athletes: [4, 9] });
  });

  it("builds scheduled Start Day payloads and groups resolution states", () => {
    expect(buildTrainingDayPayload(" Today ", "a".repeat(64))).toEqual({ label: "Today", preview_version: "a".repeat(64) });
    const rows = [{ athlete: { id: 1 }, eligible: true, source: "date" }, { athlete: { id: 2 }, eligible: false, is_rest: true }, { athlete: { id: 3 }, eligible: false }];
    expect(previewGroups({ athletes: rows })).toEqual({ eligible: [rows[0]], rest: [rows[1]], missing: [rows[2]] });
  });

  it("normalizes unfinished rack conflict variants", () => {
    expect(unfinishedRackNumbers({ rack_numbers: [3, "7"] })).toEqual([3, 7]);
    expect(unfinishedRackNumbers({ unfinished_racks: [2] })).toEqual([2]);
    expect(unfinishedRackNumbers({})).toEqual([]);
  });
});

describe("generated report presentation", () => {
  it("shows missing values as unavailable while preserving zero", () => {
    expect(reportValue(null, " m/s")).toBe("--");
    expect(reportValue(undefined, " lbs")).toBe("--");
    expect(reportValue(0, " reps")).toBe("0 reps");
  });

  it("orders effective prescriptions and supports the report athlete envelope", () => {
    const athlete = { effective_prescriptions: [{ position: 2, exercise: "Press" }, { position: 1, exercise: "Squat" }] };
    expect(orderedReportPrescriptions(athlete).map((item) => item.exercise)).toEqual(["Squat", "Press"]);
    expect(reportAthletes({ participants: [athlete] })).toEqual([athlete]);
  });

  it("unwraps an immutable report and derives its summary", () => {
    const snapshot = { athletes: [{ prescription: { source: "athlete" }, sets: [{ reps_completed: 3 }, { reps_completed: 0 }] }] };
    expect(reportSnapshot({ id: 8, snapshot })).toBe(snapshot);
    expect(reportSummary(snapshot)).toEqual({ athlete_count: 1, completed_sets: 2, completed_reps: 3 });
    expect(orderedReportPrescriptions(snapshot.athletes[0])).toEqual([{ source: "athlete" }]);
    expect(orderedReportExercises({ exercises: [{ position: 2 }, { position: 1 }] }).map((exercise) => exercise.position)).toEqual([1, 2]);
  });

  it("retains false set records while excluding them from completed summaries", () => {
    const sets = [
      { id: 1, reps_completed: 4, is_false_set: false },
      { id: 2, reps_completed: 0, is_false_set: true },
    ];
    expect(qualifyingReportSets(sets)).toEqual([sets[0]]);
    expect(reportSummary({ athletes: [{ sets }] })).toEqual({
      athlete_count: 1,
      completed_sets: 1,
      completed_reps: 4,
    });
  });

  it("binds schema-three sets to their frozen exercise occurrence", () => {
    const athlete = { sets: [{ id: 1, day_plan_exercise_id: 12 }, { id: 2, day_plan_exercise_id: 13 }] };
    expect(reportExerciseSets(athlete, { occurrence_id: 8 }, { id: 12, exercise: "Squat" })).toEqual([athlete.sets[0]]);
    expect(orderedReportPrescriptions({ frozen_plan: { workouts: [{ position: 2 }, { position: 1 }] } }).map((row) => row.position)).toEqual([1, 2]);
  });

  it("exposes schema-three schedule, program, progress, and rack hierarchy", () => {
    expect(reportAthleteContext({
      frozen_plan: { name: "Tuesday Strength", schedule_source: "date", schedule_version: 4 },
      final_progress: { status: "complete" },
      rack_participation: [1, 3],
    })).toEqual({ scheduleSource: "date", scheduleVersion: 4, programName: "Tuesday Strength", progressStatus: "complete", rackNumbers: [1, 3] });
  });

  it("applies deterministic global athlete, set, and rep budgets without mutating the snapshot", () => {
    const athletes = [
      { athlete: { id: 1 }, sets: [{ id: 11, reps: [{ id: 111 }, { id: 112 }] }, { id: 12, reps: [{ id: 121 }, { id: 122 }] }] },
      { athlete: { id: 2 }, sets: [{ id: 21, reps: [{ id: 211 }] }] },
      { athlete: { id: 3 }, sets: [{ id: 31, reps: [{ id: 311 }] }] },
    ];
    const rendered = budgetReportRendering(athletes, { athletes: 2, sets: 2, reps: 3 });
    expect(rendered.counts).toEqual({ athletes: { rendered: 2, total: 3 }, sets: { rendered: 2, total: 4 }, reps: { rendered: 3, total: 6 } });
    expect(rendered.athletes[0].sets.map((record) => record.workoutSet.id)).toEqual([11, 12]);
    expect(rendered.athletes[0].sets[1].reps.map((rep) => rep.id)).toEqual([121]);
    expect(rendered.athletes[1]).toEqual({ entry: athletes[1], sets: [], totalSets: 1 });
    expect(athletes[0].sets[1].reps).toHaveLength(2);
  });
});
