// WorkoutCatalog.jsx — where a coach designs training and puts it to work.
//
// Three things happen on this screen, in the order a coach actually does them:
//
//   1. BUILD A BLOCK      A block is the reusable template: a name, how many
//                         weeks it runs, and which days of the week it's
//                         trained. It has no group and no dates — it's the
//                         recipe, not a serving of it.
//
//   2. ADD DAYS TO IT     Each day ("Day 1 — Lower") belongs to one block and
//                         holds its movements in order. A day cannot exist on
//                         its own.
//
//   3. DEPLOY IT          Pick a block, a group, and a start date, and the
//                         template is copied down into a real plan those
//                         athletes train. The copy is independent from that
//                         moment on, so editing it never disturbs the template.
//
// The thing to understand about every prescription here: the load is a
// PERCENTAGE OF EACH ATHLETE'S OWN MAX, never a number of pounds. One line —
// "Back squat, 5x3 @ 80%" — serves a whole group, and each athlete's actual bar
// weight is worked out from their own tested max when they reach the rack. A
// coach who has no max on file for someone sees that plainly rather than
// getting a guessed number.
//
// Movements are chosen from the shared exercise catalog rather than typed, so
// "Back Squat" and "back squat" can never drift into two different movements.
//
// Days can be created but NOT yet renamed, removed, or reordered — those routes
// don't exist. See P10 in the merge canon.

import { useEffect, useState } from "react";
import { applyCorrection, buildDeployPayload, buildTrainingBlockPayload, buildWorkoutPayload, CADENCE_DAYS, correctionKind, countCorrections, createExerciseDraft, errorLabel, flattenApiErrors, MAX_TARGET_PERCENT, MIN_TARGET_PERCENT, repairableErrors, repairChoices, sameOriginPath, toggleCadenceDay } from "./workoutCatalog.js";

const TRAINING_BLOCKS_URL = "/api/training-blocks/";
const CSV_PREVIEW_URL = "/api/imports/preview/";
const CSV_IMPORT_URL = "/api/imports/";
// A day lives inside a block, so its URL says so.
const blockWorkoutsUrl = (blockId) => `/api/training-blocks/${blockId}/workouts/`;
const EXERCISES_URL = "/api/exercises/";
const TRAINING_GROUPS_URL = "/api/training-groups/";
const DEPLOY_URL = "/api/training-programs/";
const ATHLETES_URL = "/api/athletes/";

// One unmatched name, and the answer to "who did you mean?".
//
// The choices are ordered closest-match-first, but the full list is always
// underneath: the suggestion algorithm can miss, and a coach who knows the
// answer shouldn't be blocked because it did. Picking here fixes EVERY row
// spelled that way, which is what makes this better than editing the file.
function RepairRow({ error, records, value, onPick, disabled }) {
  const kind = correctionKind(error.code);
  const choices = repairChoices(error, records);
  const label = { athlete: "athlete", exercise: "movement", training_group: "group" }[kind] || "record";
  return (
    <fieldset className="workout-repair-row">
      <legend>{error.row ? `Row ${error.row}` : "Sheet"} · <b>{error.value}</b></legend>
      <p className="monitor-empty">{error.detail}</p>
      <label>Which {label} is this?
        <select value={value ?? ""} onChange={(event) => onPick(kind, error.value, event.target.value)} disabled={disabled}>
          <option value="">Not matched yet</option>
          {choices.map((choice) => (
            <option value={choice.id} key={choice.id}>{choice.suggested ? `${choice.name}  (closest match)` : choice.name}</option>
          ))}
        </select>
      </label>
    </fieldset>
  );
}

