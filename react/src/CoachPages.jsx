import { useState } from "react";
import "./App.css";
import RouteLauncher from "./RouteLauncher.jsx";
import { athlete, coachAlerts, complianceRows, racks, setupHealth, setupRows } from "./data/demoDashboardData.js";

function formatVelocity(value) {
  if (value === null || value === undefined) return "--";
  return value.toFixed(2);
}

function MiniBarChart({ values, targetZone }) {
  return (
    <div className="mini-chart">
      {values.map((value, index) => {
        const color = value >= targetZone.min ? "green" : value >= targetZone.min * 0.9 ? "yellow" : "red";
        return (
          <div className="mini-chart-bar" key={`${value}-${index}`}>
            <span>{index + 1}</span>
            <i className={color} style={{ height: `${Math.max(18, value * 100)}%` }} />
            <b>{value.toFixed(2)}</b>
          </div>
        );
      })}
    </div>
  );
}

function PageShell({ title, subtitle, children }) {
  return (
    <main className="coach-page-shell">
      <RouteLauncher />
      <header className="coach-page-header">
        <div>
          <p className="screen-kicker">Coach tools</p>
          <h1>{title}</h1>
          <span>{subtitle}</span>
        </div>
      </header>
      {children}
    </main>
  );
}

export function RackDetailPage() {
  const [selectedRackNumber, setSelectedRackNumber] = useState(1);
  const rack = racks.find((item) => item.rackNumber === selectedRackNumber) || racks[0];
  const avg = rack.reps.reduce((sum, rep) => sum + rep, 0) / rack.reps.length;
  const drop = rack.reps[0] - rack.reps[rack.reps.length - 1];

  return (
    <PageShell title={`Rack ${rack.rackNumber} Detail`} subtitle="Current set, reps, velocity chart, and rest guidance">
      <section className="rack-picker-strip" aria-label="Choose rack or athlete">
        {racks.map((item) => (
          <button
            className={item.rackNumber === rack.rackNumber ? "active" : ""}
            key={item.rackNumber}
            onClick={() => setSelectedRackNumber(item.rackNumber)}
          >
            <span>Rack {item.rackNumber}</span>
            <strong>{item.athleteName}</strong>
            <b className={item.statusColor}>{item.status}</b>
          </button>
        ))}
      </section>
      <section className="detail-page-grid">
        <article className="large-detail-card">
          <div className="detail-heading">
            <span>Current set</span>
            <h3>{rack.athleteName} - {rack.exercise}</h3>
            <p>Set {rack.setNumber} of 5 - {rack.loadLbs} lbs - {rack.repCount} reps</p>
          </div>
          <div className="detail-metric-grid wide">
            <div><span>Current velocity</span><strong>{formatVelocity(rack.currentVelocity)} m/s</strong></div>
            <div><span>Average velocity</span><strong>{formatVelocity(avg)} m/s</strong></div>
            <div><span>Rest timer</span><strong>{rack.restSecondsRemaining ? `${rack.restSecondsRemaining}s` : "Ready"}</strong></div>
            <div><span>Target zone</span><strong>{rack.targetZone.min.toFixed(2)}-{rack.targetZone.max.toFixed(2)}</strong></div>
            <div><span>Set quality</span><strong>{rack.setQuality}%</strong></div>
            <div><span>Velocity drop</span><strong>{drop.toFixed(2)} m/s</strong></div>
            <div><span>Compliance</span><strong>{rack.compliance}</strong></div>
            <div><span>Readiness</span><strong>{rack.readiness}</strong></div>
          </div>
          <MiniBarChart values={rack.reps} targetZone={rack.targetZone} />
        </article>
        <article className="large-detail-card">
          <div className="detail-section-title">Coach guidance</div>
          <p className="detail-copy">{rack.recommendation}</p>
          <p className="detail-copy">Trend: {rack.trend}</p>
          <p className="detail-copy">Form cue: {rack.formCue}</p>
          <section className="decision-stack">
            <div><span>If next rep is above 0.80</span><strong>Finish planned set</strong></div>
            <div><span>If next rep is 0.72-0.79</span><strong>Complete set, extend rest</strong></div>
            <div><span>If next rep is below 0.72</span><strong>Stop set or reduce load</strong></div>
          </section>
          <div className="detail-actions stacked">
            <button>End set</button>
            <button>Start rest timer</button>
            <button>Flag form check</button>
          </div>
        </article>
      </section>
    </PageShell>
  );
}

