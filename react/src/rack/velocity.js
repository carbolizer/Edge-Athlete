// rack/velocity.js — turn a bar speed into a green / yellow / red read.
//
// The tablet (not the sensor) decides a rep's color by comparing its speed to the
// exercise's target velocity zone. green = on target, yellow = dropping off,
// red = clearly fatigued. The zone comes from the active-session fetch's
// session_exercises[].velocity_zone_min/max (per the message contract).
//
// In this phase no exercise is selected yet, so RackScreen passes a stand-in zone
// just to light up the chip; the real per-exercise coloring lands in Phase 11.

export function velocityColor(meanVelocity, zoneMin) {
  if (zoneMin == null || meanVelocity == null) return 'green'
  if (meanVelocity >= zoneMin) return 'green'          // at/above target
  if (meanVelocity >= zoneMin * 0.85) return 'yellow'  // dropping off
  return 'red'                                          // fatigued
}

// The reference-UI palette, keyed by color name, so every screen reads the same.
export const VELOCITY_HEX = {
  green: '#5DCAA5',
  yellow: '#EF9F27',
  red: '#F09595',
}
