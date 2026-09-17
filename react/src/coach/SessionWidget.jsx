/*
 * SessionWidget.jsx — the strip above the three states.
 *
 * Right now it shows one thing: the training day that is currently running, how
 * long it has been going, and the button that ends it. It is deliberately built
 * as A STRIP THAT IS CURRENTLY SHOWING A SESSION rather than as a session bar,
 * because this is the slot other important notifications will land in later —
 * a node that stopped reporting, a tablet that dropped off. Adding those should
 * not mean rewriting this.
 *
 * WHY IT LIVES OUTSIDE THE THREE STATES. Ending a day is something a coach does
 * while looking at anything — mid-plan, mid-room, mid-report. The strip is the
 * only thing on screen in all three states, so it is the only honest home for
 * that button. Starting a day is the opposite: it belongs to SESSION, because
 * starting one is the act of opening the room you are about to look at.
 *
 * IT IS NOT ALWAYS VISIBLE. Nothing renders unless a day is actually running.
 * An empty strip on a quiet morning is furniture, and furniture is what this
 * redesign is removing.
 *
 * ⚠️ ENDING IS THE POINT OF NO RETURN. It freezes the day into a report that is
 * never edited again AND recalculates every athlete's reference max from what
 * they actually lifted. That is why it asks first, and why the confirmation
 * names the day — see the long note in TrainingDayPanel.jsx about the day that
 * looked like it would not end.
 */

import { useEffect, useState } from 'react'
import { buildEndDayPayload, endedDayMessage, endTimeChoices, timestampLabel } from '../trainingDay.js'
import { elapsedLabel } from './sessionTiming.js'
import './SessionWidget.css'

// One tick a second, and only while a day is on screen. The timer is derived
// from `started_at`, so this interval exists purely to re-render — it holds no
// count of its own and cannot drift away from the truth.
function useNow(active) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return undefined
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [active])
  return now
}

export default function SessionWidget({ roomState, accessToken, onLogout, refresh, onDayEnded }) {
  const session = roomState?.session || null
  const simulated = Boolean(session && (session.is_simulated || session.simulated || roomState.meta?.session_is_simulated))
  const stale = Boolean(session?.opened_on_a_previous_day)
  const [confirming, setConfirming] = useState(false)
  // A corrected end time, only ever typed for a day that outlived a reboot.
  // Empty means "end it now", which is the normal case.
  const [endedAtOverride, setEndedAtOverride] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const now = useNow(Boolean(session))

  // Hooks must run every render, so the "nothing to show" exit comes after them.
  if (!session) return null

  const headers = { Accept: 'application/json', Authorization: `Bearer ${accessToken}` }

  async function endDay() {
    setBusy(true)
    setError('')
    try {
      // Ending a day is a PATCH on the session itself, not a POST to an end/
      // route (merge canon R2): "end the day" is "set its end time", and that
      // endpoint already did that. An empty body means "end it now"; a corrected
      // time is for the power-cut case, where the honest end time is when the
      // room actually emptied rather than when someone next managed to log in.
      const response = await fetch(`/api/sessions/${session.id}/`, {
        method: 'PATCH',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify(buildEndDayPayload(endedAtOverride)),
      })
      if (response.status === 401 || response.status === 403) { onLogout(); return }
      const body = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(body.detail || 'Training day could not be ended.')

      // The PATCH answers with a POINTER to the finished report, not the report
      // itself. We do not render it here — a finished day belongs in ANALYTICS,
      // not in a strip that floats over every state. Hand the pointer up and let
      // the coach be taken to it.
      setConfirming(false)
      setEndedAtOverride('')
      await refresh({ preserveSnapshot: true, forceAfterInFlight: true })
      onDayEnded?.({ reportId: body.daily_report?.id ?? null, message: endedDayMessage(body) })
    } catch (endError) {
      setError(endError.message || 'Training day could not be ended.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`coach-strip${stale ? ' is-stale' : ''}`} role="status" aria-label="Active training day">
      <div className="coach-strip-main">
        <span className="coach-strip-eyebrow">
          {simulated ? 'Simulation active' : stale ? 'Still open from an earlier day' : 'Active training day'}
        </span>
        <h3>{session.label}</h3>
        <p>
          {roomState.participants?.length || roomState.summary?.participant_count || 0} athletes
          {session.started_at ? ` · started ${timestampLabel(session.started_at)}` : ''}
        </p>
      </div>

      {/* Counted in the browser from `started_at`. No API sends this — see
          sessionTiming.js for why a number from the server would be stale on
          arrival. */}
      <div className="coach-strip-timer">
        <span className="coach-strip-eyebrow">Elapsed</span>
        <b>{elapsedLabel(session.started_at, now)}</b>
      </div>

      <div className="coach-strip-actions">
        {simulated
          // The simulator owns this day; ending it here would generate a report
          // for training that never happened.
          ? <p className="coach-strip-note">Stop or restart this from the simulation controls.</p>
          : confirming
            ? <div className="coach-strip-confirm" role="group" aria-label="Confirm end training day">
                <strong>End “{session.label}” and freeze its report?</strong>
                <label>Ended at
                  <select value={endedAtOverride} disabled={busy}
                    onChange={(event) => setEndedAtOverride(event.target.value)}>
                    {endTimeChoices(session.started_at).map((choice) => (
                      <option key={choice.value || 'now'} value={choice.value}>{choice.label}</option>
                    ))}
                  </select>
                </label>
                <div className="coach-strip-confirm-actions">
                  <button type="button" className="workout-secondary" disabled={busy}
                    onClick={() => { setConfirming(false); setEndedAtOverride(''); setError('') }}>Cancel</button>
                  <button type="button" disabled={busy} onClick={endDay}>
                    {busy ? 'Ending…' : 'Confirm end'}
                  </button>
                </div>
              </div>
            : <button type="button" className="coach-strip-end" onClick={() => setConfirming(true)}>
                End training day
              </button>}
      </div>

      {stale && !confirming && <p className="coach-strip-stale">
        Open since before today — most likely the base station restarted before anyone
        ended it. <b>Nothing was lost;</b> every set is saved. End it and set the time the
        room actually emptied so the report reads true.
      </p>}
      {error && <p className="coach-strip-error" role="alert">{error}</p>}
    </div>
  )
}
