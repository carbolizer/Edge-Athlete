/*
 * Provides two production monitoring surfaces: a room-scale athlete scoreboard
 * and a protected coach tablet. Both reconcile saved PostgreSQL state through MQTT revisions.
 */
// Dashboard.jsx — one file, two screens, chosen by the `mode` prop.
//
//   mode="wall"   → /dashboard. The big screen on the gym wall. Read-only, no
//                   login, nothing private on it: current movement, a
//                   leaderboard, and how the room is doing. Anyone can see it.
//   mode="coach"  → /coach. The coach's working tool, behind a login. Same live
//                   room feed, plus everything the wall deliberately leaves out
//                   — names, history, planning, notes, reports.
//
// They share a file because they share a heartbeat: both are driven by
// useLiveRoomState, which holds a snapshot of the room and refetches it when
// MQTT says something changed. The database stays the source of truth; MQTT only
// says "look again". The two views ask the same endpoint for different amounts
// of detail (?details=true for the coach, which needs the login).
//
// The coach view is a set of tabs across one selected athlete — summary,
// history, programs, notes — plus workouts and reports, which stand alone.
//
// What is NOT here, on purpose: assigning athletes or workouts to a rack ahead
// of time. See the D8 note further down.

import { useEffect, useState } from "react";
import "./App.css";
import { navigate } from "./router.js";
import { coachFetch, coachLogin, getCoachToken, setCoachToken } from "./coach/api.js";
import useLiveRoomState from "./useLiveRoomState.js";
import { compareReps, groupHistorySets } from "./historyView.js";
import WorkoutCatalog from "./WorkoutCatalog.jsx";
import AthleteWorkoutPlanning from "./AthleteWorkoutPlanning.jsx";
import TrainingDayPanel from "./TrainingDayPanel.jsx";
import ReportsWorkspace from "./ReportsWorkspace.jsx";
import ScheduleWorkspace from "./ScheduleWorkspace.jsx";
import { sameOriginPath } from "./workoutCatalog.js";
import { coachRackView, measuredInsights, rackMetrics, wallDisplayState, wallMovementView } from "./dashboardView.js";
import { ATHLETE_TABS, ROOM_TABS, tabDisabled } from "./coachTabs.js";
import { roleIconSrc } from "./roleIcon.js";

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

