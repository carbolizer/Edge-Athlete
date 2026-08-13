import { describe, expect, it } from "vitest";
import {
  ATHLETE_TABS, ROOM_TABS, ALL_TABS, tabDisabled, tabGroup,
} from "./coachTabs.js";

describe("coach tab groups", () => {
  it("splits room-level views from per-athlete ones", () => {
    expect(ROOM_TABS).toEqual(["room", "workouts", "schedule", "reports"]);
    expect(ATHLETE_TABS).toEqual(["athlete", "history", "programs", "notes"]);
    expect(ALL_TABS).toHaveLength(8);
    // No overlap: every tab belongs to exactly one group.
    expect(ROOM_TABS.filter((t) => ATHLETE_TABS.includes(t))).toEqual([]);
  });

  it("groups every tab correctly", () => {
    for (const t of ROOM_TABS) expect(tabGroup(t)).toBe("room");
    for (const t of ATHLETE_TABS) expect(tabGroup(t)).toBe("athlete");
  });

  it("only disables per-athlete tabs when no athlete is selected", () => {
    expect(tabDisabled("room", null)).toBe(false);
    expect(tabDisabled("workouts", null)).toBe(false);
    expect(tabDisabled("schedule", null)).toBe(false);
    expect(tabDisabled("reports", null)).toBe(false);

    expect(tabDisabled("athlete", null)).toBe(true);
    expect(tabDisabled("history", null)).toBe(true);
    expect(tabDisabled("programs", null)).toBe(true);
    expect(tabDisabled("notes", null)).toBe(true);

    expect(tabDisabled("athlete", 4)).toBe(false);
    expect(tabDisabled("history", 4)).toBe(false);
  });
});
