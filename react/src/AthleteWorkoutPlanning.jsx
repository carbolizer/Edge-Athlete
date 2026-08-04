import { useEffect, useState } from "react";
import { addWorkoutOccurrence, buildSchedulePayload, confirmedProgramSelection, materializeProgram, moveOccurrence, normalizeSchedule, scheduleValidation, validationErrorsAt, WEEKDAYS } from "./athletePlanning.js";
import { errorLabel, flattenApiErrors, sameOriginPath } from "./workoutCatalog.js";

function PlanningErrors({ errors }) {
  if (!errors.length) return null;
  return <div className="workout-errors" role="alert"><strong>Schedule not saved:</strong><ul>{errors.map((error, index) => <li key={index}>{typeof error === "string" ? error : errorLabel(error)}</li>)}</ul></div>;
}

function FieldErrors({ errors, path, exact = false }) {
  const local = exact ? errors.filter((error) => error?.path === path) : validationErrorsAt(errors, path);
  if (!local.length) return null;
  return <div className="schedule-field-errors">{local.map((error, index) => <p key={`${error.path}-${index}`}>{error.detail}</p>)}</div>;
}

export default function AthleteWorkoutPlanning({ athlete, accessToken, onLogout }) {
  const empty = { version: 0, training_date: "", plans: [], entries: [] };
  const [draft, setDraft] = useState(empty);
  const [savedDraft, setSavedDraft] = useState(empty);
  const [workouts, setWorkouts] = useState([]);
  const [programs, setPrograms] = useState([]);
  const [sourceProgramId, setSourceProgramId] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState([]);
  const [status, setStatus] = useState("");
  const headers = { Accept: "application/json", Authorization: `Bearer ${accessToken}` };
  const dirty = JSON.stringify(draft) !== JSON.stringify(savedDraft);
  const plan = draft.plans[0];

  async function parse(response, fallback) {
    if (response.status === 401 || response.status === 403) { onLogout(); return null; }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw flattenApiErrors(body, fallback);
    return body;
  }

  async function readAll(url, signal) {
    const rows = [];
    for (let page = 0; url && page < 20; page += 1) {
      const body = await parse(await fetch(url, { headers, signal }), "Planning catalogs could not be loaded.");
      if (!body) return [];
      rows.push(...(Array.isArray(body) ? body : body.results || []));
      url = Array.isArray(body) ? null : sameOriginPath(body.next, window.location.origin);
    }
    return rows;
  }

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setErrors([]); setStatus("");
    Promise.all([
      readAll("/api/workouts/?page_size=100", controller.signal),
      readAll("/api/workout-programs/?page_size=100", controller.signal),
      fetch(`/api/athletes/${athlete.id}/schedule/`, { headers, signal: controller.signal }).then((response) => response.status === 404 ? null : parse(response, "Schedule could not be loaded.")),
    ]).then(([nextWorkouts, nextPrograms, schedule]) => {
      const normalized = normalizeSchedule(schedule);
      setWorkouts(nextWorkouts); setPrograms(nextPrograms); setDraft(normalized); setSavedDraft(normalized);
      setSourceProgramId(String(normalized.plans[0]?.workout_program_id || ""));
    }).catch((caught) => { if (caught?.name !== "AbortError") setErrors(Array.isArray(caught) ? caught : [{ detail: "Athlete schedule could not be loaded." }]); }).finally(() => setLoading(false));
    return () => controller.abort();
  }, [athlete.id, accessToken]);

  useEffect(() => {
    const warn = (event) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.__edgePlanningDirty = { ...window.__edgePlanningDirty, schedule: dirty };
    window.addEventListener("beforeunload", warn);
    return () => { window.removeEventListener("beforeunload", warn); window.__edgePlanningDirty = { ...window.__edgePlanningDirty, schedule: false }; };
  }, [dirty]);

  function chooseProgram(id) {
    const selection = confirmedProgramSelection(sourceProgramId, id, dirty, () => window.confirm("Replace the current unsaved athlete plan with this program?"));
    if (!selection.confirmed) return;
    const program = programs.find((row) => Number(row.id) === Number(id));
    if (!program) return;
    setSourceProgramId(selection.id);
    const expanded = { ...program, items: (program.items || []).map((item) => ({ ...item, workout: workouts.find((workout) => Number(workout.id) === Number(item.workout.id)) || item.workout })) };
    setDraft((current) => ({ ...current, plans: [materializeProgram(expanded)] }));
  }

  function changePlan(updater) { setDraft((current) => ({ ...current, plans: [updater(current.plans[0])] })); }
  function updateExercise(workoutIndex, exerciseIndex, field, value) {
    changePlan((current) => ({ ...current, workouts: current.workouts.map((workout, index) => index !== workoutIndex ? workout : { ...workout, exercises: workout.exercises.map((exercise, row) => row === exerciseIndex ? { ...exercise, [field]: value } : exercise) }) }));
  }

  async function save(event) {
    event.preventDefault();
    const validation = scheduleValidation(draft);
    if (validation.length) { setErrors(validation); return; }
    setSaving(true); setErrors([]); setStatus("");
    try {
      const body = await parse(await fetch(`/api/athletes/${athlete.id}/schedule/`, { method: "PUT", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(buildSchedulePayload(draft)) }), "Schedule could not be saved.");
      if (!body) return;
      const normalized = normalizeSchedule(body);
      setDraft(normalized); setSavedDraft(normalized); setStatus(`Schedule version ${normalized.version} saved atomically.`);
    } catch (caught) { setErrors(Array.isArray(caught) ? caught : [{ detail: "Schedule could not be saved." }]); }
    finally { setSaving(false); }
  }

  function discard() {
    if (dirty && !window.confirm("Discard all unsaved schedule changes?")) return;
    setDraft(savedDraft); setErrors([]); setStatus("Unsaved changes discarded.");
    setSourceProgramId(String(savedDraft.plans[0]?.workout_program_id || ""));
  }

  if (loading) return <p className="monitor-empty" role="status">Loading athlete schedule...</p>;
  return <form className="athlete-planning schedule-editor" onSubmit={save}>
    <section className="context-section athlete-assignment-panel"><header><span>Server-local schedule</span><h3>{athlete.name}</h3><p>Exact dates take precedence over recurring weekdays. Removing an exact date restores weekday resolution.</p></header>
      <div className="schedule-source-row"><label>Materialize source program<select value={sourceProgramId} onChange={(event) => chooseProgram(event.target.value)} disabled={saving}><option value="">Choose a program</option>{programs.map((program) => <option key={program.id} value={program.id}>{program.name}</option>)}</select></label><b>Version {draft.version || "new"}</b>{dirty && <span>Unsaved changes</span>}</div>
      <div className="schedule-entry-list"><header><h4>When this plan applies</h4><button type="button" className="workout-secondary" onClick={() => setDraft((current) => ({ ...current, entries: [...current.entries, { selector_type: "weekday", weekday: "", date: "", is_rest: false, plan_client_id: plan?.client_id || "main" }] }))} disabled={!plan}>Add schedule entry</button></header>
        {draft.entries.length === 0 ? <><p className="monitor-empty">No explicit schedule. Add a program, then weekdays or exact dates.</p><FieldErrors errors={errors} path="entries" /></> : draft.entries.map((entry, index) => {
          const selectorType = entry.selector_type || (entry.date ? "date" : "weekday");
          const entryErrors = validationErrorsAt(errors, `entries.${index}`);
          return <fieldset className={entryErrors.length ? "has-errors" : ""} key={index}><legend>Entry {index + 1}</legend><label>Type<select value={selectorType} onChange={(event) => setDraft((current) => ({ ...current, entries: current.entries.map((row, i) => i !== index ? row : event.target.value === "date" ? { ...row, selector_type: "date", date: current.training_date || "", weekday: "" } : { ...row, selector_type: "weekday", date: "", weekday: 0 }) }))}><option value="weekday">Recurring weekday</option><option value="date">Exact date</option></select></label>{selectorType === "date" ? <label>Exact date<input type="date" value={entry.date} aria-invalid={validationErrorsAt(errors, `entries.${index}.date`).length > 0} onChange={(event) => setDraft((current) => ({ ...current, entries: current.entries.map((row, i) => i === index ? { ...row, date: event.target.value } : row) }))} /><FieldErrors errors={errors} path={`entries.${index}.date`} /></label> : <label>Weekday<select value={entry.weekday} aria-invalid={validationErrorsAt(errors, `entries.${index}.weekday`).length > 0} onChange={(event) => setDraft((current) => ({ ...current, entries: current.entries.map((row, i) => i === index ? { ...row, weekday: event.target.value } : row) }))}><option value="">Choose weekday</option>{WEEKDAYS.map((day, dayIndex) => <option value={dayIndex} key={day}>{day}</option>)}</select><FieldErrors errors={errors} path={`entries.${index}.weekday`} /></label>}<label className="schedule-rest"><input type="checkbox" checked={entry.is_rest} onChange={(event) => setDraft((current) => ({ ...current, entries: current.entries.map((row, i) => i === index ? { ...row, is_rest: event.target.checked, plan_client_id: event.target.checked ? null : plan?.client_id || "main" } : row) }))} />Explicit rest</label><button type="button" className="program-remove" onClick={() => setDraft((current) => ({ ...current, entries: current.entries.filter((_, i) => i !== index) }))}>Remove</button><FieldErrors errors={errors} path={`entries.${index}.selector`} /></fieldset>;
        })}
      </div>
    </section>
    <section className="context-section athlete-override-panel"><header><span>Athlete-local materialization</span><h3>Ordered workout occurrences</h3><p>Duplicates are allowed. Targets belong to this occurrence and do not alter shared templates or an active day.</p></header>
      {!plan ? <><p className="monitor-empty">Choose a source program to begin.</p><FieldErrors errors={errors} path="plan.workouts" /></> : <><div className="schedule-add-workout"><label>Add catalog workout<select defaultValue="" onChange={(event) => { const workout = workouts.find((row) => Number(row.id) === Number(event.target.value)); if (workout) changePlan((current) => addWorkoutOccurrence(current, workout)); event.target.value = ""; }}><option value="">Select workout</option>{workouts.map((workout) => <option value={workout.id} key={workout.id}>{workout.name}</option>)}</select></label></div><ol className="schedule-workouts">{plan.workouts.map((workout, workoutIndex) => <li className={validationErrorsAt(errors, `plan.workouts.${workoutIndex}`).length ? "has-errors" : ""} key={`${workout.workout_id}-${workoutIndex}`}><header><span>{workoutIndex + 1}</span><h4>{workout.name}</h4><div><button type="button" onClick={() => changePlan((current) => ({ ...current, workouts: moveOccurrence(current.workouts, workoutIndex, -1) }))} disabled={workoutIndex === 0}>Up</button><button type="button" onClick={() => changePlan((current) => ({ ...current, workouts: moveOccurrence(current.workouts, workoutIndex, 1) }))} disabled={workoutIndex === plan.workouts.length - 1}>Down</button><button type="button" className="program-remove" onClick={() => changePlan((current) => ({ ...current, workouts: current.workouts.filter((_, index) => index !== workoutIndex) }))}>Remove</button></div></header><FieldErrors errors={errors} path={`plan.workouts.${workoutIndex}`} exact /><div className="schedule-exercises">{workout.exercises.map((exercise, exerciseIndex) => <fieldset className={validationErrorsAt(errors, `plan.workouts.${workoutIndex}.exercises.${exerciseIndex}`).length ? "has-errors" : ""} key={exercise.workout_exercise_id}><legend>{exerciseIndex + 1}. {exercise.exercise}</legend>{[["sets", "Sets", 1], ["reps", "Reps", 1], ["weight_lbs", "Weight (lbs)", 0]].map(([field, label, min]) => { const path = `plan.workouts.${workoutIndex}.exercises.${exerciseIndex}.${field}`; return <label key={field}>{label}<input type="number" min={min} step={field === "weight_lbs" ? "any" : "1"} value={exercise[field]} aria-invalid={validationErrorsAt(errors, path).length > 0} onChange={(event) => updateExercise(workoutIndex, exerciseIndex, field, event.target.value)} /><FieldErrors errors={errors} path={path} /></label>; })}</fieldset>)}</div></li>)}</ol></>}
      <PlanningErrors errors={errors} />{status && <p className="workout-status" role="status">{status}</p>}
      <div className="athlete-override-actions"><button type="button" className="workout-secondary" onClick={discard} disabled={!dirty || saving}>Discard changes</button><button type="submit" disabled={!dirty || saving}>{saving ? "Saving atomically..." : "Save schedule"}</button></div>
    </section>
  </form>;
}
