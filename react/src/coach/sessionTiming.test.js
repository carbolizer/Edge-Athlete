// The elapsed timer, tested without waiting for real seconds to pass.
//
// The case worth pinning is the one nobody will reproduce by hand: a base
// station that lost power comes back with yesterday's day still open, and the
// timer must say "26 hours", not wrap to "2 hours". A wrapped timer would
// contradict the stale-day banner sitting right next to it.

import { describe, expect, it } from "vitest";
import { elapsedLabel, elapsedMs } from "./sessionTiming.js";

const START = "2026-08-01T09:00:00.000Z";
const at = (isoOrMs) => new Date(isoOrMs).getTime();

describe("elapsedMs", () => {
  it("is null for a day that has not started", () => {
    expect(elapsedMs(null)).toBeNull();
    expect(elapsedMs(undefined)).toBeNull();
  });

  it("is null for a timestamp it cannot read", () => {
    expect(elapsedMs("not a date")).toBeNull();
  });

  // A tablet clock behind the base station's would otherwise count backwards.
  it("never goes negative when the tablet clock is behind", () => {
    expect(elapsedMs(START, at("2026-08-01T08:55:00.000Z"))).toBe(0);
  });
});

describe("elapsedLabel", () => {
  it("shows placeholder dashes before a day starts", () => {
    expect(elapsedLabel(null)).toBe("--:--:--");
  });

  it("counts up in zero-padded hours, minutes and seconds", () => {
    expect(elapsedLabel(START, at("2026-08-01T09:00:05.000Z"))).toBe("00:00:05");
    expect(elapsedLabel(START, at("2026-08-01T10:24:36.000Z"))).toBe("01:24:36");
  });

  // The power-cut case. 26 hours must read as 26, not wrap to 02.
  it("does not wrap at 24 hours, so a stale day reads as stale", () => {
    expect(elapsedLabel(START, at("2026-08-02T11:10:04.000Z"))).toBe("26:10:04");
  });
});
