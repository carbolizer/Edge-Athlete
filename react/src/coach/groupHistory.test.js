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
  // Velocities are listed oldest-first here for readability, so a falling list
  // is a falling athlete.
  const training = (velocities) => payload(
    velocities.map((v, i) => set(daysAgo(velocities.length - i), v)));

  // Down on 4 of the last 5 days: turns up every session and gets slower.
  const sliding = training([0.80, 0.78, 0.75, 0.72, 0.70, 0.68]);
  // Climbing, with one off day.
  const improving = training([0.60, 0.64, 0.68, 0.66, 0.71, 0.75]);
  const members = [athlete(1, "Jordan"), athlete(2, "Alex"), athlete(3, "Taylor")];
  const analytics = { 1: improving, 2: sliding, 3: payload([set(daysAgo(11), 0.58)]) };

  it("flags the athlete who is down on 3 of their last 5 days", () => {
    const rows = buildGroupRows(members, analytics, { now: NOW, windowDays: 30 });
    const byName = Object.fromEntries(rows.map((r) => [r.athlete.name, r]));
    expect(byName.Alex.behind).toBe(true);
    expect(byName.Alex.downCount).toBeGreaterThanOrEqual(3);
    expect(byName.Jordan.behind).toBe(false);
  });

  // The rule is about performance, not attendance — someone can be away a long
  // time and still not be sliding. "Last trained" already tells a coach that.
  it("does not flag someone purely for being away a long time", () => {
    const rows = buildGroupRows(members, analytics, { now: NOW, windowDays: 30 });
    const taylor = rows.find((r) => r.athlete.name === "Taylor");
    expect(taylor.behind).toBe(false);
    expect(taylor.lastTrainedLabel).toBe("11 days ago");
  });

  // Requiring a full five would let the shortest, steepest slide go unflagged.
  it("judges on what exists when there are fewer than five days", () => {
    const rows = buildGroupRows([athlete(7, "Short")], { 7: training([0.80, 0.76, 0.72, 0.68]) },
      { now: NOW, windowDays: 30 });
    expect(rows[0].judgedOver).toBe(4);
    expect(rows[0].behind).toBe(true);
  });

  // Judged over all history, so the dropdown describes the filter and not the
  // lifter.
  it("does not change the flag when the window changes", () => {
    const wide = buildGroupRows(members, analytics, { now: NOW, windowDays: 90 });
    const narrow = buildGroupRows(members, analytics, { now: NOW, windowDays: 3 });
    const flag = (rows, name) => rows.find((r) => r.athlete.name === name).behind;
    expect(flag(narrow, "Alex")).toBe(flag(wide, "Alex"));
  });

  // The point of the view. Making a coach scroll a squad of a hundred to spot a
  // flag defeats it.
  it("sorts the behind members to the top", () => {
    const rows = buildGroupRows(members, analytics, { now: NOW, windowDays: 30 });
    expect(rows[0].athlete.name).toBe("Alex");
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
    // Jordan's six days are 0.60 0.64 0.68 0.66 0.71 0.75 — mean 0.6733.
    const wide = buildGroupRows(members, analytics, { now: NOW, windowDays: 30 });
    expect(wide.find((r) => r.athlete.name === "Jordan").avgVelocity).toBeCloseTo(0.6733, 3);
    // A 3-day window keeps only the most recent, so the average rises with it.
    const narrow = buildGroupRows(members, analytics, { now: NOW, windowDays: 3 });
    expect(narrow.find((r) => r.athlete.name === "Jordan").avgVelocity).toBeGreaterThan(0.6733);
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

  // Not "behind" — there is nothing to judge. Kept as its own state so a new
  // signing is not quietly counted as fine, and not accused of sliding either.
  it("marks someone who has never trained as no-history, not behind", () => {
    const rows = buildGroupRows([athlete(9, "New Signing")], { 9: payload([]) }, { now: NOW });
    expect(rows[0].behind).toBe(false);
    expect(rows[0].noHistory).toBe(true);
    expect(rows[0].lastTrainedLabel).toBe("Never");
    expect(rows[0].avgVelocity).toBeNull();
  });

  it("survives an empty group", () => {
    expect(buildGroupRows([], {}, { now: NOW })).toEqual([]);
    expect(buildGroupRows(null, null, { now: NOW })).toEqual([]);
  });
});
