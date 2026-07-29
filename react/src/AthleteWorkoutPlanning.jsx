// AthleteWorkoutPlanning.jsx — what one athlete is training, and their exceptions.
//
// Two panels:
//
//   ASSIGNMENT   Which plan(s) this athlete is on. Assigning them to a plan
//                really means putting them in the GROUP that runs it, so a
//                write here can affect more than the wording suggests — the
//                server says exactly which groups changed, and we show it.
//                An athlete can be on several plans at once.
//
//   OVERRIDES    An exception for this athlete on one prescribed line, for the
//                outlier the group's percentage doesn't suit — someone back
//                from injury, or a lifter whose bench trails their squat. It
//                moves the PERCENTAGE, never a fixed weight, so their number
//                keeps tracking their own max. Most athletes never need one.
//
// Everything on this screen comes from ONE endpoint: the assignment response
// already carries each plan, its days, and every prescribed row with the right
// id and this athlete's resolved pounds. There is nothing to stitch together.

import { useEffect, useState } from "react";
import { assignedWorkoutOptions, assignmentSummary, buildAthleteAssignmentPayload, buildOverrideFields, exerciseTargetView } from "./athletePlanning.js";
import { errorLabel, flattenApiErrors, MAX_TARGET_PERCENT, MIN_TARGET_PERCENT } from "./workoutCatalog.js";

// Pounds are shown next to every percentage, because "80%" tells a coach
// nothing about what actually goes on the bar. A dash means no max on file.
function poundsLabel(value) {
  return value === null || value === undefined ? "—" : `${value} lbs`;
}

function PlanningErrors({ errors }) {
  if (!errors.length) return null;
  return <div className="workout-errors" role="alert"><strong>Please correct the following:</strong><ul>{errors.map((error, index) => <li key={`${error.row || ""}-${error.field || ""}-${index}`}>{errorLabel(error)}</li>)}</ul></div>;
}

