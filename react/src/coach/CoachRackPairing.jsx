import { useEffect, useState } from 'react'
import { navigate } from '../router.js'
import {
  claimRackEndpoint, coachLogin, confirmRackHelper, getCoachToken,
  getCoachTrainingGroups, setCoachToken,
} from './api.js'
import {
  endpointClaimErrorMessage, endpointClaimPayload, helperConfirmationErrorMessage,
  helperPairingId,
} from './rackPairing.js'
import './CoachRackPairing.css'

export function RackPairingWorkspace({ token, groups, loadingGroups, onAuthLost }) {
  const [endpointCode, setEndpointCode] = useState('')
  const [trainingGroup, setTrainingGroup] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [helperCode, setHelperCode] = useState('')
  const [phraseConfirmed, setPhraseConfirmed] = useState(false)
  const [endpointState, setEndpointState] = useState({ busy: false, error: '', result: null })
  const [helperState, setHelperState] = useState({ busy: false, error: '', result: null })

  async function claimEndpoint(event) {
    event.preventDefault()
    setEndpointState({ busy: true, error: '', result: null })
    try {
      const result = await claimRackEndpoint(
        token, endpointClaimPayload(endpointCode, trainingGroup, displayName),
      )
      setEndpointCode('')
      setDisplayName('')
      setEndpointState({ busy: false, error: '', result })
    } catch (error) {
      if (error.status === 401 || error.status === 403) onAuthLost()
      setEndpointState({ busy: false, error: endpointClaimErrorMessage(error), result: null })
    }
  }

  async function confirmHelper(event) {
    event.preventDefault()
    setHelperState({ busy: true, error: '', result: null })
    try {
      const result = await confirmRackHelper(token, helperPairingId(helperCode))
      setHelperCode('')
      setPhraseConfirmed(false)
      setHelperState({ busy: false, error: '', result })
    } catch (error) {
      if (error.status === 401 || error.status === 403) onAuthLost()
      setHelperState({ busy: false, error: helperConfirmationErrorMessage(error), result: null })
    }
  }

  return (
    <main className="coach-pairing-main">
      <header className="coach-pairing-heading">
        <div><span>Hosted Rack setup</span><h1>Connect a Rack endpoint</h1></div>
        <p>Claim a browser for one TrainingGroup, then approve its Rack Helper after comparing both six-word phrases.</p>
      </header>

      <div className="coach-pairing-grid">
        <form className="coach-pairing-card" onSubmit={claimEndpoint}>
          <div className="coach-pairing-step">01</div>
          <span className="coach-pairing-kicker">Browser identity</span>
          <h2>Claim endpoint</h2>
          <p>Enter the eight-character code shown on the hosted Rack.</p>
          <label htmlFor="endpoint-code">Endpoint code</label>
          <input id="endpoint-code" value={endpointCode} onChange={(event) => setEndpointCode(event.target.value.toUpperCase())} autoComplete="off" autoCapitalize="characters" maxLength="8" pattern="[0-9A-HJ-KM-NP-TV-Z]{8}" placeholder="ABCDEFGH" required />
          <label htmlFor="endpoint-group">TrainingGroup</label>
          <select id="endpoint-group" value={trainingGroup} onChange={(event) => setTrainingGroup(event.target.value)} disabled={loadingGroups} required>
            <option value="">{loadingGroups ? 'Loading TrainingGroups...' : 'Select TrainingGroup'}</option>
            {groups.map((group) => <option value={group.id} key={group.id}>{group.name}</option>)}
          </select>
          <label htmlFor="endpoint-label">Rack label</label>
          <input id="endpoint-label" value={displayName} onChange={(event) => setDisplayName(event.target.value)} maxLength="80" placeholder="Rack 3" required />
          {endpointState.error && <p className="coach-pairing-error" role="alert">{endpointState.error}</p>}
          {endpointState.result && <p className="coach-pairing-success" role="status"><strong>{endpointState.result.endpoint.display_name}</strong> is claimed for {endpointState.result.endpoint.training_group.name}.</p>}
          <button disabled={endpointState.busy || loadingGroups}>{endpointState.busy ? 'Claiming...' : 'Claim Rack endpoint'}</button>
        </form>

        <form className="coach-pairing-card" onSubmit={confirmHelper}>
          <div className="coach-pairing-step">02</div>
          <span className="coach-pairing-kicker">Helper trust</span>
          <h2>Confirm Rack Helper</h2>
          <p>Use the pairing ID shown with the Rack’s Helper code. Confirm only while both screens show the same six words.</p>
          <label htmlFor="helper-code">Helper pairing ID</label>
          <input id="helper-code" value={helperCode} onChange={(event) => setHelperCode(event.target.value)} autoComplete="off" spellCheck="false" placeholder="00000000-0000-0000-0000-000000000000" required />
          <label className="coach-pairing-check" htmlFor="phrase-confirmed">
            <input id="phrase-confirmed" type="checkbox" checked={phraseConfirmed} onChange={(event) => setPhraseConfirmed(event.target.checked)} required />
            <span>I compared all six words on the Rack and Helper, and they exactly match.</span>
          </label>
          {helperState.error && <p className="coach-pairing-error" role="alert">{helperState.error}</p>}
          {helperState.result && <p className="coach-pairing-success" role="status">Helper confirmed. Activation is available until {new Date(helperState.result.activation_expires_at).toLocaleString()}.</p>}
          <button disabled={helperState.busy || !phraseConfirmed}>{helperState.busy ? 'Confirming...' : 'Confirm Rack Helper'}</button>
        </form>
      </div>
    </main>
  )
}

function PairingLogin({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event) {
    event.preventDefault()
    setBusy(true); setError('')
    try { onLogin(await coachLogin(username, password)) }
    catch (requestError) { setError(requestError.message) }
    finally { setBusy(false) }
  }

  return <main className="coach-pairing-login"><form onSubmit={submit}><span>Coach authentication</span><h1>Sign in to pair a Rack</h1><label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label><label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required /></label>{error && <p role="alert">{error}</p>}<button disabled={busy}>{busy ? 'Signing in...' : 'Continue'}</button></form></main>
}

export default function CoachRackPairing({ showCoachWorkspace = true }) {
  const [token, setToken] = useState(() => getCoachToken())
  const [groups, setGroups] = useState([])
  const [groupError, setGroupError] = useState('')
  const [loadingGroups, setLoadingGroups] = useState(Boolean(token))

  function logout() {
    setCoachToken(null)
    setToken(null)
  }

  useEffect(() => {
    if (!token) return
    let active = true
    setLoadingGroups(true); setGroupError('')
    getCoachTrainingGroups(token).then((result) => { if (active) setGroups(result) }).catch((error) => {
      if (!active) return
      if (error.status === 401 || error.status === 403) logout()
      else setGroupError(error.message)
    }).finally(() => { if (active) setLoadingGroups(false) })
    return () => { active = false }
  }, [token])

  if (!token) return <PairingLogin onLogin={setToken} />
  return <div className="coach-pairing-root"><nav className="coach-pairing-nav" aria-label="Rack pairing navigation">{showCoachWorkspace && <button onClick={() => navigate('/coach')}>Back to coach workspace</button>}<button onClick={logout}>Log out</button></nav>{groupError && <p className="coach-pairing-load-error" role="alert">{groupError}</p>}<RackPairingWorkspace token={token} groups={groups} loadingGroups={loadingGroups} onAuthLost={logout} /></div>
}
