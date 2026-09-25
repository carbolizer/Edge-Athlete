import { useEffect, useState } from "react";

const EXERCISES_URL = "/api/exercises/";

// A coach-facing fix for the one thing the catalog couldn't do until now: once
// an Exercise exists, there was no way to correct its name or tags short of a
// database console. Listing stays open for tablets/pickers (unauthenticated
// GET), but every edit here goes through the coach-only PATCH endpoint.
//
// Editing a stub (an auto-created row from an unrecognized import name) IS the
// confirm step — there's no separate "confirm" button to press, since fixing
// the row is the act of vouching for it.
export default function ExerciseCatalogPanel({ accessToken, onLogout }) {
  const [exercises, setExercises] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [draftName, setDraftName] = useState("");
  const [draftTags, setDraftTags] = useState("");
  const [rowError, setRowError] = useState("");
  const [busy, setBusy] = useState(false);

  const headers = { Accept: "application/json", Authorization: `Bearer ${accessToken}` };

  async function load() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(EXERCISES_URL, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("The catalog could not be loaded.");
      setExercises(await response.json());
    } catch (problem) {
      setError(problem.message || "The catalog could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { if (open) load(); }, [open, accessToken]);

  function startEdit(exercise) {
    setEditingId(exercise.id);
    setDraftName(exercise.name);
    setDraftTags((exercise.tags || []).join(", "));
    setRowError("");
  }

  function cancelEdit() {
    setEditingId(null);
    setRowError("");
  }

  async function saveEdit(exercise) {
    if (busy) return;
    setBusy(true);
    setRowError("");
    try {
      const response = await fetch(`${EXERCISES_URL}${exercise.id}/`, {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          name: draftName.trim(),
          tags: draftTags.split(",").map((tag) => tag.trim()).filter(Boolean),
        }),
      });
      if (response.status === 401 || response.status === 403) { onLogout(); return; }
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const message = body.name?.[0] || body.detail || body.non_field_errors?.[0]
          || "That edit couldn't be saved.";
        throw new Error(message);
      }
      setExercises((current) => current.map((row) => (row.id === exercise.id ? body : row)));
      setEditingId(null);
    } catch (problem) {
      setRowError(problem.message || "That edit couldn't be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="exercise-catalog-panel">
      <button type="button" onClick={() => setOpen((value) => !value)}>
        {open ? "Hide exercise catalog" : "Manage exercise catalog"}
      </button>
      {open && (
        <div className="exercise-catalog-body">
          <p>
            Fix a name or tags on a movement here — this changes it everywhere it's
            used, since every plan and set links to this one catalog entry rather
            than a typed name.
          </p>
          {error && (
            <p className="exercise-catalog-error" role="alert">
              {error} <button onClick={load} disabled={loading}>Retry</button>
            </p>
          )}
          {loading ? (
            <p role="status">Loading catalog…</p>
          ) : (
            <ul className="exercise-catalog-list">
              {exercises.map((exercise) => (
                <li key={exercise.id}>
                  {editingId === exercise.id ? (
                    <div className="exercise-catalog-edit">
                      <label>
                        Name
                        <input
                          value={draftName}
                          maxLength={255}
                          disabled={busy}
                          onChange={(e) => setDraftName(e.target.value)}
                        />
                      </label>
                      <label>
                        Tags (comma separated)
                        <input
                          value={draftTags}
                          disabled={busy}
                          onChange={(e) => setDraftTags(e.target.value)}
                          placeholder="lower, push"
                        />
                      </label>
                      {rowError && <p className="exercise-catalog-row-error" role="alert">{rowError}</p>}
                      <div className="exercise-catalog-edit-actions">
                        <button
                          type="button"
                          disabled={busy || !draftName.trim()}
                          onClick={() => saveEdit(exercise)}
                        >
                          {busy ? "Saving…" : "Save"}
                        </button>
                        <button type="button" disabled={busy} onClick={cancelEdit}>Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <div className="exercise-catalog-row">
                      <span className="exercise-catalog-name">
                        {exercise.name}
                        {exercise.is_stub && (
                          <em className="exercise-catalog-badge">unconfirmed — from an import</em>
                        )}
                      </span>
                      {exercise.tags && exercise.tags.length > 0 && (
                        <span className="exercise-catalog-tags">{exercise.tags.join(", ")}</span>
                      )}
                      <button type="button" onClick={() => startEdit(exercise)}>Edit</button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}