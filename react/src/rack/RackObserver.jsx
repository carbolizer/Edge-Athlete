import { useEffect, useState } from 'react'
import { T } from '../theme.js'

const REST_SECONDS = 120
const COUNTDOWN_SECONDS = 3

export function snapshotTiming(snapshot, now = Date.now()) {
  const started = Date.parse(snapshot?.phase_started_at)
  const server = Date.parse(snapshot?.server_time)
  const received = snapshot?._received_at ?? now
  const elapsed = Number.isFinite(started)
    ? Math.max(0, Math.floor(((Number.isFinite(server) ? server : received) - started + (now - received)) / 1000))
    : 0
  if (snapshot?.phase === 'countdown') return Math.max(0, COUNTDOWN_SECONDS - elapsed)
  if (snapshot?.phase === 'rest') return Math.max(0, REST_SECONDS - elapsed)
  return elapsed
}

export function formatSnapshot(snapshot, now = Date.now()) {
  const timing = snapshotTiming(snapshot, now)
  return {
    rack: snapshot?.rack_number ?? '—',
    athlete: snapshot?.selected_athlete?.name || 'No athlete selected',
    exercise: snapshot?.selected_exercise?.name || 'No exercise selected',
    phase: snapshot?.phase || 'idle',
    currentSet: snapshot?.current_set ?? '—',
    reps: snapshot?.rep_count ?? 0,
    mean: snapshot?.latest_mean_velocity,
    peak: snapshot?.latest_peak_velocity,
    color: snapshot?.latest_color || 'neutral',
    timing,
    lease: snapshot?.controller_active ? 'Controller connected' : 'No active controller',
  }
}

function metric(value) {
  return value == null ? '—' : `${Number(value).toFixed(2)} m/s`
}

export default function RackObserver({ snapshot, reason, canRecover = false, onRecover }) {
  const [, tick] = useState(0)
  useEffect(() => {
    const interval = setInterval(() => tick((value) => value + 1), 1000)
    return () => clearInterval(interval)
  }, [])
  const view = formatSnapshot(snapshot)
  const timer = view.phase === 'rest'
    ? `${Math.floor(view.timing / 60)}:${String(view.timing % 60).padStart(2, '0')}`
    : view.phase === 'countdown' ? String(view.timing) : `${view.timing}s`

  return (
    <div style={{ minHeight: '100vh', background: T.bg, color: T.ink, fontFamily: T.sans }}>
      <header style={{ padding: '18px 24px', borderBottom: `1px solid ${T.line}` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <strong style={{ fontSize: 18 }}>Rack {view.rack}</strong>
          <span style={{ color: T.amber, fontSize: 11, fontWeight: 900, letterSpacing: '.12em', textTransform: 'uppercase' }}>
            Read-only observer
          </span>
        </div>
        <div style={{ color: T.muted, fontSize: 13, marginTop: 8 }}>
          {view.lease}{view.phase === 'recovery_required' ? ' · Recovery required' : ''}
          {reason === 'rack_screen_not_assigned' ? ' · This screen is not assigned to control this rack' : ''}
        </div>
      </header>
      <main style={{ width: 'min(520px, calc(100% - 40px))', margin: '0 auto', padding: '28px 0' }}>
        {/* The dead end this replaces: a rack left holding an unfinished set
            refused every claim, and the screen sat here read-only with no
            explanation and nothing to press. Say what is wrong in words an
            athlete can act on, and give them the one action that fixes it. */}
        {canRecover && (
          <div style={{
            border: `1px solid ${T.amber}`, borderRadius: 14, padding: 20, marginBottom: 26,
          }}>
            {/* TWO DIFFERENT OUTCOMES, so two different promises. A refused claim
                means this browser can no longer prove it started the set, and
                taking the rack ends that set — say so. A lapsed lease means the
                tab never died, the server still recognises it, and re-claiming
                picks the set straight back up with its reps. Telling an athlete
                mid-session that we are about to bin their set, when we are not,
                is how you get someone refusing to press the one button that
                fixes their rack. */}
            {reason === 'rack_recovery_required' ? (
              <>
                <div style={{ fontSize: 19, fontWeight: 850 }}>This rack has an unfinished set</div>
                <div style={{ color: T.muted, fontSize: 14, marginTop: 8, lineHeight: 1.5 }}>
                  It was left open by an earlier session and cannot be finished.
                  Recovering ends it and hands this screen back to you.
                </div>
              </>
            ) : (
              <>
                <div style={{ fontSize: 19, fontWeight: 850 }}>This screen lost its connection</div>
                <div style={{ color: T.muted, fontSize: 14, marginTop: 8, lineHeight: 1.5 }}>
                  The set is still here. Reconnecting picks it up where it left off —
                  nothing is lost.
                </div>
              </>
            )}
            <button
              onClick={onRecover}
              style={{
                marginTop: 18, width: '100%', padding: 18, fontSize: 17, fontWeight: 800,
                borderRadius: 12, border: `1px solid ${T.amber}`, background: 'transparent',
                color: T.amber, cursor: 'pointer', fontFamily: 'inherit',
              }}>
              {reason === 'rack_recovery_required' ? 'Recover this rack' : 'Reconnect to this rack'}
            </button>
          </div>
        )}
        <div style={{ color: T.lime, fontSize: 11, fontWeight: 900, letterSpacing: '.12em', textTransform: 'uppercase' }}>
          {view.phase}
        </div>
        <div style={{ fontSize: 34, fontWeight: 850, marginTop: 10 }}>{view.athlete}</div>
        <div style={{ fontSize: 20, color: T.muted, marginTop: 5 }}>{view.exercise}</div>
        <div style={{ fontSize: 82, fontWeight: 850, lineHeight: 1, margin: '38px 0 8px' }}>{view.reps}</div>
        <div style={{ color: T.muted, textTransform: 'uppercase', fontSize: 10, fontWeight: 900, letterSpacing: '.12em' }}>Reps</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12, marginTop: 28 }}>
          <ObserverField label="Latest mean" value={metric(view.mean)} />
          <ObserverField label="Latest peak" value={metric(view.peak)} />
          <ObserverField label="Latest color" value={view.color} />
          <ObserverField label="Phase timing" value={timer} />
          <ObserverField label="Current set ID" value={String(view.currentSet)} />
          <ObserverField label="State version" value={String(snapshot?.state_version ?? '—')} />
        </div>
      </main>
    </div>
  )
}

function ObserverField({ label, value }) {
  return (
    <div style={{ padding: 16, background: T.panel, border: `1px solid ${T.line}`, borderRadius: 12 }}>
      <div style={{ color: T.muted, fontSize: 9, fontWeight: 900, letterSpacing: '.12em', textTransform: 'uppercase' }}>{label}</div>
      <div style={{ marginTop: 7, fontSize: 17, fontWeight: 750 }}>{value}</div>
    </div>
  )
}
