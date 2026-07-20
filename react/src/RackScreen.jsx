import { useEffect, useRef, useState } from "react";
import mqtt from "mqtt";
import "./App.css";
import { effectiveAssignmentLabel, resolveRackPlanningState } from "./athletePlanning.js";
import { parseMonitoringEvent, ROOM_STATE_TOPIC } from "./roomMonitor.js";
import {
  appendLiveRep,
  athleteNameLabels,
  buildAthleteIdentityPayload,
  buildRackSetStartPayload,
  buildSetCompletionPayload,
  classifyVelocity,
  createDeviceId,
  hasVelocityTarget,
  parseRepMessage,
  orderedEffectiveExercises,
  rackAssignmentChanged,
  rackProgressView,
  repKey,
  repTopic,
  shouldRefreshRack,
} from "./rackState.js";

const DEVICE_ID_KEY = "edgeathlete.rack.deviceId";
let volatileDeviceId;

function deviceId() {
  try {
    const saved = window.localStorage.getItem(DEVICE_ID_KEY);
    if (saved && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(saved)) return saved;
    const created = createDeviceId(window.crypto);
    window.localStorage.setItem(DEVICE_ID_KEY, created);
    return created;
  } catch {
    volatileDeviceId ||= createDeviceId(window.crypto);
    return volatileDeviceId;
  }
}

function velocity(value) {
  return Number(value).toFixed(2);
}

function nodeMessage(node) {
  const messages = {
    unassigned: "No sensor node is assigned to this rack.",
    conflict: "Multiple sensor nodes are assigned. Ask a coach to resolve the conflict.",
    inactive: "The assigned sensor node is inactive.",
    ready: "Sensor ready for live feedback.",
  };
  return messages[node?.state] || "Live sensor state is unavailable.";
}

