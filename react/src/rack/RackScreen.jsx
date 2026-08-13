// rack/RackScreen.jsx — the rack's set-lifecycle state machine.
//
// ── WHY THIS FILE EXISTS (plain version) ───────────────────────────────────────
// This screen walks one athlete through one set at a time. At any moment it is in
// exactly ONE of five named modes, and they run in a loop:
//
//     idle → countdown → active → summary → rest → (back to idle)
//
// That "always exactly one mode" idea is the state machine. Each mode knows what
// to show and which button or timer moves to the next one. Keeping it this strict
// is what stops the screen from getting into confusing half-states.
//
// ── WHAT'S BUILT SO FAR ─────────────────────────────────────────────────────────
// The state-machine skeleton (Step 1) plus the real IDLE screen (Step 2): the
// athlete check-in + day-view picker (see Idle.jsx), which fetches the selected
// athlete's live progress and hands the chosen movement to the countdown. The
// remaining modes are still placeholders, coming next:
//   • the live MQTT rep stream + buffer  (Step 3, fills the active mode)
//   • saving + completing the set on the server  (Step 4)
//   • the real rest timer behaviour  (Step 5)
//
// Styling matches the team's `.monitor` design system (see theme.js).

import { useCallback, useEffect, useRef, useState } from 'react'
import { getAthleteProgress, getActiveSession, getRackHotList, checkInAthlete, consumeNfcTap, createSet, completeSet, getSessionStatus } from '../api/client.js'
import { subscribeNodeReps } from '../mqtt/client.js'
import { addRep, clearBuffer, getBufferedReps } from '../db/repBuffer.js'
import { velocityColor, VELOCITY_HEX } from './velocity.js'
import Idle from './Idle.jsx'
import CheckInList from './CheckInList.jsx'
import WeightPad from './WeightPad.jsx'
import { controllerCommand } from './controller.js'
import { T } from '../theme.js'
import { useRackAgentStatus } from './rackAgent.js'
import { handleNfcPollResult, pollLocalNfcTap } from './nfc.js'

const REST_SECONDS = 120 // default rest between sets (real behaviour lands in Step 5)

// A tiny uppercase, wide-tracked micro-label — the `.monitor` label treatment.
const LABEL = {
  fontSize: 10, fontWeight: 900, letterSpacing: '.14em',
  textTransform: 'uppercase', color: T.muted,
}

// One reusable button in the team style. `tone` picks the accent.
function Button({ children, onClick, tone = 'primary' }) {
  const tones = {
    primary: { bg: T.lime, fg: '#0a0f07', border: T.lime },
    ghost: { bg: T.panel, fg: T.ink, border: T.line },
    danger: { bg: 'transparent', fg: T.coral, border: T.coral + '66' },
  }
  const s = tones[tone] || tones.primary
  return (
    <button onClick={onClick}
      style={{ padding: '15px 20px', fontSize: 15, fontWeight: 800, borderRadius: 12,
        border: `1px solid ${s.border}`, background: s.bg, color: s.fg,
        cursor: 'pointer', fontFamily: 'inherit', letterSpacing: '-.01em', width: '100%' }}>
      {children}
    </button>
  )
}

// The little status pill in the top bar, colored per phase so the mode is obvious.
const PHASE_BADGE = {
  idle:      { text: 'idle',     color: T.muted },
  countdown: { text: 'starting', color: T.amber },
  active:    { text: 'lifting',  color: T.mint },
  summary:   { text: 'complete', color: T.lime },
  rest:      { text: 'resting',  color: T.muted },
}

// ─────────────────────────── the five phases ───────────────────────────
// idle is now the real day-view picker (Idle.jsx); the rest are placeholders that
// real content arrives in over Steps 3–5.

