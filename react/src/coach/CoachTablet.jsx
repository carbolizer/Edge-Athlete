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

/** Demo room size — slots are UI numbers, not a DB model. */
const RACK_SLOTS = [1, 2, 3, 4, 5, 6, 7, 8]

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
          <RoomLayout token={token} onAuthLost={logout} />
        )}
      </div>
    </div>
  )
}
