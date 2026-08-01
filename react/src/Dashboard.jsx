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
// The coach view is a THREE-POSITION STATE MACHINE — planning, session,
// analytics — which is the order a coach's day actually runs in. The position
// comes in as the `coachState` prop, read from the URL by App.jsx, so a reload
// keeps it and the Back button moves between states. See coach/coachState.js.
//
// Inside each state the original tab bar still works; the states just decide
// which tabs belong to them (STATE_TABS below). Later phases reshape what is
// inside each state — this one only builds the frame.
//
// What is NOT here, on purpose: assigning athletes or workouts to a rack ahead
// of time. See the D8 note further down.

import { useEffect, useState } from "react";
import "./App.css";
import { navigate } from "./router.js";
import { coachLogin, getCoachToken, setCoachToken } from "./coach/api.js";
import useLiveRoomState from "./useLiveRoomState.js";
import { compareReps, groupHistorySets } from "./historyView.js";
import WorkoutCatalog from "./WorkoutCatalog.jsx";
import AthleteWorkoutPlanning from "./AthleteWorkoutPlanning.jsx";
import { OpenDayFromScratch, StartStagedDay } from "./TrainingDayPanel.jsx";
import ReportsWorkspace from "./ReportsWorkspace.jsx";
import ScheduleWorkspace from "./ScheduleWorkspace.jsx";
import { sameOriginPath } from "./workoutCatalog.js";
import { coachRackView, measuredInsights, wallDisplayState, wallMovementView } from "./dashboardView.js";
import { roleIconSrc } from "./roleIcon.js";
import { isDevMode } from "./devMode.js";
import StateNavbar from "./coach/StateNavbar.jsx";
import SessionWidget from "./coach/SessionWidget.jsx";
import QuickNote from "./coach/QuickNote.jsx";
import GroupsView from "./coach/GroupsView.jsx";
import { pathForCoachState, rememberCoachState } from "./coach/coachState.js";
import { scheduleUrl, scheduleWindow, slotState } from "./schedule.js";

// Which of the old tabs belongs to which state. This is the whole of Phase A's
// reorganization: nothing inside a tab changed, the tabs were just sorted into
// the three moments of a coach's day.
//
//   PLANNING   what you set up before anyone lifts
//   SESSION    the live room, while they do
//   ANALYTICS  what you read afterwards, one athlete at a time
//
// Later phases dissolve most of these tabs into the layout in §13-15 of
// _COACH_UI_REDESIGN.md. Until then this table is the map, and the first entry
// in each list is that state's landing tab.
const STATE_TABS = {
  planning: ["design", "groups", "catalog", "calendar"],
  session: ["room"],
  analytics: ["athlete", "history", "programs", "notes", "reports"],
};

// The sub-tab bar used to print its own keys, so it read "workouts · schedule"
// in lowercase. PLANNING's four are named things a coach would say out loud, so
// the label and the internal key stop being the same string here.
// ANALYTICS sub-tabs that are about ONE athlete, and so need the selector above
// them. Reports is the odd one out — it is day-scoped and carries its own
// athlete/day mode switch, so the shared selector stays out of its way.
const ATHLETE_SCOPED_TABS = ["athlete", "history", "programs", "notes"];

const TAB_LABELS = {
  design: "Design",
  groups: "Groups",
  catalog: "Workout catalog",
  calendar: "Calendar",
  room: "Room",
  athlete: "Athlete",
  history: "History",
  programs: "Programs",
  notes: "Notes",
  reports: "Reports",
};

