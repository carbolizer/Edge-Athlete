// rack/WeightPad.jsx — a full-screen numpad for editing the working weight.
//
// ── WHY THIS FILE EXISTS (plain version) ───────────────────────────────────────
// The session hands each athlete a prescribed TARGET weight, but on any given day a
// lifter might actually load the bar a little heavier or lighter. This pad lets them
// punch in what they're really lifting, right at the rack, without touching that
// prescription. The number they enter becomes the ACTUAL load saved on THIS set
// (Set.weight_lbs) — a different slot from the target — so the day's plan stays
// clean while the real numbers still feed PRs and future-target math.
//
// It's deliberately big and thumb-friendly: a portrait tablet, one athlete, chalky
// hands. Cancel leaves the prescribed number untouched; "Set weight" hands the new
// value back to the rack, which updates the display immediately.

import { useState } from 'react'
import { T } from '../theme.js'

const LABEL = {
  fontSize: 11, fontWeight: 900, letterSpacing: '.14em',
  textTransform: 'uppercase', color: T.muted,
}

// Turn a number into the shortest sensible string for the readout (225, not 225.0).
function fmt(n) {
  if (n == null || Number.isNaN(n)) return ''
  return Number.isInteger(n) ? String(n) : String(n)
}

export default function WeightPad({ initial, movementName, onCancel, onConfirm }) {
  // The entry as a raw string so a decimal point mid-type is preserved. `fresh`
  // means nothing's been touched yet, so the first digit REPLACES the seeded value
  // (bump 225 → 230 in two taps) instead of appending to it.
  const [entry, setEntry] = useState(fmt(initial))
  const [fresh, setFresh] = useState(true)

  const press = (key) => {
    setEntry((cur) => {
      if (key === 'del') { setFresh(false); return cur.slice(0, -1) }
      if (key === '.') {
        if (fresh) { setFresh(false); return '0.' }
        return cur.includes('.') ? cur : (cur === '' ? '0.' : cur + '.')
      }
      // a digit
      if (fresh) { setFresh(false); return key }
      if (cur.replace('.', '').length >= 5) return cur   // cap at a sane length
      return cur + key
    })
  }

  const value = parseFloat(entry)
  const valid = entry !== '' && !Number.isNaN(value) && value > 0

  const keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '.', '0', 'del']

  return (
    <div style={OVERLAY}>
      <div style={{ width: '100%', maxWidth: 420, margin: '0 auto', display: 'flex',
        flexDirection: 'column', flex: 1, padding: '28px 22px 26px' }}>

        {/* what they're editing */}
        <div style={{ textAlign: 'center', marginBottom: 6 }}>
          <div style={{ ...LABEL, color: T.lime, marginBottom: 8 }}>Working weight</div>
          {movementName && (
            <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: '-.02em', color: T.muted }}>
              {movementName}
            </div>
          )}
        </div>

        {/* the big live readout */}
        <div style={{ flex: '0 0 auto', display: 'flex', alignItems: 'baseline',
          justifyContent: 'center', gap: 10, margin: '26px 0 30px' }}>
          <span style={{ fontSize: 82, fontWeight: 800, letterSpacing: '-.05em', color: T.ink,
            fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
            {entry === '' ? '0' : entry}
          </span>
          <span style={{ fontSize: 22, fontWeight: 800, color: T.muted }}>lb</span>
        </div>

        {/* numpad */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 22 }}>
          {keys.map((k) => (
            <button key={k} onClick={() => press(k)} style={KEY}>
              {k === 'del' ? '⌫' : k}
            </button>
          ))}
        </div>

        {/* actions — Cancel keeps the prescribed target untouched */}
        <div style={{ display: 'flex', gap: 12, marginTop: 'auto' }}>
          <button onClick={onCancel} style={CANCEL}>Cancel</button>
          <button onClick={() => valid && onConfirm(value)} disabled={!valid}
            style={{ ...CONFIRM, opacity: valid ? 1 : 0.4, cursor: valid ? 'pointer' : 'default' }}>
            Set weight
          </button>
        </div>
      </div>
    </div>
  )
}

const OVERLAY = {
  position: 'fixed', inset: 0, zIndex: 50, background: T.bg, color: T.ink,
  fontFamily: T.sans, display: 'flex', flexDirection: 'column',
}
const KEY = {
  padding: '20px 0', fontSize: 28, fontWeight: 800, borderRadius: 14,
  border: `1px solid ${T.line}`, background: T.panel, color: T.ink,
  cursor: 'pointer', fontFamily: 'inherit', fontVariantNumeric: 'tabular-nums',
}
const CANCEL = {
  flex: 1, padding: '16px 20px', fontSize: 15, fontWeight: 800, borderRadius: 12,
  border: `1px solid ${T.line}`, background: 'transparent', color: T.muted,
  cursor: 'pointer', fontFamily: 'inherit',
}
const CONFIRM = {
  flex: 2, padding: '16px 20px', fontSize: 16, fontWeight: 850, borderRadius: 12,
  border: `1px solid ${T.lime}`, background: T.lime, color: '#0a0f07', fontFamily: 'inherit',
}
