// useLiveRoomState.js — keeps the wall display and the coach screen showing
// what is happening in the room RIGHT NOW.
//
// The obvious way to do this would be to push the room's state over MQTT and
// render whatever arrives. We deliberately don't. MQTT only ever says "something
// changed, revision 47" — the browser then asks the database what the truth is.
// The database stays the single source of truth, and no athlete's name or
// numbers travel over a broadcast channel a gym display is subscribed to.
//
// So the loop is: connect → fetch a snapshot → listen → on a newer revision,
// fetch again. Polling would work too; this just avoids asking a question when
// nothing has happened.
//
// Both screens run through here, one boolean apart. The wall view is public and
// gets the anonymous snapshot; the coach view asks for ?details=true, which adds
// ids and requires the login.
//
// Most of the complexity below is about not lying to the room:
//   - a fetch in flight blocks a second one, but remembers a newer revision came
//     in and re-fetches once it lands, so the screen can't settle on stale data
//   - `generationRef` voids answers from a previous mode/login, so switching
//     views can't be overwritten by a reply meant for the old one
//   - a failed refresh keeps the last good snapshot and marks it "stale" rather
//     than blanking a wall screen mid-session
//   - if MQTT goes quiet for 15s the connection is shown as stale, because a
//     frozen scoreboard that looks live is worse than one that admits it
import { useEffect, useRef, useState } from "react";
import mqtt from "mqtt";
import { parseMonitoringEvent, ROOM_STATE_TOPIC, shouldReconcile } from "./roomMonitor.js";

const STALE_AFTER_MS = 15_000;

export default function useLiveRoomState({ mode, accessToken, onAuthRequired }) {
  const [roomState, setRoomState] = useState(null);
  const [requestState, setRequestState] = useState("loading");
  const [connectionState, setConnectionState] = useState("connecting");
  const [lastError, setLastError] = useState("");
  const revisionRef = useRef(0);
  const snapshotRef = useRef(null);
  const fetchInFlightRef = useRef(false);
  const queuedRevisionRef = useRef(0);
  const staleTimerRef = useRef(null);
  const abortRef = useRef(null);
  const generationRef = useRef(0);
  const tokenRef = useRef(accessToken);
  tokenRef.current = accessToken;

  const enabled = mode === "wall" || Boolean(accessToken);

  async function refresh({ preserveSnapshot = false, forceAfterInFlight = false } = {}) {
    if (!enabled) return;
    if (fetchInFlightRef.current) {
      if (forceAfterInFlight) queuedRevisionRef.current = Math.max(queuedRevisionRef.current, revisionRef.current + 1);
      return;
    }
    fetchInFlightRef.current = true;
    const generation = generationRef.current;
    const controller = new AbortController();
    abortRef.current = controller;
    if (!preserveSnapshot) setRequestState("loading");
    try {
      const headers = { Accept: "application/json" };
      if (mode === "coach" && tokenRef.current) {
        headers.Authorization = `Bearer ${tokenRef.current}`;
      }
      // One endpoint, two audiences (merge canon R3). The wall display is public,
      // so it gets the anonymous snapshot; the coach view asks for ?details=true,
      // which adds ids and requires the login. There is no separate wall-state
      // route — it was the same function one boolean apart.
      const url = mode === "coach" ? "/api/room-state/?details=true" : "/api/room-state/";
      const response = await fetch(url, { headers, signal: controller.signal });
      if (response.status === 401) {
        setRoomState(null);
        setRequestState("auth-required");
        onAuthRequired?.();
        return;
      }
      if (!response.ok) throw new Error(`Base station returned HTTP ${response.status}`);
      const snapshot = await response.json();
      if (generation !== generationRef.current) return;
      revisionRef.current = snapshot.revision || 0;
      snapshotRef.current = snapshot;
      setRoomState(snapshot);
      setRequestState("ready");
      setLastError("");
    } catch (error) {
      if (error.name === "AbortError" || generation !== generationRef.current) return;
      setLastError(error.message || "Room state unavailable");
      setRequestState(preserveSnapshot && snapshotRef.current ? "stale" : "error");
    } finally {
      if (generation !== generationRef.current) return;
      fetchInFlightRef.current = false;
      abortRef.current = null;
      if (queuedRevisionRef.current > revisionRef.current) {
        queuedRevisionRef.current = 0;
        refresh({ preserveSnapshot: true, forceAfterInFlight: true });
      }
    }
  }

  useEffect(() => {
    generationRef.current += 1;
    abortRef.current?.abort();
    fetchInFlightRef.current = false;
    queuedRevisionRef.current = 0;
    revisionRef.current = 0;
    snapshotRef.current = null;
    setRoomState(null);
    if (!enabled) {
      setRequestState("auth-required");
      setConnectionState("idle");
      return undefined;
    }

    refresh();
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const client = mqtt.connect(`${protocol}://${window.location.hostname}:9001`, {
      reconnectPeriod: 2_000,
      connectTimeout: 5_000,
      clean: true,
    });

    function clearStaleTimer() {
      if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
      staleTimerRef.current = null;
    }

    client.on("connect", () => {
      clearStaleTimer();
      setConnectionState("connecting");
      client.subscribe(ROOM_STATE_TOPIC, { qos: 1 }, (error) => {
        if (error) {
          setConnectionState("reconnecting");
          return;
        }
        setConnectionState("live");
        refresh({ preserveSnapshot: true, forceAfterInFlight: true });
      });
    });

    client.on("message", (topic, message) => {
      if (topic !== ROOM_STATE_TOPIC) return;
      const event = parseMonitoringEvent(message);
      if (mode === "wall" && event?.reason === "node_health_changed") return;
      if (!shouldReconcile(revisionRef.current, event)) return;
      queuedRevisionRef.current = Math.max(queuedRevisionRef.current, event.revision);
      refresh({ preserveSnapshot: true });
    });

    client.on("reconnect", () => setConnectionState("reconnecting"));
    client.on("close", () => {
      setConnectionState("reconnecting");
      clearStaleTimer();
      staleTimerRef.current = setTimeout(() => setConnectionState("stale"), STALE_AFTER_MS);
    });
    client.on("error", () => setConnectionState("reconnecting"));

    return () => {
      generationRef.current += 1;
      abortRef.current?.abort();
      fetchInFlightRef.current = false;
      queuedRevisionRef.current = 0;
      clearStaleTimer();
      client.end(true);
    };
  }, [mode, enabled]);

  return { roomState, requestState, connectionState, lastError, refresh };
}
