// The group view's whole job is making the person who stopped showing up
// visible. These tests are mostly about that: who gets flagged, who sorts to
// the top, and what happens to someone whose request failed.

import { describe, expect, it } from "vitest";
import { buildGroupRows, daysSince, lastTrainedLabel } from "./groupHistory.js";

const NOW = new Date("2026-08-01T12:00:00").getTime();
const daysAgo = (n, hour = 18) => {
  const d = new Date(NOW);
  d.setDate(d.getDate() - n);
  d.setHours(hour, 0, 0, 0);
  return d.toISOString();
};

const athlete = (id, name) => ({ id, name });
const payload = (sets) => ({ sets });
const set = (endedAt, avg) => ({ id: Math.random(), ended_at: endedAt, avg_velocity: avg, reps_completed: 3, session: { id: endedAt, label: "Day" } });

describe("lastTrainedLabel", () => {
  it("speaks in calendar days, the way a coach does", () => {
    expect(lastTrainedLabel(daysAgo(0), NOW)).toBe("Today");
    expect(lastTrainedLabel(daysAgo(1), NOW)).toBe("Yesterday");
    expect(lastTrainedLabel(daysAgo(11), NOW)).toBe("11 days ago");
  });

  // A set finished at 9pm and read at 8am is Yesterday, not "11 hours ago".
  it("counts calendar days, not elapsed hours", () => {
    expect(lastTrainedLabel(daysAgo(1, 21), NOW)).toBe("Yesterday");
  });

  it("says Never rather than guessing, for someone with no sets", () => {
    expect(lastTrainedLabel(null, NOW)).toBe("Never");
    expect(lastTrainedLabel("not a date", NOW)).toBe("Never");
  });
});

describe("daysSince", () => {
  it("treats never-trained as infinitely long ago, so they sort to the top", () => {
    expect(daysSince(null, NOW)).toBe(Infinity);
  });
});

describe("buildGroupRows", () => {
  const members = [athlete(1, "Jordan"), athlete(2, "Alex"), athlete(3, "Taylor")];
  const analytics = {
    1: payload([set(daysAgo(0), 0.74), set(daysAgo(2), 0.71)]),
    2: payload([set(daysAgo(1), 0.81)]),
    3: payload([set(daysAgo(11), 0.58)]),   // stopped showing up
  };

  it("flags the member who has not trained in a week", () => {
    const rows = buildGroupRows(members, analytics, { now: NOW, windowDays: 30 });
    const byName = Object.fromEntries(rows.map((r) => [r.athlete.name, r]));
    expect(byName.Taylor.behind).toBe(true);
    expect(byName.Jordan.behind).toBe(false);
    expect(byName.Alex.behind).toBe(false);
  });

  // The point of the view. Making a coach scroll a squad of a hundred to spot a
  // flag defeats it.
  it("sorts the behind members to the top", () => {
    const rows = buildGroupRows(members, analytics, { now: NOW, windowDays: 30 });
    expect(rows[0].athlete.name).toBe("Taylor");
  });

  it("counts only sets inside the window", () => {
    const rows = buildGroupRows(members, analytics, { now: NOW, windowDays: 7 });
    const taylor = rows.find((r) => r.athlete.name === "Taylor");
    // Trained 11 days ago, so nothing lands in a 7-day window...
    expect(taylor.sets).toBe(0);
    // ...but "last trained" is a fact about the athlete, not about the window.
    expect(taylor.lastTrainedLabel).toBe("11 days ago");
  });

  it("averages velocity across the window only", () => {
    const rows = buildGroupRows(members, analytics, { now: NOW, windowDays: 30 });
    const jordan = rows.find((r) => r.athlete.name === "Jordan");
    expect(jordan.avgVelocity).toBeCloseTo(0.725);
  });

  // Dropping them would quietly shrink the roster, and a missing athlete is the
  // one thing this view exists to surface.
  it("still gives a row to a member whose request failed", () => {
    const rows = buildGroupRows(members, { ...analytics, 2: null }, { now: NOW, windowDays: 30 });
    const alex = rows.find((r) => r.athlete.name === "Alex");
    expect(alex).toBeTruthy();
    expect(alex.failed).toBe(true);
    expect(alex.sets).toBe(0);
  });

  it("marks someone who has never trained as behind", () => {
    const rows = buildGroupRows([athlete(9, "New Signing")], { 9: payload([]) }, { now: NOW });
    expect(rows[0].behind).toBe(true);
    expect(rows[0].lastTrainedLabel).toBe("Never");
    expect(rows[0].avgVelocity).toBeNull();
  });

  it("survives an empty group", () => {
    expect(buildGroupRows([], {}, { now: NOW })).toEqual([]);
    expect(buildGroupRows(null, null, { now: NOW })).toEqual([]);
  });
});
