// Does the coach's room-layout subtree actually RENDER?
//
// ── WHY THIS EXISTS ──────────────────────────────────────────────────────────
// It shipped broken. Two handlers were added to this component and, through a
// bad edit, ended up nested INSIDE another function instead of beside it:
//
//     async function removeScreen(rack) {
//       async function unlinkNode(...)      <- nested
//       async function releaseAllRacks()    <- nested, invisible to the JSX
//       ...
//     }
//
// Nested function declarations are perfectly legal JavaScript, so the bundle
// built, the whole suite stayed green, and `grep` found both names — grep cannot
// see scope. The first thing that noticed was a coach opening the page on the
// base station and getting a blank screen: `releaseAllRacks is not defined`,
// thrown while React evaluated the onClick, which unmounts the entire root.
//
// renderToStaticMarkup evaluates every expression in the tree, INCLUDING the
// identifier behind each onClick, so an out-of-scope handler throws here instead
// of in front of a coach. Same reasoning as trainingDayPanel.render.test.js.
//
// ⚠️ A source-text check is NOT enough and was tried first: a nested function
// still appears in the component's source, so `toString().includes(...)` passes
// on the broken version. It has to actually render.
//
// This does NOT prove the buttons do the right work — only that the page renders
// and every handler it references exists. That is the part that was missing.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { RoomLayout } from "./coach/CoachTablet.jsx";

beforeEach(() => {
  // The component loads on mount. Neither storage nor the network exists in a
  // bare Node test, and neither is what this test is about — the first render is.
  const store = new Map();
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
    clear: () => store.clear(),
  };
  globalThis.fetch = vi.fn(() => Promise.resolve({
    ok: true, status: 200, json: () => Promise.resolve({}),
  }));
});

afterEach(() => {
  delete globalThis.localStorage;
  delete globalThis.fetch;
  vi.restoreAllMocks();
});

function render() {
  return renderToStaticMarkup(createElement(RoomLayout, {
    token: "test-token",
    onAuthLost: () => {},
  }));
}

describe("RoomLayout renders", () => {
  it("renders without throwing, with every rack handler in scope", () => {
    // The real guard. If releaseAllRacks, unlinkNode or removeScreen is not a
    // sibling of the JSX that references it, evaluating the onClick throws a
    // ReferenceError right here.
    expect(() => render()).not.toThrow();
  });

  it("shows the rack slots and the release-all control", () => {
    const html = render();
    expect(html).toContain("Rack slots");
    expect(html).toContain("Release all racks");
  });

  it("renders a slot for every rack in the room", () => {
    const html = render();
    for (const n of [1, 2, 3, 4, 5, 6, 7, 8]) {
      expect(html).toContain(`Rack ${n}`);
    }
  });
});
