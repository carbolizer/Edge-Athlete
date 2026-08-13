// ScheduleWorkspace.jsx — the training calendar.
//
// WHAT A COACH DOES HERE. Deploying a block generated a slot for every training
// day it covers. This screen shows those days and lets them do three things:
//
//   SET UP   Create the real session for a planned day — its roster and its
//            workout. This does NOT start it. A coach can set Thursday up on
//            Tuesday and the racks carry on with today.
//   START    Open the room on a day that is ready. Only one day runs at a time,
//            so this is refused while another is open, naming it.
//   MOVE     Put a day on a different date. That is a single date change and
//            regenerates nothing — the rest of the block stays where it is.
//
// The distinction between "ready" and "running" is the point of the whole phase,
// so the screen leads with it rather than showing a generic list of dates.
//
// Ending a day is deliberately NOT here — it lives on the training-day panel at
// the top of the coach view, next to the room it is ending. Two places to end a
// day is how a coach ends the wrong one.

import { useEffect, useState } from "react";
import { groupSlotsByDate, isPastDate, moveDateChoices, scheduleDayLabel,
         scheduleUrl, scheduleWindow, slotAction, slotState } from "./schedule.js";
import { flattenApiErrors } from "./workoutCatalog.js";

const STATE_COPY = {
  planned: { label: "Planned", hint: "No session created yet." },
  ready: { label: "Ready", hint: "Set up and waiting — not started." },
  running: { label: "Running", hint: "Open now. The racks are following this day." },
  done: { label: "Complete", hint: "Ended; its report is frozen." },
};

function SlotRow({ slot, slots, busy, onCreate, onStart, onMove }) {
  const state = slotState(slot);
  const action = slotAction(slot);
  const copy = STATE_COPY[state];
  const [moving, setMoving] = useState(false);

  return <article className={`schedule-slot is-${state}`}>
    <div className="schedule-slot-main">
      <span className="schedule-slot-state">{copy.label}</span>
      <h5>{slot.workout_name}</h5>
      <p>{slot.group_name} · {slot.program_name}</p>
      <small>{copy.hint}</small>
    </div>

    <div className="schedule-slot-actions">
      {action === "create" && <button type="button" disabled={Boolean(busy)}
        onClick={() => onCreate(slot)}>{busy === `create-${slot.id}` ? "Setting up..." : "Set up day"}</button>}
      {action === "start" && <button type="button" disabled={Boolean(busy)}
        onClick={() => onStart(slot)}>{busy === `start-${slot.id}` ? "Starting..." : "Start day"}</button>}

      {/* A day that has already run can still be moved — the coach is correcting
          the calendar, and the session keeps its own real start time. */}
      {moving
        ? <label className="schedule-move">Move to
            <select defaultValue={slot.date} disabled={Boolean(busy)}
              onChange={(event) => { setMoving(false); onMove(slot, event.target.value); }}>
              {moveDateChoices(slot, slots).map((choice) => <option key={choice.value} value={choice.value}>
                {choice.label}{choice.current ? " (current)" : ""}
              </option>)}
            </select>
          </label>
        : <button type="button" className="workout-secondary" disabled={Boolean(busy)}
            onClick={() => setMoving(true)}>Move</button>}
    </div>
  </article>;
}

