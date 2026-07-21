// rack/Idle.jsx — the rack's idle screen: pick who's lifting, then their day view.
//
// ── WHY THIS FILE EXISTS (plain version) ───────────────────────────────────────
// Before a set can start, the rack needs to know WHO is lifting and WHICH movement.
// This screen does both, athlete-first:
//   1. tap the athlete who's at the rack (the shared CheckInList), then
//   2. see that athlete's whole day for the session — every planned movement with
//      live progress (how many sets done of how many) — pulled fresh from the
//      server, so it looks the same and stays correct at ANY rack the athlete uses.
// The movement they're about to do is shown big ("Up now"); the rest of the day
// sits below as compact cards they can tap to switch to (e.g. for a superset).
// "Start Set" hands off to the countdown. All the numbers come from the athlete
// progress endpoint.
//
// The check-in list itself lives in CheckInList.jsx because the rest screen shares
// it. Kept deliberately lean: a portrait tablet read at a glance, one vertical
// column, only the pertinent numbers — no dense grid.

import { T } from '../theme.js'
import CheckInList from './CheckInList.jsx'

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

// One label + value pair, used in the "Up now" card's stat row.
function Stat({ label, value }) {
  return (
    <div>
      <div style={{ ...LABEL, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: '-.02em' }}>{value}</div>
    </div>
  )
}

// The Load stat, but tappable: a small pencil opens the numpad so the athlete can
// set what they're ACTUALLY lifting. Tinted lime once they've changed it from the
// prescribed target, so an override reads at a glance.
function LoadStat({ load, edited, onEdit }) {
  return (
    <div>
      <div style={{ ...LABEL, marginBottom: 4 }}>Load</div>
      <button onClick={onEdit} style={{ display: 'flex', alignItems: 'center', gap: 7,
        background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', fontFamily: 'inherit' }}>
        <span style={{ fontSize: 16, fontWeight: 800, letterSpacing: '-.02em', color: edited ? T.lime : T.ink }}>
          {load != null ? `${load} lb` : '—'}
        </span>
        <span aria-hidden style={{ fontSize: 12, color: edited ? T.lime : T.muted,
          border: `1px solid ${T.line}`, borderRadius: 6, padding: '2px 5px', lineHeight: 1 }}>✎</span>
      </button>
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

export default function Idle({ roster, hotList, groupName, statusMap, selectedAthlete, onSelectAthlete,
  onClearAthlete, progress, progressLoading, selectedExerciseId, onSelectMovement,
  effectiveLoad, onEditWeight, onStart }) {

  // ── no athlete yet: the check-in screen ──────────────────────────────────────
  if (!selectedAthlete) {
    return (
      <Scroll>
        <div style={{ ...LABEL, marginBottom: 18 }}>Rack check-in</div>
        <CheckInList roster={roster} hotList={hotList} groupName={groupName}
          statusMap={statusMap} onSelect={onSelectAthlete} />
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
              <LoadStat load={effectiveLoad ?? selected.target_weight_lbs}
                edited={effectiveLoad != null && effectiveLoad !== selected.target_weight_lbs}
                onEdit={onEditWeight} />
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

const COMPACT = { display: 'flex', alignItems: 'center', padding: '12px 16px', borderRadius: 12,
  border: `1px solid ${T.line}`, background: T.bg, color: T.ink, cursor: 'pointer',
  fontFamily: 'inherit', width: '100%' }
const GHOST_SM = { padding: '8px 12px', borderRadius: 8, border: `1px solid ${T.line}`,
  background: 'transparent', color: T.muted, fontSize: 12, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit' }
const START = { padding: '16px 20px', fontSize: 16, fontWeight: 850, borderRadius: 12,
  border: `1px solid ${T.lime}`, background: T.lime, color: '#0a0f07', cursor: 'pointer',
  fontFamily: 'inherit', width: '100%' }
