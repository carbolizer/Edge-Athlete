// The strip that shows the running day — does it render in every state a coach
// can find it in?
//
// These cases MOVED HERE from trainingDayPanel.render.test.js when Phase B split
// starting a day from ending one. They are the same cases for the same reason:
// the stale-day banner and the simulation notice are states a coach meets at the
// worst possible moment, and renderToStaticMarkup is the cheapest proof they
// draw at all.
//
// One case here cannot be reached by clicking on a live base station: reaching
// "no day running" means ENDING the open one, which freezes an immutable report
// and recalculates every athlete's reference max.

import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import SessionWidget from "./SessionWidget.jsx";

function render(roomState, props = {}) {
  return renderToStaticMarkup(createElement(SessionWidget, {
    roomState, accessToken: "test-token", onLogout: () => {},
    refresh: async () => {}, onDayEnded: () => {}, ...props,
  }));
}

const running = {
  session: { id: 3, label: "Monday — Upper", started_at: "2026-07-29T14:00:00Z" },
  participants: [{ id: 4 }, { id: 5 }],
};

describe("SessionWidget", () => {
  // An empty strip on a quiet morning is furniture, and furniture is what this
  // redesign is removing.
  it("renders nothing at all when no day is running", () => {
    expect(render({ session: null, participants: [] })).toBe("");
    expect(render({})).toBe("");
  });

  it("names the running day, its roster and the way out", () => {
    const html = render(running);
    expect(html).toContain("Monday — Upper");
    expect(html).toContain("2 athletes");
    expect(html).toContain("End training day");
  });

  // The power-cut case: the base station comes back with yesterday still open.
  it("flags a day left open from before today, and says nothing was lost", () => {
    const html = render({
      session: {
        id: 3, label: "Thursday — Lower", started_at: "2026-07-28T14:00:00Z",
        opened_on_a_previous_day: true,
      },
      participants: [],
    });
    expect(html).toContain("Still open from an earlier day");
    expect(html).toContain("Nothing was lost");
  });

  // Ending a simulated day would generate a report for training that never
  // happened.
  it("offers no end button while the simulator owns the day", () => {
    const html = render({
      session: { id: 3, label: "Sim day", started_at: "2026-07-29T14:00:00Z", is_simulated: true },
      participants: [],
    });
    expect(html).toContain("Simulation active");
    expect(html).not.toContain("End training day");
  });

  it("survives a session payload missing every optional field", () => {
    expect(render({ session: { label: "Bare" } })).toContain("Bare");
  });

  it("survives a room state with no participants array at all", () => {
    const html = render({ session: { id: 1, label: "Sparse", started_at: "2026-07-29T14:00:00Z" } });
    expect(html).toContain("Sparse");
    expect(html).toContain("0 athletes");
  });

  // A day with no start time cannot be timed. Dashes, not "NaN:NaN:NaN".
  it("shows placeholder dashes rather than NaN when there is no start time", () => {
    const html = render({ session: { id: 1, label: "No start" }, participants: [] });
    expect(html).toContain("--:--:--");
    expect(html).not.toContain("NaN");
  });
});
