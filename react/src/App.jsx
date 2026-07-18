// App.jsx — the root every Edge Athlete screen boots into, now URL-routed.
//
// The address bar is the source of truth for what's on screen:
//   /                → role picker (only if this device has no role yet)
//   /setup           → rack registration + "waiting for a rack" screen (shows the id)
//   /rack/:n         → the live rack screen for rack n
//   /coach           → coach admin (stub until a later phase)
//   /dashboard       → base-station display (stub until a later phase)
//   /connection-test → the API/architecture demo kept from the scaffold
//
// localStorage still remembers this device's identity (its role, its generated
// device id, its assigned rack number) so a cold reboot at "/" can redirect
// straight back to where it belongs — but the URL, not localStorage, now decides
// the view. Nginx serves index.html for any of these paths (see router.js), so
// refreshing or hard-loading /rack/1 works and lands back here.

import { useEffect, useRef, useState } from 'react'
import ConnectionTest from './ConnectionTest.jsx'
import RackScreen from './rack/RackScreen.jsx'
import { registerRack, getRackNumber, getActiveSession } from './api/client.js'
import { subscribeRackCommand } from './mqtt/client.js'
import { navigate, usePathname } from './router.js'

const MANIFESTS = {
  rack: '/manifest.rack.json',
  dashboard: '/manifest.dashboard.json',
  coach: '/manifest.coach.json',
}

// Point the page's <link rel="manifest"> at this role's manifest so an install
// gets the right icon/name. Creates the tag if the page doesn't have one.
function swapManifest(role) {
  let link = document.querySelector('link[rel="manifest"]')
  if (!link) {
    link = document.createElement('link')
    link.rel = 'manifest'
    document.head.appendChild(link)
  }
  link.href = MANIFESTS[role] || MANIFESTS.rack
}

// This device's stable id — generated once and kept forever, so the screen never
// re-registers across reloads/reboots.
function getDeviceId() {
  let id = localStorage.getItem('device_id')
  if (!id) { id = crypto.randomUUID(); localStorage.setItem('device_id', id) }
  return id
}

const C = {
  bg: '#080b12', card: '#1a1d26', line: 'rgba(255,255,255,0.1)',
  ink: '#fff', mute: 'rgba(255,255,255,0.45)', green: '#1D9E75',
}

function Centered({ children }) {
  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.ink, display: 'flex',
      flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 24,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', textAlign: 'center' }}>
      {children}
    </div>
  )
}

// Renders nothing; just bounces the URL to `to` once. Used for boot-time and
// fallback redirects (kept in an effect so we never navigate during render).
function Redirect({ to }) {
  useEffect(() => { navigate(to, { replace: true }) }, [to])
  return null
}

// ─────────────────────────── "/" — the picker / dispatcher ───────────────────────────

function Picker() {
  const choices = [
    { role: 'rack', label: 'Rack Tablet' },
    { role: 'dashboard', label: 'Base Station Display' },
    { role: 'coach', label: 'Coach Admin' },
  ]
  function pick(role) {
    localStorage.setItem('device_role', role)
    swapManifest(role)
    if (role === 'rack') {
      const n = localStorage.getItem('rack_number')
      navigate(n != null ? `/rack/${n}` : '/setup')
    } else {
      navigate(`/${role}`)
    }
  }
  return (
    <Centered>
      <div style={{ fontSize: 12, letterSpacing: '.14em', textTransform: 'uppercase',
        color: C.green, marginBottom: 10 }}>Edge Athlete</div>
      <div style={{ fontSize: 24, fontWeight: 700, marginBottom: 28 }}>Set up this device</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: 300 }}>
        {choices.map((c) => (
          <button key={c.role} onClick={() => pick(c.role)}
            style={{ padding: 18, fontSize: 16, fontWeight: 600, borderRadius: 12,
              border: `1px solid ${C.line}`, background: C.card, color: C.ink,
              cursor: 'pointer', fontFamily: 'inherit' }}>
            {c.label}
          </button>
        ))}
      </div>
    </Centered>
  )
}

// The "/" route: send an already-configured device to its home; otherwise show
// the picker. The redirect runs in an effect (see Redirect) so we never navigate
// mid-render.
function Home() {
  const role = localStorage.getItem('device_role')
  if (!role) return <Picker />
  if (role === 'rack') {
    const n = localStorage.getItem('rack_number')
    return <Redirect to={n != null ? `/rack/${n}` : '/setup'} />
  }
  return <Redirect to={`/${role}`} />
}

// ─────────────────────────── /setup — registration + assignment wait ───────────────────────────

