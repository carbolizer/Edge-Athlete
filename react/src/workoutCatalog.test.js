import { describe, expect, it } from "vitest";
import { applyCorrection, buildDeployPayload, buildRowEdit, buildTrainingBlockPayload, buildWorkoutPayload, correctionKind, countCorrections, errorLabel, flattenApiErrors, moveInList, repairableErrors, repairChoices, sameOriginPath, toggleCadenceDay } from "./workoutCatalog.js";

describe("buildWorkoutPayload", () => {
  // The block is in the URL, not the payload — a day cannot exist unattached, and
  // an address says so better than a field a caller can forget. Movements are
  // catalog ids, never typed names, and the load is a PERCENT of each athlete's
  // own max rather than a weight in pounds.
  it("sends catalog ids and percent targets with contiguous positions", () => {
    expect(buildWorkoutPayload("  Day 1 — Lower  ", [
      { exercise: "3", sets: "4", reps: "5", target_percent: "80", velocity_zone_min: "0.55", velocity_zone_max: "0.75" },
      { exercise: "7", sets: "3", reps: "8", target_percent: "65", velocity_zone_min: "", velocity_zone_max: "" },
    ], 1)).toEqual({
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
    ]);
    expect(payload.position).toBeUndefined();
    expect(payload.training_block).toBeUndefined();
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
    expect(sameOriginPath("/api/training-blocks/?page=2", origin)).toBe("/api/training-blocks/?page=2");
    expect(sameOriginPath("https://edge-athlete.local/api/training-blocks/?page=3", origin)).toBe("/api/training-blocks/?page=3");
  });

  it("rejects cross-origin, credentialed, and malformed pagination links", () => {
    expect(sameOriginPath("https://example.com/api/training-blocks/?page=2", origin)).toBeNull();
    expect(sameOriginPath("https://user:pass@edge-athlete.local/api/training-blocks/?page=2", origin)).toBeNull();
    expect(sameOriginPath("http://[invalid", origin)).toBeNull();
    expect(sameOriginPath(null, origin)).toBeNull();
  });
});

describe("the CSV repair loop", () => {
  const athletes = [
    { id: 1, name: "Jordan Lee" },
    { id: 2, name: "Sam Rivera" },
    { id: 3, name: "Alex Chen" },
  ];
  const unknownName = {
    row: 2, field: "athlete_name", code: "unknown_athlete",
    detail: "No athlete named 'Jordn Lee'.", value: "Jordn Lee",
    suggestions: ["Jordan Lee"],
  };

  it("treats only naming problems as repairable", () => {
    expect(correctionKind("unknown_athlete")).toBe("athlete");
    expect(correctionKind("ambiguous_exercise")).toBe("exercise");
    expect(correctionKind("unknown_training_group")).toBe("training_group");
    // A bare weight and a missing column cannot be fixed by pointing at a
    // record, so they belong in the plain error list.
    expect(correctionKind("weight_meaning_unknown")).toBeNull();
    expect(correctionKind("missing_column")).toBeNull();
  });

  it("ignores naming errors that carry no text to match", () => {
    expect(repairableErrors([{ code: "unknown_athlete" }])).toEqual([]);
    expect(repairableErrors([unknownName])).toHaveLength(1);
  });

  // The suggestion algorithm can miss. Offering only its guesses would leave a
  // coach who knows the answer with no way to give it.
  it("puts the closest match first but still offers everyone", () => {
    const choices = repairChoices(unknownName, athletes);
    expect(choices[0]).toEqual({ id: 1, name: "Jordan Lee", suggested: true });
    expect(choices).toHaveLength(3);
    expect(choices.slice(1).every((choice) => choice.suggested === false)).toBe(true);
  });

  // A duplicated name is a different question: not "who is this?" but "which of
  // these two?", and the server names both.
  it("offers the named candidates when a name is ambiguous", () => {
    const ambiguous = {
      row: 5, code: "ambiguous_athlete", value: "Jordan Lee",
      candidates: [{ id: 1, name: "Jordan Lee" }, { id: 9, name: "Jordan Lee" }],
    };
    const choices = repairChoices(ambiguous, athletes);
    expect(choices.filter((choice) => choice.suggested).map((choice) => choice.id)).toEqual([1, 9]);
  });

  it("builds the map the import endpoint expects, keyed by kind", () => {
    let corrections = applyCorrection({}, "athlete", "Jordn Lee", "1");
    corrections = applyCorrection(corrections, "exercise", "Bakc Squat", 7);
    expect(corrections).toEqual({
      athlete: { "Jordn Lee": 1 },
      exercise: { "Bakc Squat": 7 },
    });
    expect(countCorrections(corrections)).toBe(2);
  });

  // Un-picking has to actually remove the answer, not store an empty one — the
  // server would treat a blank id as a correction to nothing.
  it("removes an answer when the coach clears it, and prunes the empty kind", () => {
    const corrections = applyCorrection({ athlete: { "Jordn Lee": 1 } }, "athlete", "Jordn Lee", "");
    expect(corrections).toEqual({});
    expect(countCorrections(corrections)).toBe(0);
  });
});