export default function RackScreen() {
  const [rackDeviceId] = useState(deviceId);
  const [rackNumber, setRackNumber] = useState(null);
  const [assignmentState, setAssignmentState] = useState("registering");
  const [assignmentError, setAssignmentError] = useState("");
  const [registrationAttempt, setRegistrationAttempt] = useState(0);
  const [rackState, setRackState] = useState(null);
  const [requestState, setRequestState] = useState("idle");
  const [requestError, setRequestError] = useState("");
  const [refreshRequest, setRefreshRequest] = useState(0);
  const [mqttState, setMqttState] = useState("idle");
  const [liveReps, setLiveReps] = useState([]);
  const [pendingAthleteId, setPendingAthleteId] = useState("");
  const [confirmAthleteId, setConfirmAthleteId] = useState("");
  const [identityBusy, setIdentityBusy] = useState(false);
  const [identityError, setIdentityError] = useState("");
  const [identityStatus, setIdentityStatus] = useState("");
  const [activeSetId, setActiveSetId] = useState(null);
  const [executionBusy, setExecutionBusy] = useState(false);
  const [executionError, setExecutionError] = useState("");
  const [executionStatus, setExecutionStatus] = useState("");
  const rackNumberRef = useRef(null);
  const seenRepKeys = useRef(new Set());
  const refreshTimer = useRef(null);
  const pendingRevision = useRef(0);
  const currentRevision = useRef(0);
  const processedEventIds = useRef(new Set());

  useEffect(() => {
    let cancelled = false;
    let pollTimer;

    async function readAssignment(path, options) {
      const response = await fetch(path, options);
      if (!response.ok) throw new Error(`Base station returned HTTP ${response.status}`);
      const body = await response.json();
      if (cancelled) return;
      const nextRackNumber = body.rack_number ?? null;
      if (rackAssignmentChanged(rackNumberRef.current, nextRackNumber)) {
        rackNumberRef.current = nextRackNumber;
        setRackNumber(nextRackNumber);
        setRackState(null);
        setLiveReps([]);
        setMqttState("idle");
        seenRepKeys.current.clear();
        processedEventIds.current.clear();
        if (refreshTimer.current) {
          clearTimeout(refreshTimer.current);
          refreshTimer.current = null;
        }
        currentRevision.current = 0;
        pendingRevision.current = 0;
        setRefreshRequest(0);
        setPendingAthleteId("");
        setConfirmAthleteId("");
        setIdentityError("");
        setIdentityStatus("");
      }
      if (nextRackNumber !== null) {
        setAssignmentState("assigned");
      } else {
        setAssignmentState("waiting");
      }
      setAssignmentError("");
      return nextRackNumber !== null;
    }

    async function register() {
      setAssignmentState("registering");
      try {
        await readAssignment("/api/racks/register/", {
          method: "POST",
          headers: { Accept: "application/json", "Content-Type": "application/json" },
          body: JSON.stringify({ device_id: rackDeviceId }),
        });
        if (!cancelled) {
          pollTimer = setInterval(() => {
            readAssignment("/api/racks/racknumber/", {
              method: "POST",
              headers: { Accept: "application/json", "Content-Type": "application/json" },
              body: JSON.stringify({ device_id: rackDeviceId }),
            }).catch((error) => {
              if (!cancelled) {
                setAssignmentError(error.message);
                if (rackNumberRef.current === null) setAssignmentState("error");
              }
            });
          }, 2_000);
        }
      } catch (error) {
        if (!cancelled) {
          setAssignmentError(error.message || "Registration failed");
          setAssignmentState("error");
        }
      }
    }

    register();
    return () => {
      cancelled = true;
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [rackDeviceId, registrationAttempt]);

  useEffect(() => {
    if (rackNumber === null) return undefined;
    const controller = new AbortController();
    setRequestState((current) => rackState && current !== "loading" ? "refreshing" : "loading");
    fetch(`/api/racks/${rackNumber}/state/`, { headers: { Accept: "application/json", "X-Rack-Device-Id": rackDeviceId }, signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Rack state returned HTTP ${response.status}`);
        return response.json();
      })
      .then((body) => {
        currentRevision.current = Math.max(currentRevision.current, body.revision || 0);
        setRackState(body);
        setRequestState("ready");
        setRequestError("");
      })
      .catch((error) => {
        if (error.name === "AbortError") return;
        setRequestError(error.message || "Rack state unavailable");
        setRequestState(rackState ? "stale" : "error");
      });
    return () => controller.abort();
  }, [rackDeviceId, rackNumber, refreshRequest]);

  const activeProgram = rackState?.active_program;
  const planningState = resolveRackPlanningState(rackState);
  const catalogMode = rackState?.mode === "catalog" || rackState?.assignment_mode === "catalog" || Boolean(rackState?.catalog_assignment) || Boolean(rackState?.assignment) || planningState.identityAvailable;
  const effectiveWorkout = rackState?.effective_workout;
  const effectiveExercises = orderedEffectiveExercises(effectiveWorkout);
  const progress = rackProgressView(rackState?.progress);
  const feedbackTarget = catalogMode ? progress?.exercise : activeProgram;
  const targetMinimum = feedbackTarget?.velocity_zone_min ?? feedbackTarget?.velocity_min;
  const targetMaximum = feedbackTarget?.velocity_zone_max ?? feedbackTarget?.velocity_max;
  const node = rackState?.node;
  const liveTopic = node?.state === "ready" && node.node_id && hasVelocityTarget(feedbackTarget)
    ? repTopic(node.node_id)
    : null;
  const selectionKey = `${rackState?.rack_number || ""}:${rackState?.selected_athlete?.id || ""}:${progress?.exercise?.id || activeProgram?.id || ""}:${progress?.expectedSetNumber || ""}:${node?.state || ""}:${node?.node_id || ""}`;

  useEffect(() => setLiveReps([]), [selectionKey]);
  useEffect(() => setActiveSetId(progress?.activeSet?.id || null), [progress?.activeSet?.id]);

  useEffect(() => {
    if (rackNumber === null) return undefined;
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const client = mqtt.connect(`${protocol}://${window.location.hostname}:9001`, {
      reconnectPeriod: 2_000,
      connectTimeout: 5_000,
      clean: true,
    });
    setMqttState("connecting");
    client.on("connect", () => {
      setMqttState("connecting");
      const topics = liveTopic ? [ROOM_STATE_TOPIC, liveTopic] : [ROOM_STATE_TOPIC];
      client.subscribe(topics, { qos: 1 }, (error) => setMqttState(error ? "reconnecting" : "live"));
    });
    client.on("message", (topic, message) => {
      if (topic === ROOM_STATE_TOPIC) {
        const event = parseMonitoringEvent(message);
        if (shouldRefreshRack(currentRevision.current, event, processedEventIds.current)) {
          pendingRevision.current = Math.max(pendingRevision.current, event.revision);
          if (!refreshTimer.current) {
            refreshTimer.current = window.setTimeout(() => {
              setRefreshRequest((value) => Math.max(value, pendingRevision.current));
              refreshTimer.current = null;
            }, 500);
          }
        }
        return;
      }
      if (!liveTopic) return;
      const rep = parseRepMessage(message, topic, node.node_id, Date.now());
      if (!rep || seenRepKeys.current.has(repKey(rep))) return;
      seenRepKeys.current.add(repKey(rep));
      if (seenRepKeys.current.size > 500) seenRepKeys.current.delete(seenRepKeys.current.values().next().value);
      setLiveReps((reps) => appendLiveRep(reps, rep));
    });
    client.on("reconnect", () => setMqttState("reconnecting"));
    client.on("close", () => setMqttState("reconnecting"));
    client.on("error", () => setMqttState("reconnecting"));
    return () => {
      client.end(true);
      if (refreshTimer.current) {
        clearTimeout(refreshTimer.current);
        refreshTimer.current = null;
      }
    };
  }, [rackNumber, liveTopic]);

  if (rackNumber === null) {
    return <main className="monitor rack-screen rack-waiting-screen">
      <section className="rack-waiting-card">
        <div className="monitor-brand"><b>EA</b><span>Edge Athlete</span></div>
        <p className="rack-kicker">Rack setup</p>
        <h1>{assignmentState === "registering" ? "Registering this screen" : assignmentState === "error" ? "Base station unavailable" : "Waiting for rack assignment"}</h1>
        <p>{assignmentError || "A coach can now assign this screen to a rack."}</p>
        <code>{rackDeviceId}</code>
        {assignmentState === "error" && <button onClick={() => setRegistrationAttempt((value) => value + 1)}>Retry registration</button>}
      </section>
    </main>;
  }

  if (!rackState && requestState === "loading") {
    return <main className="monitor rack-screen rack-waiting-screen"><section className="rack-waiting-card"><p className="rack-kicker">Rack {rackNumber}</p><h1>Loading workout</h1><p>Reading the latest coach selection.</p></section></main>;
  }

  if (!rackState) {
    return <main className="monitor rack-screen rack-waiting-screen"><section className="rack-waiting-card"><p className="rack-kicker">Rack {rackNumber}</p><h1>Workout unavailable</h1><p>{requestError}</p><button onClick={() => setRefreshRequest((value) => value + 1)}>Retry</button></section></main>;
  }

  async function updateAthleteIdentity(method, athleteId = null) {
    setIdentityBusy(true);
    setIdentityError("");
    setIdentityStatus("");
    try {
      const payload = athleteId === null ? { device_id: rackDeviceId } : buildAthleteIdentityPayload(rackDeviceId, athleteId);
      const response = await fetch(`/api/racks/${rackNumber}/athlete/`, {
        method,
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setIdentityError(`${body.code ? `${body.code}: ` : ""}${body.detail || "Athlete selection could not be changed."}`);
        if (response.status === 409) setRefreshRequest((value) => value + 1);
        return;
      }
      setPendingAthleteId("");
      setConfirmAthleteId("");
      setIdentityStatus(method === "DELETE" ? "Signed out. Refreshing rack..." : "Athlete confirmed. Loading workout...");
      setRefreshRequest((value) => value + 1);
    } catch (error) {
      setIdentityError(error.message || "Athlete selection could not be changed.");
    } finally {
      setIdentityBusy(false);
    }
  }

  async function startExpectedSet() {
    setExecutionBusy(true);
    setExecutionError("");
    setExecutionStatus("");
    try {
      const response = await fetch(`/api/racks/${rackNumber}/sets/`, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(buildRackSetStartPayload(rackDeviceId)),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setExecutionError(`${body.code ? `${body.code}: ` : ""}${body.detail || "Set could not be started."}`);
        setRefreshRequest((value) => value + 1);
        return;
      }
      setActiveSetId(body.id);
      setLiveReps([]);
      setExecutionStatus(`Set ${body.set_number} started. Live reps are not saved until completion.`);
      setRefreshRequest((value) => value + 1);
    } catch (error) {
      setExecutionError(error.message || "Set could not be started.");
    } finally {
      setExecutionBusy(false);
    }
  }

  async function finishExpectedSet(isFalseSet) {
    if (!activeSetId) return;
    setExecutionBusy(true);
    setExecutionError("");
    setExecutionStatus("");
    try {
      const response = await fetch(`/api/racks/${rackNumber}/sets/${activeSetId}/complete/`, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json", "X-Rack-Device-Id": rackDeviceId },
        body: JSON.stringify(buildSetCompletionPayload(liveReps, progress?.exercise, isFalseSet)),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setExecutionError(`${body.code ? `${body.code}: ` : ""}${body.detail || body.error || "Set could not be completed."}`);
        setRefreshRequest((value) => value + 1);
        return;
      }
      setActiveSetId(null);
      setLiveReps([]);
      setExecutionStatus(isFalseSet ? "False set saved. The same set remains expected." : "Set and live reps saved. Loading the next step...");
      setRefreshRequest((value) => value + 1);
    } catch (error) {
      setExecutionError(error.message || "Set could not be completed.");
    } finally {
      setExecutionBusy(false);
    }
  }

  const latestRep = liveReps.at(-1);
  const targetLabel = latestRep && hasVelocityTarget(feedbackTarget)
    ? classifyVelocity(latestRep.mean_velocity, targetMinimum, targetMaximum)
    : "Waiting for a rep";
  const mqttLabel = mqttState === "live" ? "MQTT connected" : mqttState === "reconnecting" ? "MQTT reconnecting" : "MQTT connecting";

  if (catalogMode) {
    const athletes = athleteNameLabels(rackState.active_athletes || rackState.available_athletes || rackState.athletes || []);
    const pendingAthlete = athletes.find((athlete) => Number(athlete.id) === Number(confirmAthleteId));
    const effectiveSourceLabel = effectiveAssignmentLabel(planningState.source, effectiveWorkout);
    return <main className="monitor rack-screen">
      <header className="rack-topbar"><div className="monitor-brand"><b>EA</b><span>Edge Athlete</span></div><div><span>Training station</span><h1>Rack {rackState.rack_number}</h1></div><div className={`rack-status ${requestState === "stale" || mqttState !== "live" ? "warning" : ""}`} role="status"><b>{requestState === "stale" ? "Rack state retry needed" : mqttLabel}</b><span>{requestState === "stale" ? requestError : "Catalog workout mode"}</span></div></header>
      {requestState === "stale" && <div className="rack-retry" role="alert"><span>Showing the last valid rack assignment.</span><button onClick={() => setRefreshRequest((value) => value + 1)}>Retry rack state</button></div>}
      {!rackState.active_session ? <section className="rack-empty-state"><p className="rack-kicker">Rack ready</p><h2>No active session</h2><p>A coach must start a training session before athletes can identify themselves.</p></section>
        : !rackState.selected_athlete && !planningState.identityAvailable && !rackState.catalog_assignment && !rackState.assignment ? <section className="rack-empty-state"><p className="rack-kicker">Catalog mode</p><h2>Waiting for a workout</h2><p>A coach must assign a catalog workout to this rack.</p></section>
        : !rackState.selected_athlete ? <section className="rack-identity"><header><p className="rack-kicker">{rackState.active_session.label}</p><h2>Who is training?</h2><p>Select your name, then confirm before opening the workout.</p></header>
          {athletes.length === 0 ? <p className="monitor-empty">No athletes are available for this training day.</p> : confirmAthleteId ? <div className="rack-identity-confirm" role="group" aria-labelledby="confirm-athlete-heading"><span>Confirm athlete</span><h3 id="confirm-athlete-heading">{pendingAthlete?.label}</h3><p>This rack will show this athlete’s effective workout.</p><div><button className="rack-secondary" onClick={() => setConfirmAthleteId("")} disabled={identityBusy}>Go back</button><button onClick={() => updateAthleteIdentity("PUT", confirmAthleteId)} disabled={identityBusy}>{identityBusy ? "Confirming..." : "Confirm athlete"}</button></div></div> : <div className="rack-identity-picker"><label>Athlete name<select value={pendingAthleteId} onChange={(event) => setPendingAthleteId(event.target.value)} disabled={identityBusy}><option value="">Select your name</option>{athletes.map((athlete) => <option value={athlete.id} key={athlete.id}>{athlete.label}</option>)}</select></label><button onClick={() => setConfirmAthleteId(pendingAthleteId)} disabled={!pendingAthleteId || identityBusy}>Continue to confirmation</button></div>}
          {rackState.active_athletes_truncated && <p className="monitor-empty">Only the first 100 athletes are shown. Ask a coach if your name is not listed.</p>}
          {identityStatus && <p className="rack-identity-status" role="status">{identityStatus}</p>}{identityError && <p className="rack-identity-error" role="alert">{identityError}</p>}
        </section>
        : !progress ? <section className="rack-empty-state"><p className="rack-kicker">{rackState.selected_athlete.name}</p><h2>Progress unavailable</h2><p>The athlete’s program progress could not be restored.</p><button onClick={() => updateAthleteIdentity("DELETE")} disabled={identityBusy}>Sign out</button>{identityError && <p className="rack-identity-error" role="alert">{identityError}</p>}</section>
        : progress.complete ? <section className="rack-empty-state"><p className="rack-kicker">{progress.programName}</p><h2>Program complete</h2><p>{rackState.selected_athlete.name} has completed today’s assigned program.</p><button onClick={() => updateAthleteIdentity("DELETE")} disabled={identityBusy}>Sign out</button>{identityError && <p className="rack-identity-error" role="alert">{identityError}</p>}</section>
        : <div className="rack-layout catalog-rack-layout">
          <section className="rack-current"><div className="rack-current-heading"><div><p className="rack-kicker">{progress.programName} · Workout {progress.workoutPosition}</p><span className="rack-effective-source">{effectiveSourceLabel}</span><h2>{progress.exercise.exercise}</h2><p className="rack-athlete-name">{rackState.selected_athlete.name}</p></div><button className="rack-signout" onClick={() => updateAthleteIdentity("DELETE")} disabled={identityBusy || Boolean(activeSetId)}>{identityBusy ? "Signing out..." : "Sign out"}</button></div><dl className="rack-prescription-summary"><div><dt>Expected set</dt><dd>{progress.expectedSetNumber} of {progress.exercise.sets}</dd></div><div><dt>Reps</dt><dd>{progress.exercise.reps}</dd></div><div><dt>Load</dt><dd>{progress.exercise.default_weight_lbs ?? "--"}<small> lbs</small></dd></div></dl><div className="rack-node-state"><b>{nodeMessage(node)}</b><span>{node?.node_id || "No node ID"}</span></div><div className="rack-set-actions">{activeSetId ? <><button onClick={() => finishExpectedSet(false)} disabled={executionBusy}>{executionBusy ? "Saving..." : `Save ${liveReps.length} live reps and complete`}</button><button className="rack-false-set" onClick={() => finishExpectedSet(true)} disabled={executionBusy}>Mark false set</button></> : <button onClick={startExpectedSet} disabled={executionBusy || node?.state !== "ready"}>{executionBusy ? "Starting..." : `Start expected set ${progress.expectedSetNumber}`}</button>}</div>{executionStatus && <p className="rack-execution-status" role="status">{executionStatus}</p>}{executionError && <p className="rack-identity-error" role="alert">{executionError}</p>}{identityError && <p className="rack-identity-error" role="alert">{identityError}</p>}</section>
          <section className={`rack-live ${targetLabel.toLowerCase().replaceAll(" ", "-")}`} aria-label="Unsaved live velocity feedback"><header><div><p className="rack-kicker">Current exercise feedback</p><b>Unsaved</b></div><button onClick={() => setLiveReps([])} disabled={liveReps.length === 0}>Reset reps</button></header>{feedbackTarget && !hasVelocityTarget(feedbackTarget) ? <div className="rack-no-velocity"><strong>No velocity target</strong><p>This exercise does not use live velocity feedback.</p></div> : <div className="rack-live-grid"><div><span>Accepted reps</span><strong>{latestRep?.arrival_number || 0}</strong></div><div><span>Latest mean</span><strong>{latestRep ? velocity(latestRep.mean_velocity) : "--"}<small> m/s</small></strong></div><div><span>Target range</span><strong>{feedbackTarget && hasVelocityTarget(feedbackTarget) ? `${velocity(targetMinimum)}-${velocity(targetMaximum)}` : "--"}<small> m/s</small></strong></div><p role="status" aria-live="polite">{liveTopic ? targetLabel : "Live feedback unavailable"}</p></div>}</section>
          <section className="rack-programs"><header><p className="rack-kicker">Persisted progress</p><h3>{progress.workoutName}</h3></header><div className="catalog-exercise-list"><article><header><span>Exercise {progress.exercise.position}</span><h4>{progress.exercise.exercise}</h4></header><dl><div><dt>Sets x reps</dt><dd>{progress.exercise.sets} x {progress.exercise.reps}</dd></div><div><dt>Completed sets</dt><dd>{progress.currentExerciseCompletion?.completed_sets || 0}</dd></div><div><dt>False sets</dt><dd>{progress.currentExerciseCompletion?.false_sets || 0}</dd></div><div><dt>Velocity</dt><dd>{hasVelocityTarget(progress.exercise) ? `${velocity(progress.exercise.velocity_min)}-${velocity(progress.exercise.velocity_max)} m/s` : "No velocity target"}</dd></div></dl></article></div>{progress.currentExerciseCompletion?.sets.length > 0 && <div className="rack-persisted-sets" aria-label="Persisted completed sets">{progress.currentExerciseCompletion.sets.map((workoutSet) => <article key={workoutSet.id}><b>{workoutSet.is_false_set ? "False set" : `Persisted set ${workoutSet.set_number}`}</b><span>{workoutSet.reps_completed} reps · {workoutSet.weight_lbs ?? "--"} lbs</span></article>)}</div>}</section>
        </div>}
    </main>;
  }

  return <main className="monitor rack-screen">
    <header className="rack-topbar">
      <div className="monitor-brand"><b>EA</b><span>Edge Athlete</span></div>
      <div><span>Training station</span><h1>Rack {rackState.rack_number}</h1></div>
      <div className={`rack-status ${requestState === "stale" || mqttState !== "live" ? "warning" : ""}`} role="status">
        <b>{requestState === "stale" ? "Rack state retry needed" : mqttLabel}</b>
        <span>{requestState === "stale" ? requestError : "Unsaved live feedback"}</span>
      </div>
    </header>

    {requestState === "stale" && <div className="rack-retry" role="alert"><span>Showing the last valid coach selection.</span><button onClick={() => setRefreshRequest((value) => value + 1)}>Retry rack state</button></div>}

    {!rackState.active_session ? <section className="rack-empty-state"><p className="rack-kicker">Rack ready</p><h2>No active session</h2><p>A coach must start a training session before selecting a workout.</p></section>
      : !rackState.selected_athlete ? <section className="rack-empty-state"><p className="rack-kicker">{rackState.active_session.label}</p><h2>Waiting for coach selection</h2><p>The workout will appear here after a coach selects an athlete and movement.</p></section>
      : <div className="rack-layout">
        <section className="rack-current">
          <p className="rack-kicker">Coach-selected movement</p>
          <h2>{activeProgram?.exercise || "Movement not selected"}</h2>
          <p className="rack-athlete-name">{rackState.selected_athlete.name}</p>
          {activeProgram && <dl className="rack-prescription-summary">
            <div><dt>Sets</dt><dd>{activeProgram.target_sets}</dd></div>
            <div><dt>Reps</dt><dd>{activeProgram.target_reps}</dd></div>
            <div><dt>Load</dt><dd>{activeProgram.target_weight_lbs ?? "--"}<small> lbs</small></dd></div>
          </dl>}
          <div className="rack-node-state"><b>{nodeMessage(node)}</b><span>{node?.node_id || "No node ID"}</span></div>
        </section>

        <section className={`rack-live ${targetLabel.toLowerCase().replaceAll(" ", "-")}`} aria-label="Unsaved live velocity feedback">
          <header><div><p className="rack-kicker">Live feedback</p><b>Unsaved</b></div><button onClick={() => setLiveReps([])} disabled={liveReps.length === 0}>Reset reps</button></header>
          {activeProgram && !hasVelocityTarget(activeProgram) ? <div className="rack-no-velocity"><strong>No velocity target</strong><p>This prescription does not use live velocity feedback.</p></div>
            : <div className="rack-live-grid">
              <div><span>Accepted reps</span><strong>{latestRep?.arrival_number || 0}</strong></div>
              <div><span>Latest mean</span><strong>{latestRep ? velocity(latestRep.mean_velocity) : "--"}<small> m/s</small></strong></div>
              <div><span>Target range</span><strong>{activeProgram && hasVelocityTarget(activeProgram) ? `${velocity(activeProgram.velocity_zone_min)}-${velocity(activeProgram.velocity_zone_max)}` : "--"}<small> m/s</small></strong></div>
              <p role="status" aria-live="polite">{liveTopic ? targetLabel : "Live feedback unavailable"}</p>
            </div>}
        </section>

        <section className="rack-programs">
          <header><p className="rack-kicker">Full prescription</p><h3>Today for {rackState.selected_athlete.name}</h3></header>
          <div className="rack-program-list">{rackState.programs.map((program) => <article className={program.id === activeProgram?.id ? "active" : ""} key={program.id}>
            <div><span>{program.id === activeProgram?.id ? "Selected" : "Movement"}</span><h4>{program.exercise}</h4></div>
            <dl><div><dt>Sets × reps</dt><dd>{program.target_sets} × {program.target_reps}</dd></div><div><dt>Load</dt><dd>{program.target_weight_lbs ?? "--"} lbs</dd></div><div><dt>Velocity</dt><dd>{hasVelocityTarget(program) ? `${velocity(program.velocity_zone_min)}-${velocity(program.velocity_zone_max)} m/s` : "No velocity target"}</dd></div></dl>
          </article>)}</div>
        </section>
      </div>}
  </main>;
}
