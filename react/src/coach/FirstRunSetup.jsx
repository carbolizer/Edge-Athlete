import { useEffect, useState } from 'react'
import CoachAccess from './CoachAccess.jsx'
import { coachFetch } from './api.js'
import { navigate } from '../router.js'

// This cached flag only preserves the offline rack shell. It never grants API
// access: coach data still requires a valid server-issued credential.
const COMPLETE_KEY = 'edge_setup_complete'

export default function FirstRunSetup({ children }) {
  const [state, setState] = useState('loading')
  async function check() {
    setState('loading')
    try {
      const { setup_required: required } = await coachFetch('/api/auth/setup/')
      if (required) localStorage.removeItem(COMPLETE_KEY)
      else localStorage.setItem(COMPLETE_KEY, 'true')
      setState(required ? 'setup' : 'ready')
    } catch {
      setState(localStorage.getItem(COMPLETE_KEY) === 'true' ? 'ready' : 'error')
    }
  }
  useEffect(() => { check() }, [])
  if (state === 'ready') return children
  if (state === 'setup') return <CoachAccess onLoggedIn={() => {
    localStorage.setItem(COMPLETE_KEY, 'true')
    navigate('/coach')
    setState('ready')
  }} />
  return <main className="monitor coach-login-screen"><section className="coach-login-card">
    <h1>Edge Athlete setup</h1>
    <p role={state === 'error' ? 'alert' : 'status'}>{state === 'error' ? 'The base station could not be reached.' : 'Checking the base station…'}</p>
    {state === 'error' && <button onClick={check}>Retry connection</button>}
  </section></main>
}
