// RackStatus.jsx — one of the four fixed wall-display areas.
// A grid of rack tiles color-coded on the shared green/yellow/red velocity scale
// so the room can glance and see which racks are moving fast, slowing down, or
// idle. This component is display-only: it renders whatever `racks` array the
// single feed hook hands it and never fetches or subscribes to anything itself.

import { VELOCITY_COLORS } from "./velocityColor.js";

function RackStatus({ racks }) {
  return (
    <section className="wd-panel wd-racks">
      <h2 className="wd-panel-title">Rack Status</h2>
      {racks.length === 0 ? (
        <p className="wd-empty">No racks active yet.</p>
      ) : (
        <div className="wd-rack-grid">
          {racks.map((rack) => (
            <div
              key={rack.rack_number}
              className="wd-rack-tile"
              style={{ borderColor: VELOCITY_COLORS[rack.band] }}
            >
              <div className="wd-rack-dot" style={{ background: VELOCITY_COLORS[rack.band] }} />
              <div className="wd-rack-num">Rack {rack.rack_number}</div>
              <div className="wd-rack-athlete">{rack.athleteName}</div>
              <div className="wd-rack-vel">
                {rack.is_false_set || !rack.avg_velocity
                  ? "—"
                  : `${rack.avg_velocity.toFixed(2)} m/s`}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default RackStatus;