// Forgets what this device is (wall display / coach tablet / rack) and returns
// to the role picker. Every screen needs an escape hatch: these are kiosks, and
// without one the only way to re-purpose a tablet is clearing its browser
// storage by hand. The rack screens and the Room Layout admin each have their
// own version of this button; this is the one for the two Dashboard views.
function changeDeviceRole() {
  localStorage.removeItem("device_role");
  // Drops the coach login too. Re-purposing a tablet as a wall display must not
  // leave a valid token sitting on a screen nobody is standing at.
  setCoachToken(null);
  navigate("/");
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

// The shared loading / empty / error panel, used by both the wall and the coach
// workspace. Its mark comes from the DEVICE's role rather than a fixed image,
// because the same panel renders on both — a wall display should not wear the
// coach app's icon while it waits for a session.
function StatePanel({ title, body, action, actionLabel = "Retry" }) {
  return (
    <section className="monitor-state-panel">
      <img className="monitor-state-mark" src={roleIconSrc()} alt="" width="44" height="44" />
      <h2>{title}</h2>
      <p>{body}</p>
      {action && <button onClick={action}>{actionLabel}</button>}
    </section>
  );
}

function WallRackTile({ rack }) {
  const workoutSet = rack.latest_set;
  const metrics = rackMetrics(rack);
  return (
    <article className={`wall-rack-tile ${rack.status_color}`}>
      <header>
        <span>Rack {rack.rack_number}</span>
        <b>{rack.status}</b>
      </header>
      {workoutSet ? (
        <>
          {/* The athlete belongs to the RACK, not to the set — they are on this
              rack because they checked in here. A set carries no athlete of its
              own in our room-state. */}
          <div className="wall-rack-athlete">
            <h3>{rack.athlete?.name || "Unknown athlete"}</h3>
            <p>{workoutSet.exercise} · Set {workoutSet.set_number}</p>
          </div>
          <div className="wall-rack-result">
            <strong>{velocity(metrics.mean)}</strong>
            <span>{metrics.isLive ? "m/s latest mean" : "m/s average"}</span>
          </div>
          <footer>
            <span>{metrics.reps} reps</span>
            <span>{velocity(metrics.peak)} {metrics.isLive ? "latest peak" : "peak"}</span>
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
        {/* The WALL's own icon — this screen is the room-facing scoreboard, not
            the coach app, so it wears the dashboard mark. */}
        <div className="monitor-brand"><img src={roleIconSrc("wall")} alt="" width="38" height="38" /><span>Edge Athlete</span></div>
        <div className="wall-session">
          <span>Now training</span>
          <h1>{roomState.session.label}</h1>
        </div>
        <ConnectionBadge connectionState={connectionState} requestState={requestState} />
        <button className="coach-logout" onClick={changeDeviceRole}>Change device role</button>
      </header>

      <section className="wall-content">
        <div className="wall-rack-grid">
          {roomState.racks.map((rack) => <WallRackTile rack={rack} key={rack.rack_number} />)}
        </div>
        <aside className="wall-rail">
          <section className="wall-board-card">
            <div className="wall-card-title"><span>Current room movement</span><b>{movement.waiting ? "Ready" : "Live"}</b></div>
            <h2>{movement.name}</h2><p className="monitor-empty">{movement.detail}</p>
          </section>
          {!movement.waiting && <WallLeaderboard rows={movement.rows} movementName={movement.name} />}
          <WallInsights insights={roomState.insights} />
        </aside>
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
        {/* The coach app's own icon, matching the workspace topbar and the icon
            this device installs to a home screen — the "EA" lettermark it
            replaced belonged to no particular app. Larger here than in the
            topbar because it is the only mark on the screen. */}
        <div className="monitor-brand"><img src="/icon-coach-192.png" alt="" width="52" height="52" /><span>Edge Athlete</span></div>
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
      <strong>{velocity(view.metrics.mean)}</strong>
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
  // Derived from the reps in this set — the server sends no insights block.
  const insight = measuredInsights(workoutSet);
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

// Sensor linking, adapted from Derrilon's T10 picker.
//
// Hers called PATCH /api/nodes/<id>/, which existed when she branched and was
// removed by the BLE merge — so it compiled, merged, and 404'd. This is the same
// UI pointed at what replaced it: PUT /api/racks/node-assignment/, addressed by
// the rack SCREEN's device id rather than by rack number.
//
// The endpoint is the reason this is short. It already refuses a sensor that is on
// another rack, refuses one with an open set, and — the part that matters for "one
// rack, one sensor" — unassigns whatever was on this rack before, in the same
// transaction. A rack can never end up holding a Bluetooth sensor and an MQTT one
// at the same time, because it can never hold two.
//
// It also enforces the split between the two transports on its own: an unassigned
// Bluetooth sensor is rejected here and has to be verified standing at the rack,
// because you cannot tell anonymous nearby radios apart from across the room. An
// MQTT sensor announced its own name, so there is nothing to verify.
function CoachHardware({ rack, nodes, token, onLinked }) {
  const node = rack.node;
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [linking, setLinking] = useState(false);
  const [linkError, setLinkError] = useState("");

  // Offer only what this rack can actually take: sensors with no rack, or the one
  // already here. A sensor owned by another rack is left out rather than shown and
  // rejected — the endpoint would refuse it, but a control you are allowed to press
  // and that always fails is worse than one that is not there.
  const available = (nodes || []).filter(
    (n) => n.rack_number == null || n.rack_number === rack.rack_number,
  );
  const canLink = rack.screen_device_id != null;

  async function linkNode() {
    if (!selectedNodeId) return;
    setLinking(true);
    setLinkError("");
    try {
      const result = await coachFetch("/api/racks/node-assignment/", {
        token,
        method: "PUT",
        body: { device_id: rack.screen_device_id, node_id: selectedNodeId },
      });
      setSelectedNodeId("");
      onLinked?.(result);
    } catch (err) {
      setLinkError(err.message || "The sensor could not be linked.");
    } finally {
      setLinking(false);
    }
  }

  return (
    <section className="coach-panel coach-hardware-panel">
      {/* One rack, one sensor node. His original screen expected a LIST of
          nodes per rack plus a screen count and an assignment-conflict flag;
          our room-state reports the single node bound to this rack, and racks
          are not assigned in advance so there is no conflict to report. */}
      <header><div><span>Rack health</span><h3>Connected hardware</h3></div></header>
      {!node ? <p className="monitor-empty">No sensor node assigned.</p> : (
        <div className="coach-node" key={node.node_id}>
          {/* The server already decided whether this node has gone quiet — it
              knows when it last heard from it, and the browser's clock may not
              agree with the base station's. */}
          <i className={node.is_stale ? "stale" : "online"} />
          <span><strong>{node.node_id}</strong><small>{node.is_stale ? "Pulse overdue" : "Reporting"}</small></span>
          <b>{node.battery_level ?? "--"}%</b>
        </div>
      )}

      <div className="coach-hardware-link">
        <label htmlFor="link-sensor-select">Link a sensor to this rack</label>
        <div className="coach-hardware-link-row">
          <select
            id="link-sensor-select"
            value={selectedNodeId}
            disabled={linking || !canLink}
            onChange={(e) => setSelectedNodeId(e.target.value)}
          >
            <option value="">Choose a sensor...</option>
            {available.map((n) => (
              <option value={n.node_id} key={n.node_id}>
                {n.node_id}
                {n.acquisition_kind === "wt901_ble" ? " · Bluetooth" : " · Wi-Fi"}
                {n.rack_number === rack.rack_number ? " (currently here)" : ""}
              </option>
            ))}
          </select>
          <button type="button" onClick={linkNode} disabled={linking || !canLink || !selectedNodeId}>
            {linking ? "Linking..." : "Link sensor"}
          </button>
        </div>
        {/* Assigning is addressed by the rack SCREEN, so a rack with no screen
            registered yet cannot be linked from here. Say that, rather than
            leaving a dead button. */}
        {!canLink && (
          <p className="monitor-empty">
            No tablet is registered to this rack yet — assign one first.
          </p>
        )}
        {linkError && <p className="coach-login-error" role="alert">{linkError}</p>}
      </div>
    </section>
  );
}

// P13 wrote the read these two tabs were built against, so the "isn't available
// yet" panel they used to show is gone. What replaces it is NOT a removed guard:
// an athlete with no completed sets is an ordinary, permanent state — a new
// signing, or someone who has only ever had false sets — and it needs its own
// answer rather than an empty grid of dashes.
function NothingRecordedYet({ what }) {
  return <StatePanel title={`No ${what} yet`}
    body="Completed sets will appear here once this athlete has trained. False sets and coach weight adjustments are deliberately left out." />;
}

function AthleteSummaryTab({ context }) {
  if (!context) return <StatePanel title="Choose an athlete" body="Select an athlete to load their saved performance context." />;
  if (!context.summary?.completed_sets) return <NothingRecordedYet what="recorded performance" />;
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
  if (!context.sets?.length) return <NothingRecordedYet what="set history" />;
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

// Free-text memory a coach leaves on an athlete for whoever runs the next
// session. Saved to `Athlete.notes` — see saveNote for the last-write-wins
// caveat that came with folding away his dedicated notes route.
function NotesTab({ athlete, note, draft, setDraft, onSave, saving, error }) {
  if (!athlete) return <StatePanel title="Choose an athlete" body="Select an athlete to open their coach note." />;
  return <div className="context-tab-content"><section className="context-section notes-workspace"><header><span>Coach memory</span><h3>Notes for {athlete.name}</h3><p>Record durable context another coach should know next session.</p></header><textarea aria-label={`Coach notes for ${athlete.name}`} value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={65536} placeholder="Record durable athlete context..." /><div className="notes-actions"><span>{draft.length.toLocaleString()} / 65,536 · {draft !== note?.text ? "Unsaved changes" : "Saved"}</span><button onClick={onSave} disabled={saving || draft === note?.text}>{saving ? "Saving..." : "Save note"}</button></div>{error && <p className="coach-login-error" role="alert">{error}</p>}</section></div>;
}

// Forward rack-assignment was REMOVED here (merge canon D8).
//
// Braydon's original screen let a coach pick, in advance, which athlete and
// which workout each rack would run, and pushed that to racks/{n}/assignment/
// and racks/{n}/state/. Those routes are gone and so is the panel: a rack now
// learns who is on it when the athlete checks in at the rack itself, which is
// the thing that actually happens in a gym. Predicting it from the coach tablet
// meant two sources of truth for "who is on rack 3", and the tablet's guess
// aged badly the moment anyone moved.
//
// What replaced it is directly below: a read-only observation panel.
function RackSelectionControls({ rack }) {
  const view = coachRackView(rack);
  const latest = rack.latest_set;
  return <section className="coach-panel coach-rack-observation">
    <header><div><span>Rack observation</span><h3>{view.athleteName}</h3></div><b>Rack {rack.rack_number}</b></header>
    <div className="coach-observation-grid">
      <div><span>Movement</span><strong>{view.movementName}</strong></div>
      <div><span>Load</span><strong>{latest?.weight_lbs != null ? `${latest.weight_lbs} lbs` : "--"}</strong></div>
      <div><span>Progress</span><strong>{view.progressLabel}</strong></div>
      <div><span>Rack state</span><strong>{rack.status || "--"}</strong></div>
       <div><span>{view.metrics.isLive ? "Live result" : "Latest result"}</span><strong>{view.latestResult ? `${velocity(view.metrics.mean)} m/s · ${view.metrics.reps} reps` : "No persisted result"}</strong></div>
      {/* One node per rack, and the server decides whether it has gone quiet. */}
      <div><span>Hardware</span><strong className={rack.node?.is_stale ? "coach-observation-conflict" : ""}>{!rack.node ? "No node assigned" : rack.node.is_stale ? "Node pulse overdue" : rack.node.node_id}</strong></div>
    </div>
  </section>;
}

function CoachView({ monitor, accessToken, onLogout }) {
  const { roomState, requestState, connectionState, lastError, refresh } = monitor;
  const [selectedRackNumber,setSelectedRackNumber]=useState(null),[activeTab,setActiveTab]=useState("room"),[athletes,setAthletes]=useState([]),[selectedAthleteId,setSelectedAthleteId]=useState(null),[context,setContext]=useState(null),[programs,setPrograms]=useState([]),[note,setNote]=useState(null),[draft,setDraft]=useState(""),[loading,setLoading]=useState(false),[saving,setSaving]=useState(false),[error,setError]=useState("");
  const headers={Accept:"application/json",Authorization:`Bearer ${accessToken}`};
  useEffect(()=>{fetch("/api/athletes/",{headers}).then(r=>r.json()).then(setAthletes).catch(()=>setAthletes([]));},[accessToken]);
  // Every sensor, not just the one on the selected rack — the linking control
  // needs to offer unassigned ones too. Refetched after a link so the dropdown
  // does not keep showing a sensor as free once it has been claimed.
  const [nodes,setNodes]=useState([]);
  const [nodesTick,setNodesTick]=useState(0);
  useEffect(()=>{coachFetch("/api/nodes/",{token:accessToken}).then(setNodes).catch(()=>setNodes([]));},[accessToken,nodesTick]);
  useEffect(()=>{setContext(null);setPrograms([]);setNote(null);setDraft("");if(!selectedAthleteId)return;let cancelled=false;setLoading(true);setError("");Promise.all([fetch(`/api/analytics/athlete/${selectedAthleteId}/`,{headers}),fetch(`/api/prescriptions/?athlete=${selectedAthleteId}`,{headers}),fetch(`/api/athletes/${selectedAthleteId}/`,{headers})]).then(async rs=>{if(rs.some(r=>r.status===401||r.status===403)){onLogout();return;}if(rs.some(r=>!r.ok))throw new Error("Athlete context could not be loaded.");const [c,p,n]=await Promise.all(rs.map(r=>r.json()));if(!cancelled&&c.athlete_id===selectedAthleteId&&n.id===selectedAthleteId){setContext({...c,athlete:n});setPrograms(p);setNote({athlete_id:n.id,text:n.notes||""});setDraft(n.notes||"");}}).catch(e=>!cancelled&&setError(e.message)).finally(()=>!cancelled&&setLoading(false));return()=>{cancelled=true;};},[selectedAthleteId,accessToken]);
  useEffect(()=>{if(roomState?.racks.length&&!roomState.racks.some(r=>r.rack_number===selectedRackNumber)){const rack=roomState.racks[0];setSelectedRackNumber(rack.rack_number);const athleteId=rack.athlete?.id;if(athleteId)setSelectedAthleteId(Number(athleteId));}},[roomState,selectedRackNumber]);
  const dirty=note&&draft!==note.text;
  const chooseAthlete=id=>{if(dirty&&!window.confirm("Discard the unsaved note draft?"))return;setSelectedAthleteId(id?Number(id):null);};
  const chooseTab=tab=>{if(activeTab==="notes"&&tab!=="notes"&&dirty&&!window.confirm("Leave Notes with unsaved changes?"))return;setActiveTab(tab);};
  // Coach notes are a plain field on the athlete record, so saving one is a
  // PATCH to the athlete — there is no separate notes route (merge canon R1).
  //
  // ⚠️ This is LAST-WRITE-WINS. Braydon's original version sent an
  // `expected_version` and showed a merge banner if another coach had edited the
  // note first. Our `Athlete.notes` column has no version to compare against, so
  // that protection is gone: two coaches editing one athlete's note at the same
  // time means the second save silently overwrites the first. Recorded in the
  // canon (§8.1) as a deliberate trade, not an oversight.
  async function saveNote() {
    if (!note || note.athlete_id !== selectedAthleteId) {
      setError("Reload this athlete before saving notes.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const r = await fetch(`/api/athletes/${selectedAthleteId}/`, {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ notes: draft }),
      });
      if (r.status === 401 || r.status === 403) { onLogout(); return; }
      const b = await r.json();
      if (!r.ok) throw new Error(b.detail || "The note could not be saved.");
      // The response is the whole athlete record; keep only the note text, in
      // the shape the notes tab already expects.
      setNote({ athlete_id: b.id, text: b.notes || "" });
      setDraft(b.notes || "");
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }
  if(!roomState&&requestState==="loading")return <main className="monitor coach-monitor"><StatePanel title="Loading coach workspace" body="Reconciling saved room state." /></main>;
  if(!roomState)return <main className="monitor coach-monitor"><StatePanel title="Coach view unavailable" body={lastError||"The base station could not be reached."} action={refresh} /></main>;
  const selectedRack=roomState.racks.find(r=>r.rack_number===selectedRackNumber)||roomState.racks[0],workoutSet=selectedRack?.latest_set||null,liveMetrics=rackMetrics(selectedRack);
  const room=<section className="coach-workspace"><aside className="coach-rack-list"><div className="coach-section-label"><span>Room</span><b>{roomState.racks.length} racks</b></div>{roomState.racks.map(r=><CoachRackButton rack={r} selected={r.rack_number===selectedRack?.rack_number} onSelect={()=>{setSelectedRackNumber(r.rack_number);const athleteId=r.athlete?.id;if(athleteId)chooseAthlete(athleteId);}} key={r.rack_number}/>)}</aside><div className="coach-detail-workspace">{!selectedRack?<StatePanel title="No racks assigned" body="Assign room hardware before monitoring sets."/>:<><RackSelectionControls rack={selectedRack}/>{!workoutSet?<StatePanel title={`Rack ${selectedRack.rack_number} is ready`} body="No completed set saved for this rack."/>:<><section className="coach-set-hero"><div><span>Rack {selectedRack.rack_number} · Set {workoutSet.set_number}</span><h2>{selectedRack.athlete?.name||"Unknown athlete"}</h2><p>{workoutSet.exercise} · {workoutSet.weight_lbs??"--"} lbs</p></div><div className="coach-hero-metric"><strong>{velocity(liveMetrics.mean)}</strong><span>{liveMetrics.isLive?"m/s latest mean":"m/s average"}</span></div><dl><div><dt>{liveMetrics.isLive?"Latest peak":"Peak"}</dt><dd>{velocity(liveMetrics.peak)} m/s</dd></div><div><dt>Reps</dt><dd>{liveMetrics.reps}</dd></div><div><dt>Target</dt><dd>{workoutSet.target_zone?`${velocity(workoutSet.target_zone.min)}-${velocity(workoutSet.target_zone.max)}`:"Not set"}</dd></div></dl></section><div className="coach-panel-grid"><RepChart workoutSet={workoutSet}/><MeasuredInsights workoutSet={workoutSet}/></div></>}<CoachHardware rack={selectedRack} nodes={nodes} token={accessToken} onLinked={()=>{refresh();setNodesTick(n=>n+1);}}/></>}</div></section>;
  return <main className="monitor coach-monitor"><header className="coach-topbar">
    <div className="monitor-brand"><img src="/icon-coach-192.png" alt="" width="38" height="38" /><span>Edge Athlete</span></div>
    <div className="coach-session-title"><span>Coach workspace</span><h1>{roomState.session?.label||"No active session"}</h1></div>
    <div className="coach-topbar-actions">
      <ConnectionBadge connectionState={connectionState} requestState={requestState}/>
      <select className="coach-athlete-select" value={selectedAthleteId||""} onChange={e=>chooseAthlete(e.target.value)} aria-label="Selected athlete"><option value="">Select athlete</option>{athletes.map(a=><option value={a.id} key={a.id}>{a.name}</option>)}</select>
      {/* Room Layout — assigning tablets to rack numbers. It lives on its own
          screen because it is setup work a coach does once when the room is
          built, not something they touch during a session. */}
      <button className="coach-icon-button" onClick={()=>navigate("/coach/setup")} title="Room layout" aria-label="Room layout">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.2.66.79 1.11 1.51 1.09H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </button>
      <button className="coach-logout" onClick={onLogout}>Log out</button>
      <button className="coach-logout" onClick={changeDeviceRole}>Change device</button>
    </div>
  </header><section className="coach-summary-strip"><div><span>Active racks</span><strong>{roomState.summary.active_racks} / {roomState.racks.length}</strong></div><div><span>Athletes with sets</span><strong>{roomState.summary.athletes_with_sets}</strong></div><div><span>Sets complete</span><strong>{roomState.summary.completed_sets}</strong></div><div><span>Awaiting saved result</span><strong>{roomState.racks.filter(rack=>!rack.latest_set).length}</strong></div><div><span>Last reconciled</span><strong>{timeLabel(roomState.generated_at)}</strong></div></section><TrainingDayPanel roomState={roomState} athletes={athletes} accessToken={accessToken} onLogout={onLogout} refresh={refresh}/><nav className="coach-context-tabs" aria-label="Coach workspace tabs" role="tablist">
    <span className="coach-tab-group" aria-hidden="true">Room</span>
    {ROOM_TABS.map(t=><button className={activeTab===t?"active":""} aria-selected={activeTab===t} role="tab" onClick={()=>chooseTab(t)} key={t}>{t}</button>)}
    <span className="coach-tab-divider" aria-hidden="true" />
    <span className="coach-tab-group" aria-hidden="true">Athlete</span>
    {ATHLETE_TABS.map(t=>{
      const disabled = tabDisabled(t, selectedAthleteId);
      return <button className={(activeTab===t?"active":"")+(disabled?" needs-athlete":"")}
        aria-selected={activeTab===t} role="tab" aria-disabled={disabled}
        title={disabled?"Select an athlete first to see their view":undefined}
        onClick={()=>{if(disabled&&activeTab!==t){setError("Select an athlete to open their view.");return;}chooseTab(t);}} key={t}>{t}</button>
    })}
  </nav><div hidden={activeTab!=="workouts"}><WorkoutCatalog accessToken={accessToken} onLogout={onLogout}/></div><div hidden={activeTab!=="reports"}><ReportsWorkspace athletes={athletes} accessToken={accessToken} onLogout={onLogout}/></div><div hidden={activeTab!=="schedule"}><ScheduleWorkspace accessToken={accessToken} onLogout={onLogout} refresh={refresh}/></div>{activeTab==="workouts"||activeTab==="reports"||activeTab==="schedule"?null:activeTab==="room"?room:loading?<StatePanel title="Loading athlete context" body="Reading saved history, programs, and notes."/>:error&&!context?<StatePanel title="Athlete context unavailable" body={error}/>:activeTab==="athlete"?<AthleteSummaryTab context={context}/>:activeTab==="history"?<HistoryTab context={context}/>:activeTab==="programs"?<ProgramsTab athlete={context?.athlete} programs={programs} accessToken={accessToken} onLogout={onLogout}/>:<NotesTab athlete={context?.athlete} note={note} draft={draft} setDraft={setDraft} onSave={saveNote} saving={saving} error={error}/>}</main>;
}

export default function Dashboard({ mode = "wall" }) {
  // The token is read from storage on mount, not started at null, so a refresh,
  // a tablet waking from sleep, or a browser reloading a backgrounded tab does
  // not throw the coach back to a login screen mid-session. It is the same
  // stored token /coach/setup uses, so the two screens share one login.
  const [accessToken, setAccessToken] = useState(() => getCoachToken());
  const [loginError, setLoginError] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const monitor = useLiveRoomState({ mode, accessToken, onAuthRequired: () => forget() });

  // One place to drop the login, so the stored copy can never outlive the
  // in-memory one — a stale token left in storage is a coach still signed in on
  // a shared tablet after they walked away.
  function forget() {
    setCoachToken(null);
    setAccessToken(null);
  }

  async function login(username, password) {
    setLoginBusy(true);
    setLoginError("");
    try {
      setAccessToken(await coachLogin(username, password));
    } catch (error) {
      setLoginError(error.message || "The base station could not be reached.");
    } finally {
      setLoginBusy(false);
    }
  }

  if (mode === "coach" && !accessToken) {
    return <CoachLogin onLogin={login} error={loginError} busy={loginBusy} />;
  }
  if (mode === "coach") {
    return <CoachView monitor={monitor} accessToken={accessToken} onLogout={forget} />;
  }
  return <WallView monitor={monitor} />;
}
