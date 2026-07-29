import { useEffect, useState } from "react";
import { buildAthleteAssignmentPayload, buildOverrideFields, exerciseTargetView } from "./athletePlanning.js";
import { errorLabel, flattenApiErrors, sameOriginPath } from "./workoutCatalog.js";

function PlanningErrors({ errors }) {
  if (!errors.length) return null;
  return <div className="workout-errors" role="alert"><strong>Please correct the following:</strong><ul>{errors.map((error, index) => <li key={`${error.row || ""}-${error.field || ""}-${index}`}>{errorLabel(error)}</li>)}</ul></div>;
}

export default function AthleteWorkoutPlanning({ athlete, accessToken, onLogout }) {
  const [workouts, setWorkouts] = useState([]);
  const [workoutPrograms, setWorkoutPrograms] = useState([]);
  const [assignment, setAssignment] = useState(null);
  const [workoutProgramId, setWorkoutProgramId] = useState("");
  const [selectedWorkoutId, setSelectedWorkoutId] = useState("");
  const [loading, setLoading] = useState(true);
  const [assignmentSaving, setAssignmentSaving] = useState(false);
  const [assignmentErrors, setAssignmentErrors] = useState([]);
  const [assignmentStatus, setAssignmentStatus] = useState("");
  const [overrideWorkout, setOverrideWorkout] = useState(null);
  const [overrideDrafts, setOverrideDrafts] = useState([]);
  const [overrideLoading, setOverrideLoading] = useState(false);
  const [overrideSaving, setOverrideSaving] = useState(false);
  const [overrideErrors, setOverrideErrors] = useState([]);
  const [overrideStatus, setOverrideStatus] = useState("");
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

  async function readAll(initialUrl, signal) {
    const results = [];
    let url = initialUrl;
    for (let page = 0; url && page < 20; page += 1) {
      const response = await fetch(url, { headers, signal });
      const body = await parseResponse(response, "Workout choices could not be loaded.");
      if (body === null) return [];
      results.push(...(Array.isArray(body) ? body : body.results || []));
      url = Array.isArray(body) ? null : sameOriginPath(body.next, window.location.origin);
    }
    return results;
  }

  function applyAssignment(nextAssignment) {
    setAssignment(nextAssignment);
    const program = nextAssignment?.workout_program;
    if (program) {
      setWorkoutProgramId(String(program.id));
      setSelectedWorkoutId(String(program.items?.[0]?.workout?.id || ""));
    } else {
      setWorkoutProgramId("");
      setSelectedWorkoutId("");
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setAssignmentErrors([]);
    setAssignmentStatus("");
    Promise.all([
      readAll("/api/workouts/?page_size=100", controller.signal),
      readAll("/api/workout-programs/?page_size=100", controller.signal),
      fetch(`/api/athletes/${athlete.id}/workout-assignment/`, { headers, signal: controller.signal }).then(async (response) => {
        if (response.status === 404) return null;
        return parseResponse(response, "Athlete assignment could not be loaded.");
      }),
    ]).then(([nextWorkouts, nextPrograms, body]) => {
      setWorkouts(nextWorkouts);
      setWorkoutPrograms(nextPrograms);
      applyAssignment(body?.assignment || body);
    }).catch((errors) => {
      if (errors?.name !== "AbortError") setAssignmentErrors(Array.isArray(errors) ? errors : [{ detail: "Athlete planning could not be loaded." }]);
    }).finally(() => setLoading(false));
    return () => controller.abort();
  }, [athlete.id, accessToken]);

  const chosenWorkoutId = selectedWorkoutId;

  const chosenWorkout = workouts.find((workout) => Number(workout.id) === Number(chosenWorkoutId));

  useEffect(() => {
    if (!chosenWorkoutId) {
      setOverrideWorkout(null);
      setOverrideDrafts([]);
      return undefined;
    }
    const controller = new AbortController();
    setOverrideLoading(true);
    setOverrideErrors([]);
    setOverrideStatus("");
    if (!chosenWorkout) {
      setOverrideLoading(false);
      return undefined;
    }
    const exercises = [...(chosenWorkout.exercises || [])].sort((left, right) => left.position - right.position);
    Promise.all(exercises.map((exercise) => fetch(`/api/athletes/${athlete.id}/workout-exercises/${exercise.id}/override/`, { headers, signal: controller.signal }).then(async (response) => {
      if (response.status === 404) return null;
      return parseResponse(response, "Exercise overrides could not be loaded.");
    }))).then((overrides) => {
        const effectiveExercises = exercises.map((exercise, index) => ({ ...exercise, override: overrides[index] }));
        setOverrideWorkout({ ...chosenWorkout, exercises: effectiveExercises });
        setOverrideDrafts(effectiveExercises.map((exercise) => {
          const override = exercise.override || {};
          return {
            workout_exercise_id: exercise.id,
            sets: override.sets ?? "",
            reps: override.reps ?? "",
            weight_lbs: override.weight_lbs ?? "",
          };
        }));
      })
      .catch((errors) => {
        if (errors?.name !== "AbortError") setOverrideErrors(Array.isArray(errors) ? errors : [{ detail: "Exercise overrides could not be loaded." }]);
      })
      .finally(() => setOverrideLoading(false));
    return () => controller.abort();
  }, [athlete.id, chosenWorkoutId, chosenWorkout?.id, accessToken]);

  async function saveAssignment() {
    setAssignmentSaving(true);
    setAssignmentErrors([]);
    setAssignmentStatus("");
    try {
      const response = await fetch(`/api/athletes/${athlete.id}/workout-assignment/`, {
        method: "PUT",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(buildAthleteAssignmentPayload(workoutProgramId)),
      });
      const body = await parseResponse(response, "Athlete assignment could not be saved.");
      if (body === null) return;
      applyAssignment(body.assignment || body);
      setAssignmentStatus("Athlete assignment saved.");
    } catch (errors) {
      setAssignmentErrors(Array.isArray(errors) ? errors : [{ detail: "Athlete assignment could not be saved." }]);
    } finally {
      setAssignmentSaving(false);
    }
  }

  async function removeAssignment() {
    setAssignmentSaving(true);
    setAssignmentErrors([]);
    setAssignmentStatus("");
    try {
      const response = await fetch(`/api/athletes/${athlete.id}/workout-assignment/`, { method: "DELETE", headers });
      const body = await parseResponse(response, "Athlete assignment could not be removed.");
      if (body === null) return;
      applyAssignment(null);
       setAssignmentStatus("Athlete program assignment removed.");
    } catch (errors) {
      setAssignmentErrors(Array.isArray(errors) ? errors : [{ detail: "Athlete assignment could not be removed." }]);
    } finally {
      setAssignmentSaving(false);
    }
  }

  function updateOverride(index, field, value) {
    setOverrideDrafts((current) => current.map((draft, draftIndex) => draftIndex === index ? { ...draft, [field]: value } : draft));
  }

  async function changeOverride(index, method) {
    if (!chosenWorkoutId) return;
    setOverrideSaving(true);
    setOverrideErrors([]);
    setOverrideStatus("");
    try {
      const draft = overrideDrafts[index];
      const response = await fetch(`/api/athletes/${athlete.id}/workout-exercises/${draft.workout_exercise_id}/override/`, {
          method,
          headers: { ...headers, "Content-Type": "application/json" },
          ...(method === "PATCH" ? { body: JSON.stringify(buildOverrideFields(draft)) } : {}),
        });
      const body = await parseResponse(response, `Exercise override could not be ${method === "PATCH" ? "saved" : "reset"}.`);
      if (body === null) return;
      setOverrideWorkout((current) => ({ ...current, exercises: current.exercises.map((exercise, exerciseIndex) => exerciseIndex === index ? { ...exercise, override: method === "DELETE" ? null : body } : exercise) }));
      if (method === "DELETE") setOverrideDrafts((current) => current.map((currentDraft, draftIndex) => draftIndex === index ? { ...currentDraft, sets: "", reps: "", weight_lbs: "" } : currentDraft));
      setOverrideStatus(method === "PATCH" ? `${overrideWorkout.exercises[index].exercise} overrides saved.` : `${overrideWorkout.exercises[index].exercise} reset to template targets.`);
    } catch (errors) {
      setOverrideErrors(Array.isArray(errors) ? errors : [{ detail: `Exercise overrides could not be ${method === "PATCH" ? "saved" : "reset"}.` }]);
    } finally {
      setOverrideSaving(false);
    }
  }

  const selectedProgram = workoutPrograms.find((program) => Number(program.id) === Number(workoutProgramId));
  const includedWorkouts = selectedProgram?.items || [];
  const assignmentReady = Boolean(workoutProgramId);
  const assignedItems = assignment?.workout_program?.items || [];
  const overridesAllowed = assignedItems.some((item) => Number(item.workout?.id) === Number(chosenWorkoutId));
  const assignmentLabel = assignment?.workout_program?.name || "No workout program assigned";

  return <div className="athlete-planning">
    <section className="context-section athlete-assignment-panel"><header><span>Athlete assignment</span><h3>Complete workout program for {athlete.name}</h3><p>The athlete follows this ordered program at any rack.</p></header>
      <div className="athlete-assignment-current"><span>Current</span><b>{assignmentLabel}</b></div>
      {loading ? <p className="monitor-empty" role="status">Loading athlete workout assignment...</p> : <div className="athlete-assignment-fields">
        <label>Workout program<select value={workoutProgramId} onChange={(event) => { setWorkoutProgramId(event.target.value); setSelectedWorkoutId(""); }} disabled={assignmentSaving}><option value="">Select program</option>{workoutPrograms.map((program) => <option value={program.id} key={program.id}>{program.name}</option>)}</select></label>
        <button onClick={saveAssignment} disabled={!assignmentReady || assignmentSaving}>{assignmentSaving ? "Saving..." : "Save assignment"}</button><button className="athlete-remove-assignment" onClick={removeAssignment} disabled={!assignment || assignmentSaving}>Remove assignment</button>
      </div>}
      <PlanningErrors errors={assignmentErrors} />{assignmentStatus && <p className="workout-status" role="status">{assignmentStatus}</p>}
    </section>

    <section className="context-section athlete-override-panel"><header><span>Individual targets</span><h3>Exercise overrides</h3><p>Leave a field blank to inherit its template value. Velocity targets and exercise order cannot be changed.</p></header>
      {includedWorkouts.length > 0 && <label>Program workout<select value={selectedWorkoutId} onChange={(event) => setSelectedWorkoutId(event.target.value)} disabled={overrideSaving}><option value="">Select included workout</option>{includedWorkouts.map((item) => <option value={item.workout.id} key={item.id}>{item.position}. {item.workout.name}</option>)}</select></label>}
      {!chosenWorkoutId ? <p className="monitor-empty">Choose an assigned program workout to edit this athlete’s targets.</p> : overrideLoading ? <p className="monitor-empty" role="status">Loading effective exercise targets...</p> : overrideWorkout && <>
        <div className="athlete-override-list">{overrideWorkout.exercises.map((exercise, index) => {
          const targets = exerciseTargetView(exercise);
          const draft = overrideDrafts[index] || {};
          const hasValue = [draft.sets, draft.reps, draft.weight_lbs].some((value) => value !== "" && value !== undefined);
          return <fieldset key={exercise.id}><legend>{exercise.position}. {exercise.exercise}</legend><div className="athlete-template-targets"><span>Template</span><b>{targets.sets.template} sets · {targets.reps.template} reps · {targets.weight_lbs.template} lbs</b><span>Effective</span><b>{targets.sets.effective} sets · {targets.reps.effective} reps · {targets.weight_lbs.effective} lbs</b></div><label>Sets<input type="number" min="1" step="1" value={draft.sets ?? ""} onChange={(event) => updateOverride(index, "sets", event.target.value)} placeholder={String(targets.sets.template)} disabled={overrideSaving} /></label><label>Reps<input type="number" min="1" step="1" value={draft.reps ?? ""} onChange={(event) => updateOverride(index, "reps", event.target.value)} placeholder={String(targets.reps.template)} disabled={overrideSaving} /></label><label>Weight (lbs)<input type="number" min="0" step="any" value={draft.weight_lbs ?? ""} onChange={(event) => updateOverride(index, "weight_lbs", event.target.value)} placeholder={String(targets.weight_lbs.template)} disabled={overrideSaving} /></label><div className="athlete-exercise-actions"><button type="button" className="workout-secondary" onClick={() => changeOverride(index, "DELETE")} disabled={!overridesAllowed || overrideSaving || !exercise.override}>Reset</button><button type="button" onClick={() => changeOverride(index, "PATCH")} disabled={!overridesAllowed || overrideSaving || !hasValue}>{overrideSaving ? "Saving..." : "Save"}</button></div></fieldset>;
        })}</div>
        {!overridesAllowed && <div className="context-notice">Save this workout as the athlete assignment before changing overrides.</div>}
      </>}
      <PlanningErrors errors={overrideErrors} />{overrideStatus && <p className="workout-status" role="status">{overrideStatus}</p>}
    </section>
  </div>;
}
