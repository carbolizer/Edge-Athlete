/*
 * ConnectionTest.jsx — the base-station API & architecture showcase.
 * ------------------------------------------------------------------
 * A live demo page for the backend: it explains how the pieces fit together
 * and lets you actually CLICK the read endpoints and see real JSON come back
 * from Django. Replaces the old Sprint-1 connection-test placeholder.
 *
 * Reachable at:  http://<base-station>:8081/connection-test
 * Everything here talks to the same Nginx that serves this page, which forwards
 * /api/* to Django — so the buttons hit the real API with no extra setup.
 */
import { useState, useRef, useEffect } from 'react'
import mqtt from 'mqtt'

// ── endpoints you can run live (open — no login needed) ──
const OPEN_GETS = [
  { key: 'nodes', path: '/api/nodes/',
    what: 'List every sensor node and its latest status — battery, signal, and which rack it is on.' },
  { key: 'programs', path: '/api/programs/?athlete=2',
    what: "Get one athlete's training plan — the targets plus the speed zone the tablet uses to color reps green / yellow / red." },
]

// ── coach-only reads (need a login token) ──
const COACH_GETS = [
  { key: 'athletes', path: '/api/athletes/',
    what: 'List every lifter in the system.' },
  { key: 'aSession', path: '/api/analytics/session/2/',
    what: "Session summary — total sets, total reps, and each athlete's average bar speed." },
  { key: 'aAthlete', path: '/api/analytics/athlete/2/',
    what: "One athlete's bar-speed trend across all their sets, oldest to newest." },
]

// ── full reference (grouped) ──
const REFERENCE = [
  { group: 'Auth', items: [
    { m: 'POST', p: '/api/auth/login/', a: 'open', w: 'Log in as a coach; returns a token used for coach-only actions.' },
    { m: 'POST', p: '/api/auth/refresh/', a: 'open', w: 'Get a fresh token when the old one expires.' },
  ]},
  { group: 'Tablet — racks & sets', items: [
    { m: 'POST', p: '/api/racks/register/', a: 'open', w: 'A tablet introduces itself so a coach can assign it a rack.' },
    { m: 'POST', p: '/api/racks/racknumber/', a: 'open', w: 'A waiting tablet sends its device ID privately and asks which rack it has been given.' },
    { m: 'POST', p: '/api/sets/', a: 'simulation', w: 'Legacy simulator-owned set start. Real sessions use the rack-bound route.' },
    { m: 'POST', p: '/api/racks/{rack}/sets/{id}/complete/', a: 'rack screen', w: 'Finish an athlete-driven set with X-Rack-Device-Id and save reps atomically.' },
  ]},
  { group: 'Reads', items: [
    { m: 'GET', p: '/api/nodes/', a: 'open', w: 'List all sensor nodes.' },
    { m: 'GET', p: '/api/programs/?athlete={id}', a: 'open', w: "An athlete's training plans (targets + speed zone)." },
  ]},
  { group: 'Coach — manage', items: [
    { m: 'GET', p: '/api/athletes/', a: 'coach', w: 'List all lifters.' },
    { m: 'POST/PATCH', p: '/api/athletes/ · /api/athletes/{id}/', a: 'coach', w: 'Add or edit a lifter.' },
    { m: 'POST', p: '/api/programs/', a: 'coach', w: 'Create a training plan for a lifter.' },
    { m: 'POST/PATCH', p: '/api/sessions/ · /api/sessions/{id}/', a: 'coach', w: 'Start a session; a PATCH with no end time ends it now.' },
    { m: 'PATCH', p: '/api/nodes/{node_id}/', a: 'coach', w: 'Move a sensor to a different rack.' },
    { m: 'GET', p: '/api/racks/unassigned/', a: 'coach', w: 'See which tablets are still waiting for a rack.' },
    { m: 'PATCH', p: '/api/racks/{device_id}/', a: 'coach', w: 'Assign a rack number to a tablet.' },
  ]},
  { group: 'Coach — analytics', items: [
    { m: 'GET', p: '/api/analytics/session/{id}/', a: 'coach', w: 'Session totals + per-athlete average speed.' },
    { m: 'GET', p: '/api/analytics/athlete/{id}/', a: 'coach', w: "An athlete's speed trend across sets." },
  ]},
]