export default function ScheduleWorkspace({ accessToken, onLogout, refresh }) {
  const [slots, setSlots] = useState([]);
  const [state, setState] = useState("loading");
  const [errors, setErrors] = useState([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState("");
  // Past days are hidden by default: the calendar is a thing a coach looks
  // FORWARD in, and a finished week pushes tomorrow off the screen.
  const [showPast, setShowPast] = useState(false);
  const headers = { Accept: "application/json", Authorization: `Bearer ${accessToken}` };

  async function parseResponse(response, fallback) {
    if (response.status === 401 || response.status === 403) {
      onLogout();
      return null;
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw flattenApiErrors(body, fallback);
    return body;
  }

  async function load() {
    setState("loading");
    setErrors([]);
    try {
      const response = await fetch(scheduleUrl(scheduleWindow()), { headers });
      const body = await parseResponse(response, "The schedule could not be loaded.");
      if (body === null) return;
      setSlots(Array.isArray(body) ? body : body.results || []);
      setState("ready");
    } catch (loadErrors) {
      setErrors(Array.isArray(loadErrors) ? loadErrors : [{ detail: "The schedule could not be loaded." }]);
      setState("error");
    }
  }

  useEffect(() => { load(); }, []);

  async function act(key, url, options, fallback, describe) {
    setBusy(key);
    setErrors([]);
    setStatus("");
    try {
      const response = await fetch(url, { headers, ...options });
      const body = await parseResponse(response, fallback);
      if (body === null) return;
      setStatus(describe(body));
      await load();
      // The training-day panel above shows the running day, so starting one here
      // has to reach it — otherwise the top of the screen contradicts this one.
      if (refresh) await refresh({ preserveSnapshot: true, forceAfterInFlight: true });
    } catch (actErrors) {
      setErrors(Array.isArray(actErrors) ? actErrors : [{ detail: fallback }]);
    } finally {
      setBusy("");
    }
  }

  const createDay = (slot) => act(
    `create-${slot.id}`,
    `/api/scheduled-sessions/${slot.id}/session/`,
    { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: "{}" },
    "The day could not be set up.",
    () => `“${slot.workout_name}” is set up for ${scheduleDayLabel(slot.date)}. It is not running yet — press Start when the room fills.`,
  );

  const startDay = (slot) => act(
    `start-${slot.id}`,
    `/api/sessions/${slot.session}/start/`,
    { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: "{}" },
    "That day could not be started.",
    () => `“${slot.workout_name}” is now open. The racks are following it.`,
  );

  const moveDay = (slot, date) => act(
    `move-${slot.id}`,
    `/api/scheduled-sessions/${slot.id}/`,
    { method: "PATCH", headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ date }) },
    "That day could not be moved.",
    (body) => `“${slot.workout_name}” moved to ${scheduleDayLabel(body.date)}. Nothing else in the block moved.`,
  );

  const visible = showPast ? slots : slots.filter((slot) => !isPastDate(slot.date));
  const days = groupSlotsByDate(visible);
  const pastCount = slots.length - slots.filter((slot) => !isPastDate(slot.date)).length;

  return <div className="schedule-workspace">
    <header className="workout-catalog-heading">
      <div>
        <span>Training calendar</span>
        <h2>Scheduled days</h2>
        <p>Generated when a block was deployed. Setting a day up creates its session and roster — it does not start it.</p>
      </div>
      <b>{visible.length} day{visible.length === 1 ? "" : "s"}</b>
    </header>

    {pastCount > 0 && <div className="schedule-past-toggle">
      <button type="button" className={showPast ? "" : "workout-secondary"}
        aria-pressed={showPast} onClick={() => setShowPast(!showPast)}>
        {showPast ? "Hide" : "Show"} {pastCount} past day{pastCount === 1 ? "" : "s"}
      </button>
    </div>}

    {state === "loading" && <p className="monitor-empty" role="status">Loading the schedule...</p>}
    {errors.length > 0 && <div className="schedule-errors" role="alert">
      {errors.map((error, index) => <p key={index}>{error.detail || String(error)}</p>)}
    </div>}
    {state === "error" && <button type="button" className="workout-secondary" onClick={load}>Retry</button>}
    {status && <p className="workout-status" role="status">{status}</p>}

    {state === "ready" && days.length === 0 && <p className="monitor-empty">
      No scheduled days. A block needs training days and a duration for its calendar to be generated — deploy one from the Workouts tab.
    </p>}

    <div className="schedule-day-list">{days.map((day) => <section className="schedule-day" key={day.date}>
      <header><h4>{scheduleDayLabel(day.date)}</h4><span>{day.slots.length} session{day.slots.length === 1 ? "" : "s"}</span></header>
      <div className="schedule-slot-list">{day.slots.map((slot) => <SlotRow
        key={slot.id} slot={slot} slots={slots} busy={busy}
        onCreate={createDay} onStart={startDay} onMove={moveDay} />)}</div>
    </section>)}</div>
  </div>;
}