// Days a coach set up ahead of time and has not started yet.
//
// ⚠️ THEY ARE INVISIBLE TO THE LIVE ROOM FEED, ON PURPOSE.
// `services/active_session.py` defines "active" as STARTED and not ended, so a
// staged day never appears in `roomState.session` — that is exactly what stops
// next Thursday's session from capturing today's check-ins (canon D18). It also
// means the coach screen has to ask the calendar separately to know one exists.
//
// It matters here because SESSION is gated on a day being SET, not on one
// running: staging a day is what makes SESSION reachable, and starting it is
// what a coach goes there to do.
async function fetchStagedSlots(accessToken) {
  const response = await fetch(scheduleUrl(scheduleWindow()), {
    headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) return [];
  const body = await response.json();
  const slots = Array.isArray(body) ? body : body.results || [];
  return slots.filter((slot) => slotState(slot) === "ready");
}

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

function CoachHardware({ rack }) {
  const node = rack.node;
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

function ProgramsTab({ athlete, programs, exerciseNames, accessToken, onLogout }) {
  return <div className="context-tab-content"><section className="context-section"><header><span>Recorded prescriptions</span><h3>{athlete.name} · Programs</h3><p>No program is labeled current without effective dates.</p></header><div className="program-card-grid">{programs.map((program) => <article key={program.exercise}><span>{exerciseNames[program.exercise] ?? `Movement ${program.exercise}`}</span><strong>{program.target_sets} × {program.target_reps}</strong><p>{program.target_weight_lbs} lbs</p><div>Target velocity <b>{program.velocity_zone_min === null && program.velocity_zone_max === null ? "No velocity target" : `${velocity(program.velocity_zone_min)}–${velocity(program.velocity_zone_max)} m/s`}</b></div></article>)}</div></section><AthleteWorkoutPlanning athlete={athlete} accessToken={accessToken} onLogout={onLogout} /></div>;
}

// Free-text memory a coach leaves on an athlete for whoever runs the next
// session. Saved to `Athlete.notes` — see saveNote for the last-write-wins
// caveat that came with folding away his dedicated notes route.
function NotesTab({ athlete, note, draft, setDraft, onSave, saving, error }) {
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
      <div><span>Latest result</span><strong>{view.latestResult ? `${velocity(view.latestResult.avg_velocity)} m/s · ${view.latestResult.reps_completed} reps` : "No persisted result"}</strong></div>
      {/* One node per rack, and the server decides whether it has gone quiet. */}
      <div><span>Hardware</span><strong className={rack.node?.is_stale ? "coach-observation-conflict" : ""}>{!rack.node ? "No node assigned" : rack.node.is_stale ? "Node pulse overdue" : rack.node.node_id}</strong></div>
    </div>
  </section>;
}

function CoachView({ monitor, accessToken, onLogout, coachState }) {
  const { roomState, requestState, connectionState, lastError, refresh } = monitor;
  const [brandMenuOpen,setBrandMenuOpen]=useState(false);
  const [selectedRackNumber,setSelectedRackNumber]=useState(null),[requestedTab,setRequestedTab]=useState("room"),[athletes,setAthletes]=useState([]),[exerciseNames,setExerciseNames]=useState({}),[selectedAthleteId,setSelectedAthleteId]=useState(null),[context,setContext]=useState(null),[programs,setPrograms]=useState([]),[note,setNote]=useState(null),[draft,setDraft]=useState(""),[loading,setLoading]=useState(false),[saving,setSaving]=useState(false),[error,setError]=useState("");
  const headers={Accept:"application/json",Authorization:`Bearer ${accessToken}`};
  useEffect(()=>{fetch("/api/athletes/",{headers}).then(r=>r.json()).then(setAthletes).catch(()=>setAthletes([]));},[accessToken]);
  // The movement catalog, purely so prescriptions can show a NAME. The
  // prescriptions endpoint returns `exercise` as a catalog id (the per-athlete
  // Program table it used to read from is gone), and an id on screen tells a
  // coach nothing. Resolved here rather than server-side so no route changes.
  useEffect(()=>{fetch("/api/exercises/",{headers}).then(r=>r.json())
    .then(rows=>setExerciseNames(Object.fromEntries(rows.map(e=>[e.id,e.name]))))
    .catch(()=>setExerciseNames({}));},[accessToken]);
  useEffect(()=>{setContext(null);setPrograms([]);setNote(null);setDraft("");if(!selectedAthleteId)return;let cancelled=false;setLoading(true);setError("");Promise.all([fetch(`/api/analytics/athlete/${selectedAthleteId}/`,{headers}),fetch(`/api/prescriptions/?athlete=${selectedAthleteId}`,{headers}),fetch(`/api/athletes/${selectedAthleteId}/`,{headers})]).then(async rs=>{if(rs.some(r=>r.status===401||r.status===403)){onLogout();return;}if(rs.some(r=>!r.ok))throw new Error("Athlete context could not be loaded.");const [c,p,n]=await Promise.all(rs.map(r=>r.json()));if(!cancelled&&c.athlete_id===selectedAthleteId&&n.id===selectedAthleteId){setContext({...c,athlete:n});setPrograms(p);setNote({athlete_id:n.id,text:n.notes||""});setDraft(n.notes||"");}}).catch(e=>!cancelled&&setError(e.message)).finally(()=>!cancelled&&setLoading(false));return()=>{cancelled=true;};},[selectedAthleteId,accessToken]);
  useEffect(()=>{if(roomState?.racks.length&&!roomState.racks.some(r=>r.rack_number===selectedRackNumber)){const rack=roomState.racks[0];setSelectedRackNumber(rack.rack_number);const athleteId=rack.athlete?.id;if(athleteId)setSelectedAthleteId(Number(athleteId));}},[roomState,selectedRackNumber]);
  // Staged days, re-read whenever a day starts or ends — both change the set.
  // A failure is deliberately silent and treated as "none staged": it costs the
  // coach a shortcut, and PLANNING can always open a day from scratch.
  const [stagedSlots,setStagedSlots]=useState([]);
  const runningDayId=roomState?.session?.id??null;
  useEffect(()=>{let cancelled=false;fetchStagedSlots(accessToken).then(slots=>{if(!cancelled)setStagedSlots(slots);}).catch(()=>{if(!cancelled)setStagedSlots([]);});return()=>{cancelled=true;};},[accessToken,runningDayId]);
  // Where this device is, so a bare /coach can send it back here after a reboot.
  // In an effect rather than in goToState below, because a state can also be
  // reached by the Back button or by typing the URL, and those must count too.
  useEffect(()=>{rememberCoachState(coachState);},[coachState]);
  // The tab bar belongs to the state, so a tab the coach picked in one state is
  // held but not shown in another — come back and it is still selected. If the
  // held tab does not belong here, this state's first tab is the landing tab.
  const stateTabs=STATE_TABS[coachState]||STATE_TABS.planning;
  const activeTab=stateTabs.includes(requestedTab)?requestedTab:stateTabs[0];
  const dirty=note&&draft!==note.text;
  const chooseAthlete=id=>{if(dirty&&!window.confirm("Discard the unsaved note draft?"))return;setSelectedAthleteId(id?Number(id):null);};
  const chooseTab=tab=>{if(activeTab==="notes"&&tab!=="notes"&&dirty&&!window.confirm("Leave Notes with unsaved changes?"))return;setRequestedTab(tab);};
  // Changing STATE can also walk away from an unsaved note, so it asks the same
  // question the tab bar does — the coach should not be able to lose a draft by
  // pressing a different part of the screen.
  const goToState=key=>{if(key===coachState)return;if(activeTab==="notes"&&dirty&&!window.confirm("Leave Notes with unsaved changes?"))return;navigate(pathForCoachState(key));};
  // A day just ended. The report it froze belongs in ANALYTICS, not in a strip
  // floating over every state — so take the coach to where finished days live
  // rather than drawing one on top of whatever they were doing.
  //
  // SESSION also has nothing left to show at this point: the room is closed, and
  // staying there would leave them looking at an empty floor.
  const handleDayEnded=()=>{setRequestedTab("reports");navigate(pathForCoachState("analytics"));};
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
  const selectedRack=roomState.racks.find(r=>r.rack_number===selectedRackNumber)||roomState.racks[0],workoutSet=selectedRack?.latest_set||null;
  const room=<section className="coach-workspace"><aside className="coach-rack-list"><div className="coach-section-label"><span>Room</span><b>{roomState.racks.length} racks</b></div>{roomState.racks.map(r=><CoachRackButton rack={r} selected={r.rack_number===selectedRack?.rack_number} onSelect={()=>{setSelectedRackNumber(r.rack_number);const athleteId=r.athlete?.id;if(athleteId)chooseAthlete(athleteId);}} key={r.rack_number}/>)}</aside><div className="coach-detail-workspace">{!selectedRack?null:<><RackSelectionControls rack={selectedRack}/>{!workoutSet?null:<><section className="coach-set-hero"><div><span>Rack {selectedRack.rack_number} · Set {workoutSet.set_number}</span><h2>{selectedRack.athlete?.name||"Unknown athlete"}</h2><p>{workoutSet.exercise} · {workoutSet.weight_lbs??"--"} lbs</p></div><div className="coach-hero-metric"><strong>{velocity(workoutSet.avg_velocity)}</strong><span>m/s average</span></div><dl><div><dt>Peak</dt><dd>{velocity(workoutSet.peak_velocity)} m/s</dd></div><div><dt>Reps</dt><dd>{workoutSet.reps_completed}</dd></div><div><dt>Target</dt><dd>{workoutSet.target_zone?`${velocity(workoutSet.target_zone.min)}-${velocity(workoutSet.target_zone.max)}`:"Not set"}</dd></div></dl></section><div className="coach-panel-grid"><RepChart workoutSet={workoutSet}/><MeasuredInsights workoutSet={workoutSet}/></div><CoachHardware rack={selectedRack}/></>}{/* SESSION's only athlete-scoped control, and it needs no picker: the
          rack rail on the left already IS the picker, and it picks the way a
          coach thinks mid-floor — "whoever is on that rack". */}
      <QuickNote athlete={selectedRack.athlete} rackNumber={selectedRack.rack_number} accessToken={accessToken} onLogout={onLogout}/></>}</div></section>;
  // SESSION needs a day SET — staged from the calendar, or already running.
  // Staged counts because starting a staged day is the thing SESSION is for.
  //
  // The navbar dims the button; this covers getting here anyway — typing the
  // URL, or standing on SESSION at the moment the day ends. It deliberately does
  // NOT redirect: pulling a coach off the screen they were reading, without
  // being asked to, is worse than an empty screen that says why it is empty.
  const dayRunning=Boolean(roomState.session);
  const daySet=dayRunning||stagedSlots.length>0;
  const dayMissing=coachState==="session"&&!daySet;
  // `coach-states-clearance` is room for the navbar to float over. Without it
  // the last card on every screen sits under the glass and cannot be reached.
  return <main className="monitor coach-monitor coach-states-clearance"><header className="coach-topbar">
    {/* The logo is the account menu. Log out is a once-a-day action and did not
        earn permanent space in the toolbar; "Change device" is gone entirely
        because Room Layout already owns it (CoachTablet.jsx). */}
    <div className="monitor-brand coach-brand-menu">
      <button type="button" className="coach-brand-button" onClick={()=>setBrandMenuOpen(!brandMenuOpen)} aria-expanded={brandMenuOpen} aria-haspopup="menu">
        <img src="/icon-coach-192.png" alt="" width="38" height="38" /><span>Edge Athlete</span>
      </button>
      {brandMenuOpen && <div className="coach-brand-dropdown" role="menu">
        <button type="button" role="menuitem" onClick={onLogout}>Log out</button>
      </div>}
    </div>
    <div className="coach-session-title"><span>Coach workspace</span><h1>{roomState.session?.label||"No active session"}</h1></div>
    <div className="coach-topbar-actions">
      <ConnectionBadge connectionState={connectionState} requestState={requestState}/>
      {/* Room Layout — assigning tablets to rack numbers. It lives on its own
          screen because it is setup work a coach does once when the room is
          built, not something they touch during a session. */}
      {/* Labelled, not a bare cog. With no racks assigned the coach screen has
          nothing to show, and this is the only way out of that — so it calls
          attention to itself until at least one rack exists. */}
      <button className={`coach-icon-button coach-labeled-button${roomState.racks.length?"":" coach-button-attention"}`} onClick={()=>navigate("/coach/setup")} title="Room layout" aria-label="Room layout">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.2.66.79 1.11 1.51 1.09H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
        <span>Room layout</span>
      </button>

    </div>
  </header>{/* Developer instrumentation, not coaching information: reconciliation
          time, queue depth, raw counters. Hidden unless isDevMode(). */}
      {isDevMode() && <section className="coach-summary-strip"><div><span>Active racks</span><strong>{roomState.summary.active_racks} / {roomState.racks.length}</strong></div><div><span>Athletes with sets</span><strong>{roomState.summary.athletes_with_sets}</strong></div><div><span>Sets complete</span><strong>{roomState.summary.completed_sets}</strong></div><div><span>Awaiting saved result</span><strong>{roomState.racks.filter(rack=>!rack.latest_set).length}</strong></div><div><span>Last reconciled</span><strong>{timeLabel(roomState.generated_at)}</strong></div></section>}{/* The strip. Outside the three states because ending a day is something a
          coach does while looking at anything — and it renders nothing at all
          unless a day is actually running. */}
      <SessionWidget roomState={roomState} accessToken={accessToken} onLogout={onLogout} refresh={refresh} onDayEnded={handleDayEnded}/>{/* The athlete selector, ANALYTICS-only.
        It used to sit in the topbar, on screen in every state — but PLANNING is
        group- and program-scoped and SESSION picks by rack (the rack rail IS
        the picker there, and it picks the way a coach thinks on the floor). A
        global selector was a second path to a state only one state uses.

        Not shown on Reports: that sub-tab has its own athlete picker with its
        own day/athlete modes, and two pickers on one screen is worse than the
        one it replaced. */}
      {coachState==="analytics"&&ATHLETE_SCOPED_TABS.includes(activeTab)&&<div className="coach-analytics-bar">
        <label>Athlete
          <select value={selectedAthleteId||""} onChange={e=>chooseAthlete(e.target.value)} aria-label="Selected athlete">
            <option value="">Select athlete</option>
            {athletes.map(a=><option value={a.id} key={a.id}>{a.name}</option>)}
          </select>
        </label>
        {context?.athlete&&<span>Showing <b>{context.athlete.name}</b></span>}
      </div>}
      {!dayMissing&&<nav className="coach-context-tabs" aria-label="Coach workspace tabs" role="tablist">{stateTabs.map(t=><button className={activeTab===t?"active":""} aria-selected={activeTab===t} role="tab" onClick={()=>chooseTab(t)} key={t}>{TAB_LABELS[t]??t}</button>)}</nav>}{/* ONE instance across two sub-tabs, not two. Design and Workout catalog
          need the same blocks, categories, groups and deployed programs; mounting
          it twice would fetch all of them twice and let the two copies drift —
          a block made on Design would not show up in the catalog. */}
      <div hidden={activeTab!=="design"&&activeTab!=="catalog"}><WorkoutCatalog accessToken={accessToken} onLogout={onLogout} section={activeTab==="catalog"?"catalog":"design"} onStageDay={()=>setRequestedTab("calendar")}/></div>
      <div hidden={activeTab!=="groups"}><GroupsView accessToken={accessToken} onLogout={onLogout}/></div><div hidden={activeTab!=="reports"}><ReportsWorkspace athletes={athletes} accessToken={accessToken} onLogout={onLogout}/></div><div hidden={activeTab!=="calendar"}>{/* Opening a day with no block behind it. It lives in PLANNING, not
              SESSION, for one hard reason: `POST /api/sessions/` starts the room
              immediately — there is no staged step it could reach SESSION with —
              and SESSION is dimmed until a day is set. Putting it there would
              lock out any gym whose calendar is empty, which is every new one.

              ABOVE the calendar, not below it: the calendar can run to dozens of
              rows, and an escape hatch a coach has to scroll past three weeks of
              planned days to find is not an escape hatch. Phase D decides where
              this finally sits when PLANNING gets its four sub-tabs. */}
          {!dayRunning&&<OpenDayFromScratch athletes={athletes} accessToken={accessToken} onLogout={onLogout} refresh={refresh}/>}
          <ScheduleWorkspace accessToken={accessToken} onLogout={onLogout} refresh={refresh} onStaged={()=>{fetchStagedSlots(accessToken).then(setStagedSlots).catch(()=>{});navigate(pathForCoachState("session"));}} onOpenSession={()=>navigate(pathForCoachState("session"))}/></div>{dayMissing?<StatePanel title="No training day is set up" body="Set a day up from the calendar in Planning and it appears here, ready to start. For training with no plan behind it, Planning can open the room straight away." action={()=>goToState("planning")} actionLabel="Go to Planning"/>:activeTab==="design"||activeTab==="catalog"||activeTab==="groups"||activeTab==="reports"||activeTab==="calendar"?null:activeTab==="room"?<>{/* A day set up earlier, waiting to be opened. Above the room because
            until it is started the room below is not following anything. */}
        {!dayRunning&&<StartStagedDay slots={stagedSlots} accessToken={accessToken} onLogout={onLogout} refresh={refresh}/>}{room}</>:loading?<StatePanel title="Loading athlete context" body="Reading saved history, programs, and notes."/>:error&&!context?<StatePanel title="Athlete context unavailable" body={error}/>:!context?.athlete?<StatePanel title="Choose an athlete" body="Select an athlete to see their performance, history, prescriptions and notes."/>:activeTab==="athlete"?<AthleteSummaryTab context={context}/>:activeTab==="history"?<HistoryTab context={context}/>:activeTab==="programs"?<ProgramsTab athlete={context?.athlete} programs={programs} exerciseNames={exerciseNames} accessToken={accessToken} onLogout={onLogout}/>:<NotesTab athlete={context?.athlete} note={note} draft={draft} setDraft={setDraft} onSave={saveNote} saving={saving} error={error}/>}{/* Outside everything that swaps, on purpose — the bar is one continuous
          object, not three copies of a bar. That is what makes three routes
          read as one surface changing mode. */}
    <StateNavbar current={coachState} onSelect={goToState} daySet={daySet}/></main>;
}

export default function Dashboard({ mode = "wall", coachState = "planning" }) {
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
    return <CoachView monitor={monitor} accessToken={accessToken} onLogout={forget} coachState={coachState} />;
  }
  return <WallView monitor={monitor} />;
}
