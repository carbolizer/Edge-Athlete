import { useState } from "react";
import { budgetReportRendering, buildTrainingDayPayload, orderedReportExercises, orderedReportPrescriptions, reportAthletes, reportSnapshot, reportSummary, reportValue, unfinishedRackNumbers } from "./trainingDay.js";

function ReportRep({ rep }) {
  return <li><span>Rep {rep.rep_number ?? rep.number ?? "--"}</span><b>{reportValue(rep.mean_velocity, " m/s mean")}</b><b>{reportValue(rep.peak_velocity, " m/s peak")}</b><b>{reportValue(rep.duration_ms, " ms")}</b></li>;
}

function ReportSet({ record, index }) {
    const { workoutSet, reps, totalReps } = record;
  return <article className="training-report-set"><header><span>{workoutSet.is_false_set ? "False set (excluded)" : `Set ${workoutSet.set_number ?? index + 1}`}</span><b>{reportValue(workoutSet.weight_lbs, " lbs")}</b><b>{reportValue(workoutSet.reps_completed ?? workoutSet.completed_reps, " reps")}</b></header>{reps.length ? <ol>{reps.map((rep, repIndex) => <ReportRep rep={rep} key={rep.id || rep.rep_number || repIndex} />)}</ol> : totalReps === 0 ? <p className="monitor-empty">{workoutSet.is_false_set ? "False set; excluded from completed work." : "No persisted rep measurements."}</p> : null}{reps.length < totalReps && <p className="training-report-truncation">Showing {reps.length} of {totalReps} persisted rep rows for this set. All rows remain in the saved report.</p>}</article>;
}

function ReportPrescription({ prescription, index }) {
  const exercises = prescription.exercises ? orderedReportExercises(prescription) : [prescription];
  return <article className="training-report-prescription"><header><span>Effective at day end</span><h5>{prescription.workout_name || prescription.workout?.name || prescription.name || (prescription.source === "legacy" ? "Legacy prescription" : `Workout ${index + 1}`)}</h5></header>{exercises.map((exercise, exerciseIndex) => {
    return <section key={exercise.id || exercise.position || exerciseIndex}><div className="training-report-target"><div><span>{exercise.position ?? exerciseIndex + 1}. {exercise.exercise || exercise.name || "Exercise"}</span><b>{reportValue(exercise.sets ?? exercise.target_sets)} sets x {reportValue(exercise.reps ?? exercise.target_reps)} reps</b></div><div><span>Target load</span><b>{reportValue(exercise.default_weight_lbs ?? exercise.weight_lbs ?? exercise.target_weight_lbs, " lbs")}</b></div><div><span>Velocity</span><b>{exercise.velocity_min === null || exercise.velocity_min === undefined ? "--" : `${exercise.velocity_min}-${exercise.velocity_max} m/s`}</b></div></div></section>;
  })}</article>;
}

export function GeneratedReport({ report }) {
  const snapshot = reportSnapshot(report);
  const athletes = reportAthletes(snapshot);
  const rendering = budgetReportRendering(athletes);
  const summary = reportSummary(snapshot);
  const session = snapshot.session || snapshot.training_day || {};
  const truncated = Object.entries(rendering.counts).filter(([, count]) => count.rendered < count.total);
  return <section className="training-report" aria-labelledby="generated-report-heading"><header><div><span>Generated report</span><h3 id="generated-report-heading">{session.label || report.label || "Training day complete"}</h3><p>{reportValue(session.started_at || report.started_at)} to {reportValue(session.ended_at || report.ended_at)}</p></div><b>Finalized</b></header><dl className="training-report-summary"><div><dt>Athletes</dt><dd>{reportValue(summary.athletes ?? summary.athlete_count ?? athletes.length)}</dd></div><div><dt>Completed sets</dt><dd>{reportValue(summary.completed_sets)}</dd></div><div><dt>Completed reps</dt><dd>{reportValue(summary.completed_reps)}</dd></div><div><dt>Average velocity</dt><dd>{reportValue(summary.average_velocity ?? summary.avg_velocity, " m/s")}</dd></div></dl>{truncated.length > 0 && <div className="training-report-budget" role="status"><strong>Immediate report view is bounded.</strong>{truncated.map(([label, count]) => <p key={label}>Showing {count.rendered.toLocaleString()} of {count.total.toLocaleString()} saved {label}. The finalized report retains all {count.total.toLocaleString()}.</p>)}</div>}<div className="training-report-athletes">{rendering.athletes.length ? rendering.athletes.map(({ entry, sets: completedSets, totalSets }, index) => {
    const athlete = entry.athlete || entry;
    const prescriptions = orderedReportPrescriptions(entry);
    return <section key={athlete.id || athlete.name || index}><header><span>Athlete</span><h4>{athlete.name || "Athlete unavailable"}</h4><b>{reportValue(totalSets, " set records")}</b></header>{prescriptions.length ? prescriptions.map((prescription, prescriptionIndex) => <ReportPrescription prescription={prescription} index={prescriptionIndex} key={prescription.id || prescription.position || prescriptionIndex} />) : <p className="monitor-empty">No effective prescription was recorded.</p>}<div className="training-report-results"><h5>Persisted set records and reps</h5>{completedSets.length ? completedSets.map((record, setIndex) => <ReportSet record={record} index={setIndex} key={record.workoutSet.id || setIndex} />) : totalSets === 0 ? <p className="monitor-empty">No persisted set records.</p> : <p className="training-report-truncation">This athlete’s {totalSets} saved set{totalSets === 1 ? " is" : "s are"} retained in the finalized report but omitted from the bounded immediate view.</p>}{completedSets.length < totalSets && completedSets.length > 0 && <p className="training-report-truncation">Showing {completedSets.length} of {totalSets} saved sets for this athlete. All sets remain in the finalized report.</p>}</div></section>;
  }) : <p className="monitor-empty">No athlete snapshots were generated.</p>}</div></section>;
}

