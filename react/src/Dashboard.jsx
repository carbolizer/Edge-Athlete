import { useState, useEffect } from "react";
import "./App.css";
import RouteLauncher from "./RouteLauncher.jsx";
import StatisticsView from "./StatisticsView.jsx";
import {
  coachAlerts,
  complianceRows,
  leaderboard,
  racks as INITIAL_RACKS,
  roomSummary,
} from "./data/demoDashboardData.js";

const API_BASE = "/api";

function formatVelocity(value) {
  if (value === null || value === undefined) return "--";
  return value.toFixed(2);
}

function formatRest(seconds) {
  const safeSeconds = Math.max(0, seconds || 0);
  const minutes = Math.floor(safeSeconds / 60);
  const remaining = safeSeconds % 60;
  return `${minutes}:${String(remaining).padStart(2, "0")}`;
}

function CoachRackCard({ rack, selected, onSelect, disabled = false }) {
  const statusClass = `coach-rack-card ${rack.statusColor}${selected ? " selected" : ""}`;
  const velocityLabel = rack.status === "complete" ? "avg" : "m/s";

  return (
    <button className={statusClass} onClick={onSelect} disabled={disabled}>
      <div className="coach-rack-topline">
        <span>Rack {rack.rackNumber}</span>
        <b className={`coach-status ${rack.statusColor}`}>{rack.status}</b>
      </div>
      <div>
        <h3>{rack.athleteName}</h3>
        <p>{rack.status === "resting" ? `Rest - ${formatRest(rack.restSecondsRemaining)} left` : rack.status === "complete" ? "5 of 5 done" : `Set ${rack.setNumber} of 5`}</p>
      </div>
      <div className="coach-rack-value">
        <strong>{formatVelocity(rack.status === "complete" ? rack.lastSetAvgVelocity : rack.currentVelocity)}</strong>
        <span>{velocityLabel}</span>
      </div>
    </button>
  );
}

function CoachRackDetail({ rack }) {
  const bestRep = Math.max(...rack.reps);
  const avgRep = rack.reps.reduce((sum, rep) => sum + rep, 0) / rack.reps.length;
  const inZone = avgRep >= rack.targetZone.min && avgRep <= rack.targetZone.max;

  return (
    <aside className="coach-detail-panel">
      <div className="detail-heading">
        <span>Coach view</span>
        <h3>Rack {rack.rackNumber} - {rack.athleteName}</h3>
        <p>{rack.exercise} - {rack.loadLbs} lbs - Set {rack.setNumber} of 5</p>
      </div>

      <div className="detail-metric-grid">
        <div><span>Current</span><strong>{formatVelocity(rack.currentVelocity)} m/s</strong></div>
        <div><span>Avg set</span><strong>{formatVelocity(avgRep)} m/s</strong></div>
        <div><span>Best rep</span><strong>{formatVelocity(bestRep)} m/s</strong></div>
        <div><span>Target</span><strong>{rack.targetZone.min.toFixed(2)}-{rack.targetZone.max.toFixed(2)}</strong></div>
      </div>

      <section className={`coach-callout ${inZone ? "good" : "watch"}`}>
        <span>{inZone ? "On target" : "Needs attention"}</span>
        <strong>{rack.recommendation}</strong>
      </section>

      <section className="detail-reps">
        <div className="detail-section-title">Rep velocity</div>
        {rack.reps.map((velocity, index) => {
          const color = velocity >= rack.targetZone.min ? "green" : velocity >= rack.targetZone.min * 0.9 ? "yellow" : "red";
          return (
            <div className="detail-rep-row" key={`${rack.rackNumber}-${index}`}>
              <span>Rep {index + 1}</span>
              <div><i className={color} style={{ width: `${Math.min(100, velocity * 100)}%` }} /></div>
              <strong>{velocity.toFixed(2)}</strong>
            </div>
          );
        })}
      </section>

      <section className="detail-notes">
        <div className="detail-section-title">Coach notes</div>
        <p>{rack.trend}</p>
      </section>

      <div className="detail-actions">
        <button>Mark checked</button>
        <button>Open athlete history</button>
      </div>
    </aside>
  );
}

function ReadinessStrip() {
  return (
    <section className="readiness-strip">
      {roomSummary.readiness.map((item) => (
        <div key={item.label}>
          <strong>{item.value}</strong>
          <span>{item.label}</span>
        </div>
      ))}
    </section>
  );
}

function WallLeaderboard() {
  return (
    <section className="wall-leaderboard">
      <h3>Top velocities</h3>
      {leaderboard.map((row) => (
        <div className="wall-leader-row" key={row.rank}>
          <b>#{row.rank}</b>
          <strong>{row.name}</strong>
          <span>Rack {row.rack}</span>
          <em>{row.value}</em>
        </div>
      ))}
    </section>
  );
}

function CoachTacticalPanel() {
  return (
    <section className="coach-tactical-grid">
      <article>
        <h3>Live alerts</h3>
        {coachAlerts.map((alert) => (
          <div className={`tactical-row ${alert.level}`} key={alert.title}>
            <span>{alert.title}</span>
            <strong>{alert.body}</strong>
          </div>
        ))}
      </article>
      <article>
        <h3>Program compliance</h3>
        {complianceRows.map((row) => (
          <div className="compliance-row" key={row.label}>
            <span>{row.label}</span>
            <strong>{row.value}</strong>
            <b>{row.status}</b>
          </div>
        ))}
      </article>
    </section>
  );
}

