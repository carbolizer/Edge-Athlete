import { useEffect, useState } from "react";
import { addProgramWorkout, buildWorkoutPayload, buildWorkoutProgramPayload, createExerciseDraft, errorLabel, flattenApiErrors, moveProgramWorkout, sameOriginPath } from "./workoutCatalog.js";

const WORKOUTS_URL = "/api/workouts/";
const CSV_PREVIEW_URL = "/api/workouts/imports/preview/";
const CSV_IMPORT_URL = "/api/workouts/imports/";
const WORKOUT_PROGRAMS_URL = "/api/workout-programs/";

function ErrorList({ errors, title = "Please correct the following:" }) {
  if (!errors.length) return null;
  return <div className="workout-errors" role="alert"><strong>{title}</strong><ul>{errors.map((error, index) => <li key={`${error.row || ""}-${error.field || ""}-${index}`}>{errorLabel(error)}</li>)}</ul></div>;
}

function ExerciseSummary({ exercise }) {
  const velocity = exercise.velocity_min === null || exercise.velocity_min === undefined
    ? "No velocity target"
    : `${exercise.velocity_min}-${exercise.velocity_max} m/s`;
  return <li><b>{exercise.position}. {exercise.exercise}</b><span>{exercise.sets} x {exercise.reps} · {exercise.default_weight_lbs} lbs · {velocity}</span></li>;
}

