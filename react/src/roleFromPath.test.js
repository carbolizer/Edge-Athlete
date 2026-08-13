import { describe, expect, it } from "vitest";
import { roleFromPath } from "./device.js";

// This helper decides which PWA a screen advertises itself as. Getting it wrong
// is not a visual nit: the manifest it selects carries the `id` that makes the
// rack, coach, and wall apps three separate installs instead of one that keeps
// overwriting itself. So the mapping is worth pinning down.
describe("roleFromPath", () => {
  it("maps each role's own routes", () => {
    expect(roleFromPath("/dashboard")).toBe("dashboard");
    expect(roleFromPath("/coach")).toBe("coach");
    expect(roleFromPath("/rack/1")).toBe("rack");
  });

  it("keeps sub-routes with their role", () => {
    // These are the routes a device actually sits on day to day — /coach/setup
    // during room layout, /rack/setup while waiting for an assignment. They must
    // not fall through to the stored role.
    expect(roleFromPath("/coach/setup")).toBe("coach");
    expect(roleFromPath("/rack/setup")).toBe("rack");
  });

  it("returns null for routes that belong to no role", () => {
    // '/' is the dispatcher: it could be any role, so the caller falls back to
    // whatever is in localStorage. Answering 'rack' here would make every cold
    // boot briefly claim to be the rack app.
    expect(roleFromPath("/")).toBeNull();
    expect(roleFromPath("/connection-test")).toBeNull();
    expect(roleFromPath("/nonsense")).toBeNull();
  });

  it("does not match a role name that is merely a prefix of another word", () => {
    // '/rackets' is not a rack screen. A plain startsWith('/rack') would say it
    // is, which is why the helper compares whole path segments.
    expect(roleFromPath("/rackets")).toBeNull();
    expect(roleFromPath("/coaching")).toBeNull();
    expect(roleFromPath("/dashboards")).toBeNull();
  });

  it("survives junk input instead of throwing", () => {
    // This runs on every navigation. An exception here would take the whole app
    // down through the ErrorBoundary, over an install icon.
    expect(roleFromPath("")).toBeNull();
    expect(roleFromPath(null)).toBeNull();
    expect(roleFromPath(undefined)).toBeNull();
  });
});
