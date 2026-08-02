/*
 * CoachTablet.jsx — route /coach/setup
 * --------------------------------
 * Coach Room Layout: JWT login gate, then a dropdown-and-assign UI that wires
 * unassigned rack screens and nodes into numbered rack slots via coach PATCH
 * endpoints. Group / block / session drill-down stay out of scope.
 */

import { useCallback, useEffect, useState } from 'react'
import { applyRoleIdentity } from '../device.js'
import { navigate } from '../router.js'
import {
  coachFetch,
  coachLogin,
  getCoachToken,
  setCoachToken,
  shortId,
} from './api.js'
import './CoachTablet.css'
import DevPanel from './DevPanel.jsx'  // ⚠️ DEV-ONLY — delete with the <DevPanel/> below

/** Demo room size — slots are UI numbers, not a DB model. */
const RACK_SLOTS = [1, 2, 3, 4, 5, 6, 7, 8]

// A quiet nudge shown only while the base station is still on the default Wi-Fi
// password. Nothing otherwise — invisible on a configured box and on a laptop
// (where there is no AP, so the password reads as unknown, not default).
//
// This finishes an idea that was half-built: startup.sh set a flag file meaning
// "default password still in use" that nothing ever read. The check now lives in
// a coach-only endpoint, so the warning reaches a person — and the "change it"
// link opens the same form the always-on button does.
function DefaultsBanner({ token, onChangePassword }) {
  const [status, setStatus] = useState(null)

  useEffect(() => {
    let live = true
    coachFetch('/api/system/status/', { token })
      .then((data) => { if (live) setStatus(data) })
      .catch(() => {})   // a nudge that fails to load is not worth an error
    return () => { live = false }
  }, [token])

  if (!status || !status.wifi_password_is_default) return null

  return (
    <div className="coach-defaults-banner" role="alert">
      <strong>Wi-Fi password is still the default.</strong>{' '}
      <button type="button" className="coach-linkbtn" onClick={onChangePassword}>
        Change it before real use.
      </button>
    </div>
  )
}

// Where the just-set password is kept on THIS tablet so it survives the Wi-Fi
// drop and a reload. It is the one place that legitimately holds the new
// password: the coach typed it here, and they need it to reconnect in Settings.
// Cleared once they confirm they are back on.
const WIFI_RECENT_KEY = 'ea_wifi_recent'

