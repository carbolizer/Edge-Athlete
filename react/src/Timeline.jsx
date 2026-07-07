import { useState, useRef, useEffect } from "react";
import "./Timeline.css";

/*
 * turn database timestamps into cleaner times
 * example:
 * "2026-05-19T14:32:11Z"
 * becomes:
 * "2:32 PM"
 */
function formatTime(value) {
  if (!value) return "unknown time";

  return new Date(value).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

/*
 * timeline component
 * shows motion events as a vertical timeline
 */
export default function Timeline({ events, selectedSensor }) {

  // stores events currently shown on screen
  const [entries, setEntries] = useState([]);

  // tracks which event should animate as "new"
  const [animatingId, setAnimatingId] = useState(null);

  // stores previous event list for comparison
  const prevEventsRef = useRef(null);

  // simple counter for frontend-only ids
  const idCounter = useRef(0);

  /*
   * runs whenever the events array changes
   */
  useEffect(() => {

    // convert backend events into timeline display objects
    const flat = normalizeEvents(events);

    // previous events list
    const prev = prevEventsRef.current;

    // first page load
    if (prev === null) {

      // add frontend ids
      const withIds = flat.map((e) => ({
        ...e,
        _id: idCounter.current++,
      }));

      setEntries(withIds);

      // save current list for next comparison
      prevEventsRef.current = flat;

      return;
    }

    // compare old vs new event counts
    const prevCount = prev.length;
    const newCount = flat.length;

    // new motion event arrived
    if (newCount > prevCount) {

      // figure out how many new events were added
      const addedCount = newCount - prevCount;

      // newest events are at the top
      const newRaw = flat.slice(0, addedCount);

      // add frontend ids
      const newWithIds = newRaw.map((e) => ({
        ...e,
        _id: idCounter.current++,
      }));

      // first new item gets animation
      const newTopId = newWithIds[0]._id;

      // add new entries above old entries
      setEntries((old) => [...newWithIds, ...old]);

      // start animation
      setAnimatingId(newTopId);

      // stop animation after half a second
      setTimeout(() => setAnimatingId(null), 500);

    // event count changed unexpectedly
    } else if (newCount !== prevCount) {

      // rebuild timeline cleanly
      const withIds = flat.map((e) => ({
        ...e,
        _id: idCounter.current++,
      }));

      setEntries(withIds);

    } else {

      // keep ids stable so react does not rerender everything
      const withIds = flat.map((e, index) => ({
        ...e,
        _id: entries[index]?._id ?? idCounter.current++,
      }));

      setEntries(withIds);
    }

    // save current list for next comparison
    prevEventsRef.current = flat;

  }, [events]);

  // empty state
  if (entries.length === 0) {
    return (
      <div className="tl-empty">
        <span className="tl-empty-icon">◎</span>

        <p>
          no events yet for <strong>{selectedSensor}</strong>
        </p>
      </div>
    );
  }

  // main timeline ui
  return (
    <div className="tl-root">

      {/* timeline container */}
      <ul className="tl-list" aria-label="Event timeline">

        {/* vertical timeline line */}
        <div className="tl-line" aria-hidden="true" />

        {entries.map((entry, idx) => {

          // is this the newest event?
          const isNew = entry._id === animatingId;

          // is this the top event?
          const isFirst = idx === 0;

          return (
            <li
              key={entry._id}
              className={[
                "tl-item",
                isNew ? "tl-item--entering" : "",
                isFirst ? "tl-item--first" : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >

              {/* timeline dot */}
              <div className="tl-dot-col" aria-hidden="true">

                <div className={`tl-dot ${isNew ? "tl-dot--new" : ""}`}>
                  <div className="tl-dot-inner" />
                </div>

              </div>

              {/* event content */}
              <div className="tl-body">

                {/* top row */}
                <div className="tl-meta">

                  {/* sensor name */}
                  <span className="tl-sensor-tag">
                    {entry.sensorName}
                  </span>

                  {/* event time */}
                  <span className="tl-time">
                    {entry.time}
                  </span>

                </div>

                {/* main event text */}
                <p className="tl-message">
                  {entry.message}
                </p>

                {/* "new" badge */}
                {isNew && (
                  <span
                    className="tl-new-badge"
                    aria-label="New event"
                  >
                    new
                  </span>
                )}

              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/*
 * convert backend api events into simpler timeline objects
 */
function normalizeEvents(events) {

  return [...events].map((event) => ({

    // sensor display name
    sensorName:
      event.device_name ||
      event.node_id ||
      "Unknown Sensor",

    // readable time
    time: formatTime(event.detected_at),

    // main event text
    message:
      `Motion detected${
        event.location ? ` at ${event.location}` : ""
      }`,

    // backend event id
    rawId: event.event_id || event.id,
  }));
}