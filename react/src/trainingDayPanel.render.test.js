// Does the training-day panel actually RENDER?
//
// Every other test in this repo checks a pure helper. That left one whole class
// of bug uncovered, and it is the class that has actually hurt: a JSX file
// referencing an identifier that no longer exists compiles perfectly happily,
// and React 19 unmounts the entire root on an uncaught render error — so the
// symptom is a black screen, in the browser, at runtime. One of those (a deleted
// piece of state left behind in the JSX) shipped past a fully green suite.
//
// renderToStaticMarkup needs no DOM and no new dependencies, and it evaluates
// every expression in the tree. That is enough to catch an undefined identifier,
// a bad destructure, or a crash reading an optional field — which is most of what
// has gone wrong here.
//
// It is NOT a substitute for clicking the thing. It proves the panel renders in a
// given state; it does not prove the buttons do the right work.

import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ConflictPrompt, OpenDayFromScratch, StartStagedDay } from "./TrainingDayPanel.jsx";

const athletes = [
  { id: 4, name: "Jordan Lee" },
  { id: 5, name: "Sam Rivera" },
];

function render(props) {
  return renderToStaticMarkup(createElement(OpenDayFromScratch, {
    athletes,
    accessToken: "test-token",
    onLogout: () => {},
    refresh: async () => {},
    ...props,
  }));
}

// ⚠️ THE ACTIVE-DAY CASES ARE NOT HERE ANY MORE. Ending a day moved to
// coach/SessionWidget.jsx in Phase B, and so did its tests — the stale-day
// banner, the simulation notice and the end button now live in
// coach/sessionWidget.render.test.js. What is left here is opening a day.
describe("OpenDayFromScratch renders", () => {
  it("shows the start form with every athlete tickable", () => {
    const html = render({});
    expect(html).toContain("Open the room now");
    expect(html).toContain("Jordan Lee");
    expect(html).toContain("Sam Rivera");
  });

  // It lives in PLANNING and starts the room immediately, which is unusual
  // enough that the screen has to say so rather than let a coach discover it.
  it("says it opens the room at once, with no staged step", () => {
    expect(render({})).toContain("there is no staged step");
  });

  it("survives being handed no athletes at all — a brand-new gym", () => {
    expect(render({ athletes: [] })).toContain("Open the room now");
  });
});

describe("StartStagedDay renders", () => {
  const slot = {
    id: 9, session: 21, workout_name: "Day 1 — Lower", group_name: "Varsity",
    date: "2026-08-03", session_started_at: null, session_ended_at: null,
  };

  function renderStaged(props) {
    return renderToStaticMarkup(createElement(StartStagedDay, {
      slots: [slot], accessToken: "test-token", onLogout: () => {},
      refresh: async () => {}, ...props,
    }));
  }

  it("names the day, its group and its date", () => {
    const html = renderStaged({});
    expect(html).toContain("Day 1 — Lower");
    expect(html).toContain("Varsity");
  });

  // A coach must never read this list as the room already being open — a staged
  // day holds no racks and captures no check-ins (canon D18).
  it("says nothing is holding the racks yet", () => {
    expect(renderStaged({})).toContain("Nothing is holding the racks");
  });

  it("renders nothing at all when no day is staged", () => {
    expect(renderStaged({ slots: [] })).toBe("");
  });
});

describe("ConflictPrompt renders", () => {
  const conflict = { id: 3, label: "Thursday — Lower", started_at: "2026-07-28T14:00:00Z" };

  function renderPrompt(props) {
    return renderToStaticMarkup(createElement(ConflictPrompt, {
      conflict, endedAt: "", onEndedAtChange: () => {},
      newDayLabel: "Friday — Upper", onCancel: () => {}, onConfirm: () => {},
      busy: "", ...props,
    }));
  }

  it("names the day in the way and the day being started", () => {
    const html = renderPrompt({});
    expect(html).toContain("Thursday — Lower");
    expect(html).toContain("Friday — Upper");
  });

  it("promises the form is kept, because that is the reason it exists", () => {
    expect(renderPrompt({})).toContain("label and roster are kept");
  });

  it("offers end times for the blocking day, defaulting to now", () => {
    const html = renderPrompt({});
    expect(html).toContain("Ends it as of right now");
    expect(html).toContain("Now</option>");
  });

  it("says the report will record a chosen time once one is picked", () => {
    expect(renderPrompt({ endedAt: "2026-07-28T16:00:00.000Z" }))
      .toContain("report will record this time");
  });

  it("disables both buttons while the two requests are in flight", () => {
    const html = renderPrompt({ busy: "resolve" });
    expect(html).toContain("Ending and starting...");
    expect((html.match(/disabled/g) || []).length).toBeGreaterThanOrEqual(2);
  });

  // An unnamed day would make the button read "start “”".
  it("falls back to a readable button when no label has been typed yet", () => {
    expect(renderPrompt({ newDayLabel: "   " })).toContain("my day");
  });

  it("survives a conflict payload with no start time", () => {
    const html = renderPrompt({ conflict: { id: 3, label: "Unknown start" } });
    expect(html).toContain("Unknown start");
  });
});
