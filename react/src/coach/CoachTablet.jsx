/*
 * CoachTablet.jsx — route /coach/setup
 * --------------------------------
 * Coach Room Layout: JWT login gate, then a dropdown-and-assign UI that wires
 * unassigned rack screens into numbered rack slots via coach PATCH
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
import { getRackState } from '../api/client.js'
import './CoachTablet.css'

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
  const [busyScreen, setBusyScreen] = useState(false)
  const [screenBySlot, setScreenBySlot] = useState({})
  const [nodeId, setNodeId] = useState('')
  const [nodeSlot, setNodeSlot] = useState('')
  const [busyNode, setBusyNode] = useState(false)
  // rack number -> the device id of the screen registered to it. Assigning a sensor
  // is addressed by SCREEN, not by rack number, so this is what makes the row below
  // possible. It comes from room-state rather than screenBySlot because that only
  // remembers assignments made in the current browser session.
  const [screenIdBySlot, setScreenIdBySlot] = useState({})

  // `silent` is for the background poll below: refresh the lists without flipping
  // the loading spinner, clearing the coach's message, or otherwise disturbing a
  // selection that's in progress.
  const load = useCallback(async ({ clearMessage = true, silent = false } = {}) => {
    if (!silent) setLoading(true)
    if (clearMessage) setMsg({ text: '', kind: '' })
    try {
      const [unassigned, allNodes, room] = await Promise.all([
        coachFetch('/api/racks/unassigned/', { token }),
        coachFetch('/api/nodes/', { token }),
        coachFetch('/api/room-state/?details=true', { token }),
      ])
      setScreens(Array.isArray(unassigned) ? unassigned : [])
      setNodes(Array.isArray(allNodes) ? allNodes : [])
      const bySlot = {}
      for (const r of room?.racks || []) {
        if (r.screen_device_id) bySlot[r.rack_number] = r.screen_device_id
      }
      setScreenIdBySlot(bySlot)
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
  // screenIdBySlot comes from room-state and knows every rack, not just the ones
  // assigned in this browser session — which is what makes Release usable on a
  // tablet somebody else assigned last week.
  for (const n of RACK_SLOTS) occupancyBySlot[n] = { screenId: screenIdBySlot[n] || screenBySlot[n] || null, node: null }
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

  // Link a sensor to a rack. This row came back after being removed with the BLE
  // work: sensor selection moved to the physical rack because an anonymous nearby
  // RADIO cannot be identified from across the room. True for Bluetooth — but an
  // MQTT sensor announced its own name, so there is nothing to verify, and removing
  // both left no way to link one anywhere.
  //
  // The endpoint enforces the difference rather than this screen guessing at it: an
  // unassigned Bluetooth sensor is refused here and must be verified at the rack.
  // It also unassigns whatever sensor the rack already had, in the same transaction,
  // so a rack can never end up on Bluetooth and Wi-Fi at once.
  async function assignNode() {
    if (!nodeId || nodeSlot === '') return
    const rack = Number(nodeSlot)
    const deviceId = screenIdBySlot[rack]
    if (!deviceId) {
      setMsg({ text: `Assign a screen to rack ${rack} first — sensors are linked by screen.`, kind: 'err' })
      return
    }
    setBusyNode(true)
    setMsg({ text: '', kind: '' })
    try {
      const result = await coachFetch('/api/racks/node-assignment/', {
        token,
        method: 'PUT',
        body: { device_id: deviceId, node_id: nodeId },
      })
      setMsg({ text: `Sensor ${result.node?.node_id ?? nodeId} → rack ${result.rack_number}`, kind: 'ok' })
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

  // Send a tablet back to the waiting list.
  //
  // This is the escape from a deadlock, not a convenience. Nothing used to clear a
  // screen's rack number, and the "unassigned" list only shows screens without one —
  // so a tablet sent to setup mode kept its old rack, never reappeared for the
  // coach, and could not be reassigned. The only known workaround was wiping the
  // tablet's browser data, which does not fix it so much as replace the device.

  // Force-clear a rack so a fresh screen can take it over. This is the escape
  // hatch for a wedged rack: an open set nobody can finish because the screen
  // that started it is gone, a lease stuck in recovery_required, a tablet
  // reassigned while it still held the rack. The normal Release refuses while a
  // set is open — this is the deliberate "kill it" lever. It ends open sets as
  // false sets, resets the runtime to idle, and sends any screen back to the
  // waiting list, but leaves the sensor on the rack (a new screen should reuse it).
  // Called "Remove screen" in the UI, not "Remove rack". Nothing here removes a
  // rack — the rack is a physical thing bolted to the floor, and its sensor stays
  // assigned on purpose. What a coach is actually doing is taking the SCREEN off
  // it, so the label says that.
  async function removeScreen(rack) {
    // Take the sensor off a rack. Addressed by RACK, not by screen — the state
  // where you most want this is a rack that has a node and no screen, which is
  // exactly what a force-clear leaves behind.
  async function unlinkNode(rack, nodeId) {
    if (!window.confirm(
      `Unlink sensor ${nodeId} from rack ${rack}?\n\n` +
      `The rack keeps its screen; only the sensor comes off. Reps cannot be ` +
      `recorded at this rack until another sensor is linked. Do it?`,
    )) return
    setBusyScreen(true)
    setMsg({ text: '', kind: '' })
    try {
      await coachFetch(`/api/racks/${rack}/node/`, { token, method: 'DELETE' })
      setMsg({ text: `Sensor ${nodeId} unlinked from rack ${rack}`, kind: 'ok' })
      await load({ clearMessage: false })
    } catch (err) {
      const text = err.message || 'unlink failed'
      if (/401|403|credential|token|authentication/i.test(text)) onAuthLost()
      else setMsg({ text, kind: 'err' })
    } finally {
      setBusyScreen(false)
    }
  }

  // The end-of-session reset. Same clearing as one rack, times however many are
  // occupied — so the same data loss, multiplied. Counts the mid-set racks first
  // so the warning is specific rather than a vague "this may lose data".
  async function releaseAllRacks() {
    const occupied = RACK_SLOTS.filter((n) => occupancyBySlot[n]?.screenId)
    if (occupied.length === 0) {
      setMsg({ text: 'No screens are assigned to any rack', kind: 'ok' })
      return
    }

    const bluetooth = RACK_SLOTS.filter(
      (n) => occupancyBySlot[n]?.node?.acquisition_kind === 'wt901_ble',
    )
    if (bluetooth.length > 0) {
      window.alert(
        `Cannot release all racks: Bluetooth sensors are linked on ` +
        `rack${bluetooth.length === 1 ? '' : 's'} ${bluetooth.join(', ')}.\n\n` +
        `Unlink those sensors first. Re-linking a Bluetooth sensor has to be done ` +
        `standing at the rack, so it is not something to trigger in bulk.`,
      )
      return
    }

    const states = await Promise.all(occupied.map(
      (n) => getRackState(n).then((s) => [n, s]).catch(() => [n, null]),
    ))
    const midSet = states.filter(
      ([, s]) => s && ['active', 'countdown', 'recovery_required'].includes(s.phase),
    )
    const bufferedReps = midSet.reduce((sum, [, s]) => sum + (s.rep_count ?? 0), 0)

    let warning = ''
    if (midSet.length > 0) {
      warning =
        `⚠️ ${midSet.length} rack${midSet.length === 1 ? ' is' : 's are'} MID-SET ` +
        `(${midSet.map(([n]) => n).join(', ')}).\n\n` +
        (bufferedReps > 0
          ? `At least ${bufferedReps} rep${bufferedReps === 1 ? '' : 's'} across those tablets ` +
            `have NOT been saved and will be lost.\n\n`
          : `Those sets will be ended as false sets.\n\n`)
    }

    if (!window.confirm(
      warning +
      `Release all ${occupied.length} screen${occupied.length === 1 ? '' : 's'} ` +
      `(rack${occupied.length === 1 ? '' : 's'} ${occupied.join(', ')})?\n\n` +
      `Every screen goes back to the waiting list and returns to its setup ` +
      `screen. Sensors stay on their racks. Do it?`,
    )) return

    setBusyScreen(true)
    setMsg({ text: '', kind: '' })
    try {
      const result = await coachFetch('/api/racks/release-all/', { token, method: 'POST' })
      setScreenBySlot({})
      const cleared = result?.cleared ?? []
      setMsg({ text: `Released ${cleared.length} rack${cleared.length === 1 ? '' : 's'} — every screen is back in the waiting list`, kind: 'ok' })
      await load({ clearMessage: false })
    } catch (err) {
      const text = err.message || 'release all failed'
      if (/401|403|credential|token|authentication/i.test(text)) onAuthLost()
      else setMsg({ text, kind: 'err' })
    } finally {
      setBusyScreen(false)
    }
  }

  // ── WHY THIS ASKS THE SERVER FIRST ───────────────────────────────────────
    // Reps are held in the TABLET's buffer and only sent as one batch when the
    // set finishes. Force-clearing ends any open set as a false set with its
    // counts zeroed, so pressing this mid-set throws away everything the athlete
    // has done in that set — silently, with nothing left to say reps existed.
    //
    // The server does track the COUNT live: the tablet pushes rep_count on every
    // rep. So we can at least tell a coach what they are about to destroy. Asked
    // at click time rather than read from render state, because this is a
    // destructive decision and a number from thirty seconds ago is not good
    // enough to base it on.
    //
    // ⚠️ THE COUNT IS A FLOOR, NOT AN EXACT NUMBER, which is why the text says
    // "at least". Each rep's push is fire-and-forget (the tablet swallows the
    // error so a blip never interrupts a lift), so a tablet that has lost contact
    // keeps buffering reps the server never hears about. The stored count then
    // UNDER-reports — the dangerous direction. `controller_active` false while
    // the phase is live is the tell, and the message says so.
    // ⚠️ A Bluetooth sensor blocks this outright, and the block is deliberate.
    // Re-linking an unlinked WT901 needs verified BLE enrollment — physically at
    // the rack, moving the sensor to prove which one it is. A coach clearing
    // racks from across the gym cannot undo it from where they are standing, so
    // this asks them to unlink on purpose rather than discover it after.
    if (occupancyBySlot[rack]?.node?.acquisition_kind === 'wt901_ble') {
      window.alert(
        `Rack ${rack} has a Bluetooth sensor linked ` +
        `(${occupancyBySlot[rack].node.node_id}).\n\n` +
        `Unlink the sensor first, then release the screen.\n\n` +
        `Re-linking a Bluetooth sensor has to be done standing at the rack, so ` +
        `this is not something to trigger by accident from here.`,
      )
      return
    }

    let live = null
    try {
      live = await getRackState(rack)
    } catch {
      // Can't reach it — fall through to the generic warning rather than
      // blocking a coach from clearing a rack that may be wedged precisely
      // because something is unreachable.
    }

    const midSet = live && ['active', 'countdown', 'recovery_required'].includes(live.phase)
    const reps = live?.rep_count ?? 0
    const who = live?.selected_athlete?.name
    let warning = ''
    if (midSet && reps > 0) {
      warning =
        `⚠️ Rack ${rack} is MID-SET${who ? ` — ${who}` : ''}.\n\n` +
        `At least ${reps} rep${reps === 1 ? '' : 's'} are recorded on the tablet and ` +
        `have NOT been saved. Removing the screen discards them permanently.\n\n` +
        (live.controller_active === false
          ? `The tablet has stopped reporting, so there may be more than ${reps}.\n\n`
          : `Finishing the set on the tablet saves them.\n\n`)
    } else if (midSet) {
      warning = `⚠️ Rack ${rack} has a set open${who ? ` — ${who}` : ''}. It will be ended as a false set.\n\n`
    }

    if (!window.confirm(
      warning +
      `Remove the screen from rack ${rack}? It goes back to the waiting list and ` +
      `can be reassigned. This also ends any open set as a false set and resets ` +
      `the controller. The sensor stays on the rack. Do it?`,
    )) return
    setBusyScreen(true)
    setMsg({ text: '', kind: '' })
    try {
      await coachFetch(`/api/racks/${rack}/`, { token, method: 'DELETE' })
      setScreenBySlot((prev) => {
        const next = { ...prev }
        delete next[rack]
        return next
      })
      setMsg({ text: `Screen removed from rack ${rack} — it is back in the waiting list`, kind: 'ok' })
      await load({ clearMessage: false })
    } catch (err) {
      const text = err.message || 'remove failed'
      if (/401|403|credential|token|authentication/i.test(text)) onAuthLost()
      else setMsg({ text, kind: 'err' })
    } finally {
      setBusyScreen(false)
    }
  }

  const screenOptions = screens.map((s) => ({ key: s.device_id, ...s }))
  // Offer sensors this rack can actually take: unassigned, or already on the chosen
  // rack. One owned by a different rack is left out rather than shown and refused.
  const nodeOptions = nodes
    .filter((n) => n.rack_number == null || String(n.rack_number) === String(nodeSlot))
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
        Assign waiting screens to rack slots, and link a sensor to a rack.
        Waiting tablets pick up a new rack number within about three seconds.
        Bluetooth sensors that have never been linked must be verified standing at
        the rack — you cannot tell anonymous nearby radios apart from here.
      </p>
      <p className="coach-hint">
        Screens: <code>{'PATCH /api/racks/{device_id}/'}</code>
        {' · '}
        Sensors: <code>{'PUT /api/racks/node-assignment/'}</code>
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

          <AssignRow
            label="Link sensor to rack"
            entityLabel="Sensor"
            entities={nodeOptions}
            entityValue={nodeId}
            onEntityChange={setNodeId}
            getOptionLabel={(n) =>
              `${n.node_id}${n.acquisition_kind === 'wt901_ble' ? ' · Bluetooth' : ' · Wi-Fi'}`
            }
            slotValue={nodeSlot}
            onSlotChange={setNodeSlot}
            onAssign={assignNode}
            busy={busyNode}
            disabledReason={
              nodeSlot !== '' && !screenIdBySlot[Number(nodeSlot)]
                ? `Rack ${nodeSlot} has no screen registered yet — assign one above first.`
                : undefined
            }
          />

        </>
      )}

      {msg.text && (
        <p className={`coach-msg ${msg.kind === 'ok' ? 'coach-msg-ok' : msg.kind === 'err' ? 'coach-msg-err' : ''}`}>
          {msg.text}
        </p>
      )}

      <hr className="coach-divider" />
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
        <h3 style={{ margin: '0 0 6px', fontSize: 14, fontWeight: 700 }}>Rack slots</h3>
        {/* The end-of-session reset. Top right because it acts on the whole grid
            below it, not on any one slot — and separated from the per-rack
            buttons so it is never the one you hit by accident. */}
        <button
          type="button"
          className="coach-btn coach-btn-ghost"
          style={{ fontSize: 12, color: '#c0392b' }}
          disabled={busyScreen}
          onClick={releaseAllRacks}
          title="Send EVERY screen back to the waiting list and to its setup screen. Ends any open sets as false. Sensors stay on their racks."
        >
          Release all racks
        </button>
      </div>
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
                  {/* ONE screen button, not two. There used to be a "Release
                      screen" (PATCH rack_number null) beside a "Remove screen"
                      (DELETE), which read as two parallel options for the same
                      job — with the quieter-looking one refusing whenever a set
                      was open. The DELETE does everything the PATCH did and
                      copes with a wedged rack, so it is the only path now, and
                      it warns first when reps are about to be lost. */}
                  {slot.screenId && (
                    <button
                      type="button"
                      className="coach-btn coach-btn-ghost"
                      style={{ marginTop: 6, fontSize: 12, color: '#c0392b' }}
                      disabled={busyScreen}
                      onClick={() => removeScreen(n)}
                      title="Send this tablet back to the waiting list and to its setup screen. Ends any open set as false and resets the controller. The sensor stays on the rack."
                    >
                      Release screen
                    </button>
                  )}
                  {/* Separate from the screen: a rack keeps its sensor when the
                      screen leaves, so removing one must not imply the other. */}
                  {slot.node && (
                    <button
                      type="button"
                      className="coach-btn coach-btn-ghost"
                      style={{ marginTop: 6, fontSize: 12 }}
                      disabled={busyScreen}
                      onClick={() => unlinkNode(n, slot.node.node_id)}
                      title="Take this sensor off the rack. The screen stays. Refused while a set is open."
                    >
                      Unlink sensor
                    </button>
                  )}
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
          </>
        )}
        {token && showWifi && (
          <WifiPasswordForm token={token} onClose={() => setShowWifi(false)} />
        )}
      </div>
    </div>
  )
}