// The coach's own sheet, read back to them the way we understood it. Each of
// the three sheet types has its own shape, so each gets its own columns rather
// than a lowest-common-denominator table that suits none of them.
function PreviewRows({ sheetType, rows }) {
  if (sheetType === "plan") {
    return <>{rows.map((workout, index) => (
      <article key={workout.name || index}><strong>{workout.name}</strong><ol>{(workout.exercises || []).map((exercise, exerciseIndex) => <ExerciseSummary exercise={exercise} key={`${exercise.position}-${exercise.exercise}-${exerciseIndex}`} />)}</ol></article>
    ))}</>;
  }
  if (sheetType === "reference_max") {
    return <ol className="workout-preview-rows">{rows.map((row, index) => (
      <li key={index}><b>{row.athlete_name || row.athlete}</b><span>{row.exercise_name || row.exercise} · {row.max_lbs ?? row.weight_lbs} lbs{row.reps ? ` × ${row.reps}` : ""}</span></li>
    ))}</ol>;
  }
  return <ol className="workout-preview-rows">{rows.map((row, index) => (
    <li key={index}><b>{row.athlete_name || row.name}</b>{row.training_group ? <span>{row.training_group}</span> : null}</li>
  ))}</ol>;
}

function ErrorList({ errors, title = "Please correct the following:" }) {
  if (!errors.length) return null;
  return <div className="workout-errors" role="alert"><strong>{title}</strong><ul>{errors.map((error, index) => <li key={`${error.row || ""}-${error.field || ""}-${index}`}>{errorLabel(error)}</li>)}</ul></div>;
}

// One prescription line as the coach reads it back: "1. Back squat — 5 x 3 @
// 80% · 0.5-0.8 m/s". The percent is the whole point; there is no pounds value
// to show, because the pounds differ per athlete.
function ExerciseSummary({ exercise }) {
  const velocity = exercise.velocity_zone_min === null || exercise.velocity_zone_min === undefined
    ? "No velocity target"
    : `${exercise.velocity_zone_min}-${exercise.velocity_zone_max} m/s`;
  const name = exercise.exercise_name || exercise.exercise;
  return <li><b>{exercise.position}. {name}</b><span>{exercise.sets} x {exercise.reps} @ {exercise.target_percent}% of max · {velocity}</span></li>;
}