export default function WorkoutCatalog({ accessToken, onLogout }) {
  const [workouts, setWorkouts] = useState([]);
  const [workoutCount, setWorkoutCount] = useState(0);
  const [catalogUrl, setCatalogUrl] = useState(WORKOUTS_URL);
  const [retryCatalogUrl, setRetryCatalogUrl] = useState(WORKOUTS_URL);
  const [pagination, setPagination] = useState({ previous: null, next: null });
  const [catalogState, setCatalogState] = useState("loading");
  const [catalogErrors, setCatalogErrors] = useState([]);
  const [name, setName] = useState("");
  const [exercises, setExercises] = useState([createExerciseDraft(1)]);
  const [manualErrors, setManualErrors] = useState([]);
  const [manualStatus, setManualStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const [file, setFile] = useState(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [preview, setPreview] = useState(null);
  const [csvErrors, setCsvErrors] = useState([]);
  const [csvStatus, setCsvStatus] = useState("");
  const [csvBusy, setCsvBusy] = useState("");
  const [programName, setProgramName] = useState("");
  const [selectedWorkouts, setSelectedWorkouts] = useState([]);
  const [programErrors, setProgramErrors] = useState([]);
  const [programStatus, setProgramStatus] = useState("");
  const [programSaving, setProgramSaving] = useState(false);
  const [programs, setPrograms] = useState([]);
  const [programCount, setProgramCount] = useState(0);
  const [programUrl, setProgramUrl] = useState(WORKOUT_PROGRAMS_URL);
  const [retryProgramUrl, setRetryProgramUrl] = useState(WORKOUT_PROGRAMS_URL);
  const [programPagination, setProgramPagination] = useState({ previous: null, next: null });
  const [programCatalogState, setProgramCatalogState] = useState("loading");
  const [programCatalogErrors, setProgramCatalogErrors] = useState([]);
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

  async function loadWorkouts(url = catalogUrl) {
    setCatalogState("loading");
    setCatalogErrors([]);
    setRetryCatalogUrl(url);
    try {
      const response = await fetch(url, { headers });
      const body = await parseResponse(response, "The workout catalog could not be loaded.");
      if (body === null) return;
      const results = Array.isArray(body) ? body : body.results || body.workouts || [];
      setWorkouts(results);
      setWorkoutCount(Array.isArray(body) ? body.length : body.count ?? results.length);
      setPagination({
        previous: sameOriginPath(body.previous, window.location.origin),
        next: sameOriginPath(body.next, window.location.origin),
      });
      setCatalogUrl(url);
      setCatalogState("ready");
    } catch (errors) {
      setCatalogErrors(Array.isArray(errors) ? errors : [{ detail: "The workout catalog could not be loaded." }]);
      setCatalogState("error");
    }
  }

  async function loadPrograms(url = programUrl) {
    setProgramCatalogState("loading");
    setProgramCatalogErrors([]);
    setRetryProgramUrl(url);
    try {
      const response = await fetch(url, { headers });
      const body = await parseResponse(response, "Workout programs could not be loaded.");
      if (body === null) return;
      const results = Array.isArray(body) ? body : body.results || body.workout_programs || [];
      setPrograms(results);
      setProgramCount(Array.isArray(body) ? body.length : body.count ?? results.length);
      setProgramPagination({
        previous: sameOriginPath(body.previous, window.location.origin),
        next: sameOriginPath(body.next, window.location.origin),
      });
      setProgramUrl(url);
      setProgramCatalogState("ready");
    } catch (errors) {
      setProgramCatalogErrors(Array.isArray(errors) ? errors : [{ detail: "Workout programs could not be loaded." }]);
      setProgramCatalogState("error");
    }
  }

  useEffect(() => {
    loadWorkouts(WORKOUTS_URL);
    loadPrograms(WORKOUT_PROGRAMS_URL);
  }, [accessToken]);

  function updateExercise(index, field, value) {
    setExercises((current) => current.map((exercise, exerciseIndex) => exerciseIndex === index ? { ...exercise, [field]: value } : exercise));
  }

  function removeExercise(index) {
    setExercises((current) => current.filter((_, exerciseIndex) => exerciseIndex !== index).map((exercise, exerciseIndex) => ({ ...exercise, position: exerciseIndex + 1 })));
  }

  async function createWorkout(event) {
    event.preventDefault();
    setSaving(true);
    setManualErrors([]);
    setManualStatus("");
    try {
      const response = await fetch(WORKOUTS_URL, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(buildWorkoutPayload(name, exercises)),
      });
      const body = await parseResponse(response, "The workout could not be created.");
      if (body === null) return;
      setName("");
      setExercises([createExerciseDraft(1)]);
      setManualStatus(`${body.name || name.trim()} was added to the workout catalog.`);
      await loadWorkouts(catalogUrl);
    } catch (errors) {
      setManualErrors(Array.isArray(errors) ? errors : [{ detail: "The workout could not be created." }]);
    } finally {
      setSaving(false);
    }
  }

  function chooseFile(event) {
    setFile(event.target.files?.[0] || null);
    setPreview(null);
    setCsvErrors([]);
    setCsvStatus("");
  }

  async function submitCsv(action) {
    if (!file) return;
    setCsvBusy(action);
    setCsvErrors([]);
    setCsvStatus("");
    const form = new FormData();
    form.append("file", file);
    try {
      const response = await fetch(action === "preview" ? CSV_PREVIEW_URL : CSV_IMPORT_URL, {
        method: "POST",
        headers,
        body: form,
      });
      const body = await parseResponse(response, action === "preview" ? "The CSV could not be previewed." : "The CSV could not be imported.");
      if (body === null) return;
      if (action === "preview") {
        setPreview(body);
        setCsvErrors(body.errors ? flattenApiErrors({ errors: body.errors }, "The CSV contains errors.") : []);
        setCsvStatus(body.errors?.length ? "Preview complete. No workouts were imported." : "Preview complete. Review the normalized workouts before importing.");
      } else {
        const count = body.count;
        setCsvStatus(`${count ?? "CSV"} workout${count === 1 ? "" : "s"} imported.`);
        setFile(null);
        setPreview(null);
        setFileInputKey((key) => key + 1);
        await loadWorkouts(catalogUrl);
      }
    } catch (errors) {
      setCsvErrors(Array.isArray(errors) ? errors : [{ detail: `The CSV could not be ${action === "preview" ? "previewed" : "imported"}.` }]);
      if (action === "preview") setPreview(null);
    } finally {
      setCsvBusy("");
    }
  }

  async function createWorkoutProgram(event) {
    event.preventDefault();
    if (!selectedWorkouts.length) return;
    setProgramSaving(true);
    setProgramErrors([]);
    setProgramStatus("");
    try {
      const response = await fetch(WORKOUT_PROGRAMS_URL, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(buildWorkoutProgramPayload(programName, selectedWorkouts)),
      });
      const body = await parseResponse(response, "The workout program could not be created.");
      if (body === null) return;
      setProgramName("");
      setSelectedWorkouts([]);
      setProgramStatus(`${body.name || programName.trim()} was added to the program catalog.`);
      await loadPrograms(WORKOUT_PROGRAMS_URL);
    } catch (errors) {
      setProgramErrors(Array.isArray(errors) ? errors : [{ detail: "The workout program could not be created." }]);
    } finally {
      setProgramSaving(false);
    }
  }

  const previewWorkouts = preview?.workouts || preview?.results || [];
  const previewValid = preview && csvErrors.length === 0;

  return <div className="workout-catalog context-tab-content">
    <header className="workout-catalog-heading"><div><span>Reusable training templates</span><h2>Workout catalog</h2><p>Create ordered workouts manually or validate a CSV before an atomic import.</p></div><b>{workoutCount} workout{workoutCount === 1 ? "" : "s"}</b></header>
    <div className="workout-builder-grid">
      <section className="workout-panel"><header><span>Manual builder</span><h3>New workout</h3><p>Rows are saved in the order shown.</p></header>
        <form onSubmit={createWorkout}>
          <label className="workout-name">Workout name<input value={name} onChange={(event) => setName(event.target.value)} maxLength="255" required disabled={saving} /></label>
          <div className="workout-exercise-list">
            {exercises.map((exercise, index) => <fieldset key={exercise.position}><legend>Exercise {index + 1}</legend>
              <label className="exercise-movement">Movement<input value={exercise.exercise} onChange={(event) => updateExercise(index, "exercise", event.target.value)} required disabled={saving} /></label>
              <label>Sets<input type="number" min="1" step="1" value={exercise.sets} onChange={(event) => updateExercise(index, "sets", event.target.value)} required disabled={saving} /></label>
              <label>Reps<input type="number" min="1" step="1" value={exercise.reps} onChange={(event) => updateExercise(index, "reps", event.target.value)} required disabled={saving} /></label>
              <label>Weight (lbs)<input type="number" min="0" step="any" value={exercise.default_weight_lbs} onChange={(event) => updateExercise(index, "default_weight_lbs", event.target.value)} required disabled={saving} /></label>
              <label>Velocity min<input type="number" min="0" max="10" step="any" value={exercise.velocity_min} onChange={(event) => updateExercise(index, "velocity_min", event.target.value)} disabled={saving} /></label>
              <label>Velocity max<input type="number" min="0" max="10" step="any" value={exercise.velocity_max} onChange={(event) => updateExercise(index, "velocity_max", event.target.value)} disabled={saving} /></label>
              <button type="button" className="workout-remove" onClick={() => removeExercise(index)} disabled={exercises.length === 1 || saving} aria-label={`Remove exercise ${index + 1}`}>Remove</button>
            </fieldset>)}
          </div>
          <div className="workout-form-actions"><button type="button" className="workout-secondary" onClick={() => setExercises((current) => [...current, createExerciseDraft(current.length + 1)])} disabled={saving}>Add exercise</button><button type="submit" disabled={saving}>{saving ? "Creating..." : "Create workout"}</button></div>
          <ErrorList errors={manualErrors} />
          {manualStatus && <p className="workout-status" role="status">{manualStatus}</p>}
        </form>
      </section>

      <section className="workout-panel workout-csv"><header><span>CSV import</span><h3>Preview before import</h3><p>Accepted files use the eight-column workout CSV contract.</p></header>
        <label className="workout-file">CSV file<input key={fileInputKey} type="file" accept=".csv,text/csv" onChange={chooseFile} disabled={Boolean(csvBusy)} /></label>
        {file && <p className="workout-file-name">Selected: <b>{file.name}</b> · {(file.size / 1024).toFixed(1)} KB</p>}
        <div className="workout-form-actions"><button type="button" className="workout-secondary" onClick={() => submitCsv("preview")} disabled={!file || Boolean(csvBusy)}>{csvBusy === "preview" ? "Previewing..." : "Preview CSV"}</button><button type="button" onClick={() => submitCsv("import")} disabled={!file || !previewValid || Boolean(csvBusy)}>{csvBusy === "import" ? "Importing..." : "Import workouts"}</button></div>
        <ErrorList errors={csvErrors} title="CSV validation errors:" />
        {csvStatus && <p className="workout-status" role="status">{csvStatus}</p>}
        {preview && <div className="workout-preview"><h4>Normalized preview</h4>{previewWorkouts.length === 0 ? <p className="monitor-empty">No valid workouts to preview.</p> : previewWorkouts.map((workout, index) => <article key={workout.name || index}><strong>{workout.name}</strong><ol>{(workout.exercises || []).map((exercise) => <ExerciseSummary exercise={exercise} key={`${exercise.position}-${exercise.exercise}`} />)}</ol></article>)}</div>}
      </section>
    </div>

    <section className="workout-panel workout-catalog-list"><header><span>Saved catalog</span><h3>Available workouts</h3><p>Exercises appear in prescribed order.</p></header>
      {catalogState === "loading" && <p className="monitor-empty" role="status">Loading workout page...</p>}
      <ErrorList errors={catalogErrors} title="Catalog unavailable:" />
      {catalogState === "error" && <button type="button" className="workout-secondary" onClick={() => loadWorkouts(retryCatalogUrl)}>Retry page</button>}
      {catalogState !== "loading" && workoutCount === 0 && <p className="monitor-empty">No workouts have been created.</p>}
      <div className="workout-card-grid">{workouts.map((workout) => {
        const selected = selectedWorkouts.some((item) => Number(item.id) === Number(workout.id));
        return <article key={workout.id || workout.name}><header><span>{workout.exercises?.length || 0} exercise{workout.exercises?.length === 1 ? "" : "s"}</span><h4>{workout.name}</h4></header><ol>{(workout.exercises || []).map((exercise) => <ExerciseSummary exercise={exercise} key={`${exercise.position}-${exercise.exercise}`} />)}</ol><button type="button" className="workout-card-add" onClick={() => setSelectedWorkouts((current) => addProgramWorkout(current, workout))} disabled={selected}>{selected ? "Added to program" : "Add to program"}</button></article>;
      })}</div>
      {(pagination.previous || pagination.next || workoutCount > workouts.length) && <nav className="workout-pagination" aria-label="Workout catalog pages"><button type="button" className="workout-secondary" onClick={() => loadWorkouts(pagination.previous)} disabled={!pagination.previous || catalogState === "loading"}>Previous</button><span role="status">Showing {workouts.length} on this page · {workoutCount} total</span><button type="button" onClick={() => loadWorkouts(pagination.next)} disabled={!pagination.next || catalogState === "loading"}>Next</button></nav>}
    </section>

    <div className="workout-program-grid">
      <section className="workout-panel workout-program-builder"><header><span>Program builder</span><h3>New workout program</h3><p>Select workouts from any catalog page, then arrange their training order.</p></header>
        <form onSubmit={createWorkoutProgram}>
          <label>Program name<input value={programName} onChange={(event) => setProgramName(event.target.value)} maxLength="255" required disabled={programSaving} /></label>
          <div className="program-draft" aria-live="polite">
            <h4>Selected workouts <span>{selectedWorkouts.length}</span></h4>
            {selectedWorkouts.length === 0 ? <p className="monitor-empty">Use “Add to program” on a workout card.</p> : <ol>{selectedWorkouts.map((workout, index) => <li key={workout.id}><b><span>{index + 1}</span>{workout.name}</b><div><button type="button" onClick={() => setSelectedWorkouts((current) => moveProgramWorkout(current, index, -1))} disabled={index === 0 || programSaving} aria-label={`Move ${workout.name} up`}>Up</button><button type="button" onClick={() => setSelectedWorkouts((current) => moveProgramWorkout(current, index, 1))} disabled={index === selectedWorkouts.length - 1 || programSaving} aria-label={`Move ${workout.name} down`}>Down</button><button type="button" className="program-remove" onClick={() => setSelectedWorkouts((current) => current.filter((item) => Number(item.id) !== Number(workout.id)))} disabled={programSaving} aria-label={`Remove ${workout.name} from program`}>Remove</button></div></li>)}</ol>}
          </div>
          <div className="workout-form-actions"><button type="submit" disabled={!selectedWorkouts.length || programSaving}>{programSaving ? "Creating..." : "Create program"}</button></div>
          <ErrorList errors={programErrors} />
          {programStatus && <p className="workout-status" role="status">{programStatus}</p>}
        </form>
      </section>

      <section className="workout-panel workout-program-browser"><header><span>Saved programs</span><h3>Program catalog</h3><p>{programCount} program{programCount === 1 ? "" : "s"}, with workouts in prescribed order.</p></header>
        {programCatalogState === "loading" && <p className="monitor-empty" role="status">Loading program page...</p>}
        <ErrorList errors={programCatalogErrors} title="Program catalog unavailable:" />
        {programCatalogState === "error" && <button type="button" className="workout-secondary" onClick={() => loadPrograms(retryProgramUrl)}>Retry page</button>}
        {programCatalogState !== "loading" && programCount === 0 && <p className="monitor-empty">No workout programs have been created.</p>}
        <div className="program-browser-list">{programs.map((program) => <article key={program.id || program.name}><header><span>{program.items?.length || 0} workout{program.items?.length === 1 ? "" : "s"}</span><h4>{program.name}</h4></header><ol>{(program.items || []).map((membership, index) => <li key={membership.id || membership.workout_id || membership.workout?.id || index}><span>{membership.position ?? index + 1}</span><b>{membership.workout?.name || membership.workout_name || membership.name || "Workout unavailable"}</b></li>)}</ol></article>)}</div>
        {(programPagination.previous || programPagination.next || programCount > programs.length) && <nav className="workout-pagination" aria-label="Workout program catalog pages"><button type="button" className="workout-secondary" onClick={() => loadPrograms(programPagination.previous)} disabled={!programPagination.previous || programCatalogState === "loading"}>Previous</button><span role="status">Showing {programs.length} on this page · {programCount} total</span><button type="button" onClick={() => loadPrograms(programPagination.next)} disabled={!programPagination.next || programCatalogState === "loading"}>Next</button></nav>}
      </section>
    </div>
  </div>;
}
