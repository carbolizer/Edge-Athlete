// Does the schedule screen render in each state a coach can find it in?
//
// Same reasoning as trainingDayPanel.render.test.js: JSX referencing an
// identifier that no longer exists compiles happily, and React 19 unmounts the
// whole root on an uncaught render error — a black screen at runtime that a fully
// green helper suite will not catch.
//
// renderToStaticMarkup evaluates the whole tree with no DOM and no new
// dependencies. It proves the screen draws; it does not prove the buttons work.

import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ScheduleWorkspace from "./ScheduleWorkspace.jsx";

// The component fetches on mount. In Node there is no fetch to intercept and
// renderToStaticMarkup never runs effects, so the first paint is the loading
// state — which is exactly one of the states worth pinning.
function render(props = {}) {
  return renderToStaticMarkup(createElement(ScheduleWorkspace, {
    accessToken: "test-token", onLogout: () => {}, refresh: async () => {}, ...props,
  }));
}

describe("ScheduleWorkspace renders", () => {
  it("draws its heading and the loading state on first paint", () => {
    const html = render();
    expect(html).toContain("Scheduled days");
    expect(html).toContain("Loading the schedule");
  });

  // The heading has to explain the one thing about this screen that surprises
  // people: setting a day up does not start it.
  it("says that setting a day up does not start it", () => {
    expect(render()).toContain("does not start it");
  });

  it("survives being given no refresh callback", () => {
    expect(render({ refresh: undefined })).toContain("Scheduled days");
  });
});
