import { useEffect, useState } from 'react'
import { createCoach, listCoaches, resetCoachPassword, updateCoach } from './api.js'
import './CoachManagement.css'

// Administrator-only: create logins for the other coaches and hand out the
// temporary passwords. Everyone shares one database; an account just says who
// is doing the coaching.
export default function CoachManagement({ accessToken, currentUsername, onLogout, onChangePassword }) {
  const [coaches, setCoaches] = useState([])
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [handoff, setHandoff] = useState(null)

  function failed(err) {
    if (err.status === 401 || err.status === 403) onLogout()
    else setError(err.message || 'The base station could not be reached.')
  }
  async function load() {
    setLoading(true)
    setError('')
    try {
      setCoaches(await listCoaches(accessToken))
    } catch (err) { failed(err) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [accessToken])

  async function submit(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    setHandoff(null)
    try {
      const created = await createCoach(accessToken, username.trim(), password)
      setUsername('')
      setPassword('')
      setHandoff({ username: created.username, password: created.temporary_password })
      await load()
    } catch (err) { failed(err) }
    finally { setBusy(false) }
  }

  async function toggle(coach, changes) {
    setBusy(true)
    setError('')
    try {
      await updateCoach(accessToken, coach.id, changes)
      await load()
    } catch (err) { failed(err) }
    finally { setBusy(false) }
  }

  async function reset(coach) {
    if (!window.confirm(`Reset the password for ${coach.username}? They will have to choose a new one at next sign-in.`)) return
    setBusy(true)
    setError('')
    setHandoff(null)
    try {
      const updated = await resetCoachPassword(accessToken, coach.id)
      setHandoff({ username: updated.username, password: updated.temporary_password })
      await load()
    } catch (err) { failed(err) }
    finally { setBusy(false) }
  }

  return <section className="coach-mgmt">
    <h2>Coaches</h2>
    <p>Each coach signs in with their own account and shares the same athletes, workouts, and reports.</p>
    {error && <p className="coach-mgmt-error" role="alert">{error} <button onClick={load} disabled={busy || loading}>Retry</button></p>}
    {handoff && <p className="coach-mgmt-handoff" role="status">
      Temporary password for <b>{handoff.username}</b>: <code>{handoff.password}</code>
      <br />Give it to them now — it is shown once and cannot be read again. They will be asked to change it at first sign-in.
      <button type="button" onClick={() => setHandoff(null)}>Dismiss</button>
    </p>}

    <form className="coach-mgmt-form" onSubmit={submit}>
      <h3>Add a coach</h3>
      <label>Username<input required maxLength={150} value={username} disabled={busy} onChange={e => setUsername(e.target.value)} /></label>
      <label>Temporary password (optional)<input type="text" value={password} placeholder="Leave blank to generate one" maxLength={1024} disabled={busy} onChange={e => setPassword(e.target.value)} /></label>
      <button disabled={busy || !username.trim()}>{busy ? 'Saving…' : 'Create coach login'}</button>
    </form>

    {loading ? <p role="status">Loading coaches…</p> : <ul className="coach-mgmt-list">
      {coaches.map(coach => <li key={coach.id}>
        <span className="coach-mgmt-name">
          {coach.username}
          {coach.is_staff && <em className="coach-mgmt-badge">administrator</em>}
          {!coach.is_active && <em className="coach-mgmt-badge coach-mgmt-badge-off">deactivated</em>}
          {coach.must_change_password && <em className="coach-mgmt-badge">must change password</em>}
        </span>
        <span className="coach-mgmt-actions">
          <button disabled={busy} onClick={() => reset(coach)}>Reset password</button>
          {coach.username === currentUsername
            ? <span className="coach-mgmt-self">This is you</span>
            : <>
              <button disabled={busy} onClick={() => toggle(coach, { is_staff: !coach.is_staff })}>{coach.is_staff ? 'Make coach' : 'Make administrator'}</button>
              <button disabled={busy} onClick={() => toggle(coach, { is_active: !coach.is_active })}>{coach.is_active ? 'Deactivate' : 'Reactivate'}</button>
            </>}
        </span>
      </li>)}
    </ul>}
    <button type="button" className="coach-mgmt-password" onClick={onChangePassword}>Change my password</button>
  </section>
}