function CountdownPhase({ onDone }) {
  const [n, setN] = useState(3)
  useEffect(() => {
    if (n <= 0) { const t = setTimeout(onDone, 350); return () => clearTimeout(t) }
    const t = setTimeout(() => setN((v) => v - 1), 1000)
    return () => clearTimeout(t)
  }, [n, onDone])
  return (
    <PhaseBody>
      <div style={{ ...LABEL, marginBottom: 18 }}>Get ready</div>
      <div style={{ fontSize: 150, fontWeight: 800, lineHeight: 1, letterSpacing: '-.06em',
        color: T.ink, fontVariantNumeric: 'tabular-nums' }}>
        {n > 0 ? n : 'GO'}
      </div>
    </PhaseBody>
  )
}

function ActivePhase({ movementName, repCount, lastVelocity, lastColor, sensorMovementG, sensorState, onEnd, onFalseSet }) {
  const hex = VELOCITY_HEX[lastColor]
  const hasSensorMovement = sensorMovementG != null && Number.isFinite(Number(sensorMovementG))
  return (
    <PhaseBody>
      {movementName && <div style={{ ...LABEL, color: T.lime, marginBottom: 8 }}>{movementName}</div>}
      <div style={{ ...LABEL, marginBottom: 10 }}>Reps this set</div>
      <div style={{ fontSize: 128, fontWeight: 800, lineHeight: 0.9, letterSpacing: '-.06em',
        fontVariantNumeric: 'tabular-nums', color: T.ink }}>{repCount}</div>

      {/* latest rep's velocity + its green/yellow/red read against the movement's zone */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 26, marginBottom: 34 }}>
        <div style={{ fontSize: 44, fontWeight: 800, color: hex, letterSpacing: '-.05em',
          fontVariantNumeric: 'tabular-nums' }}>
          {lastVelocity == null ? '—' : lastVelocity.toFixed(2)}
          <span style={{ fontSize: 13, fontWeight: 700, color: T.muted, marginLeft: 5 }}>m/s</span>
        </div>
        <span style={{ fontSize: 11, fontWeight: 900, textTransform: 'uppercase', letterSpacing: '.1em',
          padding: '6px 12px', borderRadius: 999, background: hex + '22', color: hex }}>{lastColor}</span>
      </div>

      <div style={{ width: '100%', padding: 14, borderRadius: 12, border: `1px solid ${T.line}`,
        background: T.panel, marginBottom: 16, textAlign: 'center' }}>
        <div style={{ ...LABEL, marginBottom: 6 }}>WT901 movement</div>
        <div style={{ fontSize: 24, fontWeight: 850, letterSpacing: '-.03em', color: T.mint,
          fontVariantNumeric: 'tabular-nums' }}>
          {hasSensorMovement ? Number(sensorMovementG).toFixed(3) : '—'}
          <span style={{ fontSize: 12, fontWeight: 800, color: T.muted, marginLeft: 5 }}>g</span>
        </div>
        <div style={{ color: T.muted, fontSize: 11, marginTop: 6 }}>
          {sensorState === 'live'
            ? 'Diagnostic motion only. Rep counting is not enabled yet.'
            : `Sensor ${sensorState || 'checking'}`}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: '100%' }}>
        <Button onClick={onEnd} tone="ghost">End Set</Button>
        <Button onClick={onFalseSet} tone="danger">False Set</Button>
      </div>
    </PhaseBody>
  )
}

function SummaryPhase({ summary, onRest }) {
  const stat = (label, val) => (
    <div style={{ textAlign: 'center' }}>
      <div style={{ ...LABEL, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 40, fontWeight: 800, letterSpacing: '-.04em', color: T.mint,
        fontVariantNumeric: 'tabular-nums' }}>
        {val == null ? '—' : val.toFixed(2)}
        <span style={{ fontSize: 13, fontWeight: 700, color: T.muted, marginLeft: 4 }}>m/s</span>
      </div>
    </div>
  )
  return (
    <PhaseBody>
      <div style={{ ...LABEL, marginBottom: 6 }}>Set complete</div>
      <div style={{ fontSize: 30, fontWeight: 850, letterSpacing: '-.03em', marginBottom: 32 }}>
        {summary?.reps ?? 0} reps
      </div>
      <div style={{ display: 'flex', gap: 40, marginBottom: 44 }}>
        {stat('Avg', summary?.avg)}
        {stat('Peak', summary?.peak)}
      </div>
      <Button onClick={onRest}>Start Rest Timer</Button>
    </PhaseBody>
  )
}

