// The range is shared by the athlete view and the group view, so a bug here
// makes the two disagree about which sets exist. Most of these are about the
// local-vs-UTC day boundary, which is the failure this file was written to
// avoid — the same one schedule.js documents.

import { describe, expect, it } from "vitest";
import {
  isoDay, matchesPreset, normaliseRange, presetRange, rangeContains, rangeDays, rangeLabel,
} from "./historyRange.js";

const NOW = new Date(2026, 7, 15, 12, 0, 0); // 15 Aug 2026, local

describe("presetRange", () => {
  it("is inclusive, so 14 days covers 14 days", () => {
    const range = presetRange(14, NOW);
    expect(range.to).toBe("2026-08-15");
    expect(range.from).toBe("2026-08-02");
    expect(rangeDays(range)).toBe(14);
  });

  it("recognises its own presets, so the button can show as selected", () => {
    expect(matchesPreset(presetRange(30, NOW), 30, NOW)).toBe(true);
    expect(matchesPreset(presetRange(30, NOW), 14, NOW)).toBe(false);
  });
});

describe("rangeContains", () => {
  const range = { from: "2026-08-02", to: "2026-08-15" };

  it("includes both ends", () => {
    expect(rangeContains(range, "2026-08-02T06:00:00")).toBe(true);
    expect(rangeContains(range, "2026-08-15T23:30:00")).toBe(true);
  });

  it("excludes the days either side", () => {
    expect(rangeContains(range, "2026-08-01T23:59:00")).toBe(false);
    expect(rangeContains(range, "2026-08-16T00:01:00")).toBe(false);
  });

  // The bug this file exists to avoid: an evening set on the last day of the
  // range read as UTC lands on the following day and drops out.
  it("keeps an evening set on the final day inside the range", () => {
    const evening = new Date(2026, 7, 15, 20, 30).toISOString();
    expect(rangeContains(range, evening)).toBe(true);
  });

  it("says no rather than throwing on junk", () => {
    expect(rangeContains(range, null)).toBe(false);
    expect(rangeContains(range, "not a date")).toBe(false);
    expect(rangeContains(null, "2026-08-03T10:00:00")).toBe(false);
  });
});

describe("rangeLabel", () => {
  it("names a preset when the range is one", () => {
    expect(rangeLabel(presetRange(14, NOW), NOW)).toBe("Last 14 days");
  });

  it("shows the dates when a coach picked their own", () => {
    expect(rangeLabel({ from: "2026-07-03", to: "2026-07-18" }, NOW)).toMatch(/Jul.*Jul/);
  });

  it("says All time when there is no range", () => {
    expect(rangeLabel(null, NOW)).toBe("All time");
  });
});

describe("normaliseRange", () => {
  // Two inputs let a coach pick an end before a start, and every reader
  // downstream would quietly show nothing.
  it("swaps ends that are the wrong way round", () => {
    expect(normaliseRange("2026-08-20", "2026-08-01")).toEqual({ from: "2026-08-01", to: "2026-08-20" });
  });

  it("leaves a correct range alone", () => {
    expect(normaliseRange("2026-08-01", "2026-08-20")).toEqual({ from: "2026-08-01", to: "2026-08-20" });
  });

  it("returns nothing when an end is missing", () => {
    expect(normaliseRange("2026-08-01", "")).toBeNull();
  });
});

describe("isoDay", () => {
  // toISOString() would give the previous day for an evening date in the
  // Americas. This must be local.
  it("is the LOCAL calendar day, not the UTC one", () => {
    expect(isoDay(new Date(2026, 7, 3, 22, 0))).toBe("2026-08-03");
    expect(isoDay(new Date(2026, 0, 9, 1, 0))).toBe("2026-01-09");
  });
});
