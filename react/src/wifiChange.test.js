import { describe, expect, it } from "vitest";
import { passwordFromWifiChange } from "./wifiChange.js";

describe("passwordFromWifiChange", () => {
  it("reads the password out of a real change message", () => {
    expect(passwordFromWifiChange({ type: "wifi_password_changing", password: "GymFloor2026!" }))
      .toBe("GymFloor2026!");
  });

  // The broker is a shared channel — every kind of message flows past. Anything
  // that isn't exactly a change message must be ignored, not shown as a password.
  it("ignores a message of the wrong type", () => {
    expect(passwordFromWifiChange({ type: "leaderboard_update", password: "x" })).toBeNull();
  });

  it("ignores a change message with no usable password", () => {
    expect(passwordFromWifiChange({ type: "wifi_password_changing" })).toBeNull();
    expect(passwordFromWifiChange({ type: "wifi_password_changing", password: "" })).toBeNull();
    expect(passwordFromWifiChange({ type: "wifi_password_changing", password: 12345 })).toBeNull();
  });

  it("survives junk without throwing", () => {
    expect(passwordFromWifiChange(null)).toBeNull();
    expect(passwordFromWifiChange(undefined)).toBeNull();
    expect(passwordFromWifiChange({})).toBeNull();
  });
});