function RestPhase({ onDone, movementName, nextSetNumber, roster, hotList, groupName, statusMap, onSelectAthlete }) {
  const [secs, setSecs] = useState(REST_SECONDS)
  useEffect(() => {
    if (secs <= 0) { onDone(); return }
    const t = setTimeout(() => setSecs((v) => v - 1), 1000)
    return () => clearTimeout(t)
  }, [secs, onDone])
  const mm = Math.floor(secs / 60)
  const ss = String(secs % 60).padStart(2, '0')
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '22px 22px 32px', width: '100%',
      maxWidth: 460, margin: '0 auto', display: 'flex', flexDirection: 'column' }}>
      {/* the resting athlete's timer + what's up next + continue */}
      <div style={{ textAlign: 'center' }}>
        <div style={{ ...LABEL, marginBottom: 10 }}>Rest</div>
        <div style={{ fontSize: 84, fontWeight: 800, letterSpacing: '-.05em', color: T.ink,
          fontVariantNumeric: 'tabular-nums', marginBottom: 10 }}>{mm}:{ss}</div>
        {movementName && (
          <div style={{ ...LABEL, color: T.lime, marginBottom: 18 }}>
            Up next · {movementName} · Set {nextSetNumber}
          </div>
        )}
      </div>
      <Button onClick={onDone}>Next Set</Button>

      {/* or hand the rack to the next lifter — athletes rotate one set at a time */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '26px 0 18px' }}>
        <div style={{ flex: 1, height: 1, background: T.line }} />
        <span style={LABEL}>or, next lifter</span>
        <div style={{ flex: 1, height: 1, background: T.line }} />
      </div>
      <CheckInList roster={roster} hotList={hotList} groupName={groupName}
        statusMap={statusMap} onSelect={onSelectAthlete} />
    </div>
  )
}

// Shared centered column every phase renders into.
function PhaseBody({ children }) {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', padding: 28, width: '100%', maxWidth: 340, margin: '0 auto' }}>
      {children}
    </div>
  )
}

// ─────────────────────────── the state machine host ───────────────────────────

