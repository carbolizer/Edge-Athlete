// Leaderboard.jsx — one of the four fixed wall-display areas.
// Athletes ranked by their best average bar speed of the session. It re-orders
// itself the instant the feed hook hands it a new, higher-ranked athlete. Pure
// display: it ranks and renders the `leaderboard` array it is given, nothing more.

const MEDALS = ["#f4c542", "#c9ccd4", "#cd7f32"]; // gold / silver / bronze accents

function Leaderboard({ leaderboard }) {
  const top = leaderboard.slice(0, 8);
  return (
    <section className="wd-panel wd-leaderboard">
      <h2 className="wd-panel-title">Leaderboard</h2>
      {top.length === 0 ? (
        <p className="wd-empty">No sets completed yet.</p>
      ) : (
        <ol className="wd-lb-list">
          {top.map((athlete, i) => (
            <li key={athlete.id} className="wd-lb-row">
              <span className="wd-lb-rank" style={{ color: MEDALS[i] || "#8a93a6" }}>
                {i + 1}
              </span>
              <span className="wd-lb-name">{athlete.name}</span>
              <span className="wd-lb-vel">{athlete.bestAvg.toFixed(2)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export default Leaderboard;
