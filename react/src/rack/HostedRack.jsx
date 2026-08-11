import { useEffect, useRef, useState } from 'react'
import {
  bootstrapRackCsrf, createEndpointPairing, createHelperPairing, createLaunchIntent,
  getHostedRackStatus, HostedRackApiError, inspectEndpointPairing, inspectHelperPairing,
  inspectLaunchIntent,
} from './hostedApi.js'
import { helperPresentation, runLaunchAttempt } from './hostedControlPlane.js'
import './HostedRack.css'

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds))

function formatTime(value) {
  if (!value) return 'Not reported'
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? 'Not reported' : parsed.toLocaleString()
}

export function EndpointPairingPanel({ pairing, busy, error, onStart }) {
  if (!pairing) {
    return (
      <section className="hosted-rack-card hosted-rack-pairing">
        <span className="hosted-rack-kicker">Rack identity</span>
        <h2>Pair this browser</h2>
        <p>A coach must assign this browser to one TrainingGroup before it can control a Helper.</p>
        {error && <p className="hosted-rack-error" role="alert">{error}</p>}
        <button className="hosted-rack-primary" disabled={busy} onClick={onStart}>
          {busy ? 'Creating code...' : 'Create pairing code'}
        </button>
      </section>
    )
  }
  return (
    <section className="hosted-rack-card hosted-rack-pairing">
      <span className="hosted-rack-kicker">Pairing code</span>
      <strong className="hosted-rack-code">{pairing.pairing_code}</strong>
      <p>On an authenticated coach screen, claim this code, choose the TrainingGroup, and name the Rack.</p>
      <dl className="hosted-rack-meta">
        <div><dt>Status</dt><dd>Waiting for coach</dd></div>
        <div><dt>Expires</dt><dd>{formatTime(pairing.expires_at)}</dd></div>
      </dl>
      {error && <p className="hosted-rack-error" role="alert">{error}</p>}
    </section>
  )
}

export function HelperStatusPanel({ helper, attempt, disabled, onLaunch }) {
  const view = helperPresentation(helper?.status)
  const localState = attempt?.state
  return (
    <section className={`hosted-rack-card hosted-helper-status tone-${view.tone}`}>
      <header>
        <div>
          <span className="hosted-rack-kicker">Rack Helper</span>
          <h2>{localState === 'pending' ? 'Waiting for Helper' : view.label}</h2>
        </div>
        <span className="hosted-helper-chip">{helper?.freshness || 'not applicable'}</span>
      </header>
      <p>{view.detail}</p>
      <dl className="hosted-rack-meta">
        <div><dt>Last cloud check-in</dt><dd>{formatTime(helper?.status_at)}</dd></div>
        <div><dt>Status cursor</dt><dd>{helper?.status_cursor ?? 'Not available'}</dd></div>
      </dl>
      {attempt?.state === 'unconfirmed' && (
        <div className="hosted-launch-warning" role="status">
          <strong>Rack Helper has not checked in.</strong>
          <p>It may not be installed, may be blocked by the operating system, or may still be starting.</p>
          <p>If Rack Helper opened and asks to pair, continue setup.</p>
        </div>
      )}
      {attempt?.state === 'error' && <p className="hosted-rack-error" role="alert">{attempt.message}</p>}
      {view.action && (
        <button className="hosted-rack-primary" disabled={disabled || localState === 'pending'} onClick={onLaunch}>
          {localState === 'unconfirmed' ? 'Try Launch Helper Again' : view.action.label}
        </button>
      )}
      {!view.action && <p className="hosted-no-action">This transition must finish before another launch request.</p>}
    </section>
  )
}

export function DevelopmentPackageGuidance() {
  return (
    <section className="hosted-rack-card hosted-dev-guidance">
      <span className="hosted-rack-kicker">Development runtime</span>
      <h3>No verified package is published</h3>
      <p>This backend does not provide an approved release catalog, so this page offers no download.</p>
      <p>Development use is limited to the team-managed CPython 3.12 locked environment on Linux x64 or Windows x64 with OS keyring storage. Do not use unsigned downloads, disable operating-system checks, or store Helper credentials in files or environment variables.</p>
    </section>
  )
}

export function HelperPairingPanel({ pairing, busy, error, onStart }) {
  return (
    <section className="hosted-rack-card hosted-helper-pairing">
      <span className="hosted-rack-kicker">First-time Helper setup</span>
      <h3>{pairing ? 'Compare before confirming' : 'Pair a development Helper'}</h3>
      {!pairing && <p>Create a short-lived code, then enter it in the inert Helper window.</p>}
      {pairing && (
        <>
          <strong className="hosted-rack-code">{pairing.pairing_code}</strong>
          <div className="hosted-helper-pairing-id">
            <span>Coach confirmation ID</span>
            <code>{pairing.pairing_id}</code>
          </div>
          {pairing.confirmation_phrase?.length === 6 ? (
            <div className="hosted-helper-phrase" aria-label="Helper confirmation phrase">
              {pairing.confirmation_phrase.map((word, index) => <span key={`${index}-${word}`}>{word}</span>)}
            </div>
          ) : <p>Waiting for the Helper to claim this code.</p>}
          <p>Confirm only when these six words exactly match the Helper. A coach completes confirmation from the authenticated coach workflow.</p>
        </>
      )}
      {error && <p className="hosted-rack-error" role="alert">{error}</p>}
      {!pairing && <button className="hosted-rack-secondary" disabled={busy} onClick={onStart}>{busy ? 'Creating code...' : 'Pair Helper'}</button>}
    </section>
  )
}

