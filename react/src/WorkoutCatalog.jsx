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
// Days can be renamed, reordered, and removed from the "Days by block" panel.
// Reordering sends the WHOLE new order rather than one position, because the
// server renumbers a list at once — see moveInList.

import { useEffect, useState } from "react";
import { applyCorrection, blockCatalogQuery, buildDeployPayload, buildRowEdit, buildTrainingBlockPayload, buildWorkoutPayload, CADENCE_DAYS, correctionKind, countCorrections, createExerciseDraft, errorLabel, flattenApiErrors, MAX_TARGET_PERCENT, MIN_TARGET_PERCENT, moveInList, repairableErrors, repairChoices, sameOriginPath, toggleCadenceDay, toggleId } from "./workoutCatalog.js";

const TRAINING_BLOCKS_URL = "/api/training-blocks/";
// The catalog is shared by the whole department, so it opens on the coach's own
// blocks — not because the others are off limits (they are one click away and
// fully editable), but because scrolling a department-sized list to find your
// own work is the thing that makes a shared catalog feel worse than a private
// one. "Recently edited" is the default sort for the same reason: the block you
// want next is almost always the one you touched last.
const blockCatalogUrl = (scope, categoryIds) =>
  `${TRAINING_BLOCKS_URL}${blockCatalogQuery(scope, categoryIds)}`;
const BLOCK_CATEGORIES_URL = "/api/block-categories/";
// One block's own fields — used to label a block that already existed. Without
// this, categories would only ever apply to blocks made after the feature shipped.
const blockDetailUrl = (blockId) => `${TRAINING_BLOCKS_URL}${blockId}/`;
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
  // template editing: which day is open, what is being typed, and what failed
  const [openDayId, setOpenDayId] = useState(null);
  const [rowDrafts, setRowDrafts] = useState({});
  const [editBusy, setEditBusy] = useState(false);
  const [editError, setEditError] = useState("");
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
  // "mine" or "all" — see blockCatalogUrl. A lens, not a permission.
  const [blockScope, setBlockScope] = useState("mine");
  // The department's label vocabulary, and which of them the catalog is
  // currently narrowed to. Empty means no narrowing.
  const [categories, setCategories] = useState([]);
  const [categoryFilter, setCategoryFilter] = useState([]);
  const [newBlockCategories, setNewBlockCategories] = useState([]);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [categoryErrors, setCategoryErrors] = useState([]);
  const [programUrl, setProgramUrl] = useState(blockCatalogUrl("mine", []));
  const [retryProgramUrl, setRetryProgramUrl] = useState(blockCatalogUrl("mine", []));
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

  // Switching the lens is just a different URL for the same list — no reordering
  // of local state, no client-side filtering to drift out of sync with the API.
  function showBlockScope(scope) {
    setBlockScope(scope);
    loadPrograms(blockCatalogUrl(scope, categoryFilter));
  }

  function toggleCategoryFilter(categoryId) {
    const next = toggleId(categoryFilter, categoryId);
    setCategoryFilter(next);
    loadPrograms(blockCatalogUrl(blockScope, next));
  }

  async function loadCategories() {
    try {
      const response = await fetch(BLOCK_CATEGORIES_URL, { headers });
      const body = await response.json().catch(() => []);
      setCategories(Array.isArray(body) ? body : body.results || []);
    } catch {
      setCategories([]);
    }
  }

  // A new label is department-wide, so it is created here rather than buried in
  // a settings screen — the moment you need one is the moment you are filing a
  // block and find nothing that fits.
  async function createCategory(event) {
    event.preventDefault();
    setCategoryErrors([]);
    try {
      const response = await fetch(BLOCK_CATEGORIES_URL, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ name: newCategoryName.trim() }),
      });
      const body = await parseResponse(response, "The category could not be created.");
      if (body === null) return;
      setNewCategoryName("");
      await loadCategories();
    } catch (errors) {
      setCategoryErrors(Array.isArray(errors) ? errors : [{ detail: "The category could not be created." }]);
    }
  }

  // Labelling a block that already exists. PATCHes only `categories`, so it
  // cannot disturb the block's name, cadence, or its days.
  async function toggleBlockCategory(block, categoryId) {
    const next = toggleId((block.categories || []).map(Number), categoryId);
    try {
      const response = await fetch(blockDetailUrl(block.id), {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ categories: next }),
      });
      const body = await parseResponse(response, "The labels could not be saved.");
      if (body === null) return;
      // Patch the one row in place rather than refetching: a reload would
      // re-sort the list under the coach's cursor mid-click.
      setPrograms((rows) => rows.map((row) => (row.id === block.id ? { ...row, ...body } : row)));
      await loadCategories();
    } catch (errors) {
      setCategoryErrors(Array.isArray(errors) ? errors : [{ detail: "The labels could not be saved." }]);
    }
  }

  useEffect(() => {
    loadPrograms(blockCatalogUrl("mine", []));
    loadCategories();
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
        body: JSON.stringify(buildTrainingBlockPayload(programName, durationWeeks, cadenceDays, newBlockCategories)),
      });
      const body = await parseResponse(response, "The block could not be created.");
      if (body === null) return;
      setProgramName("");
      setDurationWeeks("");
      setCadenceDays([]);
      setNewBlockCategories([]);
      setProgramStatus(`${body.name || programName.trim()} was created. Add its days below.`);
      // Select it in the day builder — creating a block is almost always
      // followed by filling it in, so save the coach the extra click.
      if (body.id) setWorkoutBlockId(String(body.id));
      await loadPrograms(blockCatalogUrl(blockScope, categoryFilter));
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

  // ─────────────────── editing a template ───────────────────
  //
  // Every one of these reloads the blocks afterwards rather than patching state
  // by hand: the server owns positions, and guessing at them locally is how a
  // screen ends up disagreeing with the database.

  async function editRequest(url, options, failure) {
    setEditBusy(true);
    setEditError("");
    try {
      const response = await fetch(url, { headers, ...options });
      if (response.status === 401 || response.status === 403) { onLogout(); return false; }
      if (response.status !== 204 && !response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || failure);
      }
      await loadPrograms(programUrl);
      return true;
    } catch (problem) {
      setEditError(problem.message || failure);
      return false;
    } finally {
      setEditBusy(false);
    }
  }

  const jsonBody = (body) => ({
    method: "PATCH",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  function renameDay(block, workout) {
    const next = window.prompt("Rename this day", workout.name);
    if (next === null || next.trim() === workout.name) return;
    editRequest(`/api/training-blocks/${block.id}/workouts/${workout.id}/`,
      jsonBody({ name: next }), "The day could not be renamed.");
  }

  // Deleting a day cannot reach a group already training a copy of this block —
  // deploying copies the rows down rather than pointing at them. The wording
  // says so, because "delete" on a template a team is mid-season on is exactly
  // the thing a coach would hesitate over.
  function deleteDay(block, workout) {
    if (!window.confirm(`Delete "${workout.name}" from ${block.name}?\n\nGroups already training a deployed copy keep theirs.`)) return;
    editRequest(`/api/training-blocks/${block.id}/workouts/${workout.id}/`,
      { method: "DELETE" }, "The day could not be deleted.");
  }

  // Up/down send the WHOLE new order, because the server renumbers a list at
  // once — a one-at-a-time swap collides with the row already on that number.
  function moveDay(block, workout, direction) {
    const ids = (block.workouts || []).map((w) => w.id);
    const next = moveInList(ids, workout.id, direction);
    if (next === ids) return;
    editRequest(`/api/training-blocks/${block.id}/workout-order/`,
      { method: "PUT", headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ workout_ids: next }) },
      "The days could not be reordered.");
  }

  function moveRow(block, workout, row, direction) {
    const ids = (workout.exercises || []).map((e) => e.id);
    const next = moveInList(ids, row.id, direction);
    if (next === ids) return;
    editRequest(`/api/training-blocks/${block.id}/workouts/${workout.id}/exercise-order/`,
      { method: "PUT", headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ exercise_ids: next }) },
      "The movements could not be reordered.");
  }

  function deleteRow(block, workout, row) {
    if (!window.confirm(`Remove ${row.exercise_name || "this movement"} from ${workout.name}?`)) return;
    editRequest(`/api/training-blocks/${block.id}/workouts/${workout.id}/exercises/${row.id}/`,
      { method: "DELETE" }, "The movement could not be removed.");
  }

  async function saveRow(block, workout, row) {
    const payload = buildRowEdit(rowDrafts[row.id] || {});
    if (!Object.keys(payload).length) return;
    const ok = await editRequest(
      `/api/training-blocks/${block.id}/workouts/${workout.id}/exercises/${row.id}/`,
      jsonBody(payload), "The movement could not be saved.");
    if (ok) setRowDrafts((current) => ({ ...current, [row.id]: {} }));
  }

  function updateRowDraft(rowId, field, value) {
    setRowDrafts((current) => ({ ...current, [rowId]: { ...current[rowId], [field]: value } }));
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
    {/* Days grouped under the block they belong to, because up/down only means
        anything within one block — and because a day's name ("Day 1") is
        ambiguous without it. Open a day to edit its movements. */}
    <section className="workout-panel workout-catalog-list"><header><span>Saved catalog</span><h3>Days by block</h3><p>Rename, reorder, or remove. Changes here never touch a group already training a deployed copy.</p></header>
      {programCatalogState === "loading" && <p className="monitor-empty" role="status">Loading blocks...</p>}
      {programCatalogState !== "loading" && allDays.length === 0 && <p className="monitor-empty">No days have been added to any block yet.</p>}
      {editError && <p className="training-day-error" role="alert">{editError}</p>}

      {programs.filter((block) => (block.workouts || []).length).map((block) => (
        <div className="workout-block-group" key={block.id}>
          <h4 className="workout-block-heading">{block.name}</h4>
          <div className="workout-card-grid">{(block.workouts || []).map((workout, index, all) => {
            const open = openDayId === workout.id;
            return (
              <article key={workout.id}>
                <header>
                  <span>Day {workout.position} · {workout.exercises?.length || 0} movement{workout.exercises?.length === 1 ? "" : "s"}</span>
                  <h4>{workout.name}</h4>
                </header>

                <div className="workout-day-actions">
                  <button type="button" onClick={() => moveDay(block, workout, -1)} disabled={editBusy || index === 0} aria-label={`Move ${workout.name} earlier`}>↑</button>
                  <button type="button" onClick={() => moveDay(block, workout, 1)} disabled={editBusy || index === all.length - 1} aria-label={`Move ${workout.name} later`}>↓</button>
                  <button type="button" className="workout-secondary" onClick={() => renameDay(block, workout)} disabled={editBusy}>Rename</button>
                  <button type="button" className="workout-secondary" onClick={() => setOpenDayId(open ? null : workout.id)} disabled={editBusy}>{open ? "Done" : "Edit movements"}</button>
                  <button type="button" className="workout-remove" onClick={() => deleteDay(block, workout)} disabled={editBusy}>Delete day</button>
                </div>

                {!open ? <ol>{(workout.exercises || []).map((exercise) => <ExerciseSummary exercise={exercise} key={exercise.id || `${exercise.position}-${exercise.exercise}`} />)}</ol> : (
                  <div className="workout-row-editor">
                    {(workout.exercises || []).length === 0 && <p className="monitor-empty">This day has no movements.</p>}
                    {(workout.exercises || []).map((row, rowIndex, rows) => {
                      const draft = rowDrafts[row.id] || {};
                      return (
                        <fieldset key={row.id}>
                          <legend>{row.position}. {row.exercise_name || row.exercise}</legend>
                          {/* Blank means "leave as it is" — the server only
                              changes the fields it is actually sent. */}
                          <label>Sets<input type="number" min="1" step="1" placeholder={String(row.sets)} value={draft.sets ?? ""} onChange={(e) => updateRowDraft(row.id, "sets", e.target.value)} disabled={editBusy} /></label>
                          <label>Reps<input type="number" min="1" step="1" placeholder={String(row.reps)} value={draft.reps ?? ""} onChange={(e) => updateRowDraft(row.id, "reps", e.target.value)} disabled={editBusy} /></label>
                          <label>Target (% of max)<input type="number" min={MIN_TARGET_PERCENT} max={MAX_TARGET_PERCENT} step="any" placeholder={String(row.target_percent)} value={draft.target_percent ?? ""} onChange={(e) => updateRowDraft(row.id, "target_percent", e.target.value)} disabled={editBusy} /></label>
                          <div className="workout-day-actions">
                            <button type="button" onClick={() => moveRow(block, workout, row, -1)} disabled={editBusy || rowIndex === 0} aria-label="Move earlier">↑</button>
                            <button type="button" onClick={() => moveRow(block, workout, row, 1)} disabled={editBusy || rowIndex === rows.length - 1} aria-label="Move later">↓</button>
                            <button type="button" onClick={() => saveRow(block, workout, row)} disabled={editBusy || !Object.keys(buildRowEdit(draft)).length}>Save</button>
                            <button type="button" className="workout-remove" onClick={() => deleteRow(block, workout, row)} disabled={editBusy}>Remove</button>
                          </div>
                        </fieldset>
                      );
                    })}
                  </div>
                )}
              </article>
            );
          })}</div>
        </div>
      ))}
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
          <fieldset className="program-draft"><legend>Categories</legend>
            <p className="monitor-empty">How this block gets found later. Pick as many as fit — they sit on different axes, so a block can be both "Off-season" and "Football".</p>
            {categories.length === 0
              ? <p className="monitor-empty">No categories yet. Add one below the catalog.</p>
              : <div>{categories.map((category) => <label key={category.id}><input type="checkbox" checked={newBlockCategories.includes(category.id)} onChange={() => setNewBlockCategories((current) => toggleId(current, category.id))} disabled={programSaving} /><span>{category.name}</span></label>)}</div>}
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

      <section className="workout-panel workout-program-browser"><header><span>Saved blocks</span><h3>Block catalog</h3><p>{programCount} block{programCount === 1 ? "" : "s"}, most recently edited first. Every block in the department is reusable — this only changes what is listed.</p></header>
        <div className="block-scope-toggle" role="group" aria-label="Whose blocks to show">
          <button type="button" className={blockScope === "mine" ? "" : "workout-secondary"} aria-pressed={blockScope === "mine"} onClick={() => showBlockScope("mine")}>My blocks</button>
          <button type="button" className={blockScope === "all" ? "" : "workout-secondary"} aria-pressed={blockScope === "all"} onClick={() => showBlockScope("all")}>All coaches</button>
        </div>
        {categories.length > 0 && <div className="block-category-filter" role="group" aria-label="Filter by category">
          {categories.map((category) => <button key={category.id} type="button" className={categoryFilter.includes(category.id) ? "category-chip is-on" : "category-chip"} aria-pressed={categoryFilter.includes(category.id)} onClick={() => toggleCategoryFilter(category.id)}>{category.name} <b>{category.block_count}</b></button>)}
          {categoryFilter.length > 0 && <button type="button" className="category-chip is-clear" onClick={() => { setCategoryFilter([]); loadPrograms(blockCatalogUrl(blockScope, [])); }}>Clear</button>}
        </div>}
        {categoryFilter.length > 1 && <p className="monitor-empty">Showing blocks in <b>any</b> of the selected categories.</p>}
        {programCatalogState === "loading" && <p className="monitor-empty" role="status">Loading program page...</p>}
        <ErrorList errors={programCatalogErrors} title="Program catalog unavailable:" />
        {programCatalogState === "error" && <button type="button" className="workout-secondary" onClick={() => loadPrograms(retryProgramUrl)}>Retry page</button>}
        {programCatalogState !== "loading" && programCount === 0 && <p className="monitor-empty">{blockScope === "mine" ? "You haven't created any blocks yet — try All coaches." : "No blocks have been created."}</p>}
        <div className="program-browser-list">{programs.map((block) => <article key={block.id || block.name}><header><span>{block.workouts?.length || 0} day{block.workouts?.length === 1 ? "" : "s"}{block.duration_weeks ? ` · ${block.duration_weeks} wk` : ""}{block.cadence_days_of_week ? ` · ${block.cadence_days_of_week}` : ""}</span><h4>{block.name}</h4></header>{categories.length > 0 && <div className="block-card-categories" role="group" aria-label={`Categories for ${block.name}`}>{categories.map((category) => <button key={category.id} type="button" className={(block.categories || []).includes(category.id) ? "category-chip is-on" : "category-chip"} aria-pressed={(block.categories || []).includes(category.id)} onClick={() => toggleBlockCategory(block, category.id)}>{category.name}</button>)}</div>}{block.workouts?.length ? <ol>{block.workouts.map((workout, index) => <li key={workout.id || index}><span>{workout.position ?? index + 1}</span><b>{workout.name}</b></li>)}</ol> : <p className="monitor-empty">No days yet — add one with the manual builder.</p>}</article>)}</div>
        <form className="new-category-form" onSubmit={createCategory}>
          <label>New category<input value={newCategoryName} onChange={(event) => setNewCategoryName(event.target.value)} maxLength="60" placeholder="Off-season" /></label>
          <button type="submit" className="workout-secondary" disabled={!newCategoryName.trim()}>Add category</button>
        </form>
        <ErrorList errors={categoryErrors} title="Categories:" />
        {(programPagination.previous || programPagination.next || programCount > programs.length) && <nav className="workout-pagination" aria-label="Workout program catalog pages"><button type="button" className="workout-secondary" onClick={() => loadPrograms(programPagination.previous)} disabled={!programPagination.previous || programCatalogState === "loading"}>Previous</button><span role="status">Showing {programs.length} on this page · {programCount} total</span><button type="button" onClick={() => loadPrograms(programPagination.next)} disabled={!programPagination.next || programCatalogState === "loading"}>Next</button></nav>}
      </section>
    </div>
  </div>;
}
