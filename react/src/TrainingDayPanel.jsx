import { useEffect, useState } from "react";
import { budgetReportRendering, buildTrainingDayPayload, orderedReportExercises, orderedReportPrescriptions, previewGroups, reportAthleteContext, reportAthletes, reportExerciseSets, reportSnapshot, reportSummary, reportValue, unfinishedRackNumbers } from "./trainingDay.js";

function ReportRep({ rep }) {
  return <li><span>Rep {rep.rep_number ?? rep.number ?? "--"}</span><b>{reportValue(rep.mean_velocity, " m/s mean")}</b><b>{reportValue(rep.peak_velocity, " m/s peak")}</b><b>{reportValue(rep.duration_ms, " ms")}</b></li>;
}

function ReportSet({ record, index }) {
    const { workoutSet, reps, totalReps } = record;
  return <article className="training-report-set"><header><span>{workoutSet.is_false_set ? "False set (excluded)" : `Set ${workoutSet.set_number ?? index + 1}`}</span><b>{reportValue(workoutSet.weight_lbs, " lbs")}</b><b>{reportValue(workoutSet.reps_completed ?? workoutSet.completed_reps, " reps")}</b></header>{reps.length ? <ol>{reps.map((rep, repIndex) => <ReportRep rep={rep} key={rep.id || rep.rep_number || repIndex} />)}</ol> : totalReps === 0 ? <p className="monitor-empty">{workoutSet.is_false_set ? "False set; excluded from completed work." : "No persisted rep measurements."}</p> : null}{reps.length < totalReps && <p className="training-report-truncation">Showing {reps.length} of {totalReps} persisted rep rows for this set. All rows remain in the saved report.</p>}</article>;
}

function ReportPrescription({ athlete, prescription, index, renderedSets }) {
  const exercises = prescription.exercises ? orderedReportExercises(prescription) : [prescription];
  return <article className="training-report-prescription"><header><span>Workout {prescription.position ?? index + 1}</span><h5>{prescription.workout_name || prescription.workout?.name || prescription.name || (prescription.source === "legacy" ? "Legacy prescription" : `Workout ${index + 1}`)}</h5></header>{exercises.map((exercise, exerciseIndex) => {
    const matching = reportExerciseSets(athlete, prescription, exercise);
    const visible = renderedSets.filter((record) => matching.some((set) => set.id === record.workoutSet.id));
    const completed = matching.filter((set) => !set.is_false_set).length;
    return <section className={completed < Number(exercise.sets ?? exercise.target_sets) ? "report-incomplete" : ""} key={exercise.id || exercise.position || exerciseIndex}><div className="training-report-target"><div><span>{exercise.position ?? exerciseIndex + 1}. {exercise.exercise || exercise.name || "Exercise"}</span><b>Prescribed {reportValue(exercise.sets ?? exercise.target_sets)} x {reportValue(exercise.reps ?? exercise.target_reps)}</b></div><div><span>Completed</span><b>{completed} qualifying · {matching.filter((set) => set.is_false_set).length} false</b></div><div><span>Target load</span><b>{reportValue(exercise.default_weight_lbs ?? exercise.weight_lbs ?? exercise.target_weight_lbs, " lbs")}</b></div></div><div className="training-report-sets">{visible.map((record, setIndex) => <ReportSet record={record} index={setIndex} key={record.workoutSet.id || setIndex} />)}{matching.length === 0 && <p className="monitor-empty">Missing: no set records.</p>}</div></section>;
  })}</article>;
}

