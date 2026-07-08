// WallDisplay.jsx — the team wall display page (route /dashboard).
// This is the "big screen on the gym wall" the whole room reads at a glance. It
// opens straight into a full-bleed kiosk layout with its OWN identity (title +
// icon + web app manifest) so it installs and launches separately from the
// tablet app. It owns exactly ONE data source — the useDashboardFeed hook — and
// splits the screen into four fixed areas that only ever *display* what the hook
// hands them: Rack Status, Leaderboard, Summary, and Insights. No area fetches
// its own data; there is no interactivity; it just updates itself live.

import { useEffect } from "react";
import { useDashboardFeed } from "./useDashboardFeed.js";
import RackStatus from "./RackStatus.jsx";
import Leaderboard from "./Leaderboard.jsx";
import Summary from "./Summary.jsx";
import Insights from "./Insights.jsx";
import "./WallDisplay.css";

// Give the wall display its own name + icon at runtime. Because the whole app is
// one index.html, we swap the document title, favicon, and manifest link when
// this page mounts so the OS/browser treats "Edge Athlete Wall" as a distinct
// installable app from the tablet UI (the kiosk launcher opens it with --app=).
function useWallIdentity() {
  useEffect(() => {
    const prevTitle = document.title;
    document.title = "Edge Athlete — Wall Display";

    const icon = document.createElement("link");
    icon.rel = "icon";
    icon.type = "image/svg+xml";
    icon.href = "/wall-display-icon.svg";
    document.head.appendChild(icon);

    const manifest = document.createElement("link");
    manifest.rel = "manifest";
    manifest.href = "/wall-display.webmanifest";
    document.head.appendChild(manifest);

    return () => {
      document.title = prevTitle;
      icon.remove();
      manifest.remove();
    };
  }, []);
}

const STATUS_LABEL = {
  connecting: "Connecting…",
  live: "Live",
  offline: "Reconnecting…",
};

function WallDisplay() {
  useWallIdentity();
  const { connection, racks, leaderboard, summary, insights } = useDashboardFeed();

  return (
    <div className="wd-root">
      <header className="wd-header">
        <h1 className="wd-brand">Edge Athlete</h1>
        <div className={"wd-conn wd-conn-" + connection}>
          <span className="wd-conn-dot" />
          {STATUS_LABEL[connection] || connection}
        </div>
      </header>

      <main className="wd-grid">
        <RackStatus racks={racks} />
        <Leaderboard leaderboard={leaderboard} />
        <Summary summary={summary} />
        <Insights insights={insights} />
      </main>
    </div>
  );
}

export default WallDisplay;
