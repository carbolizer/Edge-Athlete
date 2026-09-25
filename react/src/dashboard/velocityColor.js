// velocityColor.js — the ONE velocity color rule the wall display uses.
// Everywhere in Edge Athlete, bar speed is shown on the same green / yellow / red
// scale: green = fast/explosive, yellow = slowing, red = grinding/fatigued. The
// rack tablet colors each rep against that athlete's *personal* program zone, but
// the wall display has no per-athlete zone in the `dashboard/state` message — it
// only gets an avg velocity. So here we map that average onto fixed room-wide
// thresholds. Keeping this in one tiny module means every dashboard tile agrees
// on what "green" means instead of each component inventing its own cutoffs.

export const VELOCITY_COLORS = {
  green: "#43c98a",
  yellow: "#e0a63c",
  red: "#e0533c",
  idle: "#4a5568",
};

// Fixed room-wide thresholds (m/s). Chosen to line up with the "on target /
// dropping / fatigued" language used on the tablet, since we can't read the
// athlete's exact zone from a dashboard broadcast.
export function velocityBand(avgVelocity) {
  if (avgVelocity == null || Number.isNaN(avgVelocity)) return "idle";
  if (avgVelocity >= 0.8) return "green";
  if (avgVelocity >= 0.5) return "yellow";
  return "red";
}

export function velocityColor(avgVelocity) {
  return VELOCITY_COLORS[velocityBand(avgVelocity)];
}
