// TrainingDayPanel.jsx — opening and closing a day of training.
//
// Two buttons, and the second one is permanent.
//
//   START   Name today's training, tick who is in it, and the room is open.
//           Racks only accept lifting once a day is running.
//
//   END     Closes the day and FREEZES it into a report that is never edited
//           again. It also recalculates everyone's reference maxes from what
//           they actually lifted, which is why it asks for confirmation first —
//           this is the moment today stops being editable and starts being
//           history.
//
// Ending is a PATCH on the session rather than a POST to an end/ route, because
// "end the day" is just "set its end time" and that endpoint already did that.
// It answers with a POINTER to the finished report, so we fetch the report
// itself before rendering it below.
//
// ⚠️ WHY THE CONFIRMATION NAMES THE DAY. This panel once looked broken: pressing
// End training day redrew the same active day and the same button, every time.
// It was working perfectly — the database held several unended sessions, and
// ending the newest instantly promoted the next one into its place. Only ONE day
// can be open now (the server refuses a second), and the server also answers
// with which day it just ended, so the confirmation can say so by name instead
// of leaving the coach to infer it from a screen that may look identical.
//
// The report view is deliberately BOUNDED. A busy day holds thousands of
// individual reps, and mounting them all locks up a tablet at the exact moment a
// coach wants to read the summary. So it renders a slice and says so — the saved
// report always keeps every row. Nothing here can shrink what was stored; the
// limit is about what the screen can hold.

import { useState } from "react";
import { budgetReportRendering, buildEndDayPayload, buildTrainingDayPayload, endedDayMessage, endTimeChoices, orderedReportExercises, orderedReportPrescriptions, reportAthletes, reportSnapshot, reportSummary, reportValue, timestampLabel, unfinishedRackNumbers } from "./trainingDay.js";

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
  return <section className="training-report" aria-labelledby="generated-report-heading"><header><div><span>Generated report</span><h3 id="generated-report-heading">{session.label || report.label || "Training day complete"}</h3><p>{timestampLabel(session.started_at || report.started_at)} to {timestampLabel(session.ended_at || report.ended_at)}</p></div><b>Finalized</b></header><dl className="training-report-summary"><div><dt>Athletes</dt><dd>{reportValue(summary.athletes ?? summary.athlete_count ?? athletes.length)}</dd></div><div><dt>Completed sets</dt><dd>{reportValue(summary.completed_sets)}</dd></div><div><dt>Completed reps</dt><dd>{reportValue(summary.completed_reps)}</dd></div><div><dt>Average velocity</dt><dd>{reportValue(summary.average_velocity ?? summary.avg_velocity, " m/s")}</dd></div></dl>{truncated.length > 0 && <div className="training-report-budget" role="status"><strong>Immediate report view is bounded.</strong>{truncated.map(([label, count]) => <p key={label}>Showing {count.rendered.toLocaleString()} of {count.total.toLocaleString()} saved {label}. The finalized report retains all {count.total.toLocaleString()}.</p>)}</div>}<div className="training-report-athletes">{rendering.athletes.length ? rendering.athletes.map(({ entry, sets: completedSets, totalSets }, index) => {
    const athlete = entry.athlete || entry;
    const prescriptions = orderedReportPrescriptions(entry);
    return <section key={athlete.id || athlete.name || index}><header><span>Athlete</span><h4>{athlete.name || "Athlete unavailable"}</h4><b>{reportValue(totalSets, " set records")}</b></header>{prescriptions.length ? prescriptions.map((prescription, prescriptionIndex) => <ReportPrescription prescription={prescription} index={prescriptionIndex} key={prescription.id || prescription.position || prescriptionIndex} />) : <p className="monitor-empty">No effective prescription was recorded.</p>}<div className="training-report-results"><h5>Persisted set records and reps</h5>{completedSets.length ? completedSets.map((record, setIndex) => <ReportSet record={record} index={setIndex} key={record.workoutSet.id || setIndex} />) : totalSets === 0 ? <p className="monitor-empty">No persisted set records.</p> : <p className="training-report-truncation">This athlete’s {totalSets} saved set{totalSets === 1 ? " is" : "s are"} retained in the finalized report but omitted from the bounded immediate view.</p>}{completedSets.length < totalSets && completedSets.length > 0 && <p className="training-report-truncation">Showing {completedSets.length} of {totalSets} saved sets for this athlete. All sets remain in the finalized report.</p>}</div></section>;
  }) : <p className="monitor-empty">No athlete snapshots were generated.</p>}</div></section>;
}

