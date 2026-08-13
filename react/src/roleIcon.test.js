import { afterEach, describe, expect, it, vi } from "vitest";
import { roleIconSrc } from "./roleIcon.js";

// These tests run in Node, where `localStorage` does not exist. That is itself
// worth covering — the helper must not take a screen down when storage is
// unavailable, which is also real on private-mode Safari.
function withStoredRole(role, run) {
  const original = globalThis.localStorage;
  globalThis.localStorage = {
    getItem: (key) => (key === "device_role" ? role : null),
  };
  try {
    return run();
  } finally {
    if (original === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = original;
  }
}

afterEach(() => vi.restoreAllMocks());

describe("roleIconSrc", () => {
  it("gives each role its own icon", () => {
    expect(roleIconSrc("rack")).toBe("/icon-rack-192.png");
    expect(roleIconSrc("dashboard")).toBe("/icon-dashboard-192.png");
    expect(roleIconSrc("coach")).toBe("/icon-coach-192.png");
  });

  // The Dashboard component says "wall" where device.js says "dashboard". A
  // caller should not have to remember which word belongs to which file.
  it("accepts the Dashboard's word for the wall", () => {
    expect(roleIconSrc("wall")).toBe(roleIconSrc("dashboard"));
  });

  it("falls back to the stored device role when no mode is given", () => {
    withStoredRole("rack", () => {
      expect(roleIconSrc()).toBe("/icon-rack-192.png");
    });
    withStoredRole("dashboard", () => {
      expect(roleIconSrc()).toBe("/icon-dashboard-192.png");
    });
  });

  it("prefers the mode over the stored role, since one device can show both", () => {
    withStoredRole("rack", () => {
      expect(roleIconSrc("coach")).toBe("/icon-coach-192.png");
    });
  });

  it("falls back to the coach icon when the role is unset or unknown", () => {
    withStoredRole(null, () => expect(roleIconSrc()).toBe("/icon-coach-192.png"));
    withStoredRole("nonsense", () => expect(roleIconSrc()).toBe("/icon-coach-192.png"));
  });

  // An icon is never worth a blank screen.
  it("survives localStorage being absent or throwing", () => {
    expect(roleIconSrc()).toBe("/icon-coach-192.png");

    const original = globalThis.localStorage;
    globalThis.localStorage = {
      getItem: () => { throw new Error("SecurityError"); },
    };
    try {
      expect(roleIconSrc()).toBe("/icon-coach-192.png");
    } finally {
      if (original === undefined) delete globalThis.localStorage;
      else globalThis.localStorage = original;
    }
  });

  it("always returns a real path, never undefined", () => {
    for (const mode of [undefined, null, "", "rack", "wall", "typo"]) {
      expect(roleIconSrc(mode)).toMatch(/^\/icon-.+\.png$/);
    }
  });
});
