// Summary.jsx — one of the four fixed wall-display areas.
// The room-wide session scoreboard at a glance: total sets, total reps, active
// athletes, and active racks. Pure display — it renders the `summary` object the
// feed hook computed and holds no logic of its own.

function Stat({ label, value }) {
  return (
    <div className="wd-stat">
      <div className="wd-stat-value">{value}</div>
      <div className="wd-stat-label">{label}</div>
    </div>
  );
}

function Summary({ summary }) {
  return (
    <section className="wd-panel wd-summary">
      <h2 className="wd-panel-title">Session Summary</h2>
      <div className="wd-stat-grid">
        <Stat label="Sets" value={summary.totalSets} />
        <Stat label="Reps" value={summary.totalReps} />
        <Stat label="Athletes" value={summary.activeAthletes} />
        <Stat label="Racks" value={summary.activeRacks} />
      </div>
    </section>
  );
}

export default Summary;
