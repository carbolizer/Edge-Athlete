// TrainingDayPanel.jsx — OPENING a day of training, and the report shape.
//
// ⚠️ THIS FILE USED TO DO BOTH HALVES. It opened a day and it closed one, and
// the closing half now lives in coach/SessionWidget.jsx. The split is not
// tidying: starting a day and ending a day are done at different moments, from
// different screens, by a coach thinking about different things.
//
//   START — here, in SESSION. Naming today's training and ticking who is in it
//           is the act of opening the room you are about to stand in.
//   END   — the strip above all three states. Ending is something a coach does
//           while looking at anything, so it has to be reachable from anywhere.
//
// Two ways to open a day, and they live in DIFFERENT STATES because they are
// different decisions:
//
//   OpenDayFromScratch → PLANNING. No block behind it. Name it, tick a roster,
//                  go. Deciding that today happens at all is a planning act, and
//                  this route (`POST /api/sessions/`) opens the room the instant
//                  it succeeds — there is no staged step to reach SESSION with.
//                  It has to live where a coach can always get to it, including
//                  in a gym whose calendar is empty.
//   StartStagedDay → SESSION. The day already exists, set up from the calendar
//                  days ago with its roster and plan attached (P14's nullable
//                  `started_at`). One button, no typing.
//
// ⚠️ A STAGED DAY IS NOT LIVE. It holds no racks and captures no check-ins until
// it is started (canon D18). That is the whole reason it can be set up early,
// and the screen must never present one as if the room were already open.
//
// What is still here besides starting: GeneratedReport, the frozen record of a
// finished day, which ReportsWorkspace also renders. It is deliberately BOUNDED
// — a busy day holds thousands of reps, and mounting them all locks up a tablet
// at the exact moment a coach wants to read the summary. It renders a slice and
// says so; the saved report always keeps every row.

import { useState } from "react";
import { budgetReportRendering, buildEndDayPayload, buildTrainingDayPayload, endedDayMessage, endTimeChoices, orderedReportExercises, orderedReportPrescriptions, reportAthletes, reportSnapshot, reportSummary, reportValue, timestampLabel, unfinishedRackNumbers } from "./trainingDay.js";
import { scheduleDayLabel } from "./schedule.js";

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

export function OpenDayFromScratch({ athletes, accessToken, onLogout, refresh }) {
  const [label, setLabel] = useState("");
  const [selectedAthleteIds, setSelectedAthleteIds] = useState([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  // The day that blocked this one, when a start hits 409. Held rather than just
  // reported, so it can be resolved without retyping the form.
  const [conflict, setConflict] = useState(null);
  const [conflictEndedAt, setConflictEndedAt] = useState("");
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
      setStatus(`${endedDayMessage(ended)} “${body.label}” is now open.`);
      await refresh({ preserveSnapshot: true, forceAfterInFlight: true });
    } catch (resolveError) {
      setError(resolveError.message || "The previous day could not be ended.");
    } finally {
      setBusy("");
    }
  }

  return <section className="training-day-shell" aria-label="Open a training day">
    <form className="training-day-start" onSubmit={startDay}><header><div><span>Unplanned day</span><h3>Open the room now</h3><p>For training with no block behind it. Name it, tick who is in, and the room opens immediately — there is no staged step.</p></div><b>Starts at once</b></header><label>Training day label<input value={label} onChange={(event) => setLabel(event.target.value)} maxLength="255" required disabled={Boolean(busy)} /></label><fieldset><legend>Athletes</legend><div>{athletes.map((athlete) => <label key={athlete.id}><input type="checkbox" checked={selectedAthleteIds.includes(athlete.id)} onChange={() => toggleAthlete(athlete.id)} disabled={Boolean(busy)} /><span>{athlete.name}</span></label>)}</div></fieldset><button type="submit" disabled={!selectedAthleteIds.length || Boolean(busy)}>{busy === "start" ? "Starting..." : "Start training day"}</button>{conflict && <ConflictPrompt conflict={conflict} endedAt={conflictEndedAt} onEndedAtChange={setConflictEndedAt} newDayLabel={label} busy={busy} onCancel={() => { setConflict(null); setConflictEndedAt(""); setError(""); }} onConfirm={endConflictAndStart} />}</form>
    {status && <p className="training-day-status" role="status">{status}</p>}{error && <p className="training-day-error" role="alert">{error}</p>}
  </section>;
}

/*
 * StartStagedDay — SESSION's half. Days that already exist and have not run.
 *
 * A coach set Thursday up on Tuesday from the calendar; its roster and its plan
 * were attached then. Starting it is one button and no typing, because every
 * decision was already made. That is the entire difference between this and
 * OpenDayFromScratch above.
 *
 * ⚠️ NONE OF THESE ARE LIVE. A staged day holds no racks and captures no
 * check-ins until it is started (canon D18) — that is precisely why it can be
 * set up days early. The copy says "nothing is holding the racks" for that
 * reason: a coach must never read this list as the room already being open.
 */
export function StartStagedDay({ slots, accessToken, onLogout, refresh, onStarted }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const headers = { Accept: "application/json", Authorization: `Bearer ${accessToken}` };

  // Its own route rather than a PATCH: `PATCH sessions/{id}/` with an empty body
  // already means "END the day now" (canon R2), so start could never have been a
  // PATCH without the two meaning opposite things through one door.
  async function start(slot) {
    setBusy(`staged-${slot.id}`);
    setError("");
    try {
      const response = await fetch(`/api/sessions/${slot.session}/start/`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: "{}",
      });
      if (response.status === 401 || response.status === 403) { onLogout(); return; }
      const body = await response.json().catch(() => ({}));
      // 409 is another day already running. The server names it, so say which.
      if (!response.ok) throw new Error(body.detail || "That day could not be started.");
      await refresh({ preserveSnapshot: true, forceAfterInFlight: true });
      onStarted?.();
    } catch (startError) {
      setError(startError.message || "That day could not be started.");
    } finally {
      setBusy("");
    }
  }

  if (!slots.length) return null;

  return <div className="training-day-staged">
    <header><div><span>Ready to start</span><h3>Set up and waiting</h3><p>Roster and plan already attached. Nothing is holding the racks until you start one.</p></div><b>{slots.length} ready</b></header>
    {slots.map((slot) => <article key={slot.id}>
      <div><h4>{slot.workout_name}</h4><p>{slot.group_name} · {scheduleDayLabel(slot.date)}</p></div>
      <button type="button" disabled={Boolean(busy)} onClick={() => start(slot)}>
        {busy === `staged-${slot.id}` ? "Starting..." : "Start day"}
      </button>
    </article>)}
    {error && <p className="training-day-error" role="alert">{error}</p>}
  </div>;
}