function readRecentWifi() {
  try {
    const raw = localStorage.getItem(WIFI_RECENT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    // Stale after a couple of hours — a password from last week is not something
    // to keep flashing on a tablet.
    if (!parsed.password || Date.now() - parsed.ts > 2 * 60 * 60 * 1000) return null
    return parsed
  } catch { return null }
}

async function copyToClipboard(text) {
  try { await navigator.clipboard.writeText(text); return true } catch { return false }
}

// The Wi-Fi password change form — THE FRONT DESK in the "work-order slip"
// handshake (see django/event_handler/wifi_config.py for the full picture).
// Picture the base station as a building: this form is where the coach fills out
// the request. It cannot flip the switch itself — a web app has no keys to a
// device's Wi-Fi — so it hands the request to the clerk (the endpoint), who
// leaves a slip for the maintenance worker on the host to carry out.
//
// Opened from two places (the banner link and the always-on button), as a modal
// so either works without navigating away. It has two faces: the entry form,
// and — after a change, or on any later open while a recent one is remembered —
// a "here is the new password, copy it and reconnect in Settings" view. That
// second face matters because changing the Wi-Fi drops THIS tablet too, and no
// web app can rejoin it for you; the most it can do is hand you the password.
//
// Re-auth is deliberate: the coach is already logged in, but changing the gym
// Wi-Fi is a standing-config change, so it costs the coach password again.
function WifiPasswordForm({ token, onClose }) {
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [coachPassword, setCoachPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // If a recent change is remembered, open straight onto the copy view.
  const [saved, setSaved] = useState(() => readRecentWifi())
  const [copied, setCopied] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setError('')
    // Client-side checks first, so the obvious mistakes never cost a round trip.
    // The server re-checks all of this — the client is a courtesy, not the gate.
    if (newPassword.length < 8 || newPassword.length > 63) {
      setError('Wi-Fi password must be 8–63 characters.')
      return
    }
    if (newPassword !== confirm) {
      setError('The two Wi-Fi passwords do not match.')
      return
    }
    setBusy(true)
    try {
      const data = await coachFetch('/api/system/wifi-password/', {
        token, method: 'POST',
        body: { new_password: newPassword, coach_password: coachPassword },
      })
      if (data.applied) {
        // Remember it locally so it survives the drop, then show the copy view.
        const record = { password: newPassword, ts: Date.now() }
        try { localStorage.setItem(WIFI_RECENT_KEY, JSON.stringify(record)) } catch {}
        setSaved(record)
      } else {
        // e.g. running on a dev box with no base station to change.
        setError(data.detail || 'Nothing to change here.')
      }
    } catch (err) {
      setError(err.message || 'Could not change the Wi-Fi password.')
    } finally {
      setBusy(false)
    }
  }

  function done() {
    try { localStorage.removeItem(WIFI_RECENT_KEY) } catch {}
    onClose()
  }

  // ── the copy view (after a change) ──────────────────────────────────────────
  if (saved) {
    return (
      <div className="coach-modal-backdrop" onClick={onClose}>
        <div className="coach-modal" onClick={(event) => event.stopPropagation()}>
          <h3 style={{ margin: '0 0 8px' }}>New Wi-Fi password</h3>
          <p className="coach-modal-warn">
            The gym Wi-Fi is changing. This tablet — and every other device — will
            drop and must reconnect to “EdgeAthlete” with this password in
            Settings › Wi-Fi. A web app cannot change that for you.
          </p>
          <div className="coach-wifi-reveal">
            <code>{saved.password}</code>
          </div>
          <div className="coach-modal-actions">
            <button type="button" className="coach-btn coach-btn-ghost" onClick={done}>
              I’m reconnected
            </button>
            <button type="button" className="coach-btn"
                    onClick={async () => setCopied(await copyToClipboard(saved.password))}>
              {copied ? 'Copied ✓' : 'Copy password'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ── the entry form ──────────────────────────────────────────────────────────
  return (
    <div className="coach-modal-backdrop" onClick={onClose}>
      <div className="coach-modal" onClick={(event) => event.stopPropagation()}>
        <h3 style={{ margin: '0 0 8px' }}>Change Wi-Fi password</h3>
        <p className="coach-modal-warn">
          This changes the gym Wi-Fi (“EdgeAthlete”). Every device — including this
          one — drops and must rejoin with the new password.
        </p>
        <form onSubmit={submit}>
          <label className="coach-field">New Wi-Fi password
            <input type="password" value={newPassword} autoComplete="new-password"
                   onChange={(event) => setNewPassword(event.target.value)} />
          </label>
          <label className="coach-field">Confirm new password
            <input type="password" value={confirm} autoComplete="new-password"
                   onChange={(event) => setConfirm(event.target.value)} />
          </label>
          <label className="coach-field">Your coach password
            <input type="password" value={coachPassword} autoComplete="current-password"
                   onChange={(event) => setCoachPassword(event.target.value)} />
          </label>
          {error && <p className="coach-msg-err" style={{ marginTop: 10 }}>{error}</p>}
          <div className="coach-modal-actions">
            <button type="button" className="coach-btn coach-btn-ghost" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="coach-btn" disabled={busy}>
              {busy ? 'Saving…' : 'Change password'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function useCoachIdentity() {
  useEffect(() => {
    const prevTitle = document.title
    document.title = 'EA Coach'
    localStorage.setItem('device_role', 'coach')
    applyRoleIdentity('coach')
    return () => { document.title = prevTitle }
  }, [])
}

function LoginGate({ onLoggedIn }) {
  const [username, setUsername] = useState('coach')
  const [password, setPassword] = useState('coachpass')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const token = await coachLogin(username.trim(), password)
      onLoggedIn(token)
    } catch (err) {
      setError(err.message || 'login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="coach-card">
      <h2>Coach login</h2>
      <p className="coach-card-sub">
        Sign in with a coach account. Assignment APIs require a JWT from
        <code> /api/auth/login/</code>.
      </p>
      <form className="coach-form" onSubmit={handleSubmit}>
        <label className="coach-label">
          Username
          <input
            className="coach-input"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        <label className="coach-label">
          Password
          <input
            className="coach-input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button className="coach-btn coach-btn-primary" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
      {error && <p className="coach-msg coach-msg-err">{error}</p>}
    </section>
  )
}

function AssignRow({
  label,
  entityLabel,
  entities,
  entityValue,
  onEntityChange,
  getOptionLabel,
  slotValue,
  onSlotChange,
  onAssign,
  busy,
  disabledReason,
}) {
  const canAssign = Boolean(entityValue) && slotValue !== '' && !busy
  return (
    <div>
      <h3 style={{ margin: '0 0 10px', fontSize: 14, fontWeight: 700 }}>{label}</h3>
      <div className="coach-assign-row">
        <label className="coach-label">
          {entityLabel}
          <select
            className="coach-select"
            value={entityValue}
            onChange={(e) => onEntityChange(e.target.value)}
          >
            <option value="">
              {entities.length === 0 ? `No ${entityLabel.toLowerCase()} available` : `Select ${entityLabel.toLowerCase()}…`}
            </option>
            {entities.map((item) => (
              <option key={item.key} value={item.key}>
                {getOptionLabel(item)}
              </option>
            ))}
          </select>
        </label>
        <label className="coach-label">
          Rack slot
          <select
            className="coach-select"
            value={slotValue}
            onChange={(e) => onSlotChange(e.target.value)}
          >
            <option value="">Select slot…</option>
            {RACK_SLOTS.map((n) => (
              <option key={n} value={String(n)}>Rack {n}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="coach-btn coach-btn-primary"
          disabled={!canAssign}
          onClick={onAssign}
        >
          {busy ? 'Assigning…' : 'Assign'}
        </button>
      </div>
      {disabledReason && <p className="coach-msg">{disabledReason}</p>}
    </div>
  )
}

function RoomLayout({ token, onAuthLost }) {
  const [screens, setScreens] = useState([])
  const [nodes, setNodes] = useState([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState({ text: '', kind: '' })
  const [screenId, setScreenId] = useState('')
  const [screenSlot, setScreenSlot] = useState('')
  const [nodeId, setNodeId] = useState('')
  const [nodeSlot, setNodeSlot] = useState('')
  const [busyScreen, setBusyScreen] = useState(false)
  const [busyNode, setBusyNode] = useState(false)
  const [screenBySlot, setScreenBySlot] = useState({})

  // `silent` is for the background poll below: refresh the lists without flipping
  // the loading spinner, clearing the coach's message, or otherwise disturbing a
  // selection that's in progress.
  const load = useCallback(async ({ clearMessage = true, silent = false } = {}) => {
    if (!silent) setLoading(true)
    if (clearMessage) setMsg({ text: '', kind: '' })
    try {
      const [unassigned, allNodes] = await Promise.all([
        coachFetch('/api/racks/unassigned/', { token }),
        coachFetch('/api/nodes/', { token }),
      ])
      setScreens(Array.isArray(unassigned) ? unassigned : [])
      setNodes(Array.isArray(allNodes) ? allNodes : [])
    } catch (err) {
      const text = err.message || 'failed to load room state'
      if (/401|403|credential|token|authentication/i.test(text)) {
        onAuthLost()
        return
      }
      if (!silent) setMsg({ text, kind: 'err' })
    } finally {
      if (!silent) setLoading(false)
    }
  }, [token, onAuthLost])

  useEffect(() => { load() }, [load])

  // Keep the waiting-tablet + node lists fresh on their own: a tablet that enters
  // setup mode should show up here without the coach hitting Refresh. Poll quietly
  // every 3s (matches the "within about three seconds" note in the copy above).
  useEffect(() => {
    const id = setInterval(() => { load({ clearMessage: false, silent: true }) }, 3000)
    return () => clearInterval(id)
  }, [load])

  const occupancyBySlot = {}
  for (const n of RACK_SLOTS) occupancyBySlot[n] = { screenId: screenBySlot[n] || null, node: null }
  for (const n of nodes) {
    if (n.rack_number != null && occupancyBySlot[n.rack_number]) {
      occupancyBySlot[n.rack_number].node = n
    }
  }

  async function assignScreen() {
    if (!screenId || screenSlot === '') return
    setBusyScreen(true)
    setMsg({ text: '', kind: '' })
    try {
      const rack_number = Number(screenSlot)
      const result = await coachFetch(`/api/racks/${encodeURIComponent(screenId)}/`, {
        token,
        method: 'PATCH',
        body: { rack_number },
      })
      setScreenBySlot((prev) => {
        const next = { ...prev }
        for (const [slot, id] of Object.entries(next)) {
          if (id === result.device_id) delete next[slot]
        }
        next[result.rack_number] = result.device_id
        return next
      })
      setMsg({
        text: `Screen ${shortId(result.device_id)} → rack ${result.rack_number}`,
        kind: 'ok',
      })
      setScreenId('')
      setScreenSlot('')
      await load({ clearMessage: false })
    } catch (err) {
      const text = err.message || 'assign failed'
      if (/401|403|credential|token|authentication/i.test(text)) onAuthLost()
      else setMsg({ text, kind: 'err' })
    } finally {
      setBusyScreen(false)
    }
  }

  async function assignNode() {
    if (!nodeId || nodeSlot === '') return
    setBusyNode(true)
    setMsg({ text: '', kind: '' })
    try {
      const rack_number = Number(nodeSlot)
      const result = await coachFetch(`/api/nodes/${encodeURIComponent(nodeId)}/`, {
        token,
        method: 'PATCH',
        body: { rack_number },
      })
      setMsg({
        text: `Node ${result.node_id} → rack ${result.rack_number}`,
        kind: 'ok',
      })
      setNodeId('')
      setNodeSlot('')
      await load({ clearMessage: false })
    } catch (err) {
      const text = err.message || 'assign failed'
      if (/401|403|credential|token|authentication/i.test(text)) onAuthLost()
      else setMsg({ text, kind: 'err' })
    } finally {
      setBusyNode(false)
    }
  }

  const screenOptions = screens.map((s) => ({ key: s.device_id, ...s }))
  const nodeOptions = [...nodes]
    .sort((a, b) => {
      const au = a.rack_number == null ? 0 : 1
      const bu = b.rack_number == null ? 0 : 1
      if (au !== bu) return au - bu
      return String(a.node_id).localeCompare(String(b.node_id))
    })
    .map((n) => ({ key: n.node_id, ...n }))

  return (
    <section className="coach-card">
      <div className="coach-toolbar">
        <h2 style={{ flex: 1 }}>Room Layout</h2>
        <button
          type="button"
          className="coach-btn coach-btn-ghost"
          onClick={() => load()}
          disabled={loading}
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      <p className="coach-card-sub">
        Pick an unassigned screen or a node, pick a rack slot, then Assign.
        Waiting tablets pick up a new rack number within about three seconds.
      </p>
      <p className="coach-hint">
        Screens: <code>{'PATCH /api/racks/{device_id}/'}</code>
        {' · '}
        Nodes: <code>{'PATCH /api/nodes/{node_id}/'}</code>
      </p>

      {loading && screens.length === 0 && nodes.length === 0 ? (
        <p className="coach-msg">Loading room state…</p>
      ) : (
        <>
          <AssignRow
            label="Assign rack screen"
            entityLabel="Unassigned screen"
            entities={screenOptions}
            entityValue={screenId}
            onEntityChange={setScreenId}
            getOptionLabel={(s) => shortId(s.device_id)}
            slotValue={screenSlot}
            onSlotChange={setScreenSlot}
            onAssign={assignScreen}
            busy={busyScreen}
          />

          <hr className="coach-divider" />

          <AssignRow
            label="Assign node"
            entityLabel="Node"
            entities={nodeOptions}
            entityValue={nodeId}
            onEntityChange={setNodeId}
            getOptionLabel={(n) =>
              n.rack_number == null
                ? `${n.node_id} (unassigned)`
                : `${n.node_id} (rack ${n.rack_number})`
            }
            slotValue={nodeSlot}
            onSlotChange={setNodeSlot}
            onAssign={assignNode}
            busy={busyNode}
          />
        </>
      )}

      {msg.text && (
        <p className={`coach-msg ${msg.kind === 'ok' ? 'coach-msg-ok' : msg.kind === 'err' ? 'coach-msg-err' : ''}`}>
          {msg.text}
        </p>
      )}

      <hr className="coach-divider" />
      <h3 style={{ margin: '0 0 6px', fontSize: 14, fontWeight: 700 }}>Rack slots</h3>
      <p className="coach-hint" style={{ marginBottom: 8 }}>
        Nodes refresh from the API. Screen labels stick after an assign in this
        session (there is no list-all-screens endpoint yet).
      </p>
      <div className="coach-slot-grid">
        {RACK_SLOTS.map((n) => {
          const slot = occupancyBySlot[n]
          const empty = !slot.screenId && !slot.node
          return (
            <div key={n} className="coach-slot">
              <div className="coach-slot-num">Rack {n}</div>
              {empty ? (
                <div className="coach-slot-empty">Empty</div>
              ) : (
                <>
                  <div className="coach-slot-line">
                    Screen{' '}
                    <strong>{slot.screenId ? shortId(slot.screenId) : '—'}</strong>
                  </div>
                  <div className="coach-slot-line">
                    Node <strong>{slot.node ? slot.node.node_id : '—'}</strong>
                  </div>
                </>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

function changeDeviceRole() {
  localStorage.removeItem('device_role')
  setCoachToken(null)
  navigate('/')
}

export default function CoachTablet() {
  useCoachIdentity()
  const [token, setToken] = useState(() => getCoachToken())
  // Open the Wi-Fi modal on its own if a change was made just before the tablet
  // dropped/reloaded — so the coach lands back on the "here is the password"
  // view and can copy it, rather than having to remember to reopen it.
  const [showWifi, setShowWifi] = useState(() => Boolean(readRecentWifi()))

  // Stable identity (useCallback) on purpose: this is passed down as onAuthLost,
  // which RoomLayout's `load` depends on. A fresh function each render made `load`
  // churn and re-fire its load-on-mount effect repeatedly (a burst of fetches at
  // page load). Both setters are stable, so [] deps are correct.
  const logout = useCallback(() => {
    setCoachToken(null)
    setToken(null)
  }, [])

  return (
    <div className="coach-root">
      <div className="coach-shell">
        <div className="coach-topbar">
          <div>
            <p className="coach-eyebrow">Edge Athlete</p>
            <h1 className="coach-brand">Coach Admin</h1>
            <p className="coach-lede">
              Wire real hardware into numbered rack slots for the demo — no
              config-file edits.
            </p>
          </div>
          <div className="coach-topbar-actions">
            {/* Room Layout is reached from a cog on the coach workspace, so it
                needs a way back. Without it the only exits are Sign out and
                Change device role — both of which drop the login, which is a
                harsh price for opening the wrong screen. */}
            <button type="button" className="coach-btn coach-btn-ghost" onClick={() => navigate('/coach')}>
              ← Coach workspace
            </button>
            {token && (
              <button type="button" className="coach-btn coach-btn-ghost" onClick={() => setShowWifi(true)}>
                Wi-Fi password
              </button>
            )}
            {token && (
              <button type="button" className="coach-btn coach-btn-ghost" onClick={logout}>
                Sign out
              </button>
            )}
            <button type="button" className="coach-btn coach-btn-ghost" onClick={changeDeviceRole}>
              Change device role
            </button>
          </div>
        </div>

        {!token ? (
          <LoginGate onLoggedIn={setToken} />
        ) : (
          <>
            <DefaultsBanner token={token} onChangePassword={() => setShowWifi(true)} />
            <RoomLayout token={token} onAuthLost={logout} />
            {/* ⚠️ DEV-ONLY — delete this line and the DevPanel import above. */}
            <DevPanel token={token} />
          </>
        )}
        {token && showWifi && (
          <WifiPasswordForm token={token} onClose={() => setShowWifi(false)} />
        )}
      </div>
    </div>
  )
}