function Dashboard({ onSensorChange, mode = "wall" }) {
  const [racks, setRacks] = useState(INITIAL_RACKS);
  const [nodes, setNodes] = useState([]);
  const [status, setStatus] = useState("Loading...");
  const [activeTab, setActiveTab] = useState("overview");
  const [selectedRackNumber, setSelectedRackNumber] = useState(3);

  useEffect(() => {
    let mounted = true;

    async function loadNodes() {
      try {
        const res = await fetch(`${API_BASE}/nodes/`);
        if (!res.ok) throw new Error("API failed");
        const data = await res.json();
        if (!mounted) return;
        setNodes(Array.isArray(data) ? data : []);
        setStatus("Connected to base station");
      } catch {
        if (mounted) setStatus("Showing dashboard shell data");
      }
    }

    loadNodes();
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      setRacks((current) => current.map((rack) => {
        if (rack.status !== "resting") return rack;
        return {
          ...rack,
          restSecondsRemaining: Math.max(0, rack.restSecondsRemaining - 1),
        };
      }));
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  function applyLiveRep(rackNumber, velocity) {
    setRacks((current) => current.map((rack) => {
      if (rack.rackNumber !== rackNumber) return rack;
      const status = velocity >= rack.targetZone.min
        ? velocity <= rack.targetZone.max ? "green" : "yellow"
        : velocity >= rack.targetZone.min * 0.9 ? "yellow" : "red";

      return {
        ...rack,
        currentVelocity: velocity,
        repCount: rack.repCount + 1,
        status,
      };
    }));
  }

  const nodeCount = nodes.length;
  const selectedRack = racks.find((rack) => rack.rackNumber === selectedRackNumber) || racks[0];
  const isCoachMode = mode === "coach";

  return (
    <div className={`app dashboard-app ${isCoachMode ? "coach-mode" : "wall-mode"}`}>
      <RouteLauncher />
      <div className="sidebar">
        <h1 className="brand-mark">09 - Coach's Set Summary</h1>
        <button className="sensor-button" onClick={() => onSensorChange?.("Room Dashboard")}>
          <span>Room Dashboard</span>
          <span className="status online" />
        </button>
        <div className="sidebar-note">
          <strong>{racks.length}</strong> racks live
          <span>{nodeCount} nodes connected</span>
        </div>
      </div>

      <div className="main">
        <div className="coach-header">
          <div>
            <p className="screen-kicker">{isCoachMode ? "Coach workspace" : "Weight room live board"}</p>
            <h2 className="main-title">{roomSummary.sessionName}</h2>
            <p>{isCoachMode ? "Rack details, trends, and coaching actions" : roomSummary.location}</p>
          </div>
          <div className="coach-summary-metrics">
            <div><span>Elapsed</span><strong>{roomSummary.elapsed}</strong></div>
            <div><span>Active racks</span><strong>{roomSummary.activeRacks}</strong></div>
            <div><span>Room avg vel</span><strong className="metric-good">{roomSummary.roomAvgVelocity}</strong></div>
            <div><span>Sets done</span><strong>{roomSummary.setsCompleted}</strong></div>
          </div>
        </div>

        <div className="tab-bar">
          <button
            className={"tab" + (activeTab === "overview" ? " active" : "")}
            onClick={() => setActiveTab("overview")}
          >
            Overview
          </button>
          <button
            className={"tab" + (activeTab === "statistics" ? " active" : "")}
            onClick={() => setActiveTab("statistics")}
          >
            Statistics
          </button>
        </div>

        {activeTab === "overview" ? (
          <div className={isCoachMode ? "coach-room-layout" : "coach-room-layout wall-room-layout"}>
            <section className="coach-rack-grid" aria-label="Rack status grid">
              {racks.map((rack) => (
                <CoachRackCard
                  key={rack.rackNumber}
                  rack={rack}
                  selected={isCoachMode && rack.rackNumber === selectedRack.rackNumber}
                  onSelect={() => isCoachMode && setSelectedRackNumber(rack.rackNumber)}
                  disabled={!isCoachMode}
                />
              ))}
            </section>

            {isCoachMode ? (
              <div className="coach-side-column">
                <aside className="coach-insights">
                  <h3>Room insights</h3>
                  <div className="insight-card watch">
                    <span>Watch</span>
                    <strong>Rack 3 velocity down 18% - fatigue likely next set.</strong>
                  </div>
                  <div className="insight-card pace">
                    <span>Pace</span>
                    <strong>Room is 8% ahead of session plan.</strong>
                  </div>
                <div className="insight-card trend">
                  <span>Trend</span>
                  <strong>B. Callendar on a PR trajectory - 0.91 m/s at set 2.</strong>
                </div>
                <div className="insight-card watch">
                  <span>Fatigue</span>
                  <strong>2 athletes below target zone on their latest rep.</strong>
                </div>
                <div className="insight-card pace">
                  <span>Program compliance</span>
                  <strong>4 of 6 active racks are matching prescribed load and rep targets.</strong>
                </div>
                </aside>
                <CoachRackDetail rack={selectedRack} />
                <CoachTacticalPanel />
              </div>
            ) : (
              <aside className="coach-insights wall-side-panel">
                <h3>Room highlights</h3>
                <ReadinessStrip />
                <div className="wall-highlight-card live">
                  <span>Now lifting</span>
                  <strong>J. Williams</strong>
                  <p>Rack 1 - 0.82 m/s</p>
                </div>
                <div className="wall-highlight-card best">
                  <span>Fastest set</span>
                  <strong>B. Callendar</strong>
                  <p>0.91 m/s - Rack 5</p>
                </div>
                <div className="wall-highlight-card watch">
                  <span>Watch</span>
                  <strong>Rack 3</strong>
                  <p>Velocity dropping</p>
                </div>
                <WallLeaderboard />
              </aside>
            )}
          </div>
        ) : (
          <StatisticsView events={[]} selectedSensor="All Sensors" />
        )}
      </div>
    </div>
  );
}

export default Dashboard;