export default function AthleteWorkoutPlanning({ athlete, accessToken, onLogout }) {
  const [assignment, setAssignment] = useState([]);
  const [groupsChanged, setGroupsChanged] = useState([]);
  const [programs, setPrograms] = useState([]);
  const [programId, setProgramId] = useState("");
  const [selectedWorkoutId, setSelectedWorkoutId] = useState("");
  const [loading, setLoading] = useState(true);
  const [assignmentSaving, setAssignmentSaving] = useState(false);
  const [assignmentErrors, setAssignmentErrors] = useState([]);
  const [assignmentStatus, setAssignmentStatus] = useState("");
  const [overrideDrafts, setOverrideDrafts] = useState({});
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

  function applyAssignment(body) {
    setAssignment(body?.assignment || []);
    setGroupsChanged(body?.groups_changed || []);
  }

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setAssignmentErrors([]);
    setAssignmentStatus("");
    setGroupsChanged([]);
    setSelectedWorkoutId("");
    Promise.all([
      // Deployed plans — what an athlete can actually be put on. NOT
      // /api/training-blocks/, which lists templates nobody trains.
      fetch("/api/training-programs/", { headers, signal: controller.signal })
        .then((response) => parseResponse(response, "Plans could not be loaded.")),
      fetch(`/api/athletes/${athlete.id}/program/`, { headers, signal: controller.signal })
        .then((response) => parseResponse(response, "Athlete assignment could not be loaded.")),
    ]).then(([nextPrograms, body]) => {
      setPrograms(Array.isArray(nextPrograms) ? nextPrograms : nextPrograms?.results || []);
      applyAssignment(body);
    }).catch((errors) => {
      if (errors?.name !== "AbortError") setAssignmentErrors(Array.isArray(errors) ? errors : [{ detail: "Athlete planning could not be loaded." }]);
    }).finally(() => setLoading(false));
    return () => controller.abort();
  }, [athlete.id, accessToken]);

  async function saveAssignment() {
    setAssignmentSaving(true);
    setAssignmentErrors([]);
    setAssignmentStatus("");
    try {
      const response = await fetch(`/api/athletes/${athlete.id}/program/`, {
        method: "PUT",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(buildAthleteAssignmentPayload(programId)),
      });
      const body = await parseResponse(response, "Athlete assignment could not be saved.");
      if (body === null) return;
      applyAssignment(body);
      setAssignmentStatus(`${athlete.name} is now on this plan.`);
    } catch (errors) {
      setAssignmentErrors(Array.isArray(errors) ? errors : [{ detail: "Athlete assignment could not be saved." }]);
    } finally {
      setAssignmentSaving(false);
    }
  }

  // Removes them from every group that is currently prescribing to them, which
  // is wider than "unassign one plan" — the confirm text says so.
  async function removeAssignment() {
    if (!window.confirm(`Take ${athlete.name} out of every group currently prescribing to them?`)) return;
    setAssignmentSaving(true);
    setAssignmentErrors([]);
    setAssignmentStatus("");
    try {
      const response = await fetch(`/api/athletes/${athlete.id}/program/`, { method: "DELETE", headers });
      const body = await parseResponse(response, "Athlete assignment could not be removed.");
      if (body === null) return;
      applyAssignment(body);
      setSelectedWorkoutId("");
      setAssignmentStatus(`${athlete.name} was removed from their prescribing groups.`);
    } catch (errors) {
      setAssignmentErrors(Array.isArray(errors) ? errors : [{ detail: "Athlete assignment could not be removed." }]);
    } finally {
      setAssignmentSaving(false);
    }
  }

  function updateOverride(rowId, field, value) {
    setOverrideDrafts((current) => ({ ...current, [rowId]: { ...current[rowId], [field]: value } }));
  }

  async function changeOverride(row, method) {
    setOverrideSaving(true);
    setOverrideErrors([]);
    setOverrideStatus("");
    try {
      const draft = overrideDrafts[row.id] || {};
      const response = await fetch(`/api/athletes/${athlete.id}/program-exercises/${row.id}/override/`, {
        method,
        headers: { ...headers, "Content-Type": "application/json" },
        ...(method === "PATCH" ? { body: JSON.stringify(buildOverrideFields(draft)) } : {}),
      });
      if (method === "DELETE" && response.status === 204) {
        setOverrideDrafts((current) => ({ ...current, [row.id]: {} }));
        setOverrideStatus(`${row.exercise?.name || "Movement"} reset to the group's target.`);
        return;
      }
      const body = await parseResponse(response, `Override could not be ${method === "PATCH" ? "saved" : "reset"}.`);
      if (body === null) return;
      setOverrideDrafts((current) => ({
        ...current,
        [row.id]: { target_percent: body.target_percent ?? "", sets: body.sets ?? "", reps: body.reps ?? "" },
      }));
      setOverrideStatus(`${row.exercise?.name || "Movement"} override saved.`);
    } catch (errors) {
      setOverrideErrors(Array.isArray(errors) ? errors : [{ detail: "Override could not be saved." }]);
    } finally {
      setOverrideSaving(false);
    }
  }

  const workoutOptions = assignedWorkoutOptions(assignment);
  const chosenWorkout = workoutOptions.find((option) => String(option.id) === String(selectedWorkoutId));

  return <div className="athlete-planning">
    <section className="context-section athlete-assignment-panel"><header><span>Athlete assignment</span><h3>What {athlete.name} is training</h3><p>An athlete trains a plan by being in the group that runs it, so they can be on more than one.</p></header>
      <div className="athlete-assignment-current"><span>Current</span><b>{assignmentSummary(assignment)}</b></div>
      {loading ? <p className="monitor-empty" role="status">Loading athlete assignment...</p> : <div className="athlete-assignment-fields">
        <label>Plan<select value={programId} onChange={(event) => setProgramId(event.target.value)} disabled={assignmentSaving || !programs.length}><option value="">{programs.length ? "Select a plan" : "No plans deployed yet"}</option>{programs.map((program) => <option value={program.id} key={program.id}>{program.name}{program.group_name ? ` — ${program.group_name}` : ""}</option>)}</select></label>
        <button onClick={saveAssignment} disabled={!programId || assignmentSaving}>{assignmentSaving ? "Saving..." : "Add to this plan"}</button>
        <button className="athlete-remove-assignment" onClick={removeAssignment} disabled={!assignment.length || assignmentSaving}>Remove from all plans</button>
      </div>}
      {/* A write here changes group membership, which is wider than the button
          wording implies. Saying so beats letting a coach discover it later. */}
      {groupsChanged.length > 0 && <div className="context-notice">{groupsChanged.map((group) => `${group.name} (${group.action})`).join(" · ")}</div>}
      <PlanningErrors errors={assignmentErrors} />{assignmentStatus && <p className="workout-status" role="status">{assignmentStatus}</p>}
    </section>

    <section className="context-section athlete-override-panel"><header><span>Individual targets</span><h3>Exercise overrides</h3><p>Leave a field blank to inherit the group's value. Overrides move the percentage, so the target still follows this athlete's own max.</p></header>
      {!workoutOptions.length ? <p className="monitor-empty">This athlete is not on a plan yet, so there is nothing to override.</p> : <>
        <label>Training day<select value={selectedWorkoutId} onChange={(event) => setSelectedWorkoutId(event.target.value)} disabled={overrideSaving}><option value="">Select a training day</option>{workoutOptions.map((option) => <option value={option.id} key={option.id}>{option.label}</option>)}</select></label>
        {!chosenWorkout ? <p className="monitor-empty">Choose a training day to adjust this athlete's targets.</p> : <div className="athlete-override-list">{chosenWorkout.exercises.map((row) => {
          const targets = exerciseTargetView(row);
          const draft = overrideDrafts[row.id] || {};
          const hasValue = [draft.target_percent, draft.sets, draft.reps].some((value) => value !== "" && value !== undefined);
          return <fieldset key={row.id}><legend>{row.position}. {row.exercise?.name || "Movement"}</legend>
            <div className="athlete-template-targets">
              <span>Group</span><b>{targets.sets.group} sets · {targets.reps.group} reps · {targets.target_percent.group}%</b>
              <span>For {athlete.name}</span><b>{poundsLabel(targets.target_weight_lbs)}</b>
            </div>
            <label>Sets<input type="number" min="1" step="1" value={draft.sets ?? ""} onChange={(event) => updateOverride(row.id, "sets", event.target.value)} placeholder={String(targets.sets.group)} disabled={overrideSaving} /></label>
            <label>Reps<input type="number" min="1" step="1" value={draft.reps ?? ""} onChange={(event) => updateOverride(row.id, "reps", event.target.value)} placeholder={String(targets.reps.group)} disabled={overrideSaving} /></label>
            <label>Target (% of max)<input type="number" min={MIN_TARGET_PERCENT} max={MAX_TARGET_PERCENT} step="any" value={draft.target_percent ?? ""} onChange={(event) => updateOverride(row.id, "target_percent", event.target.value)} placeholder={String(targets.target_percent.group)} disabled={overrideSaving} /></label>
            <div className="athlete-exercise-actions">
              <button type="button" className="workout-secondary" onClick={() => changeOverride(row, "DELETE")} disabled={overrideSaving}>Reset</button>
              <button type="button" onClick={() => changeOverride(row, "PATCH")} disabled={overrideSaving || !hasValue}>{overrideSaving ? "Saving..." : "Save"}</button>
            </div>
          </fieldset>;
        })}</div>}
      </>}
      <PlanningErrors errors={overrideErrors} />{overrideStatus && <p className="workout-status" role="status">{overrideStatus}</p>}
    </section>
  </div>;
}