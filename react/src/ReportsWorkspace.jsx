// ReportsWorkspace.jsx — the coach's filing cabinet of finished training days.
//
// When a training day ends, the server freezes everything that happened into a
// permanent snapshot (a "daily report") and never edits it again. This screen is
// how a coach reads those snapshots back. Nothing here can change history — it
// only looks.
//
// There are two ways to look, and the "mode" toggle at the top switches between
// them:
//
//   "daily"    → one whole training day, every athlete in it. Team-wide view.
//   "athlete"  → one athlete's own days, one at a time. Their personal record.
//
// Both read the SAME stored snapshot from the same route; the athlete view just
// asks for it through a narrower lens (?athlete={id}). That is deliberate — if
// they came from two different places they could eventually disagree, and then
// nobody knows which one is true.
//
// Each mode is a two-level drill-down: a LIST of days, and then the DETAIL of
// the one you clicked. A day can hold thousands of individual reps, which would
// freeze a tablet if rendered all at once, so the detail view mounts reps 100 at
// a time (see repWindow). The full set is always still in the saved report — the
// limit is about what the screen holds, not what the server kept.
//
// The whole detail view can also be downloaded as a PDF, rendered from that same
// frozen snapshot, so a printout and the screen can never disagree either.

import { useEffect, useState } from "react";
import { GeneratedReport } from "./TrainingDayPanel.jsx";
import { reportValue } from "./trainingDay.js";
import { athleteDayEntry, athleteDayLabel, athleteDaySets, normalizeReportPage, repWindow, reportPdfDownload, reportRequestState } from "./reportBrowsing.js";

const DAILY_REPORTS_URL = "/api/reports/";

// One report family, filtered — not a second athletes/{id}/reports/ family
// (merge canon R6). Both list modes now read the same route; what still differs
// is the DETAIL lens, where ?athlete= narrows a day to one athlete's own work.
function athleteReportsUrl(athleteId) {
  return `${DAILY_REPORTS_URL}?athlete=${encodeURIComponent(athleteId)}`;
}

// ─────────────────────────── small shared pieces ───────────────────────────

// The box shown INSTEAD of results when a request didn't work out — missing
// report, a report saved by a version this build can't read, or a plain failure.
// Each gets its own wording so a coach knows whether to retry or to stop.
function RequestPanel({ state, onRetry }) {
  const titles = { not_found: "Report not found", unsupported: "Report version unsupported", error: "Reports unavailable" };
  return <section className="reports-request-panel" role={state.type === "error" ? "alert" : "status"}><h3>{titles[state.type] || "Reports unavailable"}</h3><p>{state.message}</p>{onRetry && <button onClick={onRetry}>Retry</button>}</section>;
}

// Previous/Next for a long list of reports. Hides itself entirely when
// everything already fits on one page.
function PageControls({ page, loading, onPage, label }) {
  if (!page || (!page.previous && !page.next && page.count <= page.results.length)) return null;
  return <nav className="workout-pagination" aria-label={label}><button className="workout-secondary" onClick={() => onPage(page.previous)} disabled={!page.previous || loading}>Previous</button><span role="status">Showing {page.results.length} on this page · {page.count} total</span><button onClick={() => onPage(page.next)} disabled={!page.next || loading}>Next</button></nav>;
}

// ─────────────────────────── level 1: the lists ───────────────────────────

// "daily" mode's list: one card per finished training day, with the headline
// numbers for the whole room. Click one to open it.
function DailyList({ page, onOpen }) {
  if (!page.results.length) return <p className="monitor-empty">No finalized daily reports match this filter.</p>;
  return <div className="daily-report-list">{page.results.map((report) => {
    const summary = report.summary || {};
    const session = report.session || {};
    return <article key={report.id}><div><span>{report.local_date || "Date unavailable"}</span><h3>{session.label || report.label || `Report ${report.id}`}</h3><p>{reportValue(session.ended_at || report.ended_at)}</p></div><dl><div><dt>Athletes</dt><dd>{reportValue(summary.athletes ?? summary.athlete_count)}</dd></div><div><dt>Sets</dt><dd>{reportValue(summary.completed_sets)}</dd></div><div><dt>Reps</dt><dd>{reportValue(summary.completed_reps)}</dd></div></dl><button onClick={() => onOpen(report.id)}>Open report</button></article>;
  })}</div>;
}

