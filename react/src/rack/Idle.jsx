// rack/Idle.jsx — the rack's idle screen: pick who's lifting, then their day view.
//
// ── WHY THIS FILE EXISTS (plain version) ───────────────────────────────────────
// Before a set can start, the rack needs to know WHO is lifting and WHICH movement.
// This screen does both, athlete-first:
//   1. tap the athlete who's at the rack (from the session roster), then
//   2. see that athlete's whole day for the session — every planned movement with
//      live progress (how many sets done of how many) — pulled fresh from the
//      server, so it looks the same and stays correct at ANY rack the athlete uses.
// The movement they're about to do is shown big ("Up now"); the rest of the day
// sits below as compact cards they can tap to switch to (e.g. for a superset).
// "Start Set" hands off to the countdown. All the numbers come from the athlete
// progress endpoint (Step 2a-i).
//
// Kept deliberately lean: this is a portrait tablet read at a glance, so it's ONE
// vertical column with only the pertinent numbers — no dense grid.

import { T } from '../theme.js'

const LABEL = {
  fontSize: 10, fontWeight: 900, letterSpacing: '.14em',
  textTransform: 'uppercase', color: T.muted,
}

// A thin progress bar: `value` of `max`, filled in lime.
function Bar({ value, max, height = 6 }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0
  return (
    <div style={{ width: '100%', height, background: T.panel2, borderRadius: 999, overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: T.lime, borderRadius: 999,
        transition: 'width .4s ease' }} />
    </div>
  )
}