export function GeneratedReport({ report }) {
  const snapshot = reportSnapshot(report);
  const athletes = reportAthletes(snapshot);
  const rendering = budgetReportRendering(athletes);
  const summary = reportSummary(snapshot);
  const session = snapshot.session || snapshot.training_day || {};
  const truncated = Object.entries(rendering.counts).filter(([, count]) => count.rendered < count.total);
  return <section className="training-report" aria-labelledby="generated-report-heading"><header><div><span>Generated report</span><h3 id="generated-report-heading">{session.label || report.label || "Training day complete"}</h3><p className="training-report-date">Training date {reportValue(session.training_date || report.local_date)}</p><p>{reportValue(session.started_at || report.started_at)} to {reportValue(session.ended_at || report.ended_at)}</p></div><b>Finalized</b></header><dl className="training-report-summary"><div><dt>Athletes</dt><dd>{reportValue(summary.athletes ?? summary.athlete_count ?? athletes.length)}</dd></div><div><dt>Completed sets</dt><dd>{reportValue(summary.completed_sets)}</dd></div><div><dt>Completed reps</dt><dd>{reportValue(summary.completed_reps)}</dd></div><div><dt>Average velocity</dt><dd>{reportValue(summary.average_velocity ?? summary.avg_velocity, " m/s")}</dd></div></dl>{truncated.length > 0 && <div className="training-report-budget" role="status"><strong>Immediate report view is bounded.</strong>{truncated.map(([label, count]) => <p key={label}>Showing {count.rendered.toLocaleString()} of {count.total.toLocaleString()} saved {label}. The finalized report retains all {count.total.toLocaleString()}.</p>)}</div>}<div className="training-report-athletes">{rendering.athletes.length ? rendering.athletes.map(({ entry, sets: completedSets, totalSets }, index) => {
    const athlete = entry.athlete || entry;
    const prescriptions = orderedReportPrescriptions(entry);
    const context = reportAthleteContext(entry);
    return <section key={athlete.id || athlete.name || index}><header><span>Athlete</span><h4>{athlete.name || "Athlete unavailable"}</h4><b>{context.programName || reportValue(totalSets, " set records")}</b></header><dl className="training-report-athlete-context"><div><dt>Schedule source</dt><dd>{context.scheduleSource}{context.scheduleVersion !== null ? ` · version ${context.scheduleVersion}` : ""}</dd></div><div><dt>Final progress</dt><dd>{context.progressStatus || "Not recorded"}</dd></div><div><dt>Rack visits</dt><dd>{context.rackNumbers.length ? context.rackNumbers.join(", ") : "None recorded"}</dd></div></dl>{prescriptions.length ? prescriptions.map((prescription, prescriptionIndex) => <ReportPrescription athlete={entry} renderedSets={completedSets} prescription={prescription} index={prescriptionIndex} key={prescription.id || prescription.position || prescriptionIndex} />) : <p className="monitor-empty">No effective prescription was recorded.</p>}{completedSets.length < totalSets && <p className="training-report-truncation">Showing {completedSets.length} of {totalSets} saved sets. All remain in the finalized report.</p>}</section>;
  }) : <p className="monitor-empty">No athlete snapshots were generated.</p>}</div></section>;
}

