// ui.jsx — small shared screen chrome used by the picker / setup / stub screens.
//
// Centered is the plain full-height, centered, near-black frame those simple
// screens sit in. The live rack panel paints its own richer layout; this is just
// for the one-message screens.

import { T } from './theme.js'

export function Centered({ children }) {
  return (
    <div style={{ minHeight: '100vh', background: T.bg, color: T.ink, display: 'flex',
      flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 24,
      fontFamily: T.sans, textAlign: 'center' }}>
      {children}
    </div>
  )
}