// "athlete" mode's list: the same days, but only the ones this athlete trained,
// and the numbers are theirs alone. Dated by the gym's local date, not the
// server's clock, so a late-evening session doesn't show up as tomorrow.
function AthleteDayList({ page, onOpen }) {
  if (!page.results.length) return <p className="monitor-empty">No finalized report days exist for this athlete.</p>;
  return <div className="athlete-day-list">{page.results.map((day) => <article key={day.id}><div><span>Local training date</span><h3>{athleteDayLabel(day)}</h3><p>{day.session?.label || `Report ${day.id}`}</p></div><dl><div><dt>Sets</dt><dd>{reportValue(day.summary?.completed_sets)}</dd></div><div><dt>Reps</dt><dd>{reportValue(day.summary?.completed_reps)}</dd></div><div><dt>Average</dt><dd>{reportValue(day.summary?.average_velocity, " m/s")}</dd></div></dl><button onClick={() => onOpen(day.id)}>Open athlete day</button></article>)}</div>;
}

// ─────────────────────────── level 2: the detail ───────────────────────────

// One set an athlete actually lifted, collapsed to its headline numbers until
// you open it. Opening it reveals the individual reps — 100 at a time, because
// a heavy day can hold thousands and mounting them all locks up the tablet.
//
// False sets stay visible and are labelled rather than hidden: a mis-tracked set
// is part of the audit trail, it just doesn't count toward completed work.
function AthleteSetDetail({ workoutSet, expanded, repStart, onToggle, onRepStart }) {
  const reps = workoutSet.reps || [];
  const windowed = repWindow(reps, repStart);
  return <article className={`athlete-report-set ${expanded ? "expanded" : ""}`}><div className="athlete-report-set-summary"><div><span>{workoutSet.is_false_set ? "False set (excluded)" : `Set ${workoutSet.set_number ?? "--"}`} · Rack {reportValue(workoutSet.rack_number)}</span><h4>{workoutSet.exercise || "Exercise unavailable"}</h4></div><dl><div><dt>Load</dt><dd>{reportValue(workoutSet.weight_lbs, " lbs")}</dd></div><div><dt>Reps</dt><dd>{reportValue(workoutSet.reps_completed)}</dd></div><div><dt>Average</dt><dd>{reportValue(workoutSet.avg_velocity, " m/s")}</dd></div><div><dt>Peak</dt><dd>{reportValue(workoutSet.peak_velocity, " m/s")}</dd></div></dl><button onClick={onToggle} aria-expanded={expanded}>{expanded ? "Close reps" : "View reps"}</button></div>{expanded && <div className="athlete-report-reps"><p>{workoutSet.is_false_set ? "This false set is retained for audit history and excluded from completed work. " : ""}Mounted rep rows {windowed.rows.length ? `${windowed.start + 1}-${windowed.end}` : "0"} of {windowed.total}. The saved report retains all rows.</p>{windowed.rows.length ? <div className="athlete-report-rep-table-wrap"><table><caption>Persisted reps for {workoutSet.exercise}, set {workoutSet.set_number}</caption><thead><tr><th scope="col">Rep</th><th scope="col">Mean</th><th scope="col">Peak</th><th scope="col">Duration</th></tr></thead><tbody>{windowed.rows.map((rep, index) => <tr key={rep.id || rep.rep_number || index}><td>{reportValue(rep.rep_number)}</td><td>{reportValue(rep.mean_velocity, " m/s")}</td><td>{reportValue(rep.peak_velocity, " m/s")}</td><td>{reportValue(rep.duration_ms, " ms")}</td></tr>)}</tbody></table></div> : <p className="monitor-empty">No persisted rep rows.</p>}<div className="athlete-report-rep-pages"><button onClick={() => onRepStart(windowed.previousStart)} disabled={windowed.previousStart === null}>Previous 100</button><button onClick={() => onRepStart(windowed.nextStart)} disabled={windowed.nextStart === null}>Next 100</button></div></div>}</article>;
}

