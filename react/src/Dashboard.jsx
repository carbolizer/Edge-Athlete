/*
 * Provides two production monitoring surfaces: a room-scale athlete scoreboard
 * and a protected coach tablet. Both reconcile saved PostgreSQL state through MQTT revisions.
 */
import { useEffect, useState } from "react";
import "./App.css";
import useLiveRoomState from "./useLiveRoomState.js";
import { compareReps, groupHistorySets } from "./historyView.js";
import WorkoutCatalog from "./WorkoutCatalog.jsx";
import AthleteWorkoutPlanning from "./AthleteWorkoutPlanning.jsx";
import TrainingDayPanel from "./TrainingDayPanel.jsx";
import ReportsWorkspace from "./ReportsWorkspace.jsx";
import { sameOriginPath } from "./workoutCatalog.js";
import { buildRackAssignmentPayload } from "./rackState.js";
import { coachRackView, wallDisplayState, wallMovementView } from "./dashboardView.js";

function velocity(value) {
  return value === null || value === undefined ? "--" : Number(value).toFixed(2);
}

function signed(value, digits = 2) {
  if (value === null || value === undefined) return "--";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(digits)}`;
}

function timeLabel(value) {
  if (!value) return "--";
  return new Date(value).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function ConnectionBadge({ connectionState, requestState }) {
  const state = requestState === "stale" ? "stale" : connectionState;
  const labels = {
    live: "Live",
    connecting: "Connecting",
    reconnecting: "Reconnecting",
    stale: "Snapshot stale",
    idle: "Offline",
  };
  return (
    <div className={`monitor-connection ${state}`} role="status">
      <i />
      <span>{labels[state] || "Connecting"}</span>
    </div>
  );
}

function StatePanel({ title, body, action, actionLabel = "Retry" }) {
  return (
    <section className="monitor-state-panel">
      <span className="monitor-state-mark">EA</span>
      <h2>{title}</h2>
      <p>{body}</p>
      {action && <button onClick={action}>{actionLabel}</button>}
    </section>
  );
}

function WallRackTile({ rack }) {
  const workoutSet = rack.latest_set;
  return (
    <article className={`wall-rack-tile ${rack.status_color}`}>
      <header>
        <span>Rack {rack.rack_number}</span>
        <b>{rack.status}</b>
      </header>
      {workoutSet ? (
        <>
          <div className="wall-rack-athlete">
            <h3>{workoutSet.athlete.name}</h3>
            <p>{workoutSet.exercise} · Set {workoutSet.set_number}</p>
          </div>
          <div className="wall-rack-result">
            <strong>{velocity(workoutSet.avg_velocity)}</strong>
            <span>m/s average</span>
          </div>
          <footer>
            <span>{workoutSet.reps_completed} reps</span>
            <span>{velocity(workoutSet.peak_velocity)} peak</span>
          </footer>
        </>
      ) : (
        <div className="wall-rack-waiting">
          <h3>Ready</h3>
          <p>Waiting for a completed set</p>
        </div>
      )}
    </article>
  );
}

function WallLeaderboard({ rows, movementName }) {
  return (
    <section className="wall-board-card wall-leaders">
      <div className="wall-card-title"><span>{movementName} leaders</span><b>Best set avg</b></div>
      {rows.length === 0 && <p className="monitor-empty">Complete a set to begin the leaderboard.</p>}
      {rows.slice(0, 5).map((row) => (
        <div className="wall-leader" key={`${row.rank}-${row.athlete.name}`}>
          <b>{String(row.rank).padStart(2, "0")}</b>
          <strong>{row.athlete.name}</strong>
          <span>{velocity(row.best_avg_velocity)} <small>m/s</small></span>
        </div>
      ))}
    </section>
  );
}

function WallInsights({ insights }) {
  return (
    <section className="wall-insight-stack">
      {insights.map((insight) => (
        <article className="wall-insight" key={insight.type}>
          <span>{insight.label}</span>
          <strong>{insight.athlete_name}</strong>
          <b>{Number(insight.value).toFixed(insight.unit === "reps" ? 0 : 2)} <small>{insight.unit}</small></b>
        </article>
      ))}
    </section>
  );
}

function WallView({ monitor }) {
  const { requestState, connectionState, refresh } = monitor;
  const display = wallDisplayState(monitor);
  if (display.status === "loading") {
    return <div className="monitor wall-monitor"><StatePanel title="Opening the weight room" body="Loading the current session from the base station." /></div>;
  }
  if (display.status === "unavailable") {
    return <div className="monitor wall-monitor"><StatePanel title="Live scoreboard unavailable" body={display.message} action={refresh} /></div>;
  }
  if (display.status === "empty") {
    return <div className="monitor wall-monitor"><StatePanel title="The room is ready" body="The scoreboard will begin when a coach starts a training session." action={refresh} actionLabel="Check again" /></div>;
  }

  const roomState = display.roomState;
  const movement = wallMovementView(roomState);
  return (
    <main className="monitor wall-monitor">
      <header className="wall-topbar">
        <div className="monitor-brand"><b>EA</b><span>Edge Athlete</span></div>
        <div className="wall-session">
          <span>Now training</span>
          <h1>{roomState.session.label}</h1>
        </div>
        <ConnectionBadge connectionState={connectionState} requestState={requestState} />
      </header>

      <section className={`wall-movement-board ${movement.waiting ? "waiting" : ""}`}>
        <header><span>Current room movement</span><h2>{movement.name}</h2><p>{movement.detail}</p></header>
        {movement.waiting
          ? <div className="wall-movement-wait"><b>READY</b><span>Signed-in athlete progress chooses the movement automatically.</span></div>
          : <div className="wall-movement-grid"><WallLeaderboard rows={movement.rows} movementName={movement.name} /><WallInsights insights={roomState.insights} /></div>}
      </section>

      {(roomState.truncated.racks || roomState.truncated.leaderboard) && (
        <div className="wall-truncation">Additional room results are available in the coach view.</div>
      )}
      <footer className="wall-footer">
        <span>Saved results update automatically after each set</span>
        <span>Snapshot {timeLabel(roomState.generated_at)} · Revision {roomState.revision}</span>
      </footer>
    </main>
  );
}

function CoachLogin({ onLogin, error, busy }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  return (
    <main className="monitor coach-login-screen">
      <section className="coach-login-card">
        <div className="monitor-brand"><b>EA</b><span>Edge Athlete</span></div>
        <p className="coach-eyebrow">Coach workspace</p>
        <h1>See the whole room.<br />Coach the next rep.</h1>
        <p>Live saved performance, rack comparisons, and hardware health in one focused view.</p>
        <form onSubmit={(event) => { event.preventDefault(); onLogin(username, password); }}>
          <label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label>
          <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required /></label>
          {error && <p className="coach-login-error" role="alert">{error}</p>}
          <button disabled={busy}>{busy ? "Signing in..." : "Open coach view"}</button>
        </form>
      </section>
      <aside className="coach-login-art"><span>VELOCITY</span><strong>0.86</strong><b>m/s</b></aside>
    </main>
  );
}

function CoachRackButton({ rack, selected, onSelect }) {
  const view = coachRackView(rack);
  return (
    <button className={`coach-rack-row ${selected ? "selected" : ""}`} aria-pressed={selected} onClick={onSelect}>
      <i className={rack.status_color} />
      <span><b>Rack {rack.rack_number}</b><small>{view.athleteName} · {view.movementName}</small></span>
      <strong>{velocity(view.latestResult?.avg_velocity)}</strong>
    </button>
  );
}

function RepChart({ workoutSet }) {
  const reps = workoutSet.reps || [];
  const max = Math.max(1, ...reps.map((rep) => rep.mean_velocity));
  return (
    <section className="coach-panel coach-rep-panel">
      <header><div><span>Saved rep profile</span><h3>Mean velocity by rep</h3></div><b>m/s</b></header>
      {reps.length === 0 ? <p className="monitor-empty">No saved reps for this set.</p> : (
        <div className="coach-rep-chart">
          {reps.map((rep) => (
            <div className="coach-rep-bar" key={rep.rep_number}>
              <strong>{velocity(rep.mean_velocity)}</strong>
              <div><i className={rep.velocity_color} style={{ height: `${Math.max(8, rep.mean_velocity / max * 100)}%` }} /></div>
              <span>R{rep.rep_number}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function MeasuredInsights({ workoutSet }) {
  const insight = workoutSet.measured_insights;
  const change = insight.avg_velocity_change_percent;
  return (
    <section className="coach-panel coach-measured-panel">
      <header><div><span>Measured set signals</span><h3>What changed</h3></div></header>
      <div className="coach-insight-grid">
        <div><span>First→last change</span><strong className={insight.velocity_loss_percent <= 0 ? "positive" : "negative"}>{insight.velocity_loss_percent === null ? "--" : `${signed(-insight.velocity_loss_percent, 1)}%`}</strong><small>mean rep velocity</small></div>
        <div><span>Vs previous set</span><strong className={change >= 0 ? "positive" : "negative"}>{change === null ? "--" : `${signed(change, 1)}%`}</strong><small>average velocity</small></div>
        <div><span>Rep range</span><strong>{velocity(insight.rep_velocity_range)}</strong><small>m/s spread</small></div>
        <div><span>Mean rep time</span><strong>{insight.mean_rep_duration_ms === null ? "--" : `${Math.round(insight.mean_rep_duration_ms)} ms`}</strong><small>saved duration</small></div>
      </div>
      {workoutSet.target_zone && (
        <div className="coach-zone-row">
          <span><i className="red" />Below target <b>{insight.reps_below_zone}</b></span>
          <span><i className="green" />In target <b>{insight.reps_in_zone}</b></span>
          <span><i className="yellow" />Above target <b>{insight.reps_above_zone}</b></span>
        </div>
      )}
    </section>
  );
}

function CoachHardware({ rack }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(timer);
  }, []);
  return (
    <section className="coach-panel coach-hardware-panel">
      <header><div><span>Rack health</span><h3>Connected hardware</h3></div>{rack.assignment_conflict && <b className="coach-warning">Conflict</b>}</header>
      {rack.nodes.length === 0 && <p className="monitor-empty">No sensor node assigned.</p>}
      {rack.nodes.map((node) => {
        const stale = node.is_stale || !node.last_seen || now - new Date(node.last_seen).getTime() > 15_000;
        return (
          <div className="coach-node" key={node.node_id}>
            <i className={stale ? "stale" : "online"} />
            <span><strong>{node.node_id}</strong><small>{stale ? "Pulse overdue" : `Seen ${timeLabel(node.last_seen)}`}</small></span>
            <b>{node.battery_level ?? "--"}%</b>
          </div>
        );
      })}
      {rack.nodes_truncated && <p className="coach-truncation">Additional nodes are not shown.</p>}
      <p className="coach-screen-count">{rack.screen_count} screen{rack.screen_count === 1 ? "" : "s"} assigned</p>
    </section>
  );
}

function AthleteSummaryTab({ context }) {
  if (!context) return <StatePanel title="Choose an athlete" body="Select an athlete to load their saved performance context." />;
  return <div className="context-tab-content">
    <section className="context-athlete-hero"><div><span>Athlete overview</span><h2>{context.athlete.name}</h2><p>History since {new Date(context.athlete.created_at).toLocaleDateString()}</p></div><div className="context-summary-grid">
      <div><span>Completed sets</span><strong>{context.summary.completed_sets}</strong></div><div><span>Total reps</span><strong>{context.summary.completed_reps}</strong></div><div><span>Best set avg</span><strong>{velocity(context.summary.best_average)} <small>m/s</small></strong></div><div><span>Highest peak</span><strong>{velocity(context.summary.highest_peak)} <small>m/s</small></strong></div><div><span>Heaviest load</span><strong>{context.summary.heaviest_weight ?? "--"} <small>lbs</small></strong></div>
    </div></section>
    <section className="context-section"><header><span>Exercise memory</span><h3>Performance by movement</h3></header><div className="context-exercise-grid">{context.exercise_summaries.map((row) => <article key={row.exercise}><span>{row.exercise}</span><strong>{velocity(row.best_average)} <small>m/s best avg</small></strong><dl><div><dt>Sets</dt><dd>{row.completed_sets}</dd></div><div><dt>Reps</dt><dd>{row.completed_reps}</dd></div><div><dt>Load high</dt><dd>{row.heaviest_weight ?? "--"} lb</dd></div></dl></article>)}</div></section>
  </div>;
}

function historyDayLabel(value) {
  const date = new Date(value);
  const calendarLabel = date.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return `Today · ${calendarLabel}`;
  if (date.toDateString() === yesterday.toDateString()) return `Yesterday · ${calendarLabel}`;
  return calendarLabel;
}

function RepComparison({ workoutSet }) {
  const reps = compareReps(workoutSet);
  const maxVelocity = Math.max(1, ...reps.map((rep) => rep.mean_velocity));
  if (reps.length === 0) return <div className="history-rep-detail" id={`history-set-${workoutSet.id}`}><p className="monitor-empty">No rep-level readings were saved for this set.</p></div>;
  return <div className="history-rep-detail" id={`history-set-${workoutSet.id}`}>
    <div className="history-rep-detail-title"><div><span>Rep comparison</span><strong>{workoutSet.exercise} · Set {workoutSet.set_number}</strong></div><p>Changes compare mean velocity in m/s.</p></div>
    {workoutSet.reps_truncated && <div className="context-notice">Showing the first 100 saved reps for this set.</div>}
    <div className="history-rep-table-wrap"><table className="history-rep-table">
      <caption>Rep comparison for {workoutSet.exercise}, set {workoutSet.set_number}</caption>
      <thead><tr><th scope="col">Rep</th><th scope="col">Mean velocity</th><th scope="col">Vs previous</th><th scope="col">Vs set avg</th><th scope="col">Peak</th><th scope="col">Duration</th></tr></thead>
      <tbody>{reps.map((rep) => <tr key={rep.rep_number}>
        <td><b>R{rep.rep_number}</b></td>
        <td><div className="history-rep-velocity"><strong>{velocity(rep.mean_velocity)}</strong><i><span style={{ width: `${Math.max(6, rep.mean_velocity / maxVelocity * 100)}%` }} /></i></div></td>
        <td className={rep.changeFromPrevious === null ? "" : rep.changeFromPrevious >= 0 ? "positive" : "negative"}>{signed(rep.changeFromPrevious)}</td>
        <td className={rep.changeFromAverage === null ? "" : rep.changeFromAverage >= 0 ? "positive" : "negative"}>{signed(rep.changeFromAverage)}</td>
        <td>{velocity(rep.peak_velocity)}</td><td>{rep.duration_ms} ms</td>
      </tr>)}</tbody>
    </table></div>
  </div>;
}

function HistorySetCard({ workoutSet, expanded, onToggle }) {
  return <article className={`history-set-card ${expanded ? "expanded" : ""}`}>
    <div className="history-set-summary">
      <div className="history-set-main"><span>{timeLabel(workoutSet.ended_at)} · Rack {workoutSet.rack_number ?? "--"}</span><h4>{workoutSet.exercise} · Set {workoutSet.set_number}</h4><p>{workoutSet.weight_lbs ?? "--"} lbs</p></div>
      <div className="history-set-metrics"><div><span>Avg</span><strong>{velocity(workoutSet.avg_velocity)}</strong></div><div><span>Peak</span><strong>{velocity(workoutSet.peak_velocity)}</strong></div><div><span>Reps</span><strong>{workoutSet.reps_completed}</strong></div><div><span>First→last</span><strong>{workoutSet.measured.first_to_last_change_percent === null ? "--" : `${signed(workoutSet.measured.first_to_last_change_percent, 1)}%`}</strong></div></div>
      <div className="history-rep-spark">{workoutSet.reps.map((rep) => <i key={rep.rep_number} style={{ height:`${Math.max(10,Math.min(100,rep.mean_velocity*90))}%` }} />)}</div>
      <button className="history-set-action" onClick={onToggle} aria-expanded={expanded} aria-controls={`history-set-${workoutSet.id}`}>{expanded ? "Close comparison" : "Compare reps"}<b aria-hidden="true">{expanded ? "−" : "+"}</b></button>
    </div>
    {expanded && <RepComparison workoutSet={workoutSet} />}
  </article>;
}

function HistoryTab({ context }) {
  const [expandedSetId, setExpandedSetId] = useState(null);
  if (!context) return <StatePanel title="Choose an athlete" body="Select an athlete to review their set history." />;
  const days = groupHistorySets(context.sets);
  return <div className="context-tab-content"><section className="context-section"><header><span>Saved history</span><h3>{context.athlete.name} · training days</h3><p>Open any set for a rep-by-rep velocity comparison.</p></header>
    {context.truncated && <div className="context-notice">Showing the 50 most recent sets; summaries include all history.</div>}
    {days.length === 0 && <StatePanel title="No completed training days" body="Completed sets will be organized here by day and workout." />}
    <div className="history-day-list">{days.map((day) => <section className="history-day" key={day.key}>
      <header className="history-day-heading"><div><span>Training day</span><h4>{historyDayLabel(day.endedAt)}</h4></div><dl><div><dt>Workouts</dt><dd>{day.workouts.length}</dd></div><div><dt>Sets</dt><dd>{day.sets}</dd></div><div><dt>Reps</dt><dd>{day.reps}</dd></div></dl></header>
      <div className="history-workout-list">{day.workouts.map((workout) => <section className="history-workout" key={workout.key}>
        <header><div><span>Workout</span><h5>{workout.label}</h5></div><p>{workout.sets.length} set{workout.sets.length === 1 ? "" : "s"} · {workout.reps} reps</p></header>
        <div className="history-set-list">{workout.sets.map((workoutSet) => <HistorySetCard workoutSet={workoutSet} expanded={expandedSetId === workoutSet.id} onToggle={() => setExpandedSetId(expandedSetId === workoutSet.id ? null : workoutSet.id)} key={workoutSet.id} />)}</div>
      </section>)}</div>
    </section>)}</div>
  </section></div>;
}

function ProgramsTab({ athlete, programs, accessToken, onLogout }) {
  if (!athlete) return <StatePanel title="Choose an athlete" body="Select an athlete to see their recorded prescriptions." />;
  return <div className="context-tab-content"><section className="context-section"><header><span>Recorded prescriptions</span><h3>{athlete.name} · Programs</h3><p>No program is labeled current without effective dates.</p></header><div className="program-card-grid">{programs.map((program) => <article key={program.id}><span>{program.exercise}</span><strong>{program.target_sets} × {program.target_reps}</strong><p>{program.target_weight_lbs} lbs</p><div>Target velocity <b>{program.velocity_zone_min === null && program.velocity_zone_max === null ? "No velocity target" : `${velocity(program.velocity_zone_min)}–${velocity(program.velocity_zone_max)} m/s`}</b></div></article>)}</div></section><AthleteWorkoutPlanning athlete={athlete} accessToken={accessToken} onLogout={onLogout} /></div>;
}

function NotesTab({ athlete, note, draft, setDraft, onSave, saving, error, conflict }) {
  if (!athlete) return <StatePanel title="Choose an athlete" body="Select an athlete to open their coach note." />;
  return <div className="context-tab-content"><section className="context-section notes-workspace"><header><span>Coach memory</span><h3>Notes for {athlete.name}</h3><p>Record durable context another coach should know next session.</p></header>{conflict && <div className="note-conflict" role="alert"><strong>Another coach changed this note.</strong><blockquote>{conflict.text || "(empty note)"}</blockquote><p>Your draft is preserved and can now be merged with this server version.</p></div>}<textarea aria-label={`Coach notes for ${athlete.name}`} value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={65536} placeholder="Record durable athlete context..." /><div className="notes-actions"><span>{draft.length.toLocaleString()} / 65,536 · {draft !== note?.text ? "Unsaved changes" : "Saved"}</span><button onClick={onSave} disabled={saving || draft === note?.text}>{saving ? "Saving..." : "Save note"}</button></div>{error && <p className="coach-login-error" role="alert">{error}</p>}</section></div>;
}

function LegacyRackSelectionControls({ rack, athleteId, athletes, programs, accessToken, onChooseAthlete, onLogout, refresh }) {
  const selectedAthleteId = rack.selection?.athlete?.id;
  const selectedProgramId = rack.selection?.active_program?.id;
  const eligibleAthleteId = athletes.some((athlete) => Number(athlete.id) === Number(athleteId)) ? athleteId : null;
  const [programId, setProgramId] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [catalogWorkouts, setCatalogWorkouts] = useState([]);
  const [workoutPrograms, setWorkoutPrograms] = useState([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [assignmentType, setAssignmentType] = useState("workout");
  const [workoutId, setWorkoutId] = useState("");
  const [workoutProgramId, setWorkoutProgramId] = useState("");
  const [selectedWorkoutId, setSelectedWorkoutId] = useState("");
  const [catalogSaving, setCatalogSaving] = useState(false);
  const [catalogStatus, setCatalogStatus] = useState("");
  const [loadedCatalogAssignment, setLoadedCatalogAssignment] = useState({ rackNumber: null, assignment: null });
  const authoritativeCatalogAssignment = loadedCatalogAssignment.rackNumber === rack.rack_number
    ? loadedCatalogAssignment.assignment
    : rack.catalog_assignment || rack.workout_assignment || null;

  useEffect(() => {
    setProgramId(Number(selectedAthleteId) === Number(eligibleAthleteId) && selectedProgramId ? String(selectedProgramId) : "");
  }, [rack.rack_number, eligibleAthleteId, selectedAthleteId, selectedProgramId]);

  useEffect(() => {
    setStatus("");
    setError("");
  }, [rack.rack_number, athleteId]);

  useEffect(() => {
    let cancelled = false;
    async function readAll(initialUrl) {
      let url = initialUrl;
      const results = [];
      for (let page = 0; url && page < 20; page += 1) {
        const response = await fetch(url, { headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}` } });
        if (response.status === 401 || response.status === 403) {
          onLogout();
          throw new Error("Coach access expired.");
        }
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || "Catalog choices could not be loaded.");
        results.push(...(Array.isArray(body) ? body : body.results || []));
        url = Array.isArray(body) ? null : sameOriginPath(body.next, window.location.origin);
      }
      return results;
    }
    setCatalogLoading(true);
    setCatalogError("");
    Promise.all([readAll("/api/workouts/?page_size=100"), readAll("/api/workout-programs/?page_size=100")])
      .then(([nextWorkouts, nextPrograms]) => {
        if (!cancelled) {
          setCatalogWorkouts(nextWorkouts);
          setWorkoutPrograms(nextPrograms);
        }
      })
      .catch((loadError) => {
        if (!cancelled && loadError.message !== "Coach access expired.") setCatalogError(loadError.message || "Catalog choices could not be loaded.");
      })
      .finally(() => { if (!cancelled) setCatalogLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken]);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/racks/${rack.rack_number}/state/`, { headers: { Accept: "application/json" }, signal: controller.signal })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || "Current rack assignment could not be loaded.");
        setLoadedCatalogAssignment({ rackNumber: rack.rack_number, assignment: body.assignment || null });
      })
      .catch((loadError) => { if (loadError.name !== "AbortError") setCatalogError(loadError.message); });
    return () => controller.abort();
  }, [rack.rack_number]);

  useEffect(() => {
    const assignedProgram = authoritativeCatalogAssignment?.program || authoritativeCatalogAssignment?.workout_program;
    const assignedWorkout = authoritativeCatalogAssignment?.workout;
    if (assignedProgram) {
      setAssignmentType("workout_program");
      setWorkoutProgramId(String(assignedProgram.id));
      setSelectedWorkoutId(String(assignedWorkout?.id || ""));
      setWorkoutId("");
    } else if (assignedWorkout) {
      setAssignmentType("workout");
      setWorkoutId(String(assignedWorkout.id));
      setWorkoutProgramId("");
      setSelectedWorkoutId("");
    }
    setCatalogStatus("");
    setCatalogError("");
  }, [rack.rack_number, authoritativeCatalogAssignment?.workout?.id, authoritativeCatalogAssignment?.program?.id, authoritativeCatalogAssignment?.workout_program?.id]);

  async function saveSelection() {
    setSaving(true);
    setStatus("");
    setError("");
    try {
      const response = await fetch(`/api/racks/${rack.rack_number}/state/`, {
        method: "PATCH",
        headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ athlete_id: Number(eligibleAthleteId), program_id: Number(programId) }),
      });
      if (response.status === 401 || response.status === 403) {
        onLogout();
        return;
      }
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(`${body.code ? `${body.code}: ` : ""}${body.detail || "Rack selection could not be saved."}`);
      setLoadedCatalogAssignment({ rackNumber: rack.rack_number, assignment: null });
      setStatus("Selection saved. Refreshing room state...");
      await refresh({ preserveSnapshot: true, forceAfterInFlight: true });
      setStatus("Rack selection saved.");
    } catch (saveError) {
      setError(saveError.message || "Rack selection could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function saveCatalogAssignment() {
    setCatalogSaving(true);
    setCatalogStatus("");
    setCatalogError("");
    try {
      const response = await fetch(`/api/racks/${rack.rack_number}/assignment/`, {
        method: "PUT",
        headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
        body: JSON.stringify(buildRackAssignmentPayload(assignmentType, workoutId, workoutProgramId, selectedWorkoutId)),
      });
      if (response.status === 401 || response.status === 403) {
        onLogout();
        return;
      }
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(`${body.code ? `${body.code}: ` : ""}${body.detail || "Catalog assignment could not be saved."}`);
      setLoadedCatalogAssignment({ rackNumber: rack.rack_number, assignment: body.assignment || null });
      setCatalogStatus("Catalog assignment saved. Refreshing rack state...");
      await refresh({ preserveSnapshot: true, forceAfterInFlight: true });
      setCatalogStatus("Catalog assignment saved.");
    } catch (saveError) {
      setCatalogError(saveError.message || "Catalog assignment could not be saved.");
    } finally {
      setCatalogSaving(false);
    }
  }

  const selectedWorkoutProgram = workoutPrograms.find((workoutProgram) => Number(workoutProgram.id) === Number(workoutProgramId));
  const includedWorkouts = selectedWorkoutProgram?.items || [];
  const catalogReady = assignmentType === "workout" ? Boolean(workoutId) : Boolean(workoutProgramId && selectedWorkoutId);
  const legacyLabel = selectedAthleteId && selectedProgramId
    ? `${rack.selection.athlete.name} · ${rack.selection.active_program.exercise}`
    : "No legacy athlete and movement selected";
  const catalogLabel = authoritativeCatalogAssignment?.workout?.name
    ? (authoritativeCatalogAssignment?.program || authoritativeCatalogAssignment?.workout_program ? `${(authoritativeCatalogAssignment.program || authoritativeCatalogAssignment.workout_program).name} · ${authoritativeCatalogAssignment.workout.name}` : authoritativeCatalogAssignment.workout.name)
    : "No catalog workout assigned";

  return <section className="coach-panel coach-rack-selection">
    <header><div><span>Rack workout</span><h3>Choose legacy or catalog training</h3></div><b>Rack {rack.rack_number}</b></header>
    <div className="coach-assignment-current"><span>Current legacy selection</span><b>{legacyLabel}</b><span>Current catalog assignment</span><b>{catalogLabel}</b></div>
    <h4 className="coach-assignment-subhead">Legacy athlete prescription</h4>
    <div className="coach-rack-selection-fields">
      <label>Athlete<select value={eligibleAthleteId || ""} onChange={(event) => onChooseAthlete(event.target.value)} disabled={saving}><option value="">Select active-session athlete</option>{athletes.map((athlete) => <option value={athlete.id} key={athlete.id}>{athlete.name}</option>)}</select></label>
      <label>Movement<select value={programId} onChange={(event) => setProgramId(event.target.value)} disabled={!eligibleAthleteId || saving}><option value="">Select movement</option>{eligibleAthleteId ? programs.map((program) => <option value={program.id} key={program.id}>{program.exercise}</option>) : null}</select></label>
      <button onClick={saveSelection} disabled={!eligibleAthleteId || !programId || saving}>{saving ? "Saving..." : "Save rack selection"}</button>
    </div>
    {status && <p className="coach-selection-status" role="status">{status}</p>}
    {error && <p className="coach-login-error" role="alert">{error}</p>}
    <div className="coach-catalog-assignment">
      <h4 className="coach-assignment-subhead">Catalog assignment</h4>
      <p>Saving switches this rack to catalog mode. The current legacy selection remains available until the switch succeeds.</p>
      {catalogLoading ? <p className="monitor-empty" role="status">Loading workout choices...</p> : <div className="coach-catalog-assignment-fields">
        <label>Assignment type<select value={assignmentType} onChange={(event) => { setAssignmentType(event.target.value); setWorkoutId(""); setWorkoutProgramId(""); setSelectedWorkoutId(""); }} disabled={catalogSaving}><option value="workout">Workout</option><option value="workout_program">Workout program</option></select></label>
        {assignmentType === "workout" ? <label>Workout<select value={workoutId} onChange={(event) => setWorkoutId(event.target.value)} disabled={catalogSaving}><option value="">Select workout</option>{catalogWorkouts.map((workout) => <option value={workout.id} key={workout.id}>{workout.name}</option>)}</select></label> : <><label>Workout program<select value={workoutProgramId} onChange={(event) => { setWorkoutProgramId(event.target.value); setSelectedWorkoutId(""); }} disabled={catalogSaving}><option value="">Select program</option>{workoutPrograms.map((workoutProgram) => <option value={workoutProgram.id} key={workoutProgram.id}>{workoutProgram.name}</option>)}</select></label><label>Included workout<select value={selectedWorkoutId} onChange={(event) => setSelectedWorkoutId(event.target.value)} disabled={!workoutProgramId || catalogSaving}><option value="">Select included workout</option>{includedWorkouts.map((item) => <option value={item.workout.id} key={item.id || item.workout.id}>{item.position}. {item.workout.name}</option>)}</select></label></>}
        <button onClick={saveCatalogAssignment} disabled={!catalogReady || catalogSaving}>{catalogSaving ? "Saving..." : "Switch rack to catalog"}</button>
      </div>}
      {catalogStatus && <p className="coach-selection-status" role="status">{catalogStatus}</p>}
      {catalogError && <p className="coach-login-error" role="alert">{catalogError}</p>}
    </div>
  </section>;
}

function RackSelectionControls({ rack }) {
  const view = coachRackView(rack);
  const training = rack.training;
  return <section className="coach-panel coach-rack-observation">
    <header><div><span>Rack observation</span><h3>{view.athleteName}</h3></div><b>Rack {rack.rack_number}</b></header>
    <div className="coach-observation-grid">
      <div><span>Program</span><strong>{training?.program?.name || "--"}</strong></div>
      <div><span>Workout</span><strong>{training?.workout?.name || "--"}</strong></div>
      <div><span>Movement</span><strong>{view.movementName}</strong></div>
      <div><span>Progress</span><strong>{view.progressLabel}</strong></div>
      <div><span>Latest result</span><strong>{view.latestResult ? `${velocity(view.latestResult.avg_velocity)} m/s · ${view.latestResult.reps_completed} reps` : "No persisted result"}</strong></div>
      <div><span>Hardware</span><strong className={rack.assignment_conflict ? "coach-observation-conflict" : ""}>{rack.assignment_conflict ? "Assignment conflict" : `${rack.screen_count} screen · ${rack.nodes.length} node${rack.nodes.length === 1 ? "" : "s"}`}</strong></div>
    </div>
  </section>;
}

function CoachView({ monitor, accessToken, onLogout }) {
  const { roomState, requestState, connectionState, lastError, refresh } = monitor;
  const [selectedRackNumber,setSelectedRackNumber]=useState(null),[activeTab,setActiveTab]=useState("room"),[athletes,setAthletes]=useState([]),[selectedAthleteId,setSelectedAthleteId]=useState(null),[context,setContext]=useState(null),[programs,setPrograms]=useState([]),[note,setNote]=useState(null),[draft,setDraft]=useState(""),[loading,setLoading]=useState(false),[saving,setSaving]=useState(false),[error,setError]=useState(""),[conflict,setConflict]=useState(null);
  const headers={Accept:"application/json",Authorization:`Bearer ${accessToken}`};
  useEffect(()=>{fetch("/api/athletes/",{headers}).then(r=>r.json()).then(setAthletes).catch(()=>setAthletes([]));},[accessToken]);
  useEffect(()=>{setContext(null);setPrograms([]);setNote(null);setDraft("");setConflict(null);if(!selectedAthleteId)return;let cancelled=false;setLoading(true);setError("");Promise.all([fetch(`/api/analytics/athlete/${selectedAthleteId}/`,{headers}),fetch(`/api/programs/?athlete=${selectedAthleteId}`,{headers}),fetch(`/api/athletes/${selectedAthleteId}/notes/`,{headers})]).then(async rs=>{if(rs.some(r=>r.status===401||r.status===403)){onLogout();return;}if(rs.some(r=>!r.ok))throw new Error("Athlete context could not be loaded.");const [c,p,n]=await Promise.all(rs.map(r=>r.json()));if(!cancelled&&c.athlete.id===selectedAthleteId&&n.athlete_id===selectedAthleteId){setContext(c);setPrograms(p);setNote(n);setDraft(n.text);}}).catch(e=>!cancelled&&setError(e.message)).finally(()=>!cancelled&&setLoading(false));return()=>{cancelled=true;};},[selectedAthleteId,accessToken]);
  useEffect(()=>{if(roomState?.racks.length&&!roomState.racks.some(r=>r.rack_number===selectedRackNumber)){const rack=roomState.racks[0];setSelectedRackNumber(rack.rack_number);const athleteId=rack.training?.athlete?.id||rack.selection?.athlete?.id;if(athleteId)setSelectedAthleteId(Number(athleteId));}},[roomState,selectedRackNumber]);
  const dirty=note&&draft!==note.text;
  const chooseAthlete=id=>{if(dirty&&!window.confirm("Discard the unsaved note draft?"))return;setSelectedAthleteId(id?Number(id):null);};
  const chooseTab=tab=>{if(activeTab==="notes"&&tab!=="notes"&&dirty&&!window.confirm("Leave Notes with unsaved changes?"))return;setActiveTab(tab);};
  async function saveNote(){if(!note||note.athlete_id!==selectedAthleteId){setError("Reload this athlete before saving notes.");return;}setSaving(true);setError("");setConflict(null);try{const r=await fetch(`/api/athletes/${selectedAthleteId}/notes/`,{method:"PUT",headers:{...headers,"Content-Type":"application/json"},body:JSON.stringify({text:draft,expected_version:note.version})});if(r.status===401||r.status===403){onLogout();return;}const b=await r.json();if(r.status===409){setConflict(b.current);setNote({athlete_id:selectedAthleteId,...b.current});return;}if(!r.ok)throw new Error(b.detail||"The note could not be saved.");setNote(b);setDraft(b.text);}catch(e){setError(e.message);}finally{setSaving(false);}}
  if(!roomState&&requestState==="loading")return <main className="monitor coach-monitor"><StatePanel title="Loading coach workspace" body="Reconciling saved room state." /></main>;
  if(!roomState)return <main className="monitor coach-monitor"><StatePanel title="Coach view unavailable" body={lastError||"The base station could not be reached."} action={refresh} /></main>;
  const selectedRack=roomState.racks.find(r=>r.rack_number===selectedRackNumber)||roomState.racks[0],observedResultId=selectedRack?.training?.latest_result?.id,workoutSet=selectedRack?.latest_set?.id===observedResultId?selectedRack.latest_set:null;
  const room=<section className="coach-workspace"><aside className="coach-rack-list"><div className="coach-section-label"><span>Room</span><b>{roomState.racks.length} racks</b></div>{roomState.racks.map(r=><CoachRackButton rack={r} selected={r.rack_number===selectedRack?.rack_number} onSelect={()=>{setSelectedRackNumber(r.rack_number);const athleteId=r.selection?.athlete?.id||r.latest_set?.athlete.id;if(athleteId)chooseAthlete(athleteId);}} key={r.rack_number}/>)}</aside><div className="coach-detail-workspace">{!selectedRack?<StatePanel title="No racks assigned" body="Assign room hardware before monitoring sets."/>:<><RackSelectionControls rack={selectedRack} athleteId={selectedAthleteId} athletes={roomState.participants||[]} programs={programs} accessToken={accessToken} onChooseAthlete={chooseAthlete} onLogout={onLogout} refresh={refresh}/>{!workoutSet?<StatePanel title={`Rack ${selectedRack.rack_number} is ready`} body="No completed set saved for this rack."/>:<><section className="coach-set-hero"><div><span>Rack {selectedRack.rack_number} · Set {workoutSet.set_number}</span><h2>{workoutSet.athlete.name}</h2><p>{workoutSet.exercise} · {workoutSet.weight_lbs??"--"} lbs</p></div><div className="coach-hero-metric"><strong>{velocity(workoutSet.avg_velocity)}</strong><span>m/s average</span></div><dl><div><dt>Peak</dt><dd>{velocity(workoutSet.peak_velocity)} m/s</dd></div><div><dt>Reps</dt><dd>{workoutSet.reps_completed}</dd></div><div><dt>Target</dt><dd>{workoutSet.target_zone?`${velocity(workoutSet.target_zone.min)}-${velocity(workoutSet.target_zone.max)}`:"Not set"}</dd></div></dl></section><div className="coach-panel-grid"><RepChart workoutSet={workoutSet}/><MeasuredInsights workoutSet={workoutSet}/></div><CoachHardware rack={selectedRack}/></>}</>}</div></section>;
  return <main className="monitor coach-monitor"><header className="coach-topbar"><div className="monitor-brand"><b>EA</b><span>Edge Athlete</span></div><div className="coach-session-title"><span>Coach workspace</span><h1>{roomState.session?.label||"No active session"}</h1></div><ConnectionBadge connectionState={connectionState} requestState={requestState}/><select className="coach-athlete-select" value={selectedAthleteId||""} onChange={e=>chooseAthlete(e.target.value)} aria-label="Selected athlete"><option value="">Select athlete</option>{athletes.map(a=><option value={a.id} key={a.id}>{a.name}</option>)}</select><button className="coach-logout" onClick={onLogout}>Log out</button></header><section className="coach-summary-strip"><div><span>Active racks</span><strong>{roomState.summary.active_racks} / {roomState.racks.length}</strong></div><div><span>Athletes with sets</span><strong>{roomState.summary.athletes_with_sets}</strong></div><div><span>Sets complete</span><strong>{roomState.summary.completed_sets}</strong></div><div><span>Awaiting saved result</span><strong>{roomState.racks.filter(rack=>!rack.latest_set).length}</strong></div><div><span>Last reconciled</span><strong>{timeLabel(roomState.generated_at)}</strong></div></section><TrainingDayPanel roomState={roomState} athletes={athletes} accessToken={accessToken} onLogout={onLogout} refresh={refresh}/><nav className="coach-context-tabs" aria-label="Coach workspace tabs" role="tablist">{["room","workouts","reports","athlete","history","programs","notes"].map(t=><button className={activeTab===t?"active":""} aria-selected={activeTab===t} role="tab" onClick={()=>chooseTab(t)} key={t}>{t}</button>)}</nav><div hidden={activeTab!=="workouts"}><WorkoutCatalog accessToken={accessToken} onLogout={onLogout}/></div><div hidden={activeTab!=="reports"}><ReportsWorkspace athletes={athletes} accessToken={accessToken} onLogout={onLogout}/></div>{activeTab==="workouts"||activeTab==="reports"?null:activeTab==="room"?room:loading?<StatePanel title="Loading athlete context" body="Reading saved history, programs, and notes."/>:error&&!context?<StatePanel title="Athlete context unavailable" body={error}/>:activeTab==="athlete"?<AthleteSummaryTab context={context}/>:activeTab==="history"?<HistoryTab context={context}/>:activeTab==="programs"?<ProgramsTab athlete={context?.athlete} programs={programs} accessToken={accessToken} onLogout={onLogout}/>:<NotesTab athlete={context?.athlete} note={note} draft={draft} setDraft={setDraft} onSave={saveNote} saving={saving} error={error} conflict={conflict}/>}</main>;
}

export default function Dashboard({ mode = "wall" }) {
  const [accessToken, setAccessToken] = useState(null);
  const [loginError, setLoginError] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const monitor = useLiveRoomState({ mode, accessToken, onAuthRequired: () => setAccessToken(null) });

  async function login(username, password) {
    setLoginBusy(true);
    setLoginError("");
    try {
      const response = await fetch("/api/auth/login/", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (response.status === 429) {
        setLoginError("Too many login attempts. Wait a minute, then try again.");
        return;
      }
      if (!response.ok) {
        setLoginError("The username or password was not accepted.");
        return;
      }
      const body = await response.json();
      setAccessToken(body.access);
    } catch {
      setLoginError("The base station could not be reached.");
    } finally {
      setLoginBusy(false);
    }
  }

  if (mode === "coach" && !accessToken) {
    return <CoachLogin onLogin={login} error={loginError} busy={loginBusy} />;
  }
  if (mode === "coach") {
    return <CoachView monitor={monitor} accessToken={accessToken} onLogout={() => setAccessToken(null)} />;
  }
  return <WallView monitor={monitor} />;
}
