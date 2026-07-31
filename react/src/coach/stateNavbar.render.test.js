// Does the bottom state bar say the right thing in each state a coach finds it?
//
// Same reasoning as scheduleWorkspace.render.test.js — JSX referencing a
// vanished identifier compiles happily, and an uncaught render error unmounts
// the whole root into a black screen.
//
// But there is a second reason this file exists, and it is the more important
// one. The bar has a state that CANNOT be checked by clicking: SESSION dims when
// no training day is running, and the only way to reach "no training day is
// running" on a live base station is to END the open one — which freezes an
// immutable report and recalculates every athlete's reference max. That is not
// something to do to look at a colour. So the dimmed branch is pinned here
// instead.
//
// renderToStaticMarkup never runs effects, so the sliding pill (measured in a
// layout effect) is absent from this markup by design. What it does prove is
// which buttons exist, which one is marked current, and which one is disabled.

import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import StateNavbar from "./StateNavbar.jsx";

function render(props = {}) {
  return renderToStaticMarkup(createElement(StateNavbar, {
    current: "planning", onSelect: () => {}, dayRunning: true, ...props,
  }));
}

describe("StateNavbar", () => {
  it("offers all three states, in the order a coach's day runs in", () => {
    const html = render();
    expect(html).toContain("Planning");
    expect(html).toContain("Session");
    expect(html).toContain("Analytics");
    expect(html.indexOf("Planning")).toBeLessThan(html.indexOf("Session"));
    expect(html.indexOf("Session")).toBeLessThan(html.indexOf("Analytics"));
  });

  it("marks the current state for assistive tech, not only in colour", () => {
    expect(render({ current: "analytics" })).toContain('aria-current="page"');
  });

  // The one branch that cannot be reached by clicking. See the note above.
  it("disables SESSION when no training day is running", () => {
    const html = render({ dayRunning: false });
    expect(html).toContain("No training day is running");
    expect(html.match(/<button[^>]*disabled/g) || []).toHaveLength(1);
  });

  it("enables SESSION once a day is running", () => {
    expect(render({ dayRunning: true })).not.toContain("disabled");
  });

  // A day can end while the coach is standing on SESSION. Dimming the button
  // under them would put the lime "you are here" pill and the grey "you cannot
  // go here" on one button — two opposite messages at once.
  it("does not dim the state the coach is already standing on", () => {
    const html = render({ current: "session", dayRunning: false });
    expect(html).toContain('aria-current="page"');
    expect(html).not.toContain("disabled");
  });
});
