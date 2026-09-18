import { useEffect, useState } from 'react'
import { coachFetch, coachLogin, setCoachToken } from './api.js'

const SETUP_HINT = 'On the base station, run: docker compose exec django python manage.py setup_code'

export default function CoachAccess({ onLoggedIn }) {
  const [setup, setSetup] = useState(null)
  const [codePending, setCodePending] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [setupCode, setSetupCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function checkSetup() {
    setError('')
    try {
      const data = await coachFetch('/api/auth/setup/')
      setSetup(data.setup_required)
      setCodePending(Boolean(data.setup_code_pending))
    } catch {
      setError('The base station could not be reached. Check your connection and retry.')
    }
  }
  useEffect(() => { checkSetup() }, [])

  async function submit(event) {
    event.preventDefault()
    if (busy) return
    if (setup && password !== confirmation) {
      setError('The passwords do not match.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const token = setup
        ? (await coachFetch('/api/auth/setup/', {
            method: 'POST',
            body: { username: username.trim(), password, setup_code: setupCode.trim() },
          })).access
        : await coachLogin(username.trim(), password)
      setCoachToken(token)
      setPassword('')
      setConfirmation('')
      setSetupCode('')
      onLoggedIn(token)
    } catch (err) {
      if (err.status === 409) setSetup(false)
      setError(err.message || 'Unable to sign in. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return <main className="monitor coach-login-screen">
    <section className="coach-login-card">
      <div className="monitor-brand"><img src="/icon-coach-192.png" alt="" width="52" height="52" /><span>Edge Athlete</span></div>
      <h1>{setup === null ? 'Connecting to the base station' : setup ? 'Create your first coach account' : 'Coach login'}</h1>
      {error && <p className="coach-login-error" role="alert">{error}</p>}
      {setup === null ? <button onClick={checkSetup}>Retry connection</button> : <>
        {setup
          ? <p>This account will administer this base station. Enter the one-time setup code shown on the base station&rsquo;s terminal.</p>
          : <p>Sign in to manage your team and view athlete data.</p>}
        {setup && !codePending && <>
          <p className="coach-login-hint" role="note">
            No setup code has been issued yet. {SETUP_HINT}
          </p>
          <button type="button" onClick={checkSetup} disabled={busy}>I&rsquo;ve run it — check again</button>
        </>}
        <form onSubmit={submit}>
          <label>Username<input autoComplete="username" maxLength={150} required value={username} onChange={e => setUsername(e.target.value)} disabled={busy} /></label>
          <label>Password<input type="password" autoComplete={setup ? 'new-password' : 'current-password'} required maxLength={1024} value={password} onChange={e => setPassword(e.target.value)} disabled={busy} /></label>
          {setup && <label>Confirm password<input type="password" autoComplete="new-password" required value={confirmation} onChange={e => setConfirmation(e.target.value)} disabled={busy} /></label>}
          {setup && <label>Setup code<input autoComplete="one-time-code" required maxLength={64} value={setupCode} onChange={e => setSetupCode(e.target.value)} disabled={busy} /></label>}
          <button disabled={busy}>{busy ? 'Please wait…' : setup ? 'Create account' : 'Sign in'}</button>
        </form>
      </>}
    </section>
  </main>
}
