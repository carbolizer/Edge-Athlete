import { describe, expect, it } from "vitest";
import { athleteDayEntry, athleteDayLabel, athleteDaySets, downloadReportPdf, normalizeReportPage, repWindow, reportPdfDownload, reportPdfErrorState, reportPdfRequestHeaders, reportRequestState, retryAfterSeconds, retryReportPdf, safePdfFilename, triggerBrowserDownload } from "./reportBrowsing.js";

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

describe("safe PDF download mechanics", () => {
  it("does not request an unsupported DRF PDF renderer during authenticated fetch", () => {
    expect(reportPdfRequestHeaders("token")).toEqual({ Authorization: "Bearer token" });
  });
  it("exposes browser download side effects through a harnessable helper", () => {
    const events = [];
    const timers = [];
    const link = { click: () => events.push("clicked"), remove: () => events.push("removed") };
    triggerBrowserDownload(new Blob(["pdf"]), "server-name.pdf", {
      URL: { createObjectURL: () => "blob:report", revokeObjectURL: (url) => events.push(`revoked:${url}`) },
      document: { createElement: () => link, body: { appendChild: () => events.push(`appended:${link.download}`) } },
      setTimeout: (callback, delay) => timers.push({ callback, delay }),
    });
    expect(events).toEqual(["appended:server-name.pdf", "clicked", "removed"]);
    expect(link.href).toBe("blob:report");
    expect(timers[0].delay).toBe(1_000);
    timers[0].callback();
    expect(events.at(-1)).toBe("revoked:blob:report");
  });

  it("uses a safe server filename, validates PDF bytes, and delays URL revocation", async () => {
    const clicked = [];
    const revoked = [];
    const timers = [];
    const link = { click: () => clicked.push(true), remove() {} };
    const response = new Response(new Blob(["%PDF-1.4\nbody"], { type: "application/pdf" }), { headers: { "Content-Type": "application/pdf", "Content-Disposition": "attachment; filename=server-report.pdf" } });
    const filename = await downloadReportPdf({ response, fallbackFilename: "fallback.pdf", browser: { URL: { createObjectURL: () => "blob:test", revokeObjectURL: (url) => revoked.push(url) }, document: { createElement: () => link, body: { appendChild() {} } }, setTimeout: (callback, delay) => timers.push({ callback, delay }) } });
    expect(filename).toBe("server-report.pdf");
    expect(clicked).toEqual([true]);
    expect(revoked).toEqual([]);
    expect(timers[0].delay).toBe(1000);
    timers[0].callback();
    expect(revoked).toEqual(["blob:test"]);
  });

  it("rejects empty, non-PDF responses and parses retry timing", async () => {
    await expect(downloadReportPdf({ response: new Response("oops", { headers: { "Content-Type": "text/plain" } }), fallbackFilename: "x.pdf" })).rejects.toThrow("did not return a PDF");
    await expect(downloadReportPdf({ response: new Response(new Blob([], { type: "application/pdf" }), { headers: { "Content-Type": "application/pdf" } }), fallbackFilename: "x.pdf" })).rejects.toThrow("empty");
    expect(retryAfterSeconds("7")).toBe(7);
    expect(safePdfFilename("attachment; filename=../../bad.txt", "report.pdf")).toBe("report.pdf");
  });

  it("shows retry state for transient and throttled failures but not terminal responses", () => {
    expect(reportPdfErrorState({ status: 429, retryAfter: 7, message: "Too many requests." })).toEqual({
      type: "error",
      retryable: true,
      message: "Too many requests. Retry after 7 seconds.",
    });
    expect(reportPdfErrorState({ status: 403, message: "Forbidden." }).retryable).toBe(false);
    expect(reportPdfErrorState({ status: 404, message: "Missing." }).retryable).toBe(false);
  });

  it("runs retry only for retryable PDF error state", () => {
    let attempts = 0;
    const retry = () => { attempts += 1; };
    expect(retryReportPdf({ type: "error", retryable: true }, retry)).toBe(true);
    expect(retryReportPdf({ type: "error", retryable: false }, retry)).toBe(false);
    expect(attempts).toBe(1);
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