// Reaching /setup means this device is a rack, and it's a place you can land at
// ANY time (fresh tablet, or an already-running one you want to re-home). It is
// NON-DESTRUCTIVE: it just shows this device's id and waits. It only leaves when
// a coach CHANGES the assignment — i.e. the server's rack number becomes
// different from whatever it was when we arrived here (an "override"). An already
// assigned tablet that lands here therefore stays put, showing its id, until a
// coach actually reassigns it.
function Setup() {
  const deviceId = useRef(getDeviceId()).current
  // The rack this device was on when we ARRIVED at /setup (string, or null if
  // unassigned). We only navigate away when the server reports something
  // different from this baseline.
  const baseline = useRef(localStorage.getItem('rack_number')).current

  useEffect(() => {
    localStorage.setItem('device_role', 'rack')
    swapManifest('rack')

    let timer = null
    let stopped = false
    registerRack(deviceId).catch(() => { /* harmless; the poll still runs */ })

    const poll = async () => {
      if (stopped) return
      try {
        const { rack_number } = await getRackNumber(deviceId)
        const current = rack_number == null ? null : String(rack_number)
        if (current != null && current !== baseline) {
          // a coach assigned/reassigned us to a (new) rack → go there
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
      <div style={{ fontSize: 13, color: C.mute, textTransform: 'uppercase',
        letterSpacing: '.06em', marginBottom: 20 }}>Waiting for coach to assign a rack</div>
      <div style={{ fontSize: 64, fontWeight: 700, letterSpacing: '.04em',
        fontFamily: 'ui-monospace, Menlo, monospace' }}>{shortId}</div>
      <div style={{ fontSize: 13, color: C.mute, marginTop: 18 }}>this device's id</div>
    </Centered>
  )
}

// ─────────────────────────── /rack/:n — the live rack screen ───────────────────────────

// The rack number comes from the URL — the source of truth. We also mirror it
// into localStorage so a cold reboot at "/" redirects straight back here, then
// fire the ONE active-session fetch and hand off to the live screen.
function RackLive({ rackNumber }) {
  const [session, setSession] = useState(null)
  const [sessionError, setSessionError] = useState(false)

  useEffect(() => {
    getDeviceId()
    localStorage.setItem('device_role', 'rack')
    localStorage.setItem('rack_number', String(rackNumber))
    swapManifest('rack')
  }, [rackNumber])

  useEffect(() => {
    getActiveSession().then(setSession).catch(() => setSessionError(true))
  }, [])

  if (session == null && !sessionError) {
    return <Centered><div style={{ fontSize: 16, color: C.mute }}>Loading session…</div></Centered>
  }
  return <RackScreen rackNumber={rackNumber} session={session} />
}

// ─────────────────────────── /coach and /dashboard — stubs ───────────────────────────

function StubRole({ role }) {
  return (
    <Centered>
      <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 8 }}>
        {role === 'dashboard' ? 'Base Station Display' : 'Coach Admin'}
      </div>
      <div style={{ fontSize: 14, color: C.mute }}>Coming in a later phase.</div>
      <button onClick={() => { localStorage.removeItem('device_role'); navigate('/') }}
        style={{ marginTop: 24, padding: '10px 16px', borderRadius: 8, border: `1px solid ${C.line}`,
          background: C.card, color: C.ink, cursor: 'pointer', fontFamily: 'inherit' }}>
        Change device role
      </button>
    </Centered>
  )
}

// ─────────────────────────── remote command listener ───────────────────────────

// Mounted for the whole life of a rack device (across every route), so a coach
// can steer THIS tablet remotely over MQTT. Right now it handles one command:
// `enter_setup`, which sends the tablet to /setup. The command can target every
// tablet ("all"), a single device by its id, or a single rack by its number —
// this listener just checks "is this one for me?" before acting.
function RackCommandListener() {
  useEffect(() => {
    const deviceId = localStorage.getItem('device_id')
    return subscribeRackCommand((cmd) => {
      if (!cmd || cmd.type !== 'enter_setup') return
      const target = cmd.target
      const rack = localStorage.getItem('rack_number')
      const forMe =
        target === 'all' ||
        (deviceId != null && String(target) === deviceId) ||
        (rack != null && String(target) === String(rack))
      if (forMe) navigate('/setup')
    })
  }, [])
  return null
}

// ─────────────────────────── the router itself ───────────────────────────

function route(pathname) {
  if (pathname === '/connection-test') return <ConnectionTest />
  if (pathname === '/setup') return <Setup />
  if (pathname === '/coach') return <StubRole role="coach" />
  if (pathname === '/dashboard') return <StubRole role="dashboard" />

  if (pathname.startsWith('/rack/')) {
    const rest = pathname.slice('/rack/'.length)
    const n = Number(rest)
    return rest !== '' && Number.isInteger(n) && n > 0
      ? <RackLive rackNumber={n} />
      : <Redirect to="/" />
  }

  if (pathname === '/') return <Home />

  // Anything else → back to the dispatcher.
  return <Redirect to="/" />
}

export default function App() {
  const pathname = usePathname()
  // A rack device keeps the remote-command listener mounted across every route
  // (it stays put while the screen behind it changes), so `enter_setup` works
  // whether the tablet is live, waiting, or mid-session.
  const isRack = localStorage.getItem('device_role') === 'rack'
  return (
    <>
      {route(pathname)}
      {isRack && <RackCommandListener />}
    </>
  )
}
