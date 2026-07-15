/* Covers the revision gate that prevents malformed or duplicate MQTT refreshes. */

import { describe, expect, it } from "vitest";
import { parseMonitoringEvent, shouldReconcile } from "./roomMonitor.js";

describe("room monitor events", () => {
  const event = {
    schema_version: 1,
    type: "room_state_changed",
    reason: "set_completed",
    revision: 7,
    event_id: "7bfba173-809a-44ee-a8ca-b2f603962f88",
    occurred_at: "2026-07-13T20:00:00Z",
  };

  it("accepts the versioned privacy-safe contract", () => {
    expect(parseMonitoringEvent(JSON.stringify(event))).toEqual(event);
  });

  it("rejects malformed and unknown events", () => {
    expect(parseMonitoringEvent("not json")).toBeNull();
    expect(parseMonitoringEvent(JSON.stringify({ ...event, type: "fatigue_alert" }))).toBeNull();
    expect(parseMonitoringEvent(JSON.stringify({ ...event, revision: "7" }))).toBeNull();
    expect(parseMonitoringEvent(JSON.stringify({ ...event, event_id: "not-a-uuid" }))).toBeNull();
    expect(parseMonitoringEvent(`{"padding":"${"x".repeat(2048)}"}`)).toBeNull();
  });

  it("reconciles only increasing revisions", () => {
    expect(shouldReconcile(6, event)).toBe(true);
    expect(shouldReconcile(7, event)).toBe(false);
    expect(shouldReconcile(8, event)).toBe(false);
  });
});
