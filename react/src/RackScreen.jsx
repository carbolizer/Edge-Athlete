import { useEffect, useRef, useState } from "react";
import mqtt from "mqtt";
import "./App.css";
import { parseMonitoringEvent, ROOM_STATE_TOPIC } from "./roomMonitor.js";
import {
  appendLiveRep,
  classifyVelocity,
  createDeviceId,
  hasVelocityTarget,
  parseRepMessage,
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
      if (body.rack_number !== null && body.rack_number !== undefined) {
        setRackNumber(body.rack_number);
        setAssignmentState("assigned");
        if (pollTimer) clearInterval(pollTimer);
      } else {
        setAssignmentState("waiting");
      }
      setAssignmentError("");
      return body.rack_number !== null && body.rack_number !== undefined;
    }

    async function register() {
      setAssignmentState("registering");
      try {
        const assigned = await readAssignment("/api/racks/register/", {
          method: "POST",
          headers: { Accept: "application/json", "Content-Type": "application/json" },
          body: JSON.stringify({ device_id: rackDeviceId }),
        });
        if (!cancelled && !assigned) {
          pollTimer = setInterval(() => {
            readAssignment("/api/racks/racknumber/", {
              method: "POST",
              headers: { Accept: "application/json", "Content-Type": "application/json" },
              body: JSON.stringify({ device_id: rackDeviceId }),
            }).catch((error) => {
              if (!cancelled) {
                setAssignmentError(error.message);
                setAssignmentState("error");
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
    fetch(`/api/racks/${rackNumber}/state/`, { headers: { Accept: "application/json" }, signal: controller.signal })
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
  }, [rackNumber, refreshRequest]);

  const activeProgram = rackState?.active_program;
  const node = rackState?.node;
  const liveTopic = node?.state === "ready" && node.node_id && hasVelocityTarget(activeProgram)
    ? repTopic(node.node_id)
    : null;
  const selectionKey = `${rackState?.rack_number || ""}:${rackState?.selected_athlete?.id || ""}:${activeProgram?.id || ""}:${node?.state || ""}:${node?.node_id || ""}`;

  useEffect(() => setLiveReps([]), [selectionKey]);

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

  const latestRep = liveReps.at(-1);
  const targetLabel = latestRep && hasVelocityTarget(activeProgram)
    ? classifyVelocity(latestRep.mean_velocity, activeProgram.velocity_zone_min, activeProgram.velocity_zone_max)
    : "Waiting for a rep";
  const mqttLabel = mqttState === "live" ? "MQTT connected" : mqttState === "reconnecting" ? "MQTT reconnecting" : "MQTT connecting";

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
