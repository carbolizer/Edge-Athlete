import { useEffect, useState } from 'react'
import { getNodes, getRackNumber } from '../api/client.js'
import { coachFetch, coachLogin } from '../coach/api.js'
import { getDeviceId } from '../device.js'
import { navigate } from '../router.js'
import { Centered } from '../ui.jsx'
import { T } from '../theme.js'
import {
  assignedNodeForRack,
  assignedSensorLabel,
  bleSetupError,
  candidateLabel,
  isVerificationReady,
  normalizeBleCandidates,
} from './nodeSetup.js'
import { useRackAgentStatus } from './rackAgent.js'

const inputStyle = {
  width: '100%', padding: '13px 14px', borderRadius: 10, border: `1px solid ${T.line}`,
  background: T.panel, color: T.ink, font: 'inherit', boxSizing: 'border-box',
}

const buttonStyle = {
  padding: '13px 18px', borderRadius: 10, border: 'none', background: T.lime,
  color: '#0a1106', fontWeight: 850, cursor: 'pointer', fontFamily: 'inherit',
}

const secondaryButtonStyle = {
  ...buttonStyle, background: T.panel, color: T.ink, border: `1px solid ${T.line}`,
}

export default function RackNodeSetup({ rackNumber, onReady, onObserve }) {
  const [status, setStatus] = useState('loading')
  const [currentNode, setCurrentNode] = useState(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [coachToken, setCoachToken] = useState(null)
  const [candidates, setCandidates] = useState([])
  const [selectedCandidate, setSelectedCandidate] = useState(null)
  const [verification, setVerification] = useState(null)
  const [error, setError] = useState('')
  // Wi-Fi sensors this rack could take. Bluetooth has to be discovered by
  // scanning; an MQTT sensor already announced its own name, so it is just a
  // list — which is the whole reason the two paths look different below.
  const [wifiNodes, setWifiNodes] = useState([])
  const [linkingNodeId, setLinkingNodeId] = useState(null)
  const agent = useRackAgentStatus(currentNode, rackNumber)
  const deviceId = getDeviceId()

  async function load() {
    setStatus('loading')
    setError('')
    try {
      const [allNodes, assignment] = await Promise.all([getNodes(), getRackNumber(deviceId)])

      // RELEASED: this screen is assigned to no rack at all. Back to the waiting
      // list, which is the whole point of a coach pressing Remove screen.
      //
      // This has to be checked BEFORE the mismatch branch below, because the two
      // look identical to a `!==` test and want opposite outcomes. Released used
      // to fall through to that branch, and since the force-clear deliberately
      // LEAVES THE SENSOR on the rack, `assignedNodeForRack` still found a node —
      // so the tablet flipped to the read-only observer view for a rack it no
      // longer belonged to, and sat there cycling. A coach releasing a screen got
      // a screen that looked broken instead of one waiting to be reassigned.
      //
      // Clearing rack_number matters as much as navigating: Home() reads it on
      // every cold boot and would send the tablet straight back to /rack/N.
      if (assignment.rack_number == null) {
        localStorage.removeItem('rack_number')
        navigate('/rack/setup')
        return
      }

      // MISMATCH: still assigned, but to a DIFFERENT rack — someone else's screen
      // owns this one. Observing is the right answer here; there is a live rack in
      // front of you that this tablet may not drive.
      if (assignment.rack_number !== rackNumber) {
        const assigned = assignedNodeForRack(allNodes, rackNumber)
        if (assigned) onObserve(assigned)
        else setStatus('screen-mismatch')
        return
      }
      const assigned = assignedNodeForRack(allNodes, rackNumber)
      setCurrentNode(assigned)
      setWifiNodes((allNodes || []).filter(
        (n) => n.acquisition_kind !== 'wt901_ble'
          && (n.rack_number == null || n.rack_number === rackNumber),
      ))
      setStatus(assigned ? 'ready' : 'login')
    } catch {
      setError('The base station could not confirm this rack setup.')
      setStatus('error')
    }
  }

  useEffect(() => { load() }, [rackNumber])

  function resetSelection(nextStatus = 'scan-ready') {
    setCandidates([])
    setSelectedCandidate(null)
    setVerification(null)
    setStatus(nextStatus)
  }

  async function authenticate(event) {
    event.preventDefault()
    setStatus('authenticating')
    setError('')
    try {
      const token = await coachLogin(username.trim(), password, { persist: false })
      setCoachToken(token)
      setPassword('')
      resetSelection()
    } catch (err) {
      setPassword('')
      setError(err.message || 'Coach authentication failed.')
      setStatus('login')
    }
  }

  // Link a Wi-Fi sensor. Same endpoint the coach console uses, and the same one
  // the Bluetooth flow lands on after verification — so all three routes end at one
  // place that enforces the rules. Notably it UNASSIGNS whatever sensor this rack
  // had first, in the same transaction, which is what stops a rack from holding a
  // Bluetooth sensor and a Wi-Fi one at once.
  async function linkWifiNode(nodeId) {
    setLinkingNodeId(nodeId)
    setError('')
    try {
      await coachFetch('/api/racks/node-assignment/', {
        token: coachToken,
        method: 'PUT',
        body: { device_id: deviceId, node_id: nodeId },
      })
      await load()
    } catch (err) {
      setError(bleSetupError(err, 'The sensor could not be linked. Try again.'))
    } finally {
      setLinkingNodeId(null)
    }
  }

  async function scan() {
    setStatus('scanning')
    setError('')
    setCandidates([])
    setSelectedCandidate(null)
    setVerification(null)
    try {
      const result = await coachFetch('/api/ble/scans/', {
        token: coachToken,
        method: 'POST',
        body: {},
      })
      const nextCandidates = normalizeBleCandidates(result)
      setCandidates(nextCandidates)
      if (nextCandidates.length === 0) {
        setError('No nearby sensors were found. Move the sensor closer, wake it, and scan again.')
      }
      setStatus('candidates')
    } catch (err) {
      setError(bleSetupError(err, 'The sensor scan failed. Try again.'))
      setStatus('scan-ready')
    }
  }

  async function verify(candidate) {
    setSelectedCandidate(candidate)
    setVerification(null)
    setStatus('verifying')
    setError('')
    try {
      const result = await coachFetch('/api/ble/verifications/', {
        token: coachToken,
        method: 'POST',
        body: { device_handle: candidate.device_handle },
      })
      const nextVerification = result?.verification
        ? { ...result.verification, ...result }
        : result
      if (!isVerificationReady(nextVerification)) {
        throw new Error('Movement was not detected. Move the mounted sensor, then verify it again.')
      }
      setVerification(nextVerification)
      setStatus('verified')
    } catch (err) {
      const expired = ['scan_expired', 'device_handle_expired', 'unknown_device_handle'].includes(err?.code)
      setError(bleSetupError(err, 'Sensor verification failed. Try again.'))
      if (expired) resetSelection('scan-ready')
      else setStatus('candidates')
    }
  }

  async function assignVerified() {
    if (!isVerificationReady(verification)) return
    setStatus('assigning')
    setError('')
    try {
      const result = await coachFetch(`/api/racks/${encodeURIComponent(rackNumber)}/ble-selection/`, {
        token: coachToken,
        method: 'PUT',
        body: { device_id: deviceId, verification_token: verification.verification_token },
      })
      let assigned = result?.node || null
      if (!assigned) assigned = assignedNodeForRack(await getNodes(), rackNumber)
      if (!assigned) throw new Error('The rack assignment was accepted but could not be confirmed.')
      setCurrentNode(assigned)
      setCandidates([])
      setSelectedCandidate(null)
      setVerification(null)
      setCoachToken(null)
      setStatus('ready')
    } catch (err) {
      const expired = ['verification_expired', 'verification_token_expired'].includes(err?.code)
      setError(bleSetupError(err, 'Sensor assignment failed. Try again.'))
      if (expired) resetSelection('scan-ready')
      else setStatus('verified')
    }
  }

  function beginReplacement() {
    setUsername('')
    setPassword('')
    setCoachToken(null)
    resetSelection('login')
    setError('')
  }

  function cancelReplacement() {
    setCoachToken(null)
    setPassword('')
    resetSelection('ready')
    setError('')
  }

  if (status === 'loading') {
    return <Centered><div style={{ color: T.muted }}>Checking Rack {rackNumber} sensor...</div></Centered>
  }

  if (status === 'screen-mismatch') {
    return (
      <Centered>
        <h2 style={{ margin: '0 0 10px' }}>Rack assignment mismatch</h2>
        <p style={{ color: T.muted, maxWidth: 380, textAlign: 'center' }}>
          This screen is not assigned to Rack {rackNumber}. Return to setup before athlete sign-in.
        </p>
        <button style={buttonStyle} onClick={() => navigate('/rack/setup')}>Open rack setup</button>
      </Centered>
    )
  }

  if (status === 'error') {
    return (
      <Centered>
        <p role="alert" style={{ color: T.muted }}>{error}</p>
        <button style={buttonStyle} onClick={load}>Retry</button>
      </Centered>
    )
  }

  if (status === 'ready') {
    const agentReady = agent.ready
    const sensorLabel = assignedSensorLabel(currentNode, agent.health)
    return (
      <Centered>
        <div style={{ color: T.lime, fontSize: 11, fontWeight: 900, letterSpacing: '.14em', textTransform: 'uppercase' }}>
          Rack {rackNumber} sensor assigned
        </div>
        <div style={{ fontSize: 28, fontWeight: 750, margin: '14px 0 8px', textAlign: 'center' }}>
          {sensorLabel}
        </div>
        <p role="status" aria-live="polite" style={{ color: agentReady ? T.muted : T.amber, margin: '0 0 24px', textAlign: 'center' }}>
          {agentReady
            ? `Sensor live${agent.health?.movement_g != null && Number.isFinite(Number(agent.health.movement_g)) ? ` · ${Number(agent.health.movement_g).toFixed(3)} g movement` : ''}`
            : `Waiting for server sensor health (${agent.health?.state || 'checking'})`}
        </p>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', justifyContent: 'center' }}>
          <button disabled={!agentReady} style={{ ...buttonStyle, opacity: agentReady ? 1 : .45, cursor: agentReady ? 'pointer' : 'not-allowed' }}
            onClick={() => onReady(currentNode)}>Open check-in</button>
          <button style={secondaryButtonStyle} onClick={beginReplacement}>Replace sensor</button>
        </div>
      </Centered>
    )
  }

  if (status === 'login' || status === 'authenticating') {
    const disabled = status === 'authenticating' || !username.trim() || !password
    return (
      <Centered>
        <form onSubmit={authenticate} style={{ width: 'min(390px, calc(100vw - 40px))' }}>
          <div style={{ color: T.lime, fontSize: 11, fontWeight: 900, letterSpacing: '.14em', textTransform: 'uppercase' }}>
            Rack {rackNumber} setup required
          </div>
          <h2 style={{ margin: '10px 0 8px' }}>Authorize sensor setup</h2>
          <p style={{ color: T.muted, margin: '0 0 22px' }}>
            An active staff coach must authenticate before scanning nearby BLE sensors.
          </p>
          <div style={{ display: 'grid', gap: 12 }}>
            <input aria-label="Coach username" autoComplete="username" placeholder="Coach username"
              value={username} onChange={(event) => setUsername(event.target.value)} style={inputStyle} />
            <input aria-label="Coach password" autoComplete="current-password" type="password" placeholder="Password"
              value={password} onChange={(event) => setPassword(event.target.value)} style={inputStyle} />
            {error && <div role="alert" style={{ color: '#ff8b8b', fontSize: 13 }}>{error}</div>}
            <button type="submit" disabled={disabled} style={{ ...buttonStyle, opacity: disabled ? .45 : 1 }}>
              {status === 'authenticating' ? 'Authenticating...' : 'Continue to sensor scan'}
            </button>
            {currentNode && <button type="button" onClick={cancelReplacement} style={secondaryButtonStyle}>Cancel replacement</button>}
          </div>
        </form>
      </Centered>
    )
  }

  return (
    <Centered>
      <section aria-labelledby="ble-setup-heading" style={{ width: 'min(480px, calc(100vw - 40px))' }}>
        <div style={{ color: T.lime, fontSize: 11, fontWeight: 900, letterSpacing: '.14em', textTransform: 'uppercase' }}>
          Rack {rackNumber} sensor setup
        </div>
        <h2 id="ble-setup-heading" style={{ margin: '10px 0 8px' }}>
          {status === 'verified' || status === 'assigning' ? 'Confirm sensor assignment' : 'Choose this rack\'s sensor'}
        </h2>
        <p style={{ color: T.muted, margin: '0 0 20px' }}>
           {status === 'verified' || status === 'assigning'
             ? 'Confirm the movement below came from the sensor mounted at this rack.'
             : status === 'candidates' || status === 'verifying'
               ? 'Move the sensor mounted at this rack while verification runs, then choose Verify.'
               : 'Bluetooth sensors must be verified at the rack. Wi-Fi sensors can be linked directly.'}
        </p>

        {error && <div role="alert" style={{ color: '#ff8b8b', fontSize: 13, marginBottom: 14 }}>{error}</div>}

        {(status === 'scan-ready' || status === 'scanning') && (
          <>
            <button onClick={scan} disabled={status === 'scanning'} style={{ ...buttonStyle, width: '100%', opacity: status === 'scanning' ? .45 : 1 }}>
              {status === 'scanning' ? 'Scanning...' : 'Scan nearby Bluetooth sensors'}
            </button>

            {/* The Wi-Fi path. Deliberately a plain list with no verify step: an
                MQTT sensor told the base station its own name, so there is nothing
                to confirm by watching it move. Bluetooth needs that step because
                nearby radios are anonymous until you prove which one is yours.
                Linking either kind replaces whatever this rack already had. */}
            <div style={{ marginTop: 22 }}>
              <div style={{ color: T.muted, fontSize: 11, fontWeight: 900, letterSpacing: '.14em', textTransform: 'uppercase', marginBottom: 10 }}>
                Or link a Wi-Fi sensor
              </div>
              {wifiNodes.length === 0 ? (
                <p style={{ color: T.muted, fontSize: 13, margin: 0 }}>
                  No Wi-Fi sensors are registered and free. One appears here once it
                  has reported to the base station.
                </p>
              ) : (
                <div style={{ display: 'grid', gap: 10 }}>
                  {wifiNodes.map((n) => (
                    <div key={n.node_id} style={{ padding: 14, borderRadius: 10, border: `1px solid ${T.line}`, background: T.panel }}>
                      <div style={{ fontWeight: 800 }}>{n.node_id}</div>
                      <div style={{ color: T.muted, fontSize: 12, margin: '5px 0 12px' }}>
                        {n.rack_number === rackNumber ? 'Already on this rack' : 'Wi-Fi · unassigned'}
                      </div>
                      <button
                        onClick={() => linkWifiNode(n.node_id)}
                        disabled={linkingNodeId != null || n.rack_number === rackNumber}
                        aria-label={`Link ${n.node_id} to rack ${rackNumber}`}
                        style={{ ...buttonStyle, padding: '10px 14px', opacity: (linkingNodeId != null || n.rack_number === rackNumber) ? .45 : 1 }}>
                        {linkingNodeId === n.node_id ? 'Linking...' : 'Link'}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {(status === 'candidates' || status === 'verifying') && (
          <div style={{ display: 'grid', gap: 10 }}>
            {candidates.map((candidate) => {
              const isVerifying = status === 'verifying' && selectedCandidate?.device_handle === candidate.device_handle
              return (
                <div key={candidate.device_handle} style={{ padding: 14, borderRadius: 10, border: `1px solid ${T.line}`, background: T.panel }}>
                  <div style={{ fontWeight: 800 }}>{candidateLabel(candidate, candidates)}</div>
                  <div style={{ color: T.muted, fontSize: 12, margin: '5px 0 12px' }}>
                    {candidate.rssi == null ? 'Discovered nearby' : `${candidate.rssi} dBm signal`}
                  </div>
                  <button onClick={() => verify(candidate)} disabled={status === 'verifying'}
                    aria-label={`Verify ${candidateLabel(candidate, candidates)}`}
                    style={{ ...buttonStyle, padding: '10px 14px', opacity: status === 'verifying' ? .45 : 1 }}>
                    {isVerifying ? 'Verifying movement...' : 'Verify'}
                  </button>
                </div>
              )
            })}
            <button onClick={scan} disabled={status === 'verifying'} style={secondaryButtonStyle}>Scan again</button>
          </div>
        )}

        {(status === 'verified' || status === 'assigning') && selectedCandidate && verification && (
          <div style={{ padding: 18, borderRadius: 12, border: `1px solid ${T.lime}`, background: T.panel }}>
            <div style={{ fontWeight: 850, fontSize: 20 }}>{candidateLabel(selectedCandidate, candidates)}</div>
            <div role="status" style={{ color: T.lime, margin: '10px 0 18px', fontWeight: 750 }}>
              Verified movement: {Number(verification.movement_g).toFixed(3)} g
            </div>
            <button onClick={assignVerified} disabled={status === 'assigning'}
              style={{ ...buttonStyle, width: '100%', opacity: status === 'assigning' ? .45 : 1 }}>
              {status === 'assigning' ? 'Assigning...' : `Assign to Rack ${rackNumber}`}
            </button>
            <button onClick={() => { setVerification(null); setStatus('candidates') }} disabled={status === 'assigning'}
              style={{ ...secondaryButtonStyle, width: '100%', marginTop: 10 }}>Choose another sensor</button>
          </div>
        )}

        {currentNode && status !== 'assigning' && (
          <button onClick={cancelReplacement} style={{ ...secondaryButtonStyle, width: '100%', marginTop: 12 }}>
            Cancel replacement
          </button>
        )}
      </section>
    </Centered>
  )
}