// One athlete's whole day, in two halves: what they were SUPPOSED to do (the
// prescription that was in force when the day ended) and what they ACTUALLY did
// (every set recorded). Reading them side by side is the point of the screen.
function AthleteDayDetail({ detail }) {
  const [expandedSetId, setExpandedSetId] = useState(null);
  const [repStart, setRepStart] = useState(0);
  const entry = athleteDayEntry(detail);
  const athlete = entry.athlete || {};
  const sets = athleteDaySets(detail);
  const prescriptions = entry.prescriptions || entry.assigned_program?.items || entry.effective_prescriptions || (entry.prescription ? [entry.prescription] : []);
  function toggleSet(id) {
    setExpandedSetId((current) => current === id ? null : id);
    setRepStart(0);
  }
  const qualifyingSets = sets.filter((workoutSet) => workoutSet.is_false_set !== true);
  return <section className="athlete-day-detail"><header><div><span>Athlete report day</span><h3>{athlete.name || "Athlete unavailable"}</h3><p>{athleteDayLabel(detail)}</p></div><dl><div><dt>Completed sets</dt><dd>{qualifyingSets.length}</dd></div><div><dt>Reps</dt><dd>{qualifyingSets.reduce((total, workoutSet) => total + (workoutSet.reps_completed || 0), 0)}</dd></div></dl></header><section className="athlete-day-prescriptions"><h4>Effective at day end</h4>{prescriptions.length ? prescriptions.map((prescription, index) => <article key={prescription.id || index}><span>{prescription.source || "Assignment"}</span><h5>{prescription.workout?.name || prescription.workout_name || prescription.name || "Legacy prescription"}</h5><div>{(prescription.exercises || []).map((exercise, exerciseIndex) => <p key={exercise.id || exercise.position || exerciseIndex}><b>{exercise.position ?? exerciseIndex + 1}. {exercise.exercise}</b><span>{reportValue(exercise.sets)} x {reportValue(exercise.reps)} · {reportValue(exercise.default_weight_lbs, " lbs")}</span></p>)}</div></article>) : <p className="monitor-empty">No effective prescription was recorded.</p>}</section><section className="athlete-day-results"><h4>Persisted set records</h4>{sets.length ? sets.map((workoutSet, index) => {
    const id = workoutSet.id || `${workoutSet.exercise}-${workoutSet.set_number}-${index}`;
    return <AthleteSetDetail workoutSet={workoutSet} expanded={expandedSetId === id} repStart={expandedSetId === id ? repStart : 0} onToggle={() => toggleSet(id)} onRepStart={setRepStart} key={id} />;
  }) : <p className="monitor-empty">No completed persisted sets for this athlete day.</p>}</section></section>;
}

// ─────────────────────────── the screen itself ───────────────────────────