const C = {
  bg: '#0f131b', card: '#161c27', card2: '#1c2431', line: '#26303f',
  ink: '#eef1f6', ink2: '#a9b3c6', ink3: '#6f7a91',
  accent: '#6f8cff', good: '#43c98a', warn: '#e0a63c',
  mono: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
}

function Pill({ children, color }) {
  return <span style={{ fontFamily: C.mono, fontSize: 11, padding: '1px 7px', borderRadius: 20,
    background: color + '22', color, letterSpacing: '.03em' }}>{children}</span>
}

function ConnectionTest() {
  const [resp, setResp] = useState({})
  const [busy, setBusy] = useState({})
  const [token, setToken] = useState(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loginMsg, setLoginMsg] = useState('')

  // ── live MQTT-over-WebSockets demo, one step at a time ──
  // (the browser talks straight to the broker on 9001 — no server in between)
  const [wsStatus, setWsStatus] = useState('idle')        // idle | connecting | connected | error
  const [wsSubscribed, setWsSubscribed] = useState(false)
  const [wsLog, setWsLog] = useState([])
  const mqttRef = useRef(null)

  // Keep diagnostics to connection state only. Raw MQTT packets may contain
  // private device or training data and must not reach the page or console.
  function wsAdd(line) {
    setWsLog(l => [...l, `${new Date().toLocaleTimeString()}  ${line}`])
  }

  // STEP 1 — open the WebSocket connection to the broker
  function mqttConnect() {
    if (mqttRef.current) { mqttRef.current.end(true); mqttRef.current = null }
    setWsLog([]); setWsSubscribed(false); setWsStatus('connecting')
    const url = `ws://${window.location.hostname}:9001`
    wsAdd('STEP 1 — connecting to the local broker …')
    const client = mqtt.connect(url)
    mqttRef.current = client
    client.on('connect', () => {
      setWsStatus('connected')
      wsAdd('✓ connected — the browser is talking straight to Mosquitto over WebSockets')
    })
    client.on('message', () => {
      wsAdd('← dashboard state update received')
    })
    client.on('error', (e) => { setWsStatus('error'); wsAdd('error: ' + (e && e.message)) })
    client.on('close', () => wsAdd('connection closed'))
  }

  // STEP 2 — start listening on every edgeathlete topic
  function mqttSubscribe() {
    const client = mqttRef.current
    if (!client) return
    wsAdd('STEP 2 — subscribing to the public dashboard state topic')
    client.subscribe('edgeathlete/dashboard/state', (err, granted) => {
      if (err) { wsAdd('subscribe failed: ' + err.message); return }
      setWsSubscribed(true)
      wsAdd('✓ subscribed to public room-state invalidations')
    })
  }

  // STEP 3 — publish a message and watch it come back (round trip)
  function mqttPublish() {
    const client = mqttRef.current
    if (!client) return
    const topic = 'edgeathlete/demo/handshake'
    const body = { hello: 'browser', at: new Date().toISOString() }
    wsAdd('STEP 3 — publishing a demo handshake …')
    client.publish(topic, JSON.stringify(body))
    wsAdd(`→ sent to ${topic}`)
  }

  function mqttStop() {
    if (mqttRef.current) { mqttRef.current.end(true); mqttRef.current = null }
    setWsStatus('idle'); setWsSubscribed(false)
    wsAdd('disconnected')
  }

  // clean up the broker connection if the page goes away
  useEffect(() => () => { if (mqttRef.current) mqttRef.current.end(true) }, [])

  async function run(key, path, opts = {}) {
    setBusy(b => ({ ...b, [key]: true }))
    try {
      const res = await fetch(path, opts)
      const text = await res.text()
      let body
      try { body = JSON.stringify(JSON.parse(text), null, 2) } catch { body = text }
      setResp(r => ({ ...r, [key]: `HTTP ${res.status}\n${body}` }))
    } catch (e) {
      setResp(r => ({ ...r, [key]: 'Request failed: ' + e.message }))
    } finally {
      setBusy(b => ({ ...b, [key]: false }))
    }
  }

  async function login() {
    setLoginMsg('logging in…')
    try {
      const res = await fetch('/api/auth/login/', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      const data = await res.json()
      if (data.access) { setToken(data.access); setLoginMsg('logged in as coach ✓') }
      else setLoginMsg('login failed — is the demo coach account seeded?')
    } catch (e) { setLoginMsg('login failed: ' + e.message) }
  }

  const btn = (disabled) => ({
    fontFamily: C.mono, fontSize: 12, padding: '5px 12px', borderRadius: 6,
    border: '1px solid ' + C.accent, background: disabled ? C.card2 : C.accent + '22',
    color: disabled ? C.ink3 : C.accent, cursor: disabled ? 'not-allowed' : 'pointer',
  })

  const EndpointRow = ({ item, disabled, onRun, out }) => (
    <div style={{ borderTop: '1px solid ' + C.line, padding: '14px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Pill color={C.good}>GET</Pill>
        <code style={{ fontFamily: C.mono, fontSize: 13, color: C.ink }}>{item.path}</code>
        <button style={{ ...btn(disabled), marginLeft: 'auto' }} disabled={disabled}
          onClick={onRun}>{busy[item.key] ? 'running…' : 'Run ▸'}</button>
      </div>
      <p style={{ color: C.ink2, fontSize: 13.5, margin: '8px 0 0' }}>{item.what}</p>
      {out && <pre style={{ background: C.bg, border: '1px solid ' + C.line, borderRadius: 8,
        padding: 12, marginTop: 10, overflowX: 'auto', fontFamily: C.mono, fontSize: 12,
        color: C.ink, maxHeight: 260 }}>{out}</pre>}
    </div>
  )

  const Card = ({ title, sub, children }) => (
    <section style={{ background: C.card, border: '1px solid ' + C.line, borderRadius: 12,
      padding: '20px 22px', marginTop: 18 }}>
      <h2 style={{ margin: 0, fontSize: 17, color: C.ink }}>{title}</h2>
      {sub && <p style={{ color: C.ink3, fontSize: 13, margin: '4px 0 6px' }}>{sub}</p>}
      {children}
    </section>
  )

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.ink,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' }}>
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '40px 24px 72px' }}>

        <p style={{ fontFamily: C.mono, fontSize: 12, letterSpacing: '.14em', textTransform: 'uppercase',
          color: C.accent, margin: '0 0 8px' }}>Edge Athlete · Base Station</p>
        <h1 style={{ fontSize: 32, margin: '0 0 10px', letterSpacing: '-.02em' }}>API &amp; Architecture</h1>
        <p style={{ color: C.ink2, fontSize: 15, maxWidth: '62ch', margin: 0 }}>
          The base station's brain. This page explains how the pieces fit together and lets you
          click the read endpoints to see real data come straight from the database.
        </p>

        <Card title="How it fits together">
          <ul style={{ color: C.ink2, fontSize: 14, lineHeight: 1.7, margin: 0, paddingLeft: 18 }}>
            <li><b style={{ color: C.ink }}>Web:</b> your browser → Nginx → Django (the API) → PostgreSQL (the database).</li>
            <li><b style={{ color: C.ink }}>Sensors:</b> each rack's node publishes reps &amp; heartbeats to the Mosquitto broker over MQTT (port 1883).</li>
            <li><b style={{ color: C.ink }}>Screens:</b> tablets &amp; the wall display talk to the broker <i>directly</i> over MQTT-over-WebSockets (port 9001) — no server in the middle.</li>
            <li><b style={{ color: C.ink }}>The rule:</b> Django only listens for <i>heartbeats</i>. Reps are saved to the database in one batch when a set finishes — never streamed one at a time.</li>
          </ul>
          <p style={{ color: C.ink3, fontSize: 12.5, marginTop: 12 }}>
            Seven tables: Node, RackScreen, Athlete, Program, Session, Set, Rep.
          </p>
        </Card>

        <Card title="Live MQTT over WebSockets (port 9001)"
          sub="The real-time layer, step by step — the browser talks straight to the Mosquitto broker, no server in between.">
          <p style={{ color: C.ink2, fontSize: 13.5, margin: '0 0 12px' }}>
            Walk it one step at a time: <b>connect</b> to <code style={{ fontFamily: C.mono, color: C.ink }}>{'ws://<host>:9001'}</code>,
            then <b>subscribe</b> to the public dashboard state topic,
            then <b>publish</b> a harmless demo handshake. The status log confirms connection events without displaying MQTT packet bodies.
          </p>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <button style={btn(wsStatus === 'connecting' || wsStatus === 'connected')} disabled={wsStatus === 'connecting' || wsStatus === 'connected'} onClick={mqttConnect}>1 · Connect ▸</button>
            <button style={btn(wsStatus !== 'connected' || wsSubscribed)} disabled={wsStatus !== 'connected' || wsSubscribed} onClick={mqttSubscribe}>2 · Subscribe (listen) ▸</button>
            <button style={btn(!wsSubscribed)} disabled={!wsSubscribed} onClick={mqttPublish}>3 · Publish ▸</button>
            <button style={btn(wsStatus === 'idle')} disabled={wsStatus === 'idle'} onClick={mqttStop}>Disconnect</button>
            <Pill color={wsSubscribed ? C.good : wsStatus === 'connected' ? C.accent : wsStatus === 'error' ? C.warn : C.ink3}>
              {wsSubscribed ? 'listening' : wsStatus}</Pill>
          </div>
          {wsLog.length > 0 && <pre style={{ background: C.bg, border: '1px solid ' + C.line, borderRadius: 8,
            padding: 12, marginTop: 12, overflowX: 'auto', fontFamily: C.mono, fontSize: 12, color: C.ink,
            maxHeight: 280 }}>{wsLog.join('\n')}</pre>}
        </Card>

        <Card title="Try it live — open endpoints" sub="No login needed. Click Run to hit the real API.">
          {OPEN_GETS.map(item => (
            <EndpointRow key={item.key} item={item} disabled={busy[item.key]}
              onRun={() => run(item.key, item.path)} out={resp[item.key]} />
          ))}
        </Card>

        <Card title="Try it live — coach endpoints" sub="These need a coach login. Log in, then Run.">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', paddingBottom: 4 }}>
            <input aria-label="Coach username" autoComplete="username" placeholder="Username" value={username}
              onChange={event => setUsername(event.target.value)} />
            <input aria-label="Coach password" autoComplete="current-password" placeholder="Password" type="password"
              value={password} onChange={event => setPassword(event.target.value)} />
            <button style={btn(!username || !password)} disabled={!username || !password} onClick={login}>Log in as coach</button>
            <span style={{ color: token ? C.good : C.ink3, fontSize: 13, fontFamily: C.mono }}>
              {loginMsg || 'not logged in'}</span>
          </div>
          {COACH_GETS.map(item => (
            <EndpointRow key={item.key} item={item} disabled={!token || busy[item.key]}
              onRun={() => run(item.key, item.path, { headers: { Authorization: 'Bearer ' + token } })}
              out={resp[item.key]} />
          ))}
        </Card>

        <Card title="Every endpoint" sub="The full base-station REST API.">
          {REFERENCE.map(section => (
            <div key={section.group} style={{ marginTop: 14 }}>
              <h3 style={{ fontSize: 13, color: C.accent, textTransform: 'uppercase',
                letterSpacing: '.08em', fontFamily: C.mono, margin: '0 0 6px' }}>{section.group}</h3>
              {section.items.map((it, i) => (
                <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'baseline',
                  padding: '7px 0', borderTop: i ? '1px solid ' + C.line : 'none', flexWrap: 'wrap' }}>
                  <Pill color={it.a === 'coach' ? C.warn : C.good}>{it.a === 'coach' ? 'coach' : 'open'}</Pill>
                  <code style={{ fontFamily: C.mono, fontSize: 12.5, color: C.ink, minWidth: 240 }}>
                    <span style={{ color: C.ink3 }}>{it.m}</span> {it.p}</code>
                  <span style={{ color: C.ink2, fontSize: 13, flex: 1, minWidth: 200 }}>{it.w}</span>
                </div>
              ))}
            </div>
          ))}
        </Card>

        <p style={{ color: C.ink3, fontSize: 12, marginTop: 28, textAlign: 'center' }}>
          Full docs: README.md · SPEC.md · MESSAGE_CONTRACT.md · RUNBOOK.md
        </p>
      </div>
    </div>
  )
}

export default ConnectionTest
