// useDashboardFeed.js — the SINGLE source of truth for the wall display.
// This is the one and only place that touches the network and shapes data. It
// opens a direct MQTT-over-WebSockets connection to the broker (port 9001, no
// Django in the middle), subscribes once to `edgeathlete/dashboard/state`, and
// folds every incoming broadcast into one state object with a reducer. It then
// hands the four screen areas (Rack Status, Leaderboard, Summary, Insights)
// ready-to-render slices. The area components are dumb: they NEVER fetch, poll,
// or subscribe — they only display what this hook gives them. Centralizing it
// here is what keeps the display live (push, not poll) and keeps every area
// showing a consistent snapshot of the same moment.

import { useEffect, useMemo, useReducer } from "react";
import mqtt from "mqtt";
import { velocityBand } from "./velocityColor.js";

// The broker speaks MQTT-over-WebSockets on 9001 (see mosquitto.conf). We build
// the URL from the page host so the same build works on the Pi and in dev.
function brokerUrl() {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.hostname}:9001`;
}

const DASHBOARD_TOPIC = "edgeathlete/dashboard/state";
const MAX_INSIGHT_EVENTS = 200; // rolling window we scan to build room insights

const initialState = {
  connection: "connecting", // connecting | live | offline
  racksById: {}, // rack_number -> latest tile
  athletesById: {}, // athlete id -> running aggregate
  totalSets: 0,
  totalReps: 0,
  fastestRep: null, // { name, peak_velocity, rack_number }
  recentPr: null, // { name, kind: 'velocity' | 'weight' }
  events: [], // rolling window of real sets, newest first
};

function reducer(state, action) {
  switch (action.type) {
    case "CONNECTION":
      return { ...state, connection: action.status };

    case "MESSAGE":
      return foldMessage(state, action.payload);

    default:
      return state;
  }
}

// foldMessage — the heart of the data handling. One dashboard broadcast in, one
// updated snapshot out. Everything the four areas show is derived from here.
function foldMessage(state, msg) {
  if (!msg || msg.type !== "leaderboard_update") return state;

  const rackNumber = msg.rack_number;
  const athlete = msg.athlete || {};
  const avg = Number(msg.avg_velocity);
  const peak = Number(msg.peak_velocity);
  const reps = Number(msg.reps_completed) || 0;

  // Rack tile always reflects the last thing that happened at that rack, even a
  // false set (so the room sees the rack is occupied). Color comes from the
  // shared velocity band; false sets read as idle since they aren't real work.
  const racksById = {
    ...state.racksById,
    [rackNumber]: {
      rack_number: rackNumber,
      athleteName: athlete.name || "—",
      avg_velocity: avg,
      peak_velocity: peak,
      reps_completed: reps,
      is_false_set: !!msg.is_false_set,
      band: msg.is_false_set ? "idle" : velocityBand(avg),
      updatedAt: Date.now(),
    },
  };

  // A false set is not real work: it never touches the leaderboard, the totals,
  // PRs, or the fastest-rep insight. It only lit up the rack tile above.
  if (msg.is_false_set) {
    return { ...state, racksById };
  }

  const prev = state.athletesById[athlete.id] || {
    id: athlete.id,
    name: athlete.name,
    bestAvg: 0,
    bestPeak: 0,
    totalReps: 0,
    sets: 0,
  };
  const athletesById = {
    ...state.athletesById,
    [athlete.id]: {
      ...prev,
      name: athlete.name || prev.name,
      bestAvg: Math.max(prev.bestAvg, avg || 0),
      bestPeak: Math.max(prev.bestPeak, peak || 0),
      totalReps: prev.totalReps + reps,
      sets: prev.sets + 1,
    },
  };

  const fastestRep =
    !state.fastestRep || peak > state.fastestRep.peak_velocity
      ? { name: athlete.name, peak_velocity: peak, rack_number: rackNumber }
      : state.fastestRep;

  const recentPr = msg.is_velocity_pr
    ? { name: athlete.name, kind: "velocity" }
    : msg.is_weight_pr
    ? { name: athlete.name, kind: "weight" }
    : state.recentPr;

  const events = [
    {
      name: athlete.name,
      avg_velocity: avg,
      peak_velocity: peak,
      reps,
      rack_number: rackNumber,
      at: Date.now(),
    },
    ...state.events,
  ].slice(0, MAX_INSIGHT_EVENTS);

  return {
    ...state,
    racksById,
    athletesById,
    totalSets: state.totalSets + 1,
    totalReps: state.totalReps + reps,
    fastestRep,
    recentPr,
    events,
  };
}

// buildInsights — turn the raw aggregates into the rotating, room-readable
// nuggets the Insights panel cycles through. Returns display-ready strings so
// the panel only has to rotate them.
function buildInsights(state) {
  const insights = [];

  if (state.fastestRep && state.fastestRep.peak_velocity > 0) {
    insights.push({
      key: "fastest",
      label: "Fastest rep of the session",
      value: `${state.fastestRep.name} — ${state.fastestRep.peak_velocity.toFixed(2)} m/s`,
    });
  }

  const athletes = Object.values(state.athletesById);
  if (athletes.length) {
    const mostReps = athletes.reduce((a, b) => (b.totalReps > a.totalReps ? b : a));
    if (mostReps.totalReps > 0) {
      insights.push({
        key: "most-reps",
        label: "Most reps so far",
        value: `${mostReps.name} — ${mostReps.totalReps} reps`,
      });
    }
    const topAvg = athletes.reduce((a, b) => (b.bestAvg > a.bestAvg ? b : a));
    if (topAvg.bestAvg > 0) {
      insights.push({
        key: "top-avg",
        label: "Best average bar speed",
        value: `${topAvg.name} — ${topAvg.bestAvg.toFixed(2)} m/s`,
      });
    }
  }

  if (state.recentPr) {
    insights.push({
      key: "pr",
      label: state.recentPr.kind === "velocity" ? "New velocity PR!" : "New weight PR!",
      value: state.recentPr.name,
      highlight: true,
    });
  }

  if (!insights.length) {
    insights.push({
      key: "waiting",
      label: "Insights",
      value: "Waiting for the first set of the session…",
    });
  }
  return insights;
}

export function useDashboardFeed() {
  const [state, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    const client = mqtt.connect(brokerUrl(), {
      reconnectPeriod: 2000,
      connectTimeout: 8000,
      clean: true,
    });

    client.on("connect", () => {
      client.subscribe(DASHBOARD_TOPIC, (err) => {
        dispatch({ type: "CONNECTION", status: err ? "offline" : "live" });
      });
    });

    client.on("message", (_topic, buf) => {
      try {
        dispatch({ type: "MESSAGE", payload: JSON.parse(buf.toString()) });
      } catch {
        // A malformed broadcast must never take the whole wall display down.
      }
    });

    client.on("reconnect", () => dispatch({ type: "CONNECTION", status: "connecting" }));
    client.on("offline", () => dispatch({ type: "CONNECTION", status: "offline" }));
    client.on("error", () => dispatch({ type: "CONNECTION", status: "offline" }));

    return () => client.end(true);
  }, []);

  // Derived, ready-to-render slices. useMemo so the area components get stable
  // references and only re-render when the underlying data actually changes.
  const racks = useMemo(
    () =>
      Object.values(state.racksById).sort(
        (a, b) => Number(a.rack_number) - Number(b.rack_number)
      ),
    [state.racksById]
  );

  const leaderboard = useMemo(
    () =>
      Object.values(state.athletesById)
        .filter((a) => a.bestAvg > 0)
        .sort((a, b) => b.bestAvg - a.bestAvg),
    [state.athletesById]
  );

  const summary = useMemo(
    () => ({
      totalSets: state.totalSets,
      totalReps: state.totalReps,
      activeAthletes: Object.keys(state.athletesById).length,
      activeRacks: Object.keys(state.racksById).length,
    }),
    [state.totalSets, state.totalReps, state.athletesById, state.racksById]
  );

  const insights = useMemo(() => buildInsights(state), [state]);

  return { connection: state.connection, racks, leaderboard, summary, insights };
}
