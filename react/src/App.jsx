// App.jsx — the root every Edge Athlete screen boots into, URL-routed.
//
// The address bar is the source of truth for what's on screen:
//   /                → role picker (only if this device has no role yet)
//   /rack/setup      → rack registration + "waiting for a rack" screen (see rack/RackSetup)
//   /rack/:n         → the live rack screen for rack n
//   /coach           → bounces to whichever coach state this device was last in
//   /coach/planning  → PLANNING — blocks, programs, groups, the calendar
//   /coach/session   → SESSION — the live room, while a training day runs
//   /coach/analytics → ANALYTICS — one athlete's summary, history, reports, notes
//   /coach/setup     → coach admin Room Layout (JWT gate + dropdown assign)
//   /dashboard       → base-station wall display
//   /connection-test → the API/architecture demo kept from the scaffold
//
// localStorage still remembers this device's identity (its role, its generated
// device id, its assigned rack number) so a cold reboot at "/" can redirect back
// to where it belongs — but the URL, not localStorage, decides the view. Nginx
// serves index.html for any of these paths (see router.js), so refreshing or
// hard-loading /rack/1 works and lands back here.

import { Component, useEffect, useState } from 'react'
import ConnectionTest from './ConnectionTest.jsx'
import RackScreen from './rack/RackScreen.jsx'
import RackSetup from './rack/RackSetup.jsx'
import CoachTablet from './coach/CoachTablet.jsx'
import Dashboard from './Dashboard.jsx'
import WifiChangeOverlay from './WifiChangeOverlay.jsx'
import { getActiveSession } from './api/client.js'
import { subscribeRackCommand } from './mqtt/client.js'
import { navigate, usePathname } from './router.js'
import { coachStateFromPath, pathForCoachState, resumeCoachState } from './coach/coachState.js'
import { applyRoleIdentity, getDeviceId } from './device.js'
import { Centered } from './ui.jsx'
import { T } from './theme.js'

// ─────────────────────────── when a screen breaks ───────────────────────────

