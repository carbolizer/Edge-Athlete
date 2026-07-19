// rack/RackSetup.jsx — the rack setup + "waiting for a rack" screen (/rack/setup).
//
// This is where a tablet BECOMES a rack (or gets re-homed as one): it shows the
// device's id and waits for a coach to assign it a rack number, then hands off to
// /rack/:n. It is NON-DESTRUCTIVE — it only leaves when the assignment actually
// CHANGES from what it was on arrival, so an already-assigned rack that lands here
// just sits showing its id until a coach reassigns it.
//
// GUARD (the important bit): if this device is ALREADY set up as a different type
// (a coach tablet or wall display), we do NOT silently turn it into a rack — we
// ask first. That stops an accidental navigation (or a stray remote command) from
// hijacking a coach tablet, and the same prompt doubles as the deliberate "yes,
// switch this device to a rack" confirmation. A fresh device, or one that's
// already a rack, skips the prompt (the /rack/setup URL makes the intent clear).

import { useEffect, useRef, useState } from 'react'
import { registerRack, getRackNumber } from '../api/client.js'
import { getDeviceId, applyRoleIdentity } from '../device.js'
import { navigate } from '../router.js'
import { Centered } from '../ui.jsx'
import { T } from '../theme.js'

const ROLE_LABEL = { coach: 'Coach Admin', dashboard: 'Base Station Display' }

export default function RackSetup() {
  const role = localStorage.getItem('device_role')
  // Fresh (no role) or already a rack → proceed straight through. An established
  // coach/wall device → show the confirm first (see GUARD above).
  const [confirmed, setConfirmed] = useState(role == null || role === 'rack')

  if (!confirmed) {
    return (
      <Centered>
        <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: '-.02em', marginBottom: 8 }}>
          This device is set up as {ROLE_LABEL[role] || role}
        </div>
        <div style={{ fontSize: 14, color: T.muted, marginBottom: 28, maxWidth: 360 }}>
          Set it up as a Rack instead? Its current setup will be replaced.
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <button onClick={() => setConfirmed(true)}
            style={{ padding: '14px 20px', borderRadius: 12, border: 'none', background: T.lime,
              color: '#0a1106', fontWeight: 850, fontSize: 15, cursor: 'pointer', fontFamily: 'inherit' }}>
            Set up as Rack
          </button>
          <button onClick={() => navigate(`/${role}`)}
            style={{ padding: '14px 20px', borderRadius: 12, border: `1px solid ${T.line}`,
              background: T.panel, color: T.ink, fontWeight: 700, fontSize: 15, cursor: 'pointer', fontFamily: 'inherit' }}>
            Keep as {ROLE_LABEL[role] || role}
          </button>
        </div>
      </Centered>
    )
  }
  return <Waiting />
}

// Registration + assignment wait. Reached once this device is confirmed as a rack.
function Waiting() {
  const deviceId = useRef(getDeviceId()).current
  // The rack this device was on when we arrived (string, or null if unassigned).
  // We only navigate away when the server reports something DIFFERENT from this.
  const baseline = useRef(localStorage.getItem('rack_number')).current

  useEffect(() => {
    localStorage.setItem('device_role', 'rack')
    applyRoleIdentity('rack')

    let timer = null
    let stopped = false
    registerRack(deviceId).catch(() => { /* harmless; the poll still runs */ })

    const poll = async () => {
      if (stopped) return
      try {
        const { rack_number } = await getRackNumber(deviceId)
        const current = rack_number == null ? null : String(rack_number)
        if (current != null && current !== baseline) {
          localStorage.setItem('rack_number', current)
          navigate(`/rack/${current}`, { replace: true })
          return // stop polling
        }
      } catch (e) { /* keep trying */ }
      timer = setTimeout(poll, 3000)
    }
    poll()
    return () => { stopped = true; if (timer) clearTimeout(timer) }
  }, [deviceId, baseline])

  const shortId = deviceId.slice(0, 8)
  return (
    <Centered>
      <div style={{ fontSize: 13, color: T.muted, textTransform: 'uppercase',
        letterSpacing: '.06em', marginBottom: 20 }}>Waiting for coach to assign a rack</div>
      <div style={{ fontSize: 64, fontWeight: 700, letterSpacing: '.04em',
        fontFamily: T.mono }}>{shortId}</div>
      <div style={{ fontSize: 13, color: T.muted, marginTop: 18 }}>this device's id</div>
      {/* The escape hatch: this is where you change a rack into another device type.
          Kept here (not on the live rack screen) so athletes can't tap it mid-set. */}
      <button onClick={() => { localStorage.removeItem('device_role'); navigate('/') }}
        style={{ marginTop: 40, padding: '9px 14px', borderRadius: 8, border: `1px solid ${T.line}`,
          background: 'transparent', color: T.muted, fontSize: 12, cursor: 'pointer', fontFamily: 'inherit' }}>
        Change device role
      </button>
    </Centered>
  )
}