// "That day is still open." Shown when starting a day comes back 409.
//
// Its own component so it can be render-tested — it only ever appears in
// response to a server conflict, which no prop can reproduce from outside, and
// it is the piece a coach meets in the least patient moment of their day.
//
// It resolves the problem HERE rather than sending the coach to the active-day
// panel, because the two actions are one intention: the label and roster they
// just typed are still what they want.
export function ConflictPrompt({ conflict, endedAt, onEndedAtChange, newDayLabel, onCancel, onConfirm, busy }) {
  const openedAt = conflict.started_at ? ` It opened ${timestampLabel(conflict.started_at)}.` : "";
  return <div className="training-day-conflict" role="alertdialog" aria-label="A training day is already open">
    <strong>“{conflict.label}” is still open.</strong>
    <p>Only one training day can run at a time. End that one and this day starts straight after — your label and roster are kept.{openedAt}</p>
    <label className="training-day-end-time">End “{conflict.label}” at
      <select value={endedAt} onChange={(event) => onEndedAtChange(event.target.value)} disabled={Boolean(busy)}>
        {endTimeChoices(conflict.started_at).map((choice) => <option key={choice.value || "now"} value={choice.value}>{choice.label}</option>)}
      </select>
      <small>{endedAt ? "Its report will record this time." : "Ends it as of right now."}</small>
    </label>
    <div className="training-day-conflict-actions">
      <button type="button" className="workout-secondary" onClick={onCancel} disabled={Boolean(busy)}>Cancel</button>
      <button type="button" onClick={onConfirm} disabled={Boolean(busy)}>{busy === "resolve" ? "Ending and starting..." : `End it and start “${newDayLabel.trim() || "my day"}”`}</button>
    </div>
  </div>;
}

