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

import { useEffect, useState } from 'react'
import { getAthleteProgress } from '../api/client.js'
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

function ActivePhase({ onEnd, onFalseSet }) {
  return (
    <PhaseBody>
      <div style={{ ...LABEL, marginBottom: 10 }}>Reps this set</div>
      <div style={{ fontSize: 128, fontWeight: 800, lineHeight: 0.9, letterSpacing: '-.06em',
        fontVariantNumeric: 'tabular-nums', color: T.ink }}>0</div>
      <div style={{ fontSize: 13, color: T.muted, marginTop: 18, marginBottom: 36 }}>
        (live reps stream in here — Step 3)
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: '100%' }}>
        <Button onClick={onEnd} tone="ghost">End Set</Button>
        <Button onClick={onFalseSet} tone="danger">False Set</Button>
      </div>
    </PhaseBody>
  )
}

function SummaryPhase({ onRest, onFalseSet }) {
  return (
    <PhaseBody>
      <div style={{ ...LABEL, marginBottom: 6 }}>Set complete</div>
      <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: '-.03em', marginBottom: 28 }}>
        0 reps
      </div>
      <div style={{ fontSize: 13, color: T.muted, marginBottom: 36, textAlign: 'center' }}>
        (avg / peak velocity summary goes here — Step 4)
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: '100%' }}>
        <Button onClick={onRest}>Start Rest Timer</Button>
        <Button onClick={onFalseSet} tone="danger">False Set</Button>
      </div>
    </PhaseBody>
  )
}

function RestPhase({ onDone }) {
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
        fontVariantNumeric: 'tabular-nums', marginBottom: 36 }}>{mm}:{ss}</div>
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
          session={session}
          selectedAthlete={selectedAthlete}
          onSelectAthlete={setSelectedAthlete}
          onClearAthlete={() => setSelectedAthlete(null)}
          progress={progress}
          progressLoading={progressLoading}
          selectedExerciseId={selectedExerciseId}
          onSelectMovement={setSelectedExerciseId}
          onStart={() => setPhase('countdown')}
        />
      )}
      {phase === 'countdown' && <CountdownPhase onDone={() => setPhase('active')} />}
      {phase === 'active' && <ActivePhase onEnd={() => setPhase('summary')} onFalseSet={() => setPhase('idle')} />}
      {phase === 'summary' && <SummaryPhase onRest={() => setPhase('rest')} onFalseSet={() => setPhase('idle')} />}
      {phase === 'rest' && <RestPhase onDone={() => setPhase('idle')} />}

      {/* footer: phase readout (proof the machine is where we think it is) */}
      <div style={{ padding: '14px 28px', borderTop: `1px solid ${T.line}`,
        display: 'flex', justifyContent: 'space-between', ...LABEL, fontSize: 10 }}>
        <span>phase: {phase}</span>
        <span>roster: {session?.roster?.length ?? 0}</span>
      </div>
    </div>
  )
}
