import { describe, expect, it } from "vitest";
import { uuidV4FromCrypto } from "./polyfills.js";

// The fallback that stands in for crypto.randomUUID over plain HTTP. It has to
// produce something the app (and the server) will accept as a device id — a
// well-formed UUID v4 — using only crypto.getRandomValues, which works in a
// non-secure context.
describe("uuidV4FromCrypto", () => {
  const V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

  it("produces a well-formed UUID v4 (version + variant pinned)", () => {
    expect(uuidV4FromCrypto()).toMatch(V4);
  });

  it("does not repeat itself", () => {
    const ids = new Set(Array.from({ length: 500 }, () => uuidV4FromCrypto()));
    expect(ids.size).toBe(500);
  });
});