export default function HostedRack() {
  const [phase, setPhase] = useState('loading')
  const [snapshot, setSnapshot] = useState(null)
  const [endpointPairing, setEndpointPairing] = useState(null)
  const [helperPairing, setHelperPairing] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [launchAttempt, setLaunchAttempt] = useState(null)
  const active = useRef(true)
  const launchPending = useRef(false)

  async function refreshStatus() {
    const next = await getHostedRackStatus()
    if (active.current) { setSnapshot(next); setPhase('ready'); setError('') }
    return next
  }

  useEffect(() => {
    active.current = true
    bootstrapRackCsrf().then(refreshStatus).catch((requestError) => {
      if (!active.current) return
      if (requestError instanceof HostedRackApiError && requestError.status === 401) setPhase('unpaired')
      else { setPhase('error'); setError(requestError.message) }
    })
    return () => { active.current = false }
  }, [])

  useEffect(() => {
    if (phase !== 'ready') return undefined
    const timer = setInterval(() => refreshStatus().catch((requestError) => {
      if (!active.current) return
      if (requestError instanceof HostedRackApiError && requestError.status === 401) {
        setSnapshot(null)
        setPhase('unpaired')
      } else {
        setError(requestError.message)
      }
    }), 5000)
    return () => clearInterval(timer)
  }, [phase])

  async function startEndpointPairing() {
    if (busy) return
    setBusy(true); setError('')
    try {
      const pairing = await createEndpointPairing()
      if (!active.current) return
      setEndpointPairing(pairing)
      let current = pairing
      while (active.current && current.state !== 'paired') {
        await sleep((current.poll_after_seconds || 2) * 1000)
        current = await inspectEndpointPairing()
      }
      if (active.current) await refreshStatus()
    } catch (requestError) {
      if (active.current) {
        if (requestError instanceof HostedRackApiError && requestError.code === 'pairing_expired') {
          setEndpointPairing(null)
        }
        setError(requestError.message)
      }
    } finally {
      if (active.current) setBusy(false)
    }
  }

  async function startHelperPairing() {
    if (busy) return
    setBusy(true); setError('')
    try {
      const created = await createHelperPairing()
      if (!active.current) return
      setHelperPairing(created)
      let current = created
      while (active.current && current.state !== 'activated') {
        await sleep(2000)
        current = await inspectHelperPairing(created.pairing_id)
        if (active.current) setHelperPairing({ ...created, ...current })
      }
      if (active.current) await refreshStatus()
    } catch (requestError) {
      if (active.current) {
        if (requestError instanceof HostedRackApiError && requestError.code === 'pairing_expired') {
          setHelperPairing(null)
        }
        setError(requestError.message)
      }
    } finally {
      if (active.current) setBusy(false)
    }
  }

  async function launchHelper() {
    if (launchPending.current) return
    launchPending.current = true
    setLaunchAttempt({ state: 'pending' })
    try {
      const result = await runLaunchAttempt({
        create: createLaunchIntent,
        inspect: inspectLaunchIntent,
        invoke: (uri) => { window.location.href = uri },
        wait: sleep,
      })
      if (!active.current) return
      setLaunchAttempt(result)
      await refreshStatus().catch(() => {})
    } catch (requestError) {
      if (active.current) setLaunchAttempt({ state: 'error', message: requestError.message })
    } finally {
      launchPending.current = false
    }
  }

  if (phase === 'loading') return <main className="hosted-rack hosted-rack-loading"><p>Connecting to Rack control plane...</p></main>
  if (phase === 'unpaired') return <main className="hosted-rack"><EndpointPairingPanel pairing={endpointPairing} busy={busy} error={error} onStart={startEndpointPairing} /></main>
  if (phase === 'error') return (
    <main className="hosted-rack">
      <section className="hosted-rack-card hosted-rack-pairing">
        <span className="hosted-rack-kicker">Rack control plane</span>
        <h2>Connection unavailable</h2>
        <p className="hosted-rack-error" role="alert">{error}</p>
        <button className="hosted-rack-primary" onClick={() => window.location.reload()}>Retry connection</button>
      </section>
    </main>
  )

  const endpoint = snapshot?.endpoint
  return (
    <main className="hosted-rack">
      <header className="hosted-rack-header">
        <div><span className="hosted-rack-brand">Edge Athlete</span><h1>{endpoint?.display_name || 'Hosted Rack'}</h1></div>
        <div className="hosted-rack-assignment"><span>TrainingGroup</span><strong>{endpoint?.training_group?.name || 'Unassigned'}</strong></div>
      </header>
      <div className="hosted-rack-grid">
        <HelperStatusPanel helper={snapshot?.helper} attempt={launchAttempt} disabled={busy} onLaunch={launchHelper} />
        <div className="hosted-rack-side">
          {snapshot?.helper?.status === 'pairing_required' && <HelperPairingPanel pairing={helperPairing} busy={busy} error={error} onStart={startHelperPairing} />}
          <DevelopmentPackageGuidance />
        </div>
      </div>
    </main>
  )
}
