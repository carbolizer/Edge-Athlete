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

export function reportPdfDownload(mode, reportId, athleteId) {
  if (mode === "athlete") {
    return {
      url: `/api/athletes/${athleteId}/reports/${reportId}/pdf/`,
      filename: `athlete-${athleteId}-report-${reportId}.pdf`,
    };
  }
  return { url: `/api/reports/${reportId}/pdf/`, filename: `report-${reportId}.pdf` };
}

export function reportPdfRequestHeaders(accessToken) {
  return { Authorization: `Bearer ${accessToken}` };
}

export function safePdfFilename(contentDisposition, fallback) {
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(contentDisposition || "")?.[1];
  const plain = /filename="?([^";]+)"?/i.exec(contentDisposition || "")?.[1];
  let value = plain;
  try { if (encoded) value = decodeURIComponent(encoded); } catch { value = null; }
  value = value?.replace(/[\\/\x00-\x1f\x7f]/g, "").trim();
  return value && value.toLowerCase().endsWith(".pdf") ? value.slice(0, 180) : fallback;
}

export function retryAfterSeconds(value, now = Date.now()) {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.ceil(seconds);
  const instant = Date.parse(value);
  return Number.isFinite(instant) ? Math.max(0, Math.ceil((instant - now) / 1000)) : null;
}

export function reportPdfErrorState(error) {
  const retryable = error?.status !== 403 && error?.status !== 404;
  const throttle = error?.status === 429 && error?.retryAfter != null
    ? ` Retry after ${error.retryAfter} second${error.retryAfter === 1 ? "" : "s"}.`
    : "";
  return {
    type: "error",
    retryable,
    message: `${error?.message || "Report PDF could not be downloaded."}${throttle}`,
  };
}

export function retryReportPdf(state, retry) {
  if (state?.type !== "error" || !state.retryable) return false;
  retry();
  return true;
}

export function triggerBrowserDownload(blob, filename, browser = {}) {
  const urlApi = browser.URL || URL;
  const documentApi = browser.document || document;
  const schedule = browser.setTimeout || setTimeout;
  const objectUrl = urlApi.createObjectURL(blob);
  const link = documentApi.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  documentApi.body.appendChild(link);
  link.click();
  link.remove();
  schedule(() => urlApi.revokeObjectURL(objectUrl), 1_000);
}

export async function downloadReportPdf({ response, fallbackFilename, browser = {} }) {
  const contentType = response.headers.get("Content-Type")?.toLowerCase() || "";
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(body.detail || "Report PDF could not be downloaded.");
    error.status = response.status;
    error.retryAfter = retryAfterSeconds(response.headers.get("Retry-After"));
    throw error;
  }
  if (!contentType.includes("application/pdf")) throw new Error("The server did not return a PDF file.");
  const blob = await response.blob();
  if (!blob.size) throw new Error("The PDF response was empty.");
  const prefix = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
  if (String.fromCharCode(...prefix) !== "%PDF") throw new Error("The downloaded file is not a valid PDF.");
  const filename = safePdfFilename(response.headers.get("Content-Disposition"), fallbackFilename);
  triggerBrowserDownload(blob, filename, browser);
  return filename;
}