// Holds the two modes, the athlete filter, and the list→detail drill-down, and
// owns every fetch. `pages` and `pageUrls` are keyed by mode so switching back
// and forth doesn't re-request a list that's already loaded.
export default function ReportsWorkspace({ athletes, accessToken, onLogout }) {
  const [mode, setMode] = useState("daily");
  const [athleteId, setAthleteId] = useState("");
  const [pages, setPages] = useState({ daily: null, athlete: null });
  const [pageUrls, setPageUrls] = useState({ daily: DAILY_REPORTS_URL, athlete: null });
  const [detail, setDetail] = useState(null);
  const [detailKey, setDetailKey] = useState(null);
  const [loading, setLoading] = useState(false);
  const [requestError, setRequestError] = useState(null);
  const [retryTarget, setRetryTarget] = useState(null);
  const [downloadState, setDownloadState] = useState(null);
  const headers = { Accept: "application/json", Authorization: `Bearer ${accessToken}` };

  async function read(url) {
    const response = await fetch(url, { headers });
    if (response.status === 401 || response.status === 403) {
      onLogout();
      return null;
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw reportRequestState(response.status, body);
    return body;
  }

  async function loadPage(url, targetMode = mode) {
    if (!url) return;
    setRetryTarget({ type: "page", url, mode: targetMode });
    setLoading(true);
    setRequestError(null);
    try {
      const body = await read(url);
      if (body === null) return;
      setPages((current) => ({ ...current, [targetMode]: normalizeReportPage(body, window.location.origin) }));
      setPageUrls((current) => ({ ...current, [targetMode]: url }));
    } catch (error) {
      setRequestError(error.type ? error : { type: "error", message: "Reports could not be loaded." });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadPage(DAILY_REPORTS_URL, "daily"); }, [accessToken]);

  function changeFilter(nextAthleteId) {
    setAthleteId(nextAthleteId);
    setDetail(null);
    setDetailKey(null);
    const dailyUrl = nextAthleteId ? `${DAILY_REPORTS_URL}?athlete=${encodeURIComponent(nextAthleteId)}` : DAILY_REPORTS_URL;
    setPages((current) => ({ ...current, daily: null, athlete: null }));
    const athleteUrl = nextAthleteId ? athleteReportsUrl(nextAthleteId) : null;
    setPageUrls({ daily: nextAthleteId ? athleteUrl : dailyUrl, athlete: athleteUrl });
    if (mode === "daily") loadPage(nextAthleteId ? athleteUrl : dailyUrl, "daily");
    else if (nextAthleteId) loadPage(athleteUrl, "athlete");
  }

  function changeMode(nextMode) {
    setMode(nextMode);
    setDetail(null);
    setDetailKey(null);
    setRequestError(null);
    const url = nextMode === "daily" ? pageUrls.daily : athleteId ? pageUrls.athlete || athleteReportsUrl(athleteId) : null;
    if (url && !pages[nextMode]) loadPage(url, nextMode);
  }

  async function openDetail(key) {
    setLoading(true);
    setRequestError(null);
    setDetailKey(key);
    setRetryTarget({ type: "detail", key });
    // Same report, two lenses. "daily" asks for the day whole; "athlete" asks
    // for the same day narrowed to one athlete's work with ?athlete={id}.
    const url = mode === "daily"
      ? `${DAILY_REPORTS_URL}${key}/`
      : `${DAILY_REPORTS_URL}${key}/?athlete=${encodeURIComponent(athleteId)}`;
    try {
      const body = await read(url);
      if (body !== null) setDetail(body);
    } catch (error) {
      setRequestError(error.type ? error : { type: "error", message: "Report detail could not be loaded." });
    } finally {
      setLoading(false);
    }
  }

  async function downloadPdf() {
    const download = reportPdfDownload(mode, detailKey, athleteId);
    setDownloadState({ type: "loading", message: "Preparing PDF..." });
    try {
      const response = await fetch(download.url, { headers: { Accept: "application/pdf", Authorization: `Bearer ${accessToken}` } });
      if (response.status === 401 || response.status === 403) {
        onLogout();
        return;
      }
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Report PDF could not be downloaded.");
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = download.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
      setDownloadState({ type: "success", message: "PDF download started." });
    } catch (error) {
      setDownloadState({ type: "error", message: error.message || "Report PDF could not be downloaded." });
    }
  }

  const page = pages[mode];
  const retry = () => retryTarget?.type === "detail" ? openDetail(retryTarget.key) : loadPage(retryTarget?.url || pageUrls[mode], retryTarget?.mode || mode);
  return <section className="reports-workspace context-tab-content"><header className="reports-heading"><div><span>Immutable training history</span><h2>Reports</h2><p>Browse finalized daily snapshots or one athlete’s server-local training days.</p></div><div className="reports-mode" role="group" aria-label="Report view"><button className={mode === "daily" ? "active" : ""} onClick={() => changeMode("daily")}>Daily reports</button><button className={mode === "athlete" ? "active" : ""} onClick={() => changeMode("athlete")}>Athlete days</button></div></header><div className="reports-toolbar"><label>Athlete filter<select value={athleteId} onChange={(event) => changeFilter(event.target.value)}><option value="">All athletes</option>{athletes.map((athlete) => <option value={athlete.id} key={athlete.id}>{athlete.name}</option>)}</select></label>{detailKey !== null && <div className="reports-actions"><button className="reports-back" onClick={() => { setDetail(null); setDetailKey(null); setRequestError(null); setDownloadState(null); }}>Back to {mode === "daily" ? "daily reports" : "athlete days"}</button>{detail && <button onClick={downloadPdf} disabled={downloadState?.type === "loading"}>{downloadState?.type === "loading" ? "Preparing PDF..." : "Download PDF"}</button>}</div>}</div>{downloadState?.type !== "loading" && downloadState && <p className={downloadState.type === "error" ? "training-day-error" : "training-day-status"} role={downloadState.type === "error" ? "alert" : "status"}>{downloadState.message}</p>}{loading && <p className="monitor-empty" role="status">Loading reports...</p>}{requestError && <RequestPanel state={requestError} onRetry={retry} />}{!loading && !requestError && detail && (mode === "daily" ? <GeneratedReport report={detail} /> : <AthleteDayDetail detail={detail} />)}{!loading && !requestError && !detail && detailKey === null && mode === "athlete" && !athleteId && <section className="reports-request-panel"><h3>Select an athlete</h3><p>Athlete report days use the server-provided local date.</p></section>}{!loading && !requestError && !detail && detailKey === null && page && (mode === "daily" ? <DailyList page={page} onOpen={openDetail} /> : <AthleteDayList page={page} onOpen={openDetail} />)}{detailKey === null && <PageControls page={page} loading={loading} onPage={(url) => loadPage(url, mode)} label={mode === "daily" ? "Daily report pages" : "Athlete report day pages"} />}</section>;
}