export function AthleteDetailPage() {
  return (
    <PageShell title={athlete.name} subtitle={`${athlete.team} - ${athlete.block}`}>
      <section className="athlete-grid">
        <article className="large-detail-card">
          <div className="detail-section-title">PRs</div>
          <div className="detail-metric-grid wide">
            {athlete.prs.map((pr) => <div key={pr.label}><span>{pr.label}</span><strong>{pr.value}</strong></div>)}
            <div><span>Readiness</span><strong>{athlete.readiness}</strong></div>
            <div><span>Fatigue score</span><strong>{athlete.fatigueScore}</strong></div>
            <div><span>Weekly change</span><strong>{athlete.weeklyChange}</strong></div>
          </div>
        </article>
        <article className="large-detail-card">
          <div className="detail-section-title">Performance history</div>
          {athlete.history.map((row) => (
            <div className="history-row" key={row.date}>
              <span>{row.date}</span>
              <strong>{row.lift}</strong>
              <b>{row.load} lbs</b>
              <em>{row.avg.toFixed(2)} avg / {row.peak.toFixed(2)} peak</em>
            </div>
          ))}
        </article>
        <article className="large-detail-card">
          <div className="detail-section-title">Trends</div>
          <MiniBarChart values={athlete.history.map((row) => row.avg)} targetZone={{ min: 0.72, max: 0.9 }} />
        </article>
        <article className="large-detail-card">
          <div className="detail-section-title">Coach notes</div>
          {athlete.notes.map((note) => <p className="detail-copy" key={note}>{note}</p>)}
          <div className="detail-actions stacked">
            <button>Add session note</button>
            <button>Adjust next workout</button>
          </div>
        </article>
      </section>
    </PageShell>
  );
}

function SetupSection({ title, rows, selected, onSelect }) {
  return (
    <article className="setup-card">
      <div className="setup-title-row">
        <h3>{title}</h3>
        <button>Add</button>
      </div>
      {rows.map((row) => (
        <button
          className={`setup-row ${selected?.group === title && selected?.label === row.label ? "selected" : ""}`}
          key={`${title}-${row.label}`}
          onClick={() => onSelect({ ...row, group: title })}
        >
          <strong>{row.label}</strong>
          <span>{row.value}</span>
          <b>{row.status}</b>
        </button>
      ))}
    </article>
  );
}

export function AdminSetupPage() {
  const [selected, setSelected] = useState({ ...setupRows.rackScreens[0], group: "Rack screens" });

  return (
    <PageShell title="Admin / Setup" subtitle="Assign rack screens, nodes, athletes, and programs">
      <section className="setup-health-grid">
        {setupHealth.map((item) => (
          <article className={`setup-health-card ${item.state}`} key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </article>
        ))}
      </section>
      <section className="setup-grid with-detail">
        <div className="setup-grid-list">
          <SetupSection title="Rack screens" rows={setupRows.rackScreens} selected={selected} onSelect={setSelected} />
          <SetupSection title="Nodes" rows={setupRows.nodes} selected={selected} onSelect={setSelected} />
          <SetupSection title="Athletes" rows={setupRows.athletes} selected={selected} onSelect={setSelected} />
          <SetupSection title="Programs" rows={setupRows.programs} selected={selected} onSelect={setSelected} />
        </div>
        <aside className="admin-selected-panel">
          <div className="detail-section-title">Selected {selected.group}</div>
          <h3>{selected.label}</h3>
          <p>{selected.value}</p>
          <b>{selected.status}</b>
          <div className="admin-action-grid">
            <button>Assign to rack</button>
            <button>Edit details</button>
            <button>Mark checked</button>
            <button>View history</button>
          </div>
          <div className="admin-selected-note">
            {selected.group === "Rack screens" && "Use this panel to assign a tablet to a physical rack or clear an old assignment."}
            {selected.group === "Nodes" && "Use this panel to pair a sensor node with the rack it is mounted on."}
            {selected.group === "Athletes" && "Use this panel to check in an athlete or link them to a rack for the current session."}
            {selected.group === "Programs" && "Use this panel to choose the active prescription for today’s workout."}
          </div>
        </aside>
      </section>
      <section className="admin-workflow-grid">
        <article className="large-detail-card">
          <div className="detail-section-title">Setup checklist</div>
          <div className="checklist-row done">Rack screens registered</div>
          <div className="checklist-row done">Nodes publishing heartbeat</div>
          <div className="checklist-row warn">Tablet C needs rack assignment</div>
          <div className="checklist-row warn">Rack 3 node battery below target</div>
        </article>
        <article className="large-detail-card">
          <div className="detail-section-title">Coach dashboard health</div>
          {coachAlerts.map((alert) => <p className="detail-copy" key={alert.title}>{alert.title}: {alert.body}</p>)}
          {complianceRows.map((row) => <p className="detail-copy" key={row.label}>{row.label}: {row.value} ({row.status})</p>)}
        </article>
      </section>
    </PageShell>
  );
}
