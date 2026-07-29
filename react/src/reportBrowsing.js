import { sameOriginPath } from "./workoutCatalog.js";

export const MAX_MOUNTED_REPORT_REPS = 100;

export function normalizeReportPage(body, origin) {
  const results = Array.isArray(body) ? body : body?.results || [];
  return {
    count: Array.isArray(body) ? body.length : body?.count ?? results.length,
    results,
    previous: sameOriginPath(body?.previous, origin),
    next: sameOriginPath(body?.next, origin),
  };
}

export function reportRequestState(status, body) {
  if (status === 404) return { type: "not_found", message: body?.detail || "Report not found." };
  if (status === 422 || body?.code === "unsupported_report_schema" || body?.code === "unsupported_schema") {
    return { type: "unsupported", message: body?.detail || "This report version is not supported." };
  }
  return { type: "error", message: body?.detail || "Reports could not be loaded." };
}

export function repWindow(reps, start = 0, limit = MAX_MOUNTED_REPORT_REPS) {
  const maxStart = reps.length ? Math.floor((reps.length - 1) / limit) * limit : 0;
  const safeStart = Math.max(0, Math.min(start, maxStart));
  const rows = reps.slice(safeStart, safeStart + limit);
  return {
    rows,
    start: rows.length ? safeStart : 0,
    end: safeStart + rows.length,
    total: reps.length,
    previousStart: safeStart > 0 ? Math.max(0, safeStart - limit) : null,
    nextStart: safeStart + rows.length < reps.length ? safeStart + limit : null,
  };
}

export function athleteDayLabel(day) {
  return day?.local_date || "Date unavailable";
}

export function athleteDaySets(detail) {
  return athleteDayEntry(detail)?.sets || [];
}

export function athleteDayEntry(detail) {
  return detail?.athlete?.athlete ? detail.athlete : detail;
}

// "This athlete's report" is the SAME report read through a one-athlete lens —
// so it is the same route with ?athlete={id}, not a parallel athletes/{id}/...
// family (merge canon R6). The two can never disagree because there is only one
// stored snapshot behind both.
export function reportPdfDownload(mode, reportId, athleteId) {
  if (mode === "athlete") {
    return {
      url: `/api/reports/${reportId}/pdf/?athlete=${athleteId}`,
      filename: `athlete-${athleteId}-report-${reportId}.pdf`,
    };
  }
  return { url: `/api/reports/${reportId}/pdf/`, filename: `report-${reportId}.pdf` };
}
