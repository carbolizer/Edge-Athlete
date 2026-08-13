// theme.js — the rack screen's colors and type, in ONE place.
//
// These values match the team's `.monitor` design system (Braydon's coach/wall
// surfaces) so every screen in Edge Athlete reads as one product: a near-black
// background, a lime accent, mint/amber/coral for green/yellow/red status, and
// Inter with tight, heavy numerals. If the look ever needs to change, change it
// here — every screen imports from this file.
export const T = {
  bg: '#070b0e',      // near-black page background
  panel: '#10171b',   // raised surfaces (cards, buttons)
  panel2: '#151e23',  // slightly lighter surface
  line: '#263239',    // hairline borders/dividers
  ink: '#f5f7f2',     // primary text (near-white)
  muted: '#89969d',   // secondary text / labels
  lime: '#a9f04d',    // the brand accent
  mint: '#45dcb3',    // status: on target  (green)
  amber: '#ffb63e',   // status: dropping   (yellow)
  coral: '#ff646b',   // status: fatigued   (red)

  // Inter is bundled locally (see main.jsx) so it renders on the Pi's offline
  // network; the rest are fallbacks in case the font ever fails to load.
  sans: '"Inter Variable", Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
  mono: 'ui-monospace, Menlo, Consolas, monospace',
}