export default function TrainingDayPanel({ roomState, athletes, accessToken, onLogout, refresh }) {
  const [label, setLabel] = useState("");
  const [selectedAthleteIds, setSelectedAthleteIds] = useState([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [confirmEnd, setConfirmEnd] = useState(false);
  // A corrected end time, only ever typed for a day that outlived a reboot.
  // Empty means "end it now", which is the normal case.
  const [endedAtOverride, setEndedAtOverride] = useState("");
  // The day that blocked this one, when a start hits 409. Held rather than just
  // reported, so it can be resolved without retyping the form.
  const [conflict, setConflict] = useState(null);
  const [conflictEndedAt, setConflictEndedAt] = useState("");
  const [generatedReport, setGeneratedReport] = useState(null);
  const session = roomState.session;
  const staleDay = Boolean(session?.opened_on_a_previous_day);
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

  // Actually create the day. Split out from the submit handler so the conflict
  // prompt can reuse it after closing the day that was in the way, instead of
  // duplicating the request or asking the coach to fill the form in again.
  async function postNewDay() {
    const response = await fetch("/api/sessions/", { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(buildTrainingDayPayload(label, selectedAthleteIds)) });

    // 409 means a day is already open. Rather than only reporting it, hold the
    // details so the coach can resolve it in place — see the conflict prompt.
    // Reaching this usually means another tablet opened a day, or the base
    // station restarted with yesterday's still running.
    if (response.status === 409) {
      const body = await response.json().catch(() => ({}));
      return { conflict: body.open_session || {}, detail: body.detail };
    }

    const body = await parseResponse(response, "Training day could not be started.");
    return { body };
  }

  async function startDay(event) {
    event.preventDefault();
    setBusy("start");
    setError("");
    setStatus("");
    setConflict(null);
    try {
      const { conflict, detail, body } = await postNewDay();
      if (conflict) {
        // Keep the label and roster exactly as typed — the coach still wants
        // this day, they just have to close the previous one first.
        setConflict(conflict);
        setConflictEndedAt("");
        setError(detail || "A training day is already open.");
        return;
      }
      if (body === null || body === undefined) return;
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

  // "End the day that's in the way, then start mine." Two requests, deliberately
  // in this order and deliberately not wrapped into one endpoint: ending a day
  // freezes an immutable report and recalculates reference maxes, so it is not
  // something to do as a side effect of a create call. If the end fails we stop
  // and say so — starting the new day anyway would leave two open at once, which
  // is the exact thing the guard exists to prevent.
  async function endConflictAndStart() {
    setBusy("resolve");
    setError("");
    setStatus("");
    try {
      const ending = await fetch(`/api/sessions/${conflict.id}/`, {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(buildEndDayPayload(conflictEndedAt)),
      });
      const ended = await parseResponse(ending, `'${conflict.label}' could not be ended.`);
      if (ended === null) return;

      const { conflict: stillBlocked, detail, body } = await postNewDay();
      if (stillBlocked) {
        // Somebody else opened one in the gap between our two calls.
        setConflict(stillBlocked);
        setConflictEndedAt("");
        setError(detail || "Another training day was opened in the meantime.");
        return;
      }
      if (body === null || body === undefined) return;

      setConflict(null);
      setConflictEndedAt("");
      setLabel("");
      setSelectedAthleteIds([]);
      setGeneratedReport(null);
      setStatus(`${endedDayMessage(ended)} “${body.label}” is now open.`);
      await refresh({ preserveSnapshot: true, forceAfterInFlight: true });
    } catch (resolveError) {
      setError(resolveError.message || "The previous day could not be ended.");
    } finally {
      setBusy("");
    }
  }

  async function endDay() {
    setBusy("end");
    setError("");
    setStatus("");
    try {
      // Ending a day is a PATCH on the session itself, not a POST to an end/
      // route (merge canon R2): "end the day" is "set its end time", and that
      // endpoint already did that. A PATCH with no ended_at means "end it now".
      const response = await fetch(`/api/sessions/${session.id}/`, {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        // An empty body means "end it now", which is right almost always. A
        // corrected time is for the power-cut case: the base station comes back
        // with the day still open, and the honest end time is when the room
        // actually emptied — not when someone next managed to log in.
        body: JSON.stringify(buildEndDayPayload(endedAtOverride)),
      });
      const body = await parseResponse(response, "Training day could not be ended.");
      if (body === null) return;
      // The PATCH answers with a POINTER to the finished report, not the report
      // itself, so fetch the full thing before rendering it. If that second call
      // fails the day still ended — show it as ended rather than as an error.
      const reportId = body.daily_report?.id;
      let report = null;
      if (reportId) {
        report = await fetch(`/api/reports/${reportId}/`, { headers })
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null);
      }
      setGeneratedReport(report);
      setConfirmEnd(false);
      setEndedAtOverride("");
      setStatus(endedDayMessage(body));
      await refresh({ preserveSnapshot: true, forceAfterInFlight: true });
    } catch (endError) {
      setError(endError.message || "Training day could not be ended.");
    } finally {
      setBusy("");
    }
  }

  return <section className="training-day-shell" aria-label="Training day controls">
    {generatedReport && <GeneratedReport report={generatedReport} />}
    {!session ? <form className="training-day-start" onSubmit={startDay}><header><div><span>Training day</span><h3>Open the room</h3><p>Name today’s training and select every participating athlete.</p></div><b>Not active</b></header><label>Training day label<input value={label} onChange={(event) => setLabel(event.target.value)} maxLength="255" required disabled={Boolean(busy)} /></label><fieldset><legend>Athletes</legend><div>{athletes.map((athlete) => <label key={athlete.id}><input type="checkbox" checked={selectedAthleteIds.includes(athlete.id)} onChange={() => toggleAthlete(athlete.id)} disabled={Boolean(busy)} /><span>{athlete.name}</span></label>)}</div></fieldset><button type="submit" disabled={!selectedAthleteIds.length || Boolean(busy)}>{busy === "start" ? "Starting..." : "Start training day"}</button>{conflict && <ConflictPrompt conflict={conflict} endedAt={conflictEndedAt} onEndedAtChange={setConflictEndedAt} newDayLabel={label} busy={busy} onCancel={() => { setConflict(null); setConflictEndedAt(""); setError(""); }} onConfirm={endConflictAndStart} />}</form>
      : (session.is_simulated || session.simulated || roomState.meta?.session_is_simulated) ? <div className="training-day-active simulation"><div><span>Simulation active</span><h3>{session.label}</h3><p>The simulator owns this training day. Stop or restart it with the simulation controls rather than generating a real report here.</p></div><b>Simulation</b></div>
      : <div className={staleDay ? "training-day-active is-stale" : "training-day-active"}><div><span>{staleDay ? "Still open from an earlier day" : "Active training day"}</span><h3>{session.label}</h3><p>{roomState.participants?.length || 0} athletes · started {timestampLabel(session.started_at)}</p>{staleDay && <p className="training-day-stale-note">This day has been open since before today — most likely the base station restarted before anyone ended it. <b>Nothing was lost;</b> every set is saved. End it below, and set the time the room actually emptied so the report reads true.</p>}</div>{confirmEnd ? <div className="training-day-confirm" role="group" aria-label="Confirm end training day"><strong>End this training day and finalize its report?</strong><label className="training-day-end-time">Ended at <select value={endedAtOverride} onChange={(event) => setEndedAtOverride(event.target.value)} disabled={Boolean(busy)}>{endTimeChoices(session.started_at).map((choice) => <option key={choice.value || "now"} value={choice.value}>{choice.label}</option>)}</select><small>{endedAtOverride ? "The report will record this time." : "Ends the day as of right now."}</small></label><button className="workout-secondary" onClick={() => { setConfirmEnd(false); setEndedAtOverride(""); }} disabled={Boolean(busy)}>Cancel</button><button onClick={endDay} disabled={Boolean(busy)}>{busy === "end" ? "Ending..." : "Confirm end"}</button></div> : <button onClick={() => setConfirmEnd(true)} disabled={Boolean(busy)}>End training day</button>}</div>}
    {status && <p className="training-day-status" role="status">{status}</p>}{error && <p className="training-day-error" role="alert">{error}</p>}
  </section>;
}
