import { useEffect, useRef, useState } from 'react'
import {
  webBluetoothCapability,
  WitMotionFrameDecoder,
} from './witMotion.js'
import { WitMotionConnection } from './witMotionConnection.js'

const EMPTY_METRICS = {
  samples: 0,
  rejectedBytes: 0,
  rateHz: 0,
  sampleAgeMs: null,
  latest: null,
}
const MAX_COUNTER = 999_999_999

function Vector({ label, values, unit }) {
  return (
    <div className="ble-lab-vector">
      <span>{label}</span>
      <div>{['X', 'Y', 'Z'].map((axis, index) => (
        <p key={axis}><b>{axis}</b><strong>{values ? values[index].toFixed(3) : '--'}</strong><small>{unit}</small></p>
      ))}</div>
    </div>
  )
}

export default function BleLab() {
  const capability = webBluetoothCapability()
  const [state, setState] = useState(capability.supported ? 'idle' : 'unsupported')
  const [message, setMessage] = useState(capability.reason)
  const [metrics, setMetrics] = useState(EMPTY_METRICS)
  const connectionRef = useRef(null)
  const liveRef = useRef({ ...EMPTY_METRICS, windowSamples: 0, windowStartedAt: performance.now() })

  function closeConnection(nextState = 'idle', nextMessage = '') {
    const connection = connectionRef.current
    connectionRef.current = null
    connection?.disconnect()
    setState(nextState)
    setMessage(nextMessage)
  }

  useEffect(() => {
    const timer = window.setInterval(() => {
      const current = liveRef.current
      const now = performance.now()
      const elapsed = now - current.windowStartedAt
      const sampleReference = current.lastSampleAt ?? current.connectedAt
      const age = sampleReference == null ? null : Math.round(now - sampleReference)
      if (elapsed >= 1000) {
        current.rateHz = current.windowSamples / (elapsed / 1000)
        current.windowSamples = 0
        current.windowStartedAt = now
      }
      if (connectionRef.current && current.monitoring && age != null && age >= 2000) {
        setState('stalled')
        setMessage('No valid WT901 frame received for two seconds.')
      }
      setMetrics({
        samples: current.samples,
        rejectedBytes: current.rejectedBytes,
        rateHz: current.rateHz,
        sampleAgeMs: age,
        latest: current.latest,
      })
    }, 250)
    return () => {
      window.clearInterval(timer)
      const connection = connectionRef.current
      connectionRef.current = null
      connection?.disconnect()
    }
  }, [])

  async function connect() {
    if (!capability.supported || state === 'selecting' || state === 'connecting') return
    closeConnection('selecting', 'Choose the WT901 device in the browser prompt.')
    const connection = new WitMotionConnection(navigator.bluetooth)
    connectionRef.current = connection
    const decoder = new WitMotionFrameDecoder()
    liveRef.current = {
      ...EMPTY_METRICS,
      connectedAt: null,
      lastSampleAt: null,
      monitoring: false,
      windowSamples: 0,
      windowStartedAt: performance.now(),
    }
    try {
      setState('connecting')
      setMessage('Connecting to the WT901 notification service...')
      const connected = await connection.connect({
        onValue(event) {
          const samples = decoder.feed(event.target.value)
          liveRef.current.rejectedBytes = Math.min(MAX_COUNTER, decoder.rejectedBytes)
          if (!samples.length) return
          liveRef.current.connectedAt ??= performance.now()
          liveRef.current.lastSampleAt = performance.now()
          liveRef.current.samples = Math.min(MAX_COUNTER, liveRef.current.samples + samples.length)
          liveRef.current.windowSamples = Math.min(MAX_COUNTER, liveRef.current.windowSamples + samples.length)
          liveRef.current.latest = samples.at(-1)
          setState('live')
          setMessage('Receiving local WT901 notifications. Edge Athlete does not upload this stream.')
        },
        onDisconnect() {
          connectionRef.current = null
          setState('disconnected')
          setMessage('The sensor disconnected. Use Connect WT901 to choose it again.')
        },
      })
      if (!connected || connectionRef.current !== connection) return
      liveRef.current.connectedAt = performance.now()
      liveRef.current.monitoring = true
      if (liveRef.current.samples === 0) {
        setState('waiting')
        setMessage('Connected. Waiting for a valid WT901 frame...')
      }
    } catch (error) {
      if (connectionRef.current !== connection) return
      const cancelled = error?.name === 'NotFoundError'
      closeConnection(cancelled ? 'idle' : 'error', cancelled
        ? 'No device selected.'
        : 'Could not read the WT901 notification service. Confirm the device is nearby and not connected elsewhere.')
    }
  }

  const connected = ['waiting', 'live', 'stalled'].includes(state)
  return (
    <main className="ble-lab">
      <header>
        <div><span>Edge Athlete Research</span><h1>BLE Signal Bench</h1></div>
        <b className={`ble-lab-status ${state}`}>{state}</b>
      </header>

      <section className="ble-lab-intro">
        <div>
          <span>WT901 browser feasibility</span>
          <h2>Measure the link before moving the rack.</h2>
          <p>This page tests FFE4 notifications directly in your browser. It does not authenticate or enroll a sensor, assign a rack, detect reps, save packets, or contact an Edge Athlete API.</p>
        </div>
        <aside>
          <strong>Local-only boundary</strong>
          <p>Edge Athlete does not display, store, log, or transmit raw frames, Bluetooth identifiers, or sensor labels. Your browser may retain Bluetooth permission until you revoke it.</p>
        </aside>
      </section>

      <section className="ble-lab-controls">
        <button onClick={connect} disabled={!capability.supported || state === 'selecting' || state === 'connecting'}>
          {connected ? 'Choose another WT901' : 'Connect WT901'}
        </button>
        {connected && <button className="secondary" onClick={() => closeConnection()}>Disconnect</button>}
        <p role={state === 'error' ? 'alert' : 'status'}>{message || 'Ready for a user-initiated Bluetooth connection.'}</p>
      </section>

      <section className="ble-lab-metrics" aria-live="polite">
        <article><span>Decoded samples</span><strong>{metrics.samples.toLocaleString()}</strong></article>
        <article><span>Current rate</span><strong>{metrics.rateHz.toFixed(1)}<small> Hz</small></strong></article>
        <article><span>Sample age</span><strong>{metrics.sampleAgeMs == null ? '--' : metrics.sampleAgeMs}<small> ms</small></strong></article>
        <article><span>Rejected bytes</span><strong>{metrics.rejectedBytes.toLocaleString()}</strong></article>
      </section>

      <section className="ble-lab-vectors">
        <Vector label="Acceleration" values={metrics.latest?.accelerationG} unit="g" />
        <Vector label="Angular velocity" values={metrics.latest?.angularVelocityDps} unit="deg/s" />
        <Vector label="Orientation" values={metrics.latest?.angleDegrees} unit="deg" />
      </section>

      <footer>
        Supported target: Chromium browser over HTTPS. Firefox, Safari, sleep/background behavior, and the physical sample rate remain qualification evidence, not assumptions.
      </footer>
    </main>
  )
}
