// demoCases.js — built-in wall display demo / test messages.
// These are the exact `leaderboard_update` payloads the wall display expects on
// `edgeathlete/dashboard/state` (see MESSAGE_CONTRACT.md). The demo publisher
// script replays them over real MQTT so you can watch /dashboard update live
// without a rack tablet or Django set-complete flow. Each case documents what
// you should see change on screen — use it for demos, QA, and onboarding.

export const DASHBOARD_TOPIC = "edgeathlete/dashboard/state";

/** @typedef {{ id: number, name: string }} DemoAthlete */

/**
 * One publishable test message plus what it is meant to prove on the wall.
 * @type {Record<string, { title: string, expect: string, message: object }>}
 */
export const DEMO_CASES = {
  "first-set-green": {
    title: "First set — green rack",
    expect:
      "Rack 1 turns green, Jordan appears on the leaderboard, summary shows 1 set / 5 reps / 1 athlete.",
    message: {
      type: "leaderboard_update",
      athlete: { id: 1, name: "Jordan Lee" },
      rack_number: 1,
      avg_velocity: 0.88,
      peak_velocity: 0.96,
      reps_completed: 5,
      is_false_set: false,
      is_velocity_pr: false,
      is_weight_pr: false,
    },
  },

  "second-athlete-rack-2": {
    title: "Second athlete — rack 2",
    expect:
      "Rack 2 lights up, Alex joins the leaderboard, summary totals increase.",
    message: {
      type: "leaderboard_update",
      athlete: { id: 2, name: "Alex Kim" },
      rack_number: 2,
      avg_velocity: 0.74,
      peak_velocity: 0.89,
      reps_completed: 5,
      is_false_set: false,
      is_velocity_pr: false,
      is_weight_pr: false,
    },
  },

  "leaderboard-shuffle": {
    title: "Leaderboard reorder",
    expect:
      "Alex posts a faster average (0.92) and moves above Jordan on the leaderboard.",
    message: {
      type: "leaderboard_update",
      athlete: { id: 2, name: "Alex Kim" },
      rack_number: 2,
      avg_velocity: 0.92,
      peak_velocity: 1.02,
      reps_completed: 5,
      is_false_set: false,
      is_velocity_pr: false,
      is_weight_pr: false,
    },
  },

  "velocity-pr": {
    title: "Velocity PR",
    expect:
      "Insights highlights a new velocity PR for Alex; fastest-rep insight updates.",
    message: {
      type: "leaderboard_update",
      athlete: { id: 2, name: "Alex Kim" },
      rack_number: 2,
      avg_velocity: 0.95,
      peak_velocity: 1.08,
      reps_completed: 5,
      is_false_set: false,
      is_velocity_pr: true,
      is_weight_pr: false,
    },
  },

  "third-athlete-yellow": {
    title: "Slowing athlete — yellow rack",
    expect: "Rack 3 shows yellow (mid velocity). Sam appears on the leaderboard.",
    message: {
      type: "leaderboard_update",
      athlete: { id: 3, name: "Sam Rivera" },
      rack_number: 3,
      avg_velocity: 0.62,
      peak_velocity: 0.71,
      reps_completed: 5,
      is_false_set: false,
      is_velocity_pr: false,
      is_weight_pr: false,
    },
  },

  "fatigue-red": {
    title: "Fatigue — red rack",
    expect: "Rack 3 turns red (low velocity). Sam's totals still increase.",
    message: {
      type: "leaderboard_update",
      athlete: { id: 3, name: "Sam Rivera" },
      rack_number: 3,
      avg_velocity: 0.41,
      peak_velocity: 0.48,
      reps_completed: 5,
      is_false_set: false,
      is_velocity_pr: false,
      is_weight_pr: false,
    },
  },

  "weight-pr": {
    title: "Weight PR",
    expect: "Insights highlights a new weight PR for Jordan.",
    message: {
      type: "leaderboard_update",
      athlete: { id: 1, name: "Jordan Lee" },
      rack_number: 1,
      avg_velocity: 0.85,
      peak_velocity: 0.94,
      reps_completed: 5,
      is_false_set: false,
      is_velocity_pr: false,
      is_weight_pr: true,
    },
  },

  "false-set": {
    title: "False set (accidental bar touch)",
    expect:
      "Rack 4 tile updates with Sam's name but stays idle/gray. Leaderboard and summary do NOT change.",
    message: {
      type: "leaderboard_update",
      athlete: { id: 3, name: "Sam Rivera" },
      rack_number: 4,
      avg_velocity: 0.55,
      peak_velocity: 0.6,
      reps_completed: 1,
      is_false_set: true,
      is_velocity_pr: false,
      is_weight_pr: false,
    },
  },

  "busy-room-rack-5": {
    title: "Fifth rack joins",
    expect: "Rack 5 goes green; summary rack count increases to 5.",
    message: {
      type: "leaderboard_update",
      athlete: { id: 4, name: "Taylor Brooks" },
      rack_number: 5,
      avg_velocity: 0.9,
      peak_velocity: 1.01,
      reps_completed: 5,
      is_false_set: false,
      is_velocity_pr: false,
      is_weight_pr: false,
    },
  },
};

/**
 * Ordered playlists for scripted demos. Each step waits `waitMs` after the
 * previous publish (first step waits before publishing too).
 * @type {Record<string, { name: string, description: string, steps: { caseId: string, waitMs: number }[] }>}
 */
export const DEMO_PLAYLISTS = {
  full: {
    name: "Full session walkthrough",
    description:
      "~45s story: athletes arrive, leaderboard shuffles, PRs fire, fatigue shows red, false set ignored.",
    steps: [
      { caseId: "first-set-green", waitMs: 3000 },
      { caseId: "second-athlete-rack-2", waitMs: 4000 },
      { caseId: "leaderboard-shuffle", waitMs: 4000 },
      { caseId: "velocity-pr", waitMs: 4000 },
      { caseId: "third-athlete-yellow", waitMs: 4000 },
      { caseId: "fatigue-red", waitMs: 4000 },
      { caseId: "weight-pr", waitMs: 4000 },
      { caseId: "false-set", waitMs: 4000 },
      { caseId: "busy-room-rack-5", waitMs: 2000 },
    ],
  },
  quick: {
    name: "Quick smoke test",
    description: "Three messages in ~6s — enough to prove live updates work.",
    steps: [
      { caseId: "first-set-green", waitMs: 2000 },
      { caseId: "second-athlete-rack-2", waitMs: 2000 },
      { caseId: "velocity-pr", waitMs: 2000 },
    ],
  },
};
