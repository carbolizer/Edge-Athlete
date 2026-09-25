// Insights.jsx — one of the four fixed wall-display areas (the loud one).
// Rotating room "fun facts" — fastest rep, most reps, best average, new PRs. The
// spec wants this VISUALLY PROMINENT, so it gets the biggest type on the wall.
// It is still display-only: the feed hook decides WHAT the insights are; this
// component only cycles through which handed insight is on screen right now.
// (Rotation is a presentation timer, not data fetching — it never calls the
// network.)

import { useEffect, useState } from "react";

const ROTATE_MS = 6000;

function Insights({ insights }) {
  const [index, setIndex] = useState(0);

  // Keep the index in range as the list grows/shrinks, then rotate on a timer.
  useEffect(() => {
    setIndex((i) => (i >= insights.length ? 0 : i));
    if (insights.length <= 1) return;
    const timer = setInterval(
      () => setIndex((i) => (i + 1) % insights.length),
      ROTATE_MS
    );
    return () => clearInterval(timer);
  }, [insights.length]);

  const current = insights[Math.min(index, insights.length - 1)] || insights[0];

  return (
    <section className={"wd-panel wd-insights" + (current?.highlight ? " wd-insights-hot" : "")}>
      <h2 className="wd-panel-title">Insights</h2>
      <div className="wd-insight-body" key={current?.key}>
        <div className="wd-insight-label">{current?.label}</div>
        <div className="wd-insight-value">{current?.value}</div>
      </div>
      {insights.length > 1 && (
        <div className="wd-insight-dots">
          {insights.map((ins, i) => (
            <span
              key={ins.key}
              className={"wd-dot" + (i === index ? " wd-dot-on" : "")}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export default Insights;