export default function TrainingDayPanel({ roomState, athletes, accessToken, onLogout, refresh }) {
  const [label, setLabel] = useState("");
  const [selectedAthleteIds, setSelectedAthleteIds] = useState([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [generatedReport, setGeneratedReport] = useState(null);
  const session = roomState.session;
  const headers = { Accept: "application/json", Authorization: `Bearer ${accessToken}` };

  function toggleAthlete(id) {
    setSelectedAthleteIds((current) => current.includes(id) ? current.filter((athleteId) => athleteId !== id) : [...current, id]);
  }

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
      const response = await fetch("/api/sessions/", { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(buildTrainingDayPayload(label, selectedAthleteIds)) });
      const body = await parseResponse(response, "Training day could not be started.");
      if (body === null) return;
      setLabel("");
      setSelectedAthleteIds([]);
      setGeneratedReport(null);
      setStatus("Training day started.");
      await refresh({ preserveSnapshot: true, forceAfterInFlight: true });
    } catch (startError) {
      setError(startError.message || "Training day could not be started.");
    } finally {
      setBusy("");
    }
  }

  async function endDay() {
    setBusy("end");
    setError("");
    setStatus("");
    try {
      const response = await fetch(`/api/sessions/${session.id}/end/`, { method: "POST", headers });
      const body = await parseResponse(response, "Training day could not be ended.");
      if (body === null) return;
      setGeneratedReport(body.report || body);
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
    {!session ? <form className="training-day-start" onSubmit={startDay}><header><div><span>Training day</span><h3>Open the room</h3><p>Name today’s training and select every participating athlete.</p></div><b>Not active</b></header><label>Training day label<input value={label} onChange={(event) => setLabel(event.target.value)} maxLength="255" required disabled={Boolean(busy)} /></label><fieldset><legend>Athletes</legend><div>{athletes.map((athlete) => <label key={athlete.id}><input type="checkbox" checked={selectedAthleteIds.includes(athlete.id)} onChange={() => toggleAthlete(athlete.id)} disabled={Boolean(busy)} /><span>{athlete.name}</span></label>)}</div></fieldset><button type="submit" disabled={!selectedAthleteIds.length || Boolean(busy)}>{busy === "start" ? "Starting..." : "Start training day"}</button></form>
      : (session.is_simulated || session.simulated || roomState.meta?.session_is_simulated) ? <div className="training-day-active simulation"><div><span>Simulation active</span><h3>{session.label}</h3><p>The simulator owns this training day. Stop or restart it with the simulation controls rather than generating a real report here.</p></div><b>Simulation</b></div>
      : <div className="training-day-active"><div><span>Active training day</span><h3>{session.label}</h3><p>{roomState.participants?.length || 0} athletes · started {reportValue(session.started_at)}</p></div>{confirmEnd ? <div className="training-day-confirm" role="group" aria-label="Confirm end training day"><strong>End this training day and finalize its report?</strong><button className="workout-secondary" onClick={() => setConfirmEnd(false)} disabled={Boolean(busy)}>Cancel</button><button onClick={endDay} disabled={Boolean(busy)}>{busy === "end" ? "Ending..." : "Confirm end"}</button></div> : <button onClick={() => setConfirmEnd(true)} disabled={Boolean(busy)}>End training day</button>}</div>}
    {status && <p className="training-day-status" role="status">{status}</p>}{error && <p className="training-day-error" role="alert">{error}</p>}
  </section>;
}