// Without this, ONE bad value anywhere in the tree unmounts the entire app and
// the tablet goes black — no message, nothing in the console, nothing a coach
// or a teammate can report beyond "it stopped working". React does that by
// design: an uncaught render error tears down the whole root.
//
// A black screen in a weight room is the worst possible failure. It looks
// identical to a dead tablet, a WiFi drop, and a crashed app, so nobody knows
// whether to reload it, reboot it, or go find a laptop. This turns all of that
// into a screen that says what broke and offers a way out.
class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // Kept where the next person will look. The stack is minified in a
    // production build, but the message alone usually names the field.
    console.error('Edge Athlete crashed:', error, info?.componentStack)
  }

  // Navigating away from a broken screen clears the error, so one bad route
  // cannot hold the whole app hostage until someone reloads by hand.
  //
  // ⚠️ THIS USED TO BE `key={pathname}` ON THE BOUNDARY, and that was a real bug
  // once the coach app became three routes. Changing a key does not just reset a
  // component — it unmounts and rebuilds the entire subtree. So every move
  // between PLANNING, SESSION and ANALYTICS tore down the whole coach app and
  // built a new one: the navbar's sliding pill restarted from scratch instead of
  // animating, and the room state, athlete list and movement catalog were all
  // refetched. The three states are supposed to read as one surface changing
  // mode; keyed that way they were three page loads wearing a costume.
  //
  // Comparing here instead does the same job without the teardown. When there is
  // no error the children are untouched, so React reconciles /coach/planning and
  // /coach/session as the same component — which is exactly what keeps the bar
  // on screen and sliding.
  componentDidUpdate(previous) {
    if (this.state.error && previous.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <Centered>
        <div style={{ fontSize: 11, fontWeight: 900, letterSpacing: '.18em', textTransform: 'uppercase',
          color: T.lime, marginBottom: 10 }}>Edge Athlete</div>
        <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-.02em', marginBottom: 8 }}>
          This screen stopped working
        </div>
        <div style={{ fontSize: 14, color: T.muted, marginBottom: 6, maxWidth: 460, textAlign: 'center' }}>
          Nothing you did caused this and no training data was lost — sets and reps
          are saved on the base station, not here.
        </div>
        <code style={{ fontSize: 12, color: T.muted, marginBottom: 24, maxWidth: 460,
          textAlign: 'center', wordBreak: 'break-word' }}>
          {String(this.state.error?.message || this.state.error)}
        </code>
        <div style={{ display: 'flex', gap: 12 }}>
          <button onClick={() => window.location.reload()}
            style={{ padding: '10px 16px', borderRadius: 8, border: `1px solid ${T.line}`,
              background: T.panel, color: T.ink, cursor: 'pointer', fontFamily: 'inherit' }}>
            Reload this screen
          </button>
          <button onClick={() => { window.location.href = '/' }}
            style={{ padding: '10px 16px', borderRadius: 8, border: `1px solid ${T.line}`,
              background: T.panel, color: T.ink, cursor: 'pointer', fontFamily: 'inherit' }}>
            Back to start
          </button>
        </div>
      </Centered>
    )
  }
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
    applyRoleIdentity(role)
    if (role === 'rack') {
      const n = localStorage.getItem('rack_number')
      navigate(n != null ? `/rack/${n}` : '/rack/setup')
    } else if (role === 'coach') {
      // /coach is the coach's home; the Room Layout admin hangs off a button there.
      navigate('/coach')
    } else {
      navigate(`/${role}`)
    }
  }
  return (
    <Centered>
      <div style={{ fontSize: 11, fontWeight: 900, letterSpacing: '.18em', textTransform: 'uppercase',
        color: T.lime, marginBottom: 10 }}>Edge Athlete</div>
      <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: '-.03em', marginBottom: 28 }}>Set up this device</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: 300 }}>
        {choices.map((c) => (
          <button key={c.role} onClick={() => pick(c.role)}
            style={{ padding: 18, fontSize: 16, fontWeight: 600, borderRadius: 12,
              border: `1px solid ${T.line}`, background: T.panel, color: T.ink,
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
    return <Redirect to={n != null ? `/rack/${n}` : '/rack/setup'} />
  }
  if (role === 'coach') return <Redirect to="/coach/setup" />
  return <Redirect to={`/${role}`} />
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
    applyRoleIdentity('rack')
  }, [rackNumber])

  useEffect(() => {
    getActiveSession().then(setSession).catch(() => setSessionError(true))
  }, [])

  if (session == null && !sessionError) {
    return <Centered><div style={{ fontSize: 16, color: T.muted }}>Loading session…</div></Centered>
  }
  return <RackScreen rackNumber={rackNumber} session={session} />
}

// ─────────────────────────── remote command listener ───────────────────────────

// Mounted for the whole life of a rack device (across every route), so a coach can
// steer THIS tablet remotely over MQTT. Right now it handles one command,
// `enter_setup`, which sends the tablet to /rack/setup. The command can target
// every tablet ("all"), a single device by its id, or a single rack by its number
// — this listener just checks "is this one for me?" before acting.
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
      if (forMe) navigate('/rack/setup')
    })
  }, [])
  return null
}

// ─────────────────────────── the router itself ───────────────────────────

function route(pathname) {
  if (pathname === '/connection-test') return <ConnectionTest />
  if (pathname === '/rack/setup') return <RackSetup />
  if (pathname === '/coach/setup') return <CoachTablet />

  // The coach app is a three-position state machine, and the position lives in
  // the URL — so a reload keeps it, Back moves between states, and a screen can
  // be linked to. See coach/coachState.js for why. Two faces of one screen: the
  // coach view is the working tool (login, athletes, planning, reports); the
  // wall view is the read-only room display. Same file, same live room feed,
  // different `mode`.
  const coachState = coachStateFromPath(pathname)
  if (coachState) return <Dashboard mode="coach" coachState={coachState} />
  // A bare /coach names no state, so send this device back to the one it left.
  if (pathname === '/coach') return <Redirect to={pathForCoachState(resumeCoachState())} />

  if (pathname === '/dashboard') return <Dashboard mode="wall" />

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
  const role = localStorage.getItem('device_role')
  const isRack = role === 'rack'
  // The wall display and rack tablets are the "bystander" screens: they never
  // type the new Wi-Fi password and drop offline when it changes, so they get an
  // overlay showing it. The coach tablet initiates the change and has its own
  // copy-the-password flow, so it does not need this.
  const isBystanderScreen = role === 'rack' || role === 'dashboard'
  return (
    // `resetKey`, NOT `key` — see the note on componentDidUpdate above. A key
    // here would rebuild the whole app on every coach state change.
    <ErrorBoundary resetKey={pathname}>
      {route(pathname)}
      {isRack && <RackCommandListener />}
      {isBystanderScreen && <WifiChangeOverlay />}
    </ErrorBoundary>
  )
}
