import { describe, expect, it, vi } from "vitest";
import { appendLiveRep, athleteNameLabels, authoritativeIdentitySet, buildAthleteIdentityPayload, buildRackAssignmentPayload, buildRackSetStartPayload, buildSetCompletionPayload, classifyVelocity, createDeviceId, identityActionEvent, motionTopic, orderedEffectiveExercises, parseMotionMessage, parseRepMessage, rackAssignmentChanged, rackProgressView, rackSessionChanged, rackSetStartMode, randomDemoAthlete, repTopic, shouldRefreshRack } from "./rackState.js";

describe("rack live rep state", () => {
  const nodeId = "rack-node-2";
  const payload = {
    node_id: nodeId,
    rep_number: 42,
    mean_velocity: 0.72,
    peak_velocity: 0.91,
    duration_ms: 640,
    timestamp: "2026-07-15T12:00:00Z",
  };

  it("accepts bounded current velocity on the assigned motion topic", () => {
    const motion = { node_id: nodeId, event_type: "motion", velocity: 0.42, timestamp: payload.timestamp };
    expect(parseMotionMessage(JSON.stringify(motion), motionTopic(nodeId), nodeId, Date.parse(payload.timestamp))).toEqual(motion);
    expect(parseMotionMessage(JSON.stringify({ ...motion, velocity: 10.01 }), motionTopic(nodeId), nodeId)).toBeNull();
    expect(parseMotionMessage(JSON.stringify({ ...motion, accel_x: 1.2 }), motionTopic(nodeId), nodeId)).toBeNull();
    expect(parseMotionMessage(JSON.stringify(motion), motionTopic("other-node"), nodeId)).toBeNull();
  });

  it("accepts a valid rep and ignores the publisher's count for display ordering", () => {
    const rep = parseRepMessage(JSON.stringify(payload), repTopic(nodeId), nodeId, Date.parse(payload.timestamp));
    expect(rep).toEqual(payload);
    expect(appendLiveRep([], rep)[0].arrival_number).toBe(1);
  });

  it("rejects topic and payload node mismatches", () => {
    expect(parseRepMessage(JSON.stringify(payload), repTopic("other-node"), nodeId)).toBeNull();
    expect(parseRepMessage(JSON.stringify({ ...payload, node_id: "other-node" }), repTopic(nodeId), nodeId)).toBeNull();
  });

  it("rejects malformed timestamps, negative readings, and peaks below the mean", () => {
    expect(parseRepMessage("not json", repTopic(nodeId), nodeId)).toBeNull();
    expect(parseRepMessage(JSON.stringify({ ...payload, timestamp: "invalid" }), repTopic(nodeId), nodeId)).toBeNull();
    expect(parseRepMessage(JSON.stringify({ ...payload, mean_velocity: -0.1 }), repTopic(nodeId), nodeId)).toBeNull();
    expect(parseRepMessage(JSON.stringify({ ...payload, peak_velocity: 0.5 }), repTopic(nodeId), nodeId)).toBeNull();
    expect(parseRepMessage(JSON.stringify({ ...payload, rep_number: 0 }), repTopic(nodeId), nodeId)).toBeNull();
    expect(parseRepMessage(JSON.stringify({ ...payload, duration_ms: 60001 }), repTopic(nodeId), nodeId)).toBeNull();
    expect(parseRepMessage(JSON.stringify({ ...payload, timestamp: "2026-07-15T12:00:00" }), repTopic(nodeId), nodeId)).toBeNull();
    expect(parseRepMessage(JSON.stringify(payload), repTopic(nodeId), nodeId, Date.parse(payload.timestamp) + 300_001)).toBeNull();
  });

  it("classifies both bounds as on target", () => {
    expect(classifyVelocity(0.49, 0.5, 0.8)).toBe("Below target");
    expect(classifyVelocity(0.5, 0.5, 0.8)).toBe("On target");
    expect(classifyVelocity(0.8, 0.5, 0.8)).toBe("On target");
    expect(classifyVelocity(0.81, 0.5, 0.8)).toBe("Above target");
  });

  it("keeps the latest 100 accepted reps and preserves arrival order", () => {
    let reps = [];
    for (let index = 0; index < 105; index += 1) reps = appendLiveRep(reps, { ...payload, timestamp: `2026-07-15T12:${String(index).padStart(2, "0")}:00Z` });
    expect(reps).toHaveLength(100);
    expect(reps[0].arrival_number).toBe(6);
    expect(reps.at(-1).arrival_number).toBe(105);
  });

  it("ignores duplicate rep identities", () => {
    const first = appendLiveRep([], payload);
    expect(appendLiveRep(first, payload)).toBe(first);
  });

  it("creates a canonical UUID without randomUUID", () => {
    const cryptoObject = { getRandomValues: (bytes) => bytes.fill(7) };
    expect(createDeviceId(cryptoObject)).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it("refreshes only for a new event above the authoritative rack revision", () => {
    const seen = new Set();
    const event = { revision: 8, event_id: "7bfba173-809a-44ee-a8ca-b2f603962f88" };
    expect(shouldRefreshRack(7, event, seen)).toBe(true);
    expect(shouldRefreshRack(7, event, seen)).toBe(false);
    expect(shouldRefreshRack(8, { ...event, event_id: "8bfba173-809a-44ee-a8ca-b2f603962f88" }, seen)).toBe(false);
  });

  it("bounds processed monitoring event identities", () => {
    const seen = new Set();
    for (let revision = 1; revision <= 105; revision += 1) {
      shouldRefreshRack(0, { revision, event_id: `00000000-0000-4000-8000-${String(revision).padStart(12, "0")}` }, seen);
    }
    expect(seen.size).toBe(100);
  });
});

describe("catalog rack state", () => {
  it("derives current server-owned progress for rack presentation", () => {
    const exercise = { id: 9, exercise: "Squat", sets: 3, reps: 5 };
    expect(rackProgressView({
      status: "ready",
      program: { name: "Strength" },
      current_workout: { name: "Lower", position: 2 },
      current_exercise: exercise,
      expected_set_number: 2,
      active_set: { id: 12, set_number: 2 },
      current_exercise_completion: { completed_sets: 1, false_sets: 1, sets: [{ id: 4 }] },
      persisted_sets: [{ id: 4 }],
    })).toEqual({
      complete: false,
      programName: "Strength",
      workoutName: "Lower",
      workoutPosition: 2,
      exercise,
      expectedSetNumber: 2,
      activeSet: { id: 12, set_number: 2 },
      currentExerciseCompletion: { completed_sets: 1, false_sets: 1, sets: [{ id: 4 }] },
      persistedSets: [{ id: 4 }],
    });
  });

  it("builds mutually exclusive coach and athlete payloads", () => {
    expect(buildRackAssignmentPayload("workout", "4", "", "")).toEqual({ workout_id: 4, workout_program_id: null });
    expect(buildRackAssignmentPayload("workout_program", "", "8", "12")).toEqual({ workout_id: 12, workout_program_id: 8 });
    expect(buildAthleteIdentityPayload("screen-id", "5", "9", "event-id")).toEqual({
      device_id: "screen-id", athlete_id: 5, session_id: 9, event_id: "event-id",
    });
    expect(buildRackSetStartPayload("screen-id")).toEqual({ device_id: "screen-id" });
  });

  it("reuses an identity event for retry and rotates it for a new confirmed action", () => {
    const cryptoObject = { randomUUID: vi.fn()
      .mockReturnValueOnce("10000000-0000-4000-8000-000000000001")
      .mockReturnValueOnce("10000000-0000-4000-8000-000000000002") };
    const first = identityActionEvent(null, "1:9:5", cryptoObject);

    expect(identityActionEvent(first, "1:9:5", cryptoObject)).toBe(first);
    expect(identityActionEvent(first, "1:10:5", cryptoObject)).toEqual({
      key: "1:10:5", eventId: "10000000-0000-4000-8000-000000000002",
    });
    expect(cryptoObject.randomUUID).toHaveBeenCalledTimes(2);
  });

  it("uses only the top-level authoritative set from identity responses", () => {
    const historical = { id: 7, ended_at: "2026-07-22T12:00:00Z" };
    expect(authoritativeIdentitySet({
      set: null,
      identity_event: { resulting_set: historical, replayed: true },
    })).toBeNull();
    expect(authoritativeIdentitySet({
      set: { id: 8, ended_at: null },
      identity_event: { resulting_set: historical, replayed: true },
    })).toEqual({ id: 8, ended_at: null });
  });

  it("retains explicit set start only for legacy ready progress", () => {
    expect(rackSetStartMode({ status: "ready", program: { id: 2, name: "Legacy" }, active_set: null })).toBe("compatibility");
    expect(rackSetStartMode({ status: "ready", program: { id: 3, name: "Frozen", schedule_source: "weekday" }, active_set: null })).toBe("automatic");
    expect(rackSetStartMode({ status: "in_set", program: { id: 3, schedule_source: "date" }, active_set: { id: 11 } })).toBe("active");
    expect(rackSetStartMode({ status: "ready", program: { schedule_source: null }, active_set: null })).toBe("compatibility");
  });

  it("builds bounded live reps into authoritative completion order and false sets", () => {
    const target = { velocity_min: 0.5, velocity_max: 0.8 };
    const reps = [
      { rep_number: 42, mean_velocity: 0.4, peak_velocity: 0.6, duration_ms: 600, timestamp: "2026-07-15T12:00:00Z" },
      { rep_number: 2, mean_velocity: 0.9, peak_velocity: 1.0, duration_ms: 550, timestamp: "2026-07-15T12:00:01Z" },
    ];
    expect(buildSetCompletionPayload(reps, target)).toEqual({
      reps_completed: 2,
      is_false_set: false,
      reps: [
        { rep_number: 1, mean_velocity: 0.4, peak_velocity: 0.6, duration_ms: 600, timestamp: "2026-07-15T12:00:00Z", velocity_color: "red" },
        { rep_number: 2, mean_velocity: 0.9, peak_velocity: 1.0, duration_ms: 550, timestamp: "2026-07-15T12:00:01Z", velocity_color: "yellow" },
      ],
    });
    expect(buildSetCompletionPayload(reps, target, true)).toEqual({ reps_completed: 0, is_false_set: true, reps: [] });
  });

  it("disambiguates duplicate athlete names without exposing extra fields", () => {
    expect(athleteNameLabels([{ id: 2, name: "Alex" }, { id: 7, name: "Alex" }, { id: 9, name: "Sam" }])).toEqual([
      { id: 2, name: "Alex", label: "Alex (athlete 2)" },
      { id: 7, name: "Alex", label: "Alex (athlete 7)" },
      { id: 9, name: "Sam", label: "Sam" },
    ]);
  });

  it("selects only strict server-authorized demo athletes with injected randomness", () => {
    const athletes = [
      { id: 1, name: "Arbitrary", demo_wristband_eligible: true },
      { id: 2, name: "[DEMO] Prefix only", demo_wristband_eligible: false },
      { id: 3, name: "Truthy is not boolean", demo_wristband_eligible: 1 },
      { id: 4, name: "Second eligible", demo_wristband_eligible: true },
      { id: 5, name: "Missing flag" },
      { id: 6, name: "Third eligible", demo_wristband_eligible: true },
    ];
    const snapshot = structuredClone(athletes);

    expect(randomDemoAthlete(athletes, () => 0)).toEqual(athletes[0]);
    expect(randomDemoAthlete(athletes, () => 0.5)).toEqual(athletes[3]);
    expect(randomDemoAthlete(athletes, () => 0.999999)).toEqual(athletes[5]);
    expect(athletes).toEqual(snapshot);
  });

  it("returns null when no eligible demo athlete is present", () => {
    expect(randomDemoAthlete([], () => 0)).toBeNull();
    expect(randomDemoAthlete([{ id: 1, name: "[DEMO] Avery" }], () => 0)).toBeNull();
  });

  it("orders effective exercises without mutating the API response", () => {
    const exercises = [{ position: 2, exercise: "Press" }, { position: 1, exercise: "Squat" }];
    expect(orderedEffectiveExercises({ exercises })).toEqual([{ position: 1, exercise: "Squat" }, { position: 2, exercise: "Press" }]);
    expect(exercises[0].position).toBe(2);
  });

  it("detects assignment, reassignment, and unassignment transitions", () => {
    expect(rackAssignmentChanged(null, 3)).toBe(true);
    expect(rackAssignmentChanged(3, "3")).toBe(false);
    expect(rackAssignmentChanged(3, 4)).toBe(true);
    expect(rackAssignmentChanged(4, null)).toBe(true);
    expect(rackSessionChanged(9, "9")).toBe(false);
    expect(rackSessionChanged(9, 10)).toBe(true);
  });
});
