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
import { getAthleteProgress, getActiveSession, getRackHotList, checkInAthlete, getNodes, createSet, completeSet } from '../api/client.js'
import { subscribeNodeReps } from '../mqtt/client.js'
import { addRep, clearBuffer, getBufferedReps } from '../db/repBuffer.js'
import { velocityColor, VELOCITY_HEX } from './velocity.js'
import Idle from './Idle.jsx'
import { T } from '../theme.js'

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

function ActivePhase({ movementName, repCount, lastVelocity, lastColor, onEnd, onFalseSet }) {
  const hex = VELOCITY_HEX[lastColor]
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

function RestPhase({ onDone, movementName, nextSetNumber }) {
  const [secs, setSecs] = useState(REST_SECONDS)
  useEffect(() => {
    if (secs <= 0) { onDone(); return }
    const t = setTimeout(() => setSecs((v) => v - 1), 1000)
    return () => clearTimeout(t)
  }, [secs, onDone])
  const mm = Math.floor(secs / 60)
  const ss = String(secs % 60).padStart(2, '0')
  return (
    <PhaseBody>
      <div style={{ ...LABEL, marginBottom: 14 }}>Rest</div>
      <div style={{ fontSize: 92, fontWeight: 800, letterSpacing: '-.05em', color: T.ink,
        fontVariantNumeric: 'tabular-nums', marginBottom: 14 }}>{mm}:{ss}</div>
      {movementName && (
        <div style={{ ...LABEL, color: T.lime, marginBottom: 32 }}>
          Up next · {movementName} · Set {nextSetNumber}
        </div>
      )}
      <Button onClick={onDone}>Next Set</Button>
    </PhaseBody>
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

export default function RackScreen({ rackNumber, session }) {
  const [phase, setPhase] = useState('idle')

  // Step 2 selection: who's lifting + which movement, plus that athlete's day view.
  // Held HERE (not inside Idle) so the choice survives into countdown/active/etc.
  const [selectedAthlete, setSelectedAthlete] = useState(null)      // a roster entry | null
  const [progress, setProgress] = useState(null)                   // /progress payload | null
  const [progressLoading, setProgressLoading] = useState(false)
  const [selectedExerciseId, setSelectedExerciseId] = useState(null)

  // Check-in screen data: the session roster (who can lift) + this rack's hot list
  // (who it currently owns). Seeded from the one-shot fetch, kept fresh by a poll.
  const [roster, setRoster] = useState(session?.roster ?? [])
  const [hotList, setHotList] = useState([])

  // Step 3 live-set data: the linked sensor node, the created set's id, and the
  // live rep readout (count + latest velocity + its color).
  const [node, setNode] = useState(null)
  const [setId, setSetId] = useState(null)
  const [repCount, setRepCount] = useState(0)
  const [lastVelocity, setLastVelocity] = useState(null)
  const [lastColor, setLastColor] = useState('green')
  const [buffered, setBuffered] = useState(0)
  const [summary, setSummary] = useState(null)   // { reps, avg, peak } for the summary screen
  const finishingRef = useRef(false)             // guards EXACTLY ONE complete POST per set

  // When an athlete checks in, fetch their day view; default the "up now" movement
  // to the server's suggested current (first not-complete), else the first movement.
  useEffect(() => {
    if (!selectedAthlete) { setProgress(null); setSelectedExerciseId(null); return }
    let cancelled = false
    setProgressLoading(true)
    getAthleteProgress(selectedAthlete.athlete_id)
      .then((d) => {
        if (cancelled) return
        setProgress(d)
        setSelectedExerciseId(d.current_exercise_id ?? d.movements?.[0]?.exercise_id ?? null)
      })
      .catch(() => { if (!cancelled) setProgress({ movements: [] }) })
      .finally(() => { if (!cancelled) setProgressLoading(false) })
    return () => { cancelled = true }
  }, [selectedAthlete])

  // Tapping a name IS the check-in: record it (this rack now owns the athlete),
  // then open their day view. A future NFC tap would call this same path.
  function selectAthlete(a) {
    checkInAthlete(rackNumber, a.athlete_id).catch(() => { /* harmless if it fails */ })
    setSelectedAthlete(a)
  }

  // Freshness-only refresh of the roster + hot list: picks up a coach adding/removing
  // a session athlete, and drops anyone who has since checked in at another rack.
  const refreshCheckIn = useCallback(async () => {
    try {
      const [active, hot] = await Promise.all([getActiveSession(), getRackHotList(rackNumber)])
      setRoster(active?.roster ?? [])
      setHotList(hot?.athletes ?? [])
    } catch { /* keep the last known lists */ }
  }, [rackNumber])

  // Poll ONLY while the check-in screen is up (idle + nobody selected).
  useEffect(() => {
    if (phase !== 'idle' || selectedAthlete) return
    refreshCheckIn()
    const id = setInterval(refreshCheckIn, 5000)
    return () => clearInterval(id)
  }, [phase, selectedAthlete, refreshCheckIn])

  // Find this rack's linked sensor once — its node_id for the rep topic, its integer
  // pk for linking the Set on create.
  useEffect(() => {
    let cancelled = false
    getNodes().then((nodes) => {
      if (!cancelled) setNode(nodes.find((n) => n.rack_number === rackNumber) || null)
    }).catch(() => {})
    return () => { cancelled = true }
  }, [rackNumber])

  // The movement the athlete is about to do (from the day view) — drives the set's
  // exercise, weight, and set number, and the velocity zone reps are colored against.
  const selectedMovement = progress?.movements?.find((m) => m.exercise_id === selectedExerciseId) || null
  const zoneMin = selectedMovement?.velocity_zone_min ?? null

  // Countdown → active: start a fresh set. Clear the buffer first so no stray reps
  // carry over, reset the live readout, flip to active (reps start streaming), then
  // create the Set row and keep its id for the complete POST in Step 4.
  async function beginActiveSet() {
    await clearBuffer()
    setRepCount(0); setLastVelocity(null); setLastColor('green'); setBuffered(0); setSetId(null)
    setPhase('active')
    const body = {
      session: session?.session_id,
      athlete: selectedAthlete.athlete_id,
      exercise: selectedExerciseId,
      set_number: selectedMovement?.next_set_number ?? 1,
      weight_lbs: selectedMovement?.target_weight_lbs ?? null,
      is_makeup: !!selectedAthlete?.has_data,
    }
    if (node?.id != null) body.node = node.id
    createSet(body).then((s) => setSetId(s.id)).catch(() => { /* the retry story is a Known Open Item */ })
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
      await completeSet(setId, {
        reps_completed: reps.length, avg_velocity: avg, peak_velocity: peak,
        is_false_set: isFalseSet, reps,
      })
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
      setPhase(isFalseSet ? 'idle' : 'summary')
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
    if (phase !== 'active' || !node) return
    const onRep = async (rep) => {
      await addRep(rep)
      setRepCount((n) => n + 1)
      setLastVelocity(rep.mean_velocity)
      setLastColor(velocityColor(rep.mean_velocity, zoneMin))
      getBufferedReps().then((rows) => setBuffered(rows.length))
    }
    const unsub = subscribeNodeReps(node.node_id, onRep)
    return () => unsub()
  }, [phase, node, zoneMin])

  const badge = PHASE_BADGE[phase]

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
      {phase === 'idle' && (
        <Idle
          roster={roster}
          hotList={hotList}
          groupName={session?.label}
          selectedAthlete={selectedAthlete}
          onSelectAthlete={selectAthlete}
          onClearAthlete={() => setSelectedAthlete(null)}
          progress={progress}
          progressLoading={progressLoading}
          selectedExerciseId={selectedExerciseId}
          onSelectMovement={setSelectedExerciseId}
          onStart={() => setPhase('countdown')}
        />
      )}
      {phase === 'countdown' && <CountdownPhase onDone={beginActiveSet} />}
      {phase === 'active' && (
        <ActivePhase
          movementName={selectedMovement?.name}
          repCount={repCount}
          lastVelocity={lastVelocity}
          lastColor={lastColor}
          onEnd={() => finishSet(false)}
          onFalseSet={() => finishSet(true)}
        />
      )}
      {phase === 'summary' && <SummaryPhase summary={summary} onRest={() => setPhase('rest')} />}
      {phase === 'rest' && (
        <RestPhase
          onDone={() => setPhase('idle')}
          movementName={selectedMovement?.name}
          nextSetNumber={selectedMovement?.next_set_number}
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