// A purely-decorative NFC affordance under the check-in list. It hints at the
// future "tap your band to sign in" flow (NFC itself is out of scope this phase,
// per SPEC) and fills the empty space on a tall portrait screen. Not interactive.
function NfcHint() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginTop: 52 }}>
      <style>{'@keyframes eaNfcPulse{0%,100%{transform:scale(1);opacity:.5}50%{transform:scale(1.06);opacity:1}}'}</style>
      <div style={{ width: 104, height: 104, borderRadius: '50%', border: `2px dashed ${T.line}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16,
        animation: 'eaNfcPulse 2.4s ease-in-out infinite' }}>
        <svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke={T.muted}
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 9a4.5 4.5 0 0 1 0 6" />
          <path d="M9.5 6.5a9 9 0 0 1 0 11" />
          <path d="M13 4a13 13 0 0 1 0 16" />
        </svg>
      </div>
      <div style={{ fontSize: 13, color: T.muted, fontWeight: 600, letterSpacing: '-.01em' }}>
        Tap your name — or scan your NFC band
      </div>
    </div>
  )
}

// One label + value pair, used in the "Up now" card's stat row.
function Stat({ label, value }) {
  return (
    <div>
      <div style={{ ...LABEL, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: '-.02em' }}>{value}</div>
    </div>
  )
}

// The whole idle screen lives in one top-aligned, scrollable column.
function Scroll({ children }) {
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '22px 22px 32px', width: '100%',
      maxWidth: 460, margin: '0 auto' }}>
      {children}
    </div>
  )
}

export default function Idle({ session, selectedAthlete, onSelectAthlete, onClearAthlete,
  progress, progressLoading, selectedExerciseId, onSelectMovement, onStart }) {

  const roster = session?.roster ?? []

  // ── no athlete yet: the check-in list ────────────────────────────────────────
  if (!selectedAthlete) {
    return (
      <Scroll>
        <div style={{ ...LABEL, marginBottom: 4 }}>Rack check-in</div>
        <div style={{ fontSize: 24, fontWeight: 850, letterSpacing: '-.03em', marginBottom: 20 }}>
          Who&apos;s lifting?
        </div>
        {roster.length === 0
          ? <div style={{ color: T.muted, fontSize: 14 }}>No athletes in this session.</div>
          : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {roster.map((a) => (
                <button key={a.athlete_id} onClick={() => onSelectAthlete(a)} style={ROW}>
                  <span style={{ fontSize: 17, fontWeight: 700 }}>{a.name}</span>
                  {a.has_data && <span style={{ ...LABEL, color: T.mint }}>✓ in progress</span>}
                </button>
              ))}
            </div>
          )}
        <NfcHint />
      </Scroll>
    )
  }

  // ── athlete selected, progress still loading ─────────────────────────────────
  if (progressLoading || !progress) {
    return (
      <Scroll>
        <div style={{ color: T.muted, fontSize: 16, marginTop: 40 }}>
          Loading {selectedAthlete.name}&apos;s workout…
        </div>
      </Scroll>
    )
  }

  // ── athlete selected: their day view ─────────────────────────────────────────
  const movements = progress.movements ?? []
  const selected = movements.find((m) => m.exercise_id === selectedExerciseId) || movements[0]
  const others = movements.filter((m) => m.exercise_id !== selected?.exercise_id)

  // overall session progress across all the day's movements (false sets don't count)
  const totalDone = movements.reduce((s, m) => s + m.completed_sets, 0)
  const totalPlanned = movements.reduce((s, m) => s + m.planned_sets, 0)

  const zone = (m) => m.velocity_zone_min != null
    ? `${m.velocity_zone_min.toFixed(2)}–${m.velocity_zone_max.toFixed(2)}`
    : '—'

  return (
    <Scroll>
      {/* athlete + "wrong person?" escape */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <div style={{ ...LABEL, color: T.lime, marginBottom: 3 }}>Lifting</div>
          <div style={{ fontSize: 22, fontWeight: 850, letterSpacing: '-.03em' }}>{selectedAthlete.name}</div>
        </div>
        <button onClick={onClearAthlete} style={GHOST_SM}>Not here?</button>
      </div>

      {/* overall session progress */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, ...LABEL }}>
          <span>Session progress</span><span>{totalDone}/{totalPlanned} sets</span>
        </div>
        <Bar value={totalDone} max={totalPlanned} height={8} />
      </div>

      {movements.length === 0 && (
        <div style={{ color: T.muted, fontSize: 15 }}>
          No workout assigned for {selectedAthlete.name} today.
        </div>
      )}

      {/* the movement they're about to do — prominent */}
      {selected && (
        <>
          <div style={{ background: T.panel, border: `1px solid ${T.line}`, borderRadius: 16,
            padding: 20, marginBottom: 16 }}>
            <div style={{ ...LABEL, color: T.lime, marginBottom: 6 }}>Up now</div>
            <div style={{ fontSize: 26, fontWeight: 850, letterSpacing: '-.03em', marginBottom: 16 }}>
              {selected.name}
            </div>
            <div style={{ display: 'flex', gap: 22, marginBottom: 18 }}>
              <Stat label="Set" value={`${selected.next_set_number} of ${selected.planned_sets}`} />
              <Stat label="Load" value={selected.target_weight_lbs != null ? `${selected.target_weight_lbs} lb` : '—'} />
              <Stat label="Target m/s" value={zone(selected)} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, ...LABEL }}>
              <span>Sets done</span>
              <span>{selected.completed_sets}/{selected.planned_sets}{selected.false_sets ? ` · ${selected.false_sets} false` : ''}</span>
            </div>
            <Bar value={selected.completed_sets} max={selected.planned_sets} />
          </div>

          <button onClick={onStart} style={START}>Start Set {selected.next_set_number}</button>
        </>
      )}

      {/* rest of the day — tap any to switch to it (superset) */}
      {others.length > 0 && (
        <div style={{ marginTop: 26 }}>
          <div style={{ ...LABEL, marginBottom: 10 }}>Rest of today</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {others.map((m) => (
              <button key={m.exercise_id} onClick={() => onSelectMovement(m.exercise_id)} style={COMPACT}>
                <div style={{ flex: 1, textAlign: 'left' }}>
                  <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 7 }}>{m.name}</div>
                  <Bar value={m.completed_sets} max={m.planned_sets} height={4} />
                </div>
                <span style={{ ...LABEL, marginLeft: 14, color: m.status === 'complete' ? T.mint : T.muted }}>
                  {m.completed_sets}/{m.planned_sets}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </Scroll>
  )
}

const ROW = { display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  padding: '16px 18px', borderRadius: 12, border: `1px solid ${T.line}`, background: T.panel,
  color: T.ink, cursor: 'pointer', fontFamily: 'inherit', width: '100%' }
const COMPACT = { display: 'flex', alignItems: 'center', padding: '12px 16px', borderRadius: 12,
  border: `1px solid ${T.line}`, background: T.bg, color: T.ink, cursor: 'pointer',
  fontFamily: 'inherit', width: '100%' }
const GHOST_SM = { padding: '8px 12px', borderRadius: 8, border: `1px solid ${T.line}`,
  background: 'transparent', color: T.muted, fontSize: 12, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit' }
const START = { padding: '16px 20px', fontSize: 16, fontWeight: 850, borderRadius: 12,
  border: `1px solid ${T.lime}`, background: T.lime, color: '#0a0f07', cursor: 'pointer',
  fontFamily: 'inherit', width: '100%' }
