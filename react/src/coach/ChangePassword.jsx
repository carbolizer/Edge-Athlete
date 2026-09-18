import { useState } from 'react'
import { changePassword, setCoachToken } from './api.js'

// Shown when an administrator created this login with a temporary password
// (forced=true), and reachable any time afterwards from the Coaches screen.
export default function ChangePassword({ accessToken, forced = false, onChanged, onLogout }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event) {
    event.preventDefault()
    if (busy) return
    if (next !== confirmation) {
      setError('The new passwords do not match.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await changePassword(accessToken, current, next)
      setCurrent('')
      setNext('')
      setConfirmation('')
      onChanged()
    } catch (err) {
      setError(err.message || 'The password could not be changed.')
    } finally {
      setBusy(false)
    }
  }

  return <main className="monitor coach-login-screen">
    <section className="coach-login-card">
      <div className="monitor-brand"><img src="/icon-coach-192.png" alt="" width="52" height="52" /><span>Edge Athlete</span></div>
      <h1>{forced ? 'Choose your own password' : 'Change password'}</h1>
      {forced
        ? <p>Your account was created with a temporary password. Replace it before continuing.</p>
        : <p>Update the password you use to sign in.</p>}
      {error && <p className="coach-login-error" role="alert">{error}</p>}
      <form onSubmit={submit}>
        <label>{forced ? 'Temporary password' : 'Current password'}<input type="password" autoComplete="current-password" required value={current} onChange={e => setCurrent(e.target.value)} disabled={busy} /></label>
        <label>New password<input type="password" autoComplete="new-password" required maxLength={1024} value={next} onChange={e => setNext(e.target.value)} disabled={busy} /></label>
        <label>Confirm new password<input type="password" autoComplete="new-password" required value={confirmation} onChange={e => setConfirmation(e.target.value)} disabled={busy} /></label>
        <button disabled={busy}>{busy ? 'Saving…' : 'Save password'}</button>
      </form>
      {forced && onLogout && <button type="button" className="coach-login-link" onClick={() => { setCoachToken(null); onLogout() }}>Sign in as someone else</button>}
    </section>
  </main>
}