describe("buildTrainingBlockPayload", () => {
  it("sends the cadence as a day string and leaves an unset duration null", () => {
    expect(buildTrainingBlockPayload("  Fall Strength  ", "", ["Mon", "Wed", "Fri"])).toEqual({
      name: "Fall Strength",
      duration_weeks: null,
      cadence_days_of_week: "Mon,Wed,Fri",
    });
    expect(buildTrainingBlockPayload("Spring", "8", [])).toEqual({
      name: "Spring",
      duration_weeks: 8,
      cadence_days_of_week: "",
    });
  });
});

describe("toggleCadenceDay", () => {
  // Days come back in week order however they were clicked, so a coach who
  // picks Friday before Monday still gets "Mon,Wed,Fri" rather than "Fri,Mon".
  it("keeps week order regardless of click order, and removes on second click", () => {
    let days = toggleCadenceDay([], "Fri");
    days = toggleCadenceDay(days, "Mon");
    days = toggleCadenceDay(days, "Wed");
    expect(days).toEqual(["Mon", "Wed", "Fri"]);
    expect(toggleCadenceDay(days, "Wed")).toEqual(["Mon", "Fri"]);
  });
});

describe("buildDeployPayload", () => {
  it("carries the block, group, and dates", () => {
    expect(buildDeployPayload("  Varsity — Fall  ", 3, 7, "2026-09-01", "2026-11-01")).toEqual({
      name: "Varsity — Fall",
      training_group: 3,
      training_block: 7,
      start_date: "2026-09-01",
      end_date: "2026-11-01",
    });
  });

  // A one-off plan for a group, with no template behind it, is a first-class
  // path — not an error. It can be promoted to a template later.
  it("omits the block entirely for a standalone plan, and an absent end date", () => {
    const payload = buildDeployPayload("Rehab", 4, "", "2026-09-01", "");
    expect(payload.training_block).toBeUndefined();
    expect(payload.end_date).toBeUndefined();
    expect(payload.training_group).toBe(4);
  });
});

describe("editing a template", () => {
  const ids = [10, 20, 30];

  it("hands back the whole new order, because the server renumbers a list at once", () => {
    expect(moveInList(ids, 30, -1)).toEqual([10, 30, 20]);
    expect(moveInList(ids, 10, 1)).toEqual([20, 10, 30]);
  });

  // The arrow at either end should be disabled, but if it is ever clicked it
  // must not wrap the last day around to the front.
  it("refuses to move past either end rather than wrapping", () => {
    expect(moveInList(ids, 10, -1)).toBe(ids);
    expect(moveInList(ids, 30, 1)).toBe(ids);
    expect(moveInList(ids, 999, -1)).toBe(ids);
  });

  it("sends only the fields actually filled in", () => {
    expect(buildRowEdit({ sets: "4", reps: "", target_percent: "72.5" }))
      .toEqual({ sets: 4, target_percent: 72.5 });
  });

  // Ordering goes through the whole-list route; accepting it here is exactly
  // what breaks against the position constraint.
  it("never sends position", () => {
    expect(buildRowEdit({ position: "2", sets: "5" })).toEqual({ sets: 5 });
  });

  it("treats an untouched row as nothing to save", () => {
    expect(buildRowEdit({})).toEqual({});
    expect(Object.keys(buildRowEdit({ sets: "", reps: "" }))).toHaveLength(0);
  });
});
