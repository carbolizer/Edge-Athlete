// rack/RackScreen.jsx — the live panel at a rack (SHELL ONLY, this phase).
//
// Once the screen knows its rack number and has the one-shot active-session data,
// it finds the sensor node linked to this rack, subscribes to that node's rep
// stream over MQTT, and for every rep: writes it to the IndexedDB buffer FIRST
// (durability), then updates a live in-memory rep count + latest velocity + color
// chip. No set lifecycle, no batch POST yet — that's Phase 11. This proves the
// whole live path works end to end against the simulator.

import { useEffect, useRef, useState } from 'react'
import { getNodes } from '../api/client.js'
import { subscribeNodeReps, subscribeRackState, resubscribeNode } from '../mqtt/client.js'
import { addRep, getBufferedReps } from '../db/repBuffer.js'
import { velocityColor, VELOCITY_HEX } from './velocity.js'

const C = {
  bg: '#0f1117', card: '#1a1d26', line: 'rgba(255,255,255,0.08)',
  ink: '#fff', mute: 'rgba(255,255,255,0.4)', mute2: 'rgba(255,255,255,0.3)',
  green: '#1D9E75',
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
    <div style={{ minHeight: '100vh', background: C.bg, color: C.ink,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      display: 'flex', flexDirection: 'column' }}>

      {/* top bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '16px 22px', borderBottom: `0.5px solid ${C.line}` }}>
        <div style={{ fontSize: 13, fontWeight: 600, letterSpacing: '.04em' }}>Rack {rackNumber}</div>
        <div style={{ fontSize: 13, color: C.mute }}>{session?.label || 'No active session'}</div>
        <span style={{ fontSize: 11, padding: '3px 10px', borderRadius: 99,
          background: 'rgba(255,255,255,0.07)', color: C.mute }}>live</span>
      </div>

      {/* live panel */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', padding: 28, gap: 4 }}>
        <div style={{ fontSize: 12, color: C.mute2, textTransform: 'uppercase',
          letterSpacing: '.06em', marginBottom: 6 }}>Reps this session</div>
        <div style={{ fontSize: 96, fontWeight: 700, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>
          {repCount}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 22 }}>
          <div style={{ fontSize: 40, fontWeight: 700, color: chipHex, fontVariantNumeric: 'tabular-nums' }}>
            {lastVelocity == null ? '—' : lastVelocity.toFixed(2)}
            <span style={{ fontSize: 14, color: C.mute, marginLeft: 4 }}>m/s</span>
          </div>
          <span style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.05em',
            padding: '5px 12px', borderRadius: 99, background: chipHex + '22', color: chipHex }}>
            {lastColor}
          </span>
        </div>
      </div>

      {/* footer: proof-of-plumbing readouts */}
      <div style={{ padding: '14px 22px', borderTop: `0.5px solid ${C.line}`,
        display: 'flex', justifyContent: 'space-between', fontSize: 12, color: C.mute2 }}>
        <span>node: {nodeId || 'no sensor linked'}</span>
        <span>buffered: {buffered}</span>
        <span>roster: {session?.roster?.length ?? 0}</span>
      </div>
    </div>
  )
}
