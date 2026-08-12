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
import TrainingDayPanel, { ConflictPrompt } from "./TrainingDayPanel.jsx";

const athletes = [
  { id: 4, name: "Jordan Lee" },
  { id: 5, name: "Sam Rivera" },
];

function render(props) {
  return renderToStaticMarkup(createElement(TrainingDayPanel, {
    roomState: { session: null, participants: [] },
    athletes,
    accessToken: "test-token",
    onLogout: () => {},
    refresh: async () => {},
    compact: false,
    ...props,
  }));
}

describe("TrainingDayPanel renders", () => {
  it("keeps setup detail collapsed in compact coach mode", () => {
    const html = render({ compact: true });
    expect(html).toContain("No active day");
    expect(html).toContain("Open a day");
    expect(html).not.toContain("Jordan Lee");
  });

  it("shows the start form when no day is running", () => {
    const html = render({});
    expect(html).toContain("Open the room");
    expect(html).toContain("Jordan Lee");
  });

  it("shows the active day when one is running", () => {
    const html = render({
      roomState: {
        session: { id: 3, label: "Monday — Upper", started_at: "2026-07-29T14:00:00Z" },
        participants: [{ id: 4 }],
      },
    });
    expect(html).toContain("Monday — Upper");
    expect(html).toContain("End training day");
  });

  // The power-cut case. This is the state a coach meets after the base station
  // restarts, so it is the one most worth proving renders at all.
  it("flags a day left open from before today, and says nothing was lost", () => {
    const html = render({
      roomState: {
        session: {
          id: 3, label: "Thursday — Lower", started_at: "2026-07-28T14:00:00Z",
          opened_on_a_previous_day: true,
        },
        participants: [],
      },
    });
    expect(html).toContain("Still open from an earlier day");
    expect(html).toContain("Nothing was lost");
  });

  it("survives a session payload missing the optional fields", () => {
    const html = render({ roomState: { session: { label: "Bare" } } });
    expect(html).toContain("Bare");
  });

  it("survives a room state with no participants array at all", () => {
    const html = render({ roomState: { session: { id: 1, label: "Sparse" } } });
    expect(html).toContain("Sparse");
  });

  it("renders the simulation notice instead of an end button", () => {
    const html = render({
      roomState: {
        session: { id: 3, label: "Sim day", started_at: "2026-07-29T14:00:00Z", is_simulated: true },
        participants: [],
      },
    });
    expect(html).toContain("Simulation");
    expect(html).not.toContain("End training day");
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
