/*
 * Keeps a REST room snapshot current from privacy-safe MQTT revision events.
 * PostgreSQL remains authoritative; MQTT only tells the browser when to refetch.
 */
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
      const response = await fetch(mode === "coach" ? "/api/room-state/" : "/api/wall-state/", { headers, signal: controller.signal });
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
