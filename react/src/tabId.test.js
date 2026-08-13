import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { getDeviceId, getTabId } from "./device.js";

// The MQTT client id is `${getDeviceId()}-${getTabId()}`, and MQTT is unforgiving
// about that string: two live connections sharing one id make the broker kick the
// older connection off, so both ends reconnect and evict each other forever.
//
// getDeviceId is deliberately shared across tabs (it is the SCREEN's identity, and
// the server registers racks by it). getTabId is what stops that shared value from
// being the whole id. These tests pin the two properties the pairing depends on:
// different between tabs, and unchanged across a reload of one tab.
//
// This suite runs with no DOM (see the render tests — the whole suite avoids
// jsdom on purpose), so the two Web Storage areas are stubbed here. They are
// small enough to fake honestly, and faking them makes the tab/reload
// distinction explicit: a RELOAD keeps sessionStorage, a NEW TAB starts it empty.
function makeStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    clear: () => map.clear(),
  };
}

// A new tab: same browser profile (localStorage survives), fresh sessionStorage.
function openNewTab() {
  globalThis.sessionStorage = makeStorage();
}

beforeEach(() => {
  globalThis.localStorage = makeStorage();
  globalThis.sessionStorage = makeStorage();
});

afterEach(() => {
  delete globalThis.localStorage;
  delete globalThis.sessionStorage;
});

describe("getTabId", () => {
  it("survives a reload of the same tab", () => {
    // A reload re-runs the module but keeps sessionStorage. If the id changed
    // here, every refresh would reconnect as a stranger and abandon the queued
    // session that clean:false exists to keep — quietly undoing the feature
    // rather than breaking it visibly.
    const first = getTabId();
    expect(getTabId()).toBe(first);
  });

  it("differs between tabs, which is the collision this prevents", () => {
    const tabOne = getTabId();
    openNewTab();
    expect(getTabId()).not.toBe(tabOne);
  });

  it("leaves the device id shared across tabs", () => {
    // The fix must not make each tab a different DEVICE. The screen registers
    // with the server under device_id; if that changed per tab, a second tab
    // would look like an entirely new rack screen awaiting assignment.
    const device = getDeviceId();
    openNewTab();
    expect(getDeviceId()).toBe(device);
  });

  it("produces a client id that is stable per tab and unique across tabs", () => {
    // The property that actually matters, asserted on the composed string the
    // broker sees rather than on its halves.
    const clientId = () => `${getDeviceId()}-${getTabId()}`;

    const tabOne = clientId();
    expect(clientId()).toBe(tabOne); // reload

    openNewTab();
    const tabTwo = clientId();
    expect(tabTwo).not.toBe(tabOne);
    // Still the same screen — only the tab half moved.
    expect(tabTwo.startsWith(getDeviceId())).toBe(true);
  });
});