export default function TrainingDayPanel({ roomState, athletes, accessToken, onLogout, refresh }) {
  const [label, setLabel] = useState("");
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [generatedReport, setGeneratedReport] = useState(null);
  const session = roomState.session;
  const headers = { Accept: "application/json", Authorization: `Bearer ${accessToken}` };

  async function loadPreview() {
    setPreviewLoading(true); setError("");
    try { const body = await parseResponse(await fetch("/api/sessions/preview/", { headers }), "Schedule preview could not be loaded."); if (body) setPreview(body); }
    catch (previewError) { setError(previewError.message || "Schedule preview could not be loaded."); }
    finally { setPreviewLoading(false); }
  }

  useEffect(() => { if (!session) loadPreview(); }, [session?.id, accessToken]);

  async function parseResponse(response, fallback) {
    if (response.status === 401 || response.status === 403) {
      onLogout();
      return null;
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const racks = unfinishedRackNumbers(body);
      const unassigned = Number(body.unassigned_set_count) || 0;
      throw new Error(`${body.code ? `${body.code}: ` : ""}${body.detail || fallback}${racks.length ? ` Affected racks: ${racks.join(", ")}.` : ""}${unassigned ? ` ${unassigned} unfinished set${unassigned === 1 ? "" : "s"} is not assigned to a rack.` : ""}`);
    }
    return body;
  }

  async function startDay(event) {
    event.preventDefault();
    setBusy("start");
    setError("");
    setStatus("");
    try {
      const response = await fetch("/api/sessions/", { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(buildTrainingDayPayload(label, preview.preview_version)) });
      const body = await parseResponse(response, "Training day could not be started.");
      if (body === null) return;
      setLabel("");
      setGeneratedReport(null);
      setStatus("Training day started.");
      await refresh({ preserveSnapshot: true, forceAfterInFlight: true });
    } catch (startError) {
      setError(startError.message || "Training day could not be started.");
    } finally {
      setBusy("");
    }
  }

  const groups = previewGroups(preview);

  async function endDay() {
    setBusy("end");
    setError("");
    setStatus("");
    try {
      const response = await fetch(`/api/sessions/${session.id}/end/`, { method: "POST", headers });
      const body = await parseResponse(response, "Training day could not be ended.");
      if (body === null) return;
      setGeneratedReport(body.report || body);
      window.dispatchEvent(new Event("edgeathlete:report-generated"));
      setConfirmEnd(false);
      setStatus("Training day ended and report generated.");
      await refresh({ preserveSnapshot: true, forceAfterInFlight: true });
    } catch (endError) {
      setError(endError.message || "Training day could not be ended.");
    } finally {
      setBusy("");
    }
  }

  return <section className="training-day-shell" aria-label="Training day controls">
    {generatedReport && <GeneratedReport report={generatedReport} />}
    {!session ? <form className="training-day-start" onSubmit={startDay}><header><div><span>Server-local schedule preview</span><h3>{preview?.training_date || "Today"} · {preview ? ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][preview.weekday] : "Loading"}</h3><p>Exact-date entries win over weekdays. The computed eligible roster is frozen when the day starts.</p></div><button type="button" className="workout-secondary" onClick={loadPreview} disabled={previewLoading || Boolean(busy)}>{previewLoading ? "Refreshing..." : "Refresh preview"}</button></header><label>Training day label<input value={label} onChange={(event) => setLabel(event.target.value)} maxLength="255" required disabled={Boolean(busy)} /></label>{preview && <div className="training-preview-groups">{[["Eligible", groups.eligible], ["Rest", groups.rest], ["Missing schedule", groups.missing]].map(([title, rows]) => <section key={title}><h4>{title} <span>{rows.length}</span></h4>{rows.length ? rows.map((row) => <p key={row.athlete.id}><b>{row.athlete.name}</b><span>{row.source}{row.plan?.name ? ` · ${row.plan.name}` : ""}</span></p>) : <p className="monitor-empty">None</p>}</section>)}</div>}<button type="submit" disabled={!preview || !groups.eligible.length || Boolean(busy)}>{busy === "start" ? "Starting atomically..." : `Start day for ${groups.eligible.length} eligible athlete${groups.eligible.length === 1 ? "" : "s"}`}</button></form>
      : (session.is_simulated || session.simulated || roomState.meta?.session_is_simulated) ? <div className="training-day-active simulation"><div><span>Simulation active</span><h3>{session.label}</h3><p>The simulator owns this training day. Stop or restart it with the simulation controls rather than generating a real report here.</p></div><b>Simulation</b></div>
      : <div className="training-day-active"><div><span>Active training day</span><h3>{session.label}</h3><p>{roomState.participants?.length || 0} athletes · started {reportValue(session.started_at)}</p></div>{confirmEnd ? <div className="training-day-confirm" role="group" aria-label="Confirm end training day"><strong>End this training day and finalize its report?</strong><button className="workout-secondary" onClick={() => setConfirmEnd(false)} disabled={Boolean(busy)}>Cancel</button><button onClick={endDay} disabled={Boolean(busy)}>{busy === "end" ? "Ending..." : "Confirm end"}</button></div> : <button onClick={() => setConfirmEnd(true)} disabled={Boolean(busy)}>End training day</button>}</div>}
    {status && <p className="training-day-status" role="status">{status}</p>}{error && <p className="training-day-error" role="alert">{error}</p>}
  </section>;
}