export default function RackScreen({ rackNumber, session, node, controller }) {
  const agent = useRackAgentStatus(node)
  const [phase, setPhase] = useState('idle')

  // Step 2 selection: who's lifting + which movement, plus that athlete's day view.
  // Held HERE (not inside Idle) so the choice survives into countdown/active/etc.
  const [selectedAthlete, setSelectedAthlete] = useState(null)      // a roster entry | null
  const [progress, setProgress] = useState(null)                   // /progress payload | null
  const [progressLoading, setProgressLoading] = useState(false)
  const [selectedExerciseId, setSelectedExerciseId] = useState(null)

  // On-the-fly working weight: what the athlete is ACTUALLY loading, per movement,
  // when it differs from the session's prescribed target. Keyed by exercise_id and
  // kept only in the client while this athlete is at the rack — it overrides the
  // displayed load and the weight_lbs sent at set-create, but NEVER the target. The
  // numpad (WeightPad) writes here; `editingWeight` toggles that pad.
  const [weightOverrides, setWeightOverrides] = useState({})
  const [editingWeight, setEditingWeight] = useState(false)

  // Check-in screen data: the session roster (who can lift) + this rack's hot list
  // (who it currently owns). Seeded from the one-shot fetch, kept fresh by a poll.
  const [roster, setRoster] = useState(session?.roster ?? [])
  const [hotList, setHotList] = useState([])
  const [statusMap, setStatusMap] = useState({})   // athlete_id → { status, since, rack_number }

  // Step 3 live-set data: the linked sensor node, the created set's id, and the
  // live rep readout (count + latest velocity + its color).
  const [setId, setSetId] = useState(null)
  const [repCount, setRepCount] = useState(0)
  const [lastVelocity, setLastVelocity] = useState(null)
  const [lastColor, setLastColor] = useState('green')
  const [buffered, setBuffered] = useState(0)
  const [summary, setSummary] = useState(null)   // { reps, avg, peak } for the summary screen
  const [setStartError, setSetStartError] = useState('')
  const [nfcStatus, setNfcStatus] = useState('')
  const finishingRef = useRef(false)             // guards EXACTLY ONE complete POST per set
  const repQueueRef = useRef(Promise.resolve())

  useEffect(() => {
    const snapshot = controller.snapshot
    if (!snapshot) return
    setPhase(snapshot.phase === 'recovery_required' ? 'active' : snapshot.phase)
    setSelectedAthlete(snapshot.selected_athlete
      ? (roster.find((athlete) => athlete.athlete_id === snapshot.selected_athlete.id) || {
          athlete_id: snapshot.selected_athlete.id,
          name: snapshot.selected_athlete.name,
        })
      : null)
    setSelectedExerciseId(snapshot.selected_exercise?.id ?? null)
    setSetId(snapshot.current_set)
    setRepCount(snapshot.rep_count ?? 0)
    setLastVelocity(snapshot.latest_mean_velocity)
    setLastColor(snapshot.latest_color || 'green')
    if (snapshot.phase === 'summary') {
      setSummary({
        reps: snapshot.rep_count ?? 0,
        avg: snapshot.latest_mean_velocity,
        peak: snapshot.latest_peak_velocity,
      })
    }
  }, [controller.snapshot, roster])

  // When an athlete checks in, fetch their day view; default the "up now" movement
  // to the server's suggested current (first not-complete), else the first movement.
  //
  // ⚠️ KEYED ON THE ATHLETE'S ID, NOT THE OBJECT. This must fire when a DIFFERENT
  // ATHLETE arrives, and never merely because a new object describing the same
  // athlete did. The effect above rebuilds `selectedAthlete` from every snapshot,
  // and when that athlete is not in `roster` it falls back to constructing a fresh
  // object literal — a new identity on each snapshot, for the same person.
  //
  // With the object as the dependency that produced a loop you could not escape:
  //
  //   tap a different movement -> pushed to the server -> new snapshot
  //     -> the effect above builds a NEW athlete object
  //     -> this effect re-runs, thinking the lifter changed
  //     -> it resets the movement to the server's suggested current_exercise_id
  //     -> the sync effect below sees local != snapshot and pushes THAT back
  //     -> new snapshot -> round again
  //
  // On screen: the selection flickers to the new movement and snaps back, forever,
  // so the switch never takes. It only bit when the athlete was missing from the
  // roster — an NFC/makeup lifter, or a roster fetch that failed at mount — which
  // is why it looked intermittent.
  //
  // Keying on the id also stops `weightOverrides` being wiped on every snapshot,
  // which was silently discarding on-the-fly weights entered at the rack.
  const selectedAthleteId = selectedAthlete?.athlete_id ?? null
  useEffect(() => {
    setWeightOverrides({})   // a new athlete brings their own prescriptions
    if (selectedAthleteId == null) { setProgress(null); setSelectedExerciseId(null); return }
    let cancelled = false
    setProgressLoading(true)
    getAthleteProgress(selectedAthleteId)
      .then((d) => {
        if (cancelled) return
        setProgress(d)
        setSelectedExerciseId(d.current_exercise_id ?? d.movements?.[0]?.exercise_id ?? null)
      })
      .catch(() => { if (!cancelled) setProgress({ movements: [] }) })
      .finally(() => { if (!cancelled) setProgressLoading(false) })
    return () => { cancelled = true }
  }, [selectedAthleteId])

  useEffect(() => {
    if (phase !== 'idle' || selectedExerciseId == null || !controller.canControl) return
    if (controller.snapshot?.selected_exercise?.id === selectedExerciseId) return
    controller.updateState({ selected_exercise: selectedExerciseId }).catch(() => {})
  }, [phase, selectedExerciseId, controller.canControl, controller.snapshot, controller.updateState])

  // Tapping a name IS the check-in: record it (this rack now owns the athlete),
  // then open their day view. Called from the check-in screen AND the rest screen
  // (handing the rack to the next lifter), so it always lands on idle. NFC later
  // calls this same path.
  const selectAthlete = useCallback(async (a) => {
    try {
      await controller.runMutation((capability, version) => checkInAthlete(
        rackNumber,
        a.athlete_id,
        controllerCommand({}, version),
        capability,
      ))
      if (phase !== 'idle') await controller.updateState({ phase: 'idle' })
      return true
    } catch {
      return false
    }
  }, [controller.runMutation, controller.updateState, phase, rackNumber])

  // Freshness-only refresh of the roster, hot list, and live statuses: picks up a
  // coach adding/removing a session athlete, someone checking in elsewhere, and each
  // athlete's lifting/resting/ready status for the timer cards.
  const refreshCheckIn = useCallback(async () => {
    try {
      const [active, hot, stat] = await Promise.all([
        getActiveSession(), getRackHotList(rackNumber), getSessionStatus(),
      ])
      setRoster(active?.roster ?? [])
      setHotList(hot?.athletes ?? [])
      setStatusMap(Object.fromEntries((stat?.athletes ?? []).map((a) => [a.athlete_id, a])))
    } catch { /* keep the last known lists */ }
  }, [rackNumber])

  // Poll while the check-in list is visible — the idle check-in screen OR the rest
  // screen (where the next lifter can tap in).
  //
  // The rack screen reads taps from its OWN local reader (loopback HTTP, same
  // laptop) and forwards the raw tag to Django for athlete resolution. If the
  // local agent is unreachable we fall back to asking Django, which talks to a
  // reader attached to the base station — so a rack with no local reader still
  // works.
  const showCheckInList = (phase === 'idle' && !selectedAthlete) || phase === 'rest'
  useEffect(() => {
    if (!showCheckInList || !controller.canControl) {
      setNfcStatus('')
      return
    }
    let cancelled = false
    let timer
    async function poll() {
      let delay = 500
      try {
        const local = await pollLocalNfcTap()
        if (cancelled) return
        let result
        if (local.status === 'tap') {
          result = await controller.runControlled(
            (capability) => consumeNfcTap(rackNumber, capability, local.tag_id),
          )
        } else if (local.status === 'unavailable') {
          result = await controller.runControlled((capability) => consumeNfcTap(rackNumber, capability))
        } else {
          result = { status: 'none' }
        }
        if (cancelled) return
        const outcome = await handleNfcPollResult(result, selectAthlete)
        if (cancelled) return
        setNfcStatus(outcome.message)
        if (outcome.stop) return
        delay = outcome.delay
      } catch {
        if (!cancelled) {
          setNfcStatus('Card reader unavailable')
          delay = 2000
        }
      }
      if (!cancelled) timer = setTimeout(poll, delay)
    }
    poll()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [showCheckInList, controller.canControl, controller.runControlled, rackNumber, selectAthlete])
  useEffect(() => {
    if (!showCheckInList) return
    refreshCheckIn()
    const id = setInterval(refreshCheckIn, 5000)
    return () => clearInterval(id)
  }, [showCheckInList, refreshCheckIn])

  // The movement the athlete is about to do (from the day view) — drives the set's
  // exercise, weight, and set number, and the velocity zone reps are colored against.
  const selectedMovement = progress?.movements?.find((m) => m.exercise_id === selectedExerciseId) || null
  const zoneMin = selectedMovement?.velocity_zone_min ?? null

  // The load actually going on the bar for the selected movement, in priority:
  //   1. an on-the-fly override entered at this rack this visit, else
  //   2. what they LAST actually lifted for this movement THIS session (so a weight
  //      change carries forward across sets/reloads/rack moves), else
  //   3. the prescribed target (session start, or a movement not yet touched).
  // This is what the day view shows and what gets saved as the set's actual weight_lbs.
  const effectiveLoad = selectedMovement
    ? (weightOverrides[selectedMovement.exercise_id]
        ?? selectedMovement.last_weight_lbs
        ?? selectedMovement.target_weight_lbs)
    : null

  // Countdown → active: start a fresh set. Clear the buffer first so no stray reps
  // carry over, reset the live readout, flip to active (reps start streaming), then
  // create the Set row and keep its id for the complete POST in Step 4.
  async function beginActiveSet() {
    await clearBuffer()
    setRepCount(0); setLastVelocity(null); setLastColor('green'); setBuffered(0); setSetId(null)
    setSetStartError('')
    const body = {
      session: session?.session_id,
      athlete: selectedAthlete.athlete_id,
      exercise: selectedExerciseId,
      set_number: selectedMovement?.next_set_number ?? 1,
      weight_lbs: effectiveLoad ?? null,   // actual load (override or target), not the prescription itself
      is_makeup: !!selectedAthlete?.has_data,
      rack_number: rackNumber,
    }
    if (node?.id != null) body.node = node.id
    try {
      const createdSet = await controller.runMutation((capability, version) => (
        createSet(body, controllerCommand({}, version), capability)
      ))
      setSetId(createdSet.id)
    } catch (err) {
      const code = err?.code
      const detail = err?.detail
      if (code === 'rack_state_changed' || code === 'rack_controller_stale') {
        setSetStartError('The rack changed underneath this screen. Reload to pick up the current state, then try again.')
      } else if (code === 'rack_sensor_required') {
        setSetStartError('The rack sensor is not ready. Confirm the sensor is linked and showing live, then try again.')
      } else if (code === 'open_set_exists') {
        setSetStartError('A set is already open at this rack. Finish it before starting another.')
      } else if (code === 'node_assignment_changed') {
        setSetStartError('The sensor was moved to another rack. Confirm the rack sensor assignment and try again.')
      } else if (detail && typeof detail === 'string') {
        setSetStartError(detail)
      } else {
        setSetStartError('The set could not start. Confirm the rack sensor assignment and try again.')
      }
      if (controller.canControl) controller.updateState({ phase: 'idle' }).catch(() => {})
    }
  }

  // Set end: build the ONE batch complete from the buffered reps and send it. Reps
  // are renumbered 1..N HERE (the node's rep_number is advisory ordering only); the
  // buffer is cleared only AFTER the POST succeeds. A false set sends zero reps and
  // returns to idle. The ref guard makes double-taps impossible — exactly one POST.
  async function finishSet(isFalseSet) {
    if (finishingRef.current || setId == null) return
    finishingRef.current = true
    try {
      const rows = isFalseSet ? [] : await getBufferedReps()
      const reps = rows.map((r, i) => ({
        rep_number: i + 1,                       // authoritative 1..N, not the node's number
        mean_velocity: r.mean_velocity,
        peak_velocity: r.peak_velocity,
        duration_ms: r.duration_ms,
        timestamp: r.timestamp,
        velocity_color: velocityColor(r.mean_velocity, zoneMin),
      }))
      const avg = reps.length ? reps.reduce((s, x) => s + x.mean_velocity, 0) / reps.length : null
      const peak = reps.length ? Math.max(...reps.map((x) => x.peak_velocity)) : null
      await controller.runMutation((capability, version) => completeSet(setId, {
          reps_completed: reps.length, avg_velocity: avg, peak_velocity: peak,
          is_false_set: isFalseSet, reps,
        }, controllerCommand({}, version), capability))
      await clearBuffer()                        // only AFTER a successful POST
      setBuffered(0)
      setSummary({ reps: reps.length, avg, peak })
      // refresh the day view so the just-finished set shows in the progress bars,
      // and if that movement is now fully done, advance to the next one the server
      // suggests so the rotation flows on its own.
      if (selectedAthlete) {
        getAthleteProgress(selectedAthlete.athlete_id).then((d) => {
          setProgress(d)
          const m = d.movements?.find((x) => x.exercise_id === selectedExerciseId)
          if (!isFalseSet && m && m.completed_sets >= m.planned_sets && d.current_exercise_id) {
            setSelectedExerciseId(d.current_exercise_id)
          }
        }).catch(() => {})
      }
    } catch {
      // POST failed — leave the buffer intact so the set can be retried (no defined
      // retry/backoff yet; it's a Known Open Item).
    } finally {
      finishingRef.current = false
    }
  }

  // Live reps — subscribe ONLY while a set is active. This gates buffering to the
  // set: reps arriving in idle/countdown/rest are never captured. Each rep is
  // written to the durable buffer FIRST, then updates the live readout.
  useEffect(() => {
    if (phase !== 'active' || !node || !controller.canControl || !agent.ready) return
    const onRep = (rep) => {
      repQueueRef.current = repQueueRef.current.then(async () => {
        await addRep(rep)
        const rows = await getBufferedReps()
        const color = velocityColor(rep.mean_velocity, zoneMin)
        await controller.updateState({
          phase: 'active',
          rep_count: rows.length,
          latest_mean_velocity: rep.mean_velocity,
          latest_peak_velocity: rep.peak_velocity,
          latest_color: color,
        })
        setBuffered(rows.length)
      }).catch(() => {})
    }
    const unsub = subscribeNodeReps(node.node_id, onRep)
    return () => unsub()
  }, [phase, node, zoneMin, controller.canControl, controller.updateState, agent.ready])

  const badge = PHASE_BADGE[phase]

  if (agent.required && !agent.ready) {
    return (
      <div style={{ minHeight: '100vh', background: T.bg, color: T.ink, fontFamily: T.sans,
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ maxWidth: 440, textAlign: 'center' }}>
          <div style={{ ...LABEL, color: T.amber, marginBottom: 12 }}>Rack {rackNumber} sensor unavailable</div>
          <div style={{ fontSize: 28, fontWeight: 850, marginBottom: 10 }}>Controls are paused</div>
          <div style={{ color: T.muted }}>
            The local WT901 stream is {agent.health?.state || 'checking'}. Existing set data is preserved;
            check-in and set controls return when fresh BLE samples resume.
          </div>
        </div>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', background: T.bg, color: T.ink, fontFamily: T.sans,
      display: 'flex', flexDirection: 'column' }}>

      {/* top bar: rack + phase badge on top, session label centered below */}
      <div style={{ padding: '16px 24px', borderBottom: `1px solid ${T.line}` }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 16, fontWeight: 850, letterSpacing: '-.02em' }}>Rack {rackNumber}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8,
            background: T.panel, border: `1px solid ${T.line}`, borderRadius: 999,
            padding: '7px 12px', fontSize: 10, fontWeight: 850, letterSpacing: '.08em',
            textTransform: 'uppercase', color: badge.color }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: badge.color,
              boxShadow: `0 0 12px ${badge.color}` }} />
            {badge.text}
          </div>
        </div>
        <div style={{ textAlign: 'center', marginTop: 14 }}>
          <div style={{ ...LABEL, fontSize: 9, color: T.lime, marginBottom: 4 }}>Session</div>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-.035em' }}>
            {session?.label || 'No active session'}
          </div>
        </div>
      </div>

      {/* the current phase */}
      {setStartError && (
        <div role="alert" style={{ margin: '14px 24px 0', padding: '12px 14px', borderRadius: 10,
          border: '1px solid #7f3636', background: '#2b1717', color: '#ffb4b4', fontSize: 13 }}>
          {setStartError}
        </div>
      )}
      {showCheckInList && nfcStatus && (
        <div aria-live="polite" style={{ margin: '14px 24px 0', padding: '10px 14px', borderRadius: 10,
          border: `1px solid ${T.line}`, background: T.panel, color: T.muted, fontSize: 13,
          textAlign: 'center' }}>
          {nfcStatus}
        </div>
      )}
      {phase === 'idle' && (
        <Idle
          roster={roster}
          hotList={hotList}
          groupName={session?.label}
          statusMap={statusMap}
          selectedAthlete={selectedAthlete}
          onSelectAthlete={selectAthlete}
          onClearAthlete={() => controller.updateState({
            selected_athlete: null,
            selected_exercise: null,
          }).catch(() => {})}
          progress={progress}
          progressLoading={progressLoading}
          selectedExerciseId={selectedExerciseId}
          onSelectMovement={(exerciseId) => controller.updateState({ selected_exercise: exerciseId }).catch(() => {})}
          effectiveLoad={effectiveLoad}
          onEditWeight={() => setEditingWeight(true)}
          onStart={() => controller.updateState({
            phase: 'countdown',
            selected_athlete: selectedAthlete?.athlete_id,
            selected_exercise: selectedExerciseId,
            rep_count: 0,
            latest_mean_velocity: null,
            latest_peak_velocity: null,
            latest_color: null,
          }).catch(() => {})}
        />
      )}
      {phase === 'countdown' && <CountdownPhase onDone={beginActiveSet} />}
      {phase === 'active' && (
        <ActivePhase
          movementName={selectedMovement?.name}
          repCount={repCount}
          lastVelocity={lastVelocity}
          lastColor={lastColor}
          sensorMovementG={agent.health?.movement_g}
          sensorState={agent.health?.state}
          onEnd={() => finishSet(false)}
          onFalseSet={() => finishSet(true)}
        />
      )}
      {phase === 'summary' && <SummaryPhase summary={summary}
        onRest={() => controller.updateState({ phase: 'rest' }).catch(() => {})} />}
      {phase === 'rest' && (
        <RestPhase
          onDone={() => controller.updateState({ phase: 'idle' }).catch(() => {})}
          movementName={selectedMovement?.name}
          nextSetNumber={selectedMovement?.next_set_number}
          roster={roster}
          hotList={hotList}
          groupName={session?.label}
          statusMap={statusMap}
          onSelectAthlete={selectAthlete}
        />
      )}

      {/* on-the-fly weight entry — a full-screen overlay above whatever phase shows.
          Only meaningful with a movement selected; writes an override, never the target. */}
      {editingWeight && selectedMovement && (
        <WeightPad
          initial={effectiveLoad}
          movementName={selectedMovement.name}
          onCancel={() => setEditingWeight(false)}
          onConfirm={(w) => {
            setWeightOverrides((prev) => ({ ...prev, [selectedMovement.exercise_id]: w }))
            setEditingWeight(false)
          }}
        />
      )}

      {/* footer: phase readout (proof the machine is where we think it is) */}
      <div style={{ padding: '14px 28px', borderTop: `1px solid ${T.line}`,
        display: 'flex', justifyContent: 'space-between', ...LABEL, fontSize: 10 }}>
        <span>phase: {phase}</span>
        <span>node: {node?.node_id || '—'}</span>
        <span>buffered: {buffered}</span>
      </div>
    </div>
  )
}
