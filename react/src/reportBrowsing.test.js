import { describe, expect, it } from "vitest";
import { athleteDayEntry, athleteDayLabel, athleteDaySets, normalizeReportPage, repWindow, reportPdfDownload, reportRequestState } from "./reportBrowsing.js";

describe("report browsing pages", () => {
  it("normalizes pagination and rejects cross-origin links", () => {
    expect(normalizeReportPage({ count: 2, results: [{ id: 1 }], next: "https://edge.local/api/reports/?page=2", previous: "https://evil.test/reports" }, "https://edge.local")).toEqual({
      count: 2,
      results: [{ id: 1 }],
      next: "/api/reports/?page=2",
      previous: null,
    });
  });

  it("classifies missing and unsupported report responses", () => {
    expect(reportRequestState(404, { detail: "Missing." })).toEqual({ type: "not_found", message: "Missing." });
    expect(reportRequestState(400, { code: "unsupported_report_schema", detail: "Version 7." })).toEqual({ type: "unsupported", message: "Version 7." });
  });

  it("uses server local_date and supports alternate set envelopes", () => {
    expect(athleteDayLabel({ local_date: "2026-07-16" })).toBe("2026-07-16");
    const detail = { athlete: { athlete: { id: 4, name: "Alex" }, sets: [{ id: 3 }] } };
    expect(athleteDayEntry(detail)).toBe(detail.athlete);
    expect(athleteDaySets(detail)).toEqual([{ id: 3 }]);
  });

  it("builds ID-only daily and athlete PDF downloads", () => {
    expect(reportPdfDownload("daily", 12, "ignored")).toEqual({
      url: "/api/reports/12/pdf/",
      filename: "report-12.pdf",
    });
    expect(reportPdfDownload("athlete", 12, 7)).toEqual({
      url: "/api/athletes/7/reports/12/pdf/",
      filename: "athlete-7-report-12.pdf",
    });
  });
});

describe("mounted rep window", () => {
  it("mounts at most one deterministic batch with next and previous positions", () => {
    const reps = Array.from({ length: 205 }, (_, index) => ({ rep_number: index + 1 }));
    expect(repWindow(reps, 0)).toMatchObject({ start: 0, end: 100, total: 205, previousStart: null, nextStart: 100 });
    expect(repWindow(reps, 100)).toMatchObject({ start: 100, end: 200, previousStart: 0, nextStart: 200 });
    expect(repWindow(reps, 200)).toMatchObject({ start: 200, end: 205, previousStart: 100, nextStart: null });
    expect(repWindow(reps, 100).rows).toHaveLength(100);
  });
});