export default function WorkoutCatalog({ accessToken, onLogout }) {
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
  // The coach's answers to "who did you mean?", kept across re-checks so a fix
  // made on the first pass is still applied on the second.
  const [corrections, setCorrections] = useState({});
  const [rawErrors, setRawErrors] = useState([]);
  const [athletes, setAthletes] = useState([]);
  // the movement catalog and the TrainingGroups, for the pickers
  const [movements, setMovements] = useState([]);
  const [groups, setGroups] = useState([]);
  // which block the manual builder is adding a day to, and where in the block
  const [workoutBlockId, setWorkoutBlockId] = useState("");
  const [workoutPosition, setWorkoutPosition] = useState("");
  // block builder
  const [programName, setProgramName] = useState("");
  const [durationWeeks, setDurationWeeks] = useState("");
  const [cadenceDays, setCadenceDays] = useState([]);
  const [programErrors, setProgramErrors] = useState([]);
  const [programStatus, setProgramStatus] = useState("");
  const [programSaving, setProgramSaving] = useState(false);
  // deploy panel
  const [deployBlockId, setDeployBlockId] = useState("");
  const [deployGroupId, setDeployGroupId] = useState("");
  const [deployName, setDeployName] = useState("");
  const [deployStart, setDeployStart] = useState("");
  const [deployEnd, setDeployEnd] = useState("");
  const [deployErrors, setDeployErrors] = useState([]);
  const [deployStatus, setDeployStatus] = useState("");
  const [deploySaving, setDeploySaving] = useState(false);
  const [programs, setPrograms] = useState([]);
  const [programCount, setProgramCount] = useState(0);
  const [programUrl, setProgramUrl] = useState(TRAINING_BLOCKS_URL);
  const [retryProgramUrl, setRetryProgramUrl] = useState(TRAINING_BLOCKS_URL);
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
    loadPrograms(TRAINING_BLOCKS_URL);
    // The two pickers. Both are small, rarely-changing lists, so they load once
    // and are not paginated. A failure here leaves an empty dropdown rather than
    // breaking the screen — the panels that need them disable themselves.
    fetch(EXERCISES_URL, { headers })
      .then((r) => (r.ok ? r.json() : []))
      .then((body) => setMovements(Array.isArray(body) ? body : body.results || []))
      .catch(() => setMovements([]));
    fetch(TRAINING_GROUPS_URL, { headers })
      .then((r) => (r.ok ? r.json() : []))
      .then((body) => setGroups(Array.isArray(body) ? body : body.results || []))
      .catch(() => setGroups([]));
    // Needed by the repair grid: the server's suggestions come back as names,
    // and a correction has to name an id.
    fetch(ATHLETES_URL, { headers })
      .then((r) => (r.ok ? r.json() : []))
      .then((body) => setAthletes(Array.isArray(body) ? body : body.results || []))
      .catch(() => setAthletes([]));
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
      const response = await fetch(blockWorkoutsUrl(workoutBlockId), {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(buildWorkoutPayload(name, exercises, workoutPosition)),
      });
      const body = await parseResponse(response, "The workout could not be created.");
      if (body === null) return;
      setName("");
      setWorkoutPosition("");
      setExercises([createExerciseDraft(1)]);
      setManualStatus(`${body.name || name.trim()} was added to the block.`);
      await loadPrograms(programUrl);
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
    // A different file means the old answers are about names that may not even
    // appear in it.
    setCorrections({});
    setRawErrors([]);
  }

  async function submitCsv(action) {
    if (!file) return;
    setCsvBusy(action);
    setCsvErrors([]);
    setCsvStatus("");
    const form = new FormData();
    form.append("file", file);
    // The server re-reads the file from scratch every time and never trusts a
    // previous preview, so the coach's answers have to travel with it or they
    // are forgotten and the same errors come back.
    if (countCorrections(corrections)) form.append("corrections", JSON.stringify(corrections));
    // A plan needs to know which block it belongs to; the other sheet types use
    // it, when given, only to tell two same-named athletes apart.
    if (workoutBlockId) form.append("training_block", workoutBlockId);
    try {
      const response = await fetch(action === "preview" ? CSV_PREVIEW_URL : CSV_IMPORT_URL, {
        method: "POST",
        headers,
        body: form,
      });
      if (response.status === 401 || response.status === 403) { onLogout(); return; }
      const body = await response.json().catch(() => ({}));

      // A sheet with problems comes back as 400 WITH the rows and the errors
      // both present — that is the whole repair loop, so it must not be treated
      // as a plain failure and thrown away (canon D17c).
      const repairable = Array.isArray(body.errors) && Array.isArray(body.rows);
      if (!response.ok && !repairable) {
        throw flattenApiErrors(body, action === "preview" ? "The CSV could not be previewed." : "The CSV could not be imported.");
      }

      setRawErrors(body.errors || []);
      setCsvErrors(body.errors?.length ? flattenApiErrors({ errors: body.errors }, "The CSV contains errors.") : []);

      if (body.errors?.length) {
        setPreview(body);
        const repairs = repairableErrors(body.errors).length;
        setCsvStatus(repairs
          ? `Nothing was imported. ${repairs} name${repairs === 1 ? "" : "s"} need${repairs === 1 ? "s" : ""} to be matched below — fix them here and import again without editing the file.`
          : "Nothing was imported. Correct the errors listed below.");
        return;
      }

      if (action === "preview") {
        setPreview(body);
        setCsvStatus(`Preview complete. ${body.counts?.ready ?? 0} row${body.counts?.ready === 1 ? "" : "s"} ready${body.counts?.skipped ? `, ${body.counts.skipped} skipped` : ""}. Nothing has been saved yet.`);
        return;
      }

      const count = body.created ?? body.counts?.ready;
      setCsvStatus(`${count ?? "CSV"} row${count === 1 ? "" : "s"} imported.`);
      setFile(null);
      setPreview(null);
      setCorrections({});
      setRawErrors([]);
      setFileInputKey((key) => key + 1);
      await loadPrograms(programUrl);
    } catch (errors) {
      setCsvErrors(Array.isArray(errors) ? errors : [{ detail: `The CSV could not be ${action === "preview" ? "previewed" : "imported"}.` }]);
      if (action === "preview") setPreview(null);
    } finally {
      setCsvBusy("");
    }
  }

  // Step 1: create the empty template. Days are added to it afterwards.
  async function createTrainingBlock(event) {
    event.preventDefault();
    setProgramSaving(true);
    setProgramErrors([]);
    setProgramStatus("");
    try {
      const response = await fetch(TRAINING_BLOCKS_URL, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(buildTrainingBlockPayload(programName, durationWeeks, cadenceDays)),
      });
      const body = await parseResponse(response, "The block could not be created.");
      if (body === null) return;
      setProgramName("");
      setDurationWeeks("");
      setCadenceDays([]);
      setProgramStatus(`${body.name || programName.trim()} was created. Add its days below.`);
      // Select it in the day builder — creating a block is almost always
      // followed by filling it in, so save the coach the extra click.
      if (body.id) setWorkoutBlockId(String(body.id));
      await loadPrograms(TRAINING_BLOCKS_URL);
    } catch (errors) {
      setProgramErrors(Array.isArray(errors) ? errors : [{ detail: "The block could not be created." }]);
    } finally {
      setProgramSaving(false);
    }
  }

  // Step 3: copy a template down for one group, starting on a real date. This is
  // the step that turns a design into something athletes are actually training.
  async function deployBlock(event) {
    event.preventDefault();
    setDeploySaving(true);
    setDeployErrors([]);
    setDeployStatus("");
    try {
      const response = await fetch(DEPLOY_URL, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(buildDeployPayload(deployName, deployGroupId, deployBlockId, deployStart, deployEnd)),
      });
      const body = await parseResponse(response, "The block could not be deployed.");
      if (body === null) return;
      setDeployName("");
      setDeployStart("");
      setDeployEnd("");
      setDeployStatus(`${body.name || deployName.trim()} is now running for ${body.group_name || "the selected group"}.`);
    } catch (errors) {
      setDeployErrors(Array.isArray(errors) ? errors : [{ detail: "The block could not be deployed." }]);
    } finally {
      setDeploySaving(false);
    }
  }

  function pickCorrection(kind, value, recordId) {
    setCorrections((current) => applyCorrection(current, kind, value, recordId));
  }

  // Two kinds of problem, and they need different treatment. A name we couldn't
  // match is a question the coach can answer right here; a missing column or an
  // unreadable file is not, and pretending otherwise wastes their time.
  // Every day across every block, flattened for the catalog list, each carrying
  // the block it came from — "Day 1" means nothing without it.
  const allDays = programs.flatMap((block) =>
    (block.workouts || []).map((workout) => ({ block, workout })));

  const repairs = repairableErrors(rawErrors);
  const otherErrors = repairs.length ? csvErrors.filter((error) => !correctionKind(error.code)) : csvErrors;
  const repairedCount = repairs.filter((error) => corrections[correctionKind(error.code)]?.[error.value] !== undefined).length;
  const allRepaired = repairs.length > 0 && repairedCount === repairs.length;
  const previewRows = preview?.rows || [];

  return <div className="workout-catalog context-tab-content">
    <header className="workout-catalog-heading"><div><span>Reusable training templates</span><h2>Workout catalog</h2><p>Design a block, fill it with days, then deploy it to a group. Loads are a percent of each athlete's own max.</p></div><b>{programCount} block{programCount === 1 ? "" : "s"} · {allDays.length} day{allDays.length === 1 ? "" : "s"}</b></header>
    <div className="workout-builder-grid">
      <section className="workout-panel"><header><span>Manual builder</span><h3>Add a day to a block</h3><p>Movements are saved in the order shown. Loads are a percent of each athlete's own max.</p></header>
        <form onSubmit={createWorkout}>
          <label className="workout-name">Block<select value={workoutBlockId} onChange={(event) => setWorkoutBlockId(event.target.value)} required disabled={saving || !programs.length}><option value="">{programs.length ? "Select a block" : "Create a block first"}</option>{programs.map((block) => <option value={block.id} key={block.id}>{block.name}</option>)}</select></label>
          <label className="workout-name">Day name<input value={name} onChange={(event) => setName(event.target.value)} maxLength="255" required disabled={saving} placeholder="Day 1 — Lower" /></label>
          <label>Position in block<input type="number" min="1" step="1" value={workoutPosition} onChange={(event) => setWorkoutPosition(event.target.value)} disabled={saving} placeholder="Leave blank to add at the end" /></label>
          <div className="workout-exercise-list">
            {exercises.map((exercise, index) => <fieldset key={exercise.position}><legend>Exercise {index + 1}</legend>
              <label className="exercise-movement">Movement<select value={exercise.exercise} onChange={(event) => updateExercise(index, "exercise", event.target.value)} required disabled={saving || !movements.length}><option value="">{movements.length ? "Select a movement" : "Movement catalog unavailable"}</option>{movements.map((movement) => <option value={movement.id} key={movement.id}>{movement.name}</option>)}</select></label>
              <label>Sets<input type="number" min="1" step="1" value={exercise.sets} onChange={(event) => updateExercise(index, "sets", event.target.value)} required disabled={saving} /></label>
              <label>Reps<input type="number" min="1" step="1" value={exercise.reps} onChange={(event) => updateExercise(index, "reps", event.target.value)} required disabled={saving} /></label>
              <label>Target (% of max)<input type="number" min={MIN_TARGET_PERCENT} max={MAX_TARGET_PERCENT} step="any" value={exercise.target_percent} onChange={(event) => updateExercise(index, "target_percent", event.target.value)} required disabled={saving} placeholder="80" /></label>
              <label>Velocity min<input type="number" min="0" max="10" step="any" value={exercise.velocity_zone_min} onChange={(event) => updateExercise(index, "velocity_zone_min", event.target.value)} disabled={saving} /></label>
              <label>Velocity max<input type="number" min="0" max="10" step="any" value={exercise.velocity_zone_max} onChange={(event) => updateExercise(index, "velocity_zone_max", event.target.value)} disabled={saving} /></label>
              <button type="button" className="workout-remove" onClick={() => removeExercise(index)} disabled={exercises.length === 1 || saving} aria-label={`Remove exercise ${index + 1}`}>Remove</button>
            </fieldset>)}
          </div>
          <div className="workout-form-actions"><button type="button" className="workout-secondary" onClick={() => setExercises((current) => [...current, createExerciseDraft(current.length + 1)])} disabled={saving}>Add exercise</button><button type="submit" disabled={saving}>{saving ? "Creating..." : "Create workout"}</button></div>
          <ErrorList errors={manualErrors} />
          {manualStatus && <p className="workout-status" role="status">{manualStatus}</p>}
        </form>
      </section>

      <section className="workout-panel workout-csv"><header><span>Spreadsheet import</span><h3>Preview before import</h3><p>Upload a roster, a max sheet, or a plan — we work out which from its columns. Nothing is saved until you import.</p></header>
        <label className="workout-file">CSV file<input key={fileInputKey} type="file" accept=".csv,text/csv" onChange={chooseFile} disabled={Boolean(csvBusy)} /></label>
        {file && <p className="workout-file-name">Selected: <b>{file.name}</b> · {(file.size / 1024).toFixed(1)} KB</p>}
        <div className="workout-form-actions"><button type="button" className="workout-secondary" onClick={() => submitCsv("preview")} disabled={!file || Boolean(csvBusy)}>{csvBusy === "preview" ? "Checking..." : (repairs.length ? "Re-check with fixes" : "Check file")}</button><button type="button" onClick={() => submitCsv("import")} disabled={!file || Boolean(csvBusy) || (repairs.length > 0 && !allRepaired)}>{csvBusy === "import" ? "Importing..." : "Import"}</button></div>
        {csvStatus && <p className="workout-status" role="status">{csvStatus}</p>}

        {/* THE REPAIR GRID (canon D17). A name we couldn't match is a question,
            not a rejection — the coach answers it here and imports the same
            file. Their answers travel with it, so nothing needs re-uploading. */}
        {repairs.length > 0 && <div className="workout-preview">
          <h4>Match these names</h4>
          <p className="monitor-empty">Each fix applies to every row spelled the same way.</p>
          {repairs.map((error, index) => {
            const kind = correctionKind(error.code);
            const records = kind === "athlete" ? athletes : kind === "exercise" ? movements : groups;
            return <RepairRow
              key={`${error.row ?? "sheet"}-${error.value}-${index}`}
              error={error}
              records={records}
              value={corrections[kind]?.[error.value]}
              onPick={pickCorrection}
              disabled={Boolean(csvBusy)}
            />;
          })}
          <p className="workout-status" role="status">{repairedCount} of {repairs.length} matched{allRepaired ? " — import when ready." : "."}</p>
        </div>}

        {/* Anything a coach can't fix by pointing at a record: a missing column,
            an unreadable file, a number whose meaning the sheet never stated. */}
        <ErrorList errors={otherErrors} title="Still to fix in the file:" />

        {preview && <div className="workout-preview"><h4>What we understood</h4>{previewRows.length === 0 ? <p className="monitor-empty">No rows could be read from this file.</p> : <PreviewRows sheetType={preview.sheet_type} rows={previewRows} />}
          {preview.skipped?.length > 0 && <div className="context-notice"><strong>{preview.skipped.length} row{preview.skipped.length === 1 ? "" : "s"} skipped.</strong> A weight is only used when the sheet says plainly what it means — a bare number could be a one-rep max, a set of five, or a percentage, and guessing wrong would quietly become that athlete's official max.</div>}
        </div>}
      </section>
    </div>

    {/* Days no longer have a global list of their own — a day belongs to one
        block, so they are read from the blocks we already loaded. Each block
        arrives with its days and their prescription rows nested inside it. */}
    <section className="workout-panel workout-catalog-list"><header><span>Saved catalog</span><h3>Days by block</h3><p>Movements appear in prescribed order.</p></header>
      {programCatalogState === "loading" && <p className="monitor-empty" role="status">Loading blocks...</p>}
      {programCatalogState !== "loading" && allDays.length === 0 && <p className="monitor-empty">No days have been added to any block yet.</p>}
      <div className="workout-card-grid">{allDays.map(({ block, workout }) => (
        <article key={workout.id}><header><span>{block.name} · day {workout.position} · {workout.exercises?.length || 0} exercise{workout.exercises?.length === 1 ? "" : "s"}</span><h4>{workout.name}</h4></header><ol>{(workout.exercises || []).map((exercise) => <ExerciseSummary exercise={exercise} key={exercise.id || `${exercise.position}-${exercise.exercise}`} />)}</ol></article>
      ))}</div>
    </section>

    <div className="workout-program-grid">
      <section className="workout-panel workout-program-builder"><header><span>Step 1 · Block builder</span><h3>New training block</h3><p>The reusable template. No group and no dates — those arrive when it is deployed.</p></header>
        <form onSubmit={createTrainingBlock}>
          <label>Block name<input value={programName} onChange={(event) => setProgramName(event.target.value)} maxLength="255" required disabled={programSaving} placeholder="Fall Strength" /></label>
          <label>Duration (weeks)<input type="number" min="1" step="1" value={durationWeeks} onChange={(event) => setDurationWeeks(event.target.value)} disabled={programSaving} placeholder="Optional" /></label>
          <fieldset className="program-draft"><legend>Training days</legend>
            <p className="monitor-empty">Which days of the week this block is meant to be trained on.</p>
            <div>{CADENCE_DAYS.map((day) => <label key={day}><input type="checkbox" checked={cadenceDays.includes(day)} onChange={() => setCadenceDays((current) => toggleCadenceDay(current, day))} disabled={programSaving} /><span>{day}</span></label>)}</div>
          </fieldset>
          <div className="workout-form-actions"><button type="submit" disabled={programSaving}>{programSaving ? "Creating..." : "Create block"}</button></div>
          <ErrorList errors={programErrors} />
          {programStatus && <p className="workout-status" role="status">{programStatus}</p>}
        </form>
      </section>

      <section className="workout-panel workout-program-builder"><header><span>Step 3 · Deploy</span><h3>Run a block with a group</h3><p>Copies the template down for these athletes, starting on a date. The copy is independent — editing it later never changes the template.</p></header>
        <form onSubmit={deployBlock}>
          <label>Block<select value={deployBlockId} onChange={(event) => setDeployBlockId(event.target.value)} required disabled={deploySaving || !programs.length}><option value="">{programs.length ? "Select a block" : "Create a block first"}</option>{programs.map((block) => <option value={block.id} key={block.id}>{block.name}</option>)}</select></label>
          <label>Group<select value={deployGroupId} onChange={(event) => setDeployGroupId(event.target.value)} required disabled={deploySaving || !groups.length}><option value="">{groups.length ? "Select a group" : "No groups exist yet"}</option>{groups.map((group) => <option value={group.id} key={group.id}>{group.name}</option>)}</select></label>
          <label>Plan name<input value={deployName} onChange={(event) => setDeployName(event.target.value)} maxLength="255" required disabled={deploySaving} placeholder="Varsity — Fall Strength" /></label>
          <label>Start date<input type="date" value={deployStart} onChange={(event) => setDeployStart(event.target.value)} required disabled={deploySaving} /></label>
          <label>End date<input type="date" value={deployEnd} onChange={(event) => setDeployEnd(event.target.value)} disabled={deploySaving} /></label>
          <div className="workout-form-actions"><button type="submit" disabled={deploySaving || !deployBlockId || !deployGroupId}>{deploySaving ? "Deploying..." : "Deploy to group"}</button></div>
          <ErrorList errors={deployErrors} />
          {deployStatus && <p className="workout-status" role="status">{deployStatus}</p>}
        </form>
      </section>

      <section className="workout-panel workout-program-browser"><header><span>Saved blocks</span><h3>Block catalog</h3><p>{programCount} block{programCount === 1 ? "" : "s"}, with their days in training order.</p></header>
        {programCatalogState === "loading" && <p className="monitor-empty" role="status">Loading program page...</p>}
        <ErrorList errors={programCatalogErrors} title="Program catalog unavailable:" />
        {programCatalogState === "error" && <button type="button" className="workout-secondary" onClick={() => loadPrograms(retryProgramUrl)}>Retry page</button>}
        {programCatalogState !== "loading" && programCount === 0 && <p className="monitor-empty">No blocks have been created.</p>}
        <div className="program-browser-list">{programs.map((block) => <article key={block.id || block.name}><header><span>{block.workouts?.length || 0} day{block.workouts?.length === 1 ? "" : "s"}{block.duration_weeks ? ` · ${block.duration_weeks} wk` : ""}{block.cadence_days_of_week ? ` · ${block.cadence_days_of_week}` : ""}</span><h4>{block.name}</h4></header>{block.workouts?.length ? <ol>{block.workouts.map((workout, index) => <li key={workout.id || index}><span>{workout.position ?? index + 1}</span><b>{workout.name}</b></li>)}</ol> : <p className="monitor-empty">No days yet — add one with the manual builder.</p>}</article>)}</div>
        {(programPagination.previous || programPagination.next || programCount > programs.length) && <nav className="workout-pagination" aria-label="Workout program catalog pages"><button type="button" className="workout-secondary" onClick={() => loadPrograms(programPagination.previous)} disabled={!programPagination.previous || programCatalogState === "loading"}>Previous</button><span role="status">Showing {programs.length} on this page · {programCount} total</span><button type="button" onClick={() => loadPrograms(programPagination.next)} disabled={!programPagination.next || programCatalogState === "loading"}>Next</button></nav>}
      </section>
    </div>
  </div>;
}
