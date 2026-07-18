// rack/RackScreen.jsx — the live panel at a rack (SHELL ONLY, this phase).
//
// Once the screen knows its rack number and has the one-shot active-session data,
// it finds the sensor node linked to this rack, subscribes to that node's rep
// stream over MQTT, and for every rep: writes it to the IndexedDB buffer FIRST
// (durability), then updates a live in-memory rep count + latest velocity + color
// chip. No set lifecycle, no batch POST yet — that's Phase 11. This proves the
// whole live path works end to end against the simulator.
//
// Styling matches the team's `.monitor` design system (see theme.js).

import { useEffect, useRef, useState } from 'react'
import { getNodes } from '../api/client.js'
import { subscribeNodeReps, subscribeRackState, resubscribeNode } from '../mqtt/client.js'
import { addRep, getBufferedReps } from '../db/repBuffer.js'
import { velocityColor, VELOCITY_HEX } from './velocity.js'
import { T } from '../theme.js'

// A tiny uppercase, wide-tracked micro-label — the `.monitor` label treatment.
const LABEL = {
  fontSize: 10, fontWeight: 900, letterSpacing: '.14em',
  textTransform: 'uppercase', color: T.muted,
}

export default function RackScreen({ rackNumber, session }) {
  const [nodeId, setNodeId] = useState(null)
  const [repCount, setRepCount] = useState(0)
  const [lastVelocity, setLastVelocity] = useState(null)
  const [lastColor, setLastColor] = useState('green')
  const [buffered, setBuffered] = useState(0)

  // Stand-in velocity zone for the color chip: no exercise is selected yet this
  // phase, so we color against the first planned exercise's zone just to show the
  // chip works. Real per-exercise coloring is Phase 11.
  const standInZoneMin = session?.session_exercises?.[0]?.velocity_zone_min ?? null

  // Keep the live subscription's unsubscribe fn across re-renders / reassignment.
  const unsubRef = useRef(null)
  const nodeIdRef = useRef(null)

  // Every rep: buffer to IndexedDB first, then update the live panel.
  async function handleRep(rep) {
    await addRep(rep)
    setRepCount((n) => n + 1)
    setLastVelocity(rep.mean_velocity)
    setLastColor(velocityColor(rep.mean_velocity, standInZoneMin))
    getBufferedReps().then((rows) => setBuffered(rows.length))
  }

  // Find this rack's linked node, then subscribe to its reps.
  useEffect(() => {
    let cancelled = false
    getNodes().then((nodes) => {
      if (cancelled) return
      const mine = nodes.find((n) => n.rack_number === rackNumber)
      if (!mine) return // no sensor linked yet — panel still renders, just no reps
      nodeIdRef.current = mine.node_id
      setNodeId(mine.node_id)
      unsubRef.current = subscribeNodeReps(mine.node_id, handleRep)
    })
    return () => { cancelled = true; if (unsubRef.current) unsubRef.current() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rackNumber])

  // Listen for a coach re-linking a different sensor to this rack, and follow it.
  useEffect(() => {
    const unsub = subscribeRackState(rackNumber, (state) => {
      if (state.type === 'node_reassigned' && state.node_id !== nodeIdRef.current) {
        if (unsubRef.current) unsubRef.current()
        unsubRef.current = resubscribeNode(nodeIdRef.current, state.node_id, handleRep)
        nodeIdRef.current = state.node_id
        setNodeId(state.node_id)
      }
    })
    return () => unsub()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rackNumber])

  const chipHex = VELOCITY_HEX[lastColor]

  return (
    <div style={{ minHeight: '100vh', background: T.bg, color: T.ink, fontFamily: T.sans,
      display: 'flex', flexDirection: 'column' }}>

      {/* top bar (portrait): rack + live on the top row, session centered below */}
      <div style={{ padding: '16px 24px', borderBottom: `1px solid ${T.line}` }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 16, fontWeight: 850, letterSpacing: '-.02em' }}>Rack {rackNumber}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8,
            background: T.panel, border: `1px solid ${T.line}`, borderRadius: 999,
            padding: '7px 12px', fontSize: 10, fontWeight: 850, letterSpacing: '.08em',
            textTransform: 'uppercase', color: T.muted }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: T.mint,
              boxShadow: `0 0 12px ${T.mint}` }} />
            live
          </div>
        </div>
        <div style={{ textAlign: 'center', marginTop: 14 }}>
          <div style={{ ...LABEL, fontSize: 9, color: T.lime, marginBottom: 4 }}>Session</div>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-.035em' }}>
            {session?.label || 'No active session'}
          </div>
        </div>
      </div>

      {/* live panel */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', padding: 28 }}>
        <div style={{ ...LABEL, marginBottom: 10 }}>Reps this session</div>
        <div style={{ fontSize: 128, fontWeight: 800, lineHeight: 0.9, letterSpacing: '-.06em',
          fontVariantNumeric: 'tabular-nums' }}>
          {repCount}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 30 }}>
          <div style={{ fontSize: 46, fontWeight: 800, color: chipHex, letterSpacing: '-.05em',
            fontVariantNumeric: 'tabular-nums' }}>
            {lastVelocity == null ? '—' : lastVelocity.toFixed(2)}
            <span style={{ fontSize: 14, fontWeight: 700, color: T.muted, marginLeft: 5 }}>m/s</span>
          </div>
          <span style={{ fontSize: 11, fontWeight: 900, textTransform: 'uppercase', letterSpacing: '.1em',
            padding: '6px 12px', borderRadius: 999, background: chipHex + '22', color: chipHex }}>
            {lastColor}
          </span>
        </div>
      </div>

      {/* footer: proof-of-plumbing readouts */}
      <div style={{ padding: '14px 28px', borderTop: `1px solid ${T.line}`,
        display: 'flex', justifyContent: 'space-between', ...LABEL, fontSize: 10 }}>
        <span>node: {nodeId || 'no sensor linked'}</span>
        <span>buffered: {buffered}</span>
        <span>roster: {session?.roster?.length ?? 0}</span>
      </div>
    </div>
  )
}
