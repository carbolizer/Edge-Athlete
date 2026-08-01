/*
 * QuickNote.jsx — a thought about the athlete at the rack you are looking at.
 *
 * SESSION's only athlete-scoped control, and deliberately the only one. The rack
 * screen already shows an athlete their own day and the coach wrote the plan, so
 * there is nothing else about one person a coach needs mid-floor. What they do
 * need is somewhere to put "shoulder looked off on set 3" before they forget it.
 *
 * WHY IT HAS NO ATHLETE PICKER. During a session the room view IS the picker,
 * and it picks the way a coach actually thinks — "whoever is at that rack", not
 * "find a name in a list of ninety". Select a rack, the note follows.
 *
 * ✅ CONSEQUENCE, ACCEPTED ON PURPOSE: an athlete who has not checked in at any
 * rack cannot be written about here. That is who a coach has thoughts about
 * during training — the people on the floor. A note about someone who did not
 * show up waits for ANALYTICS, where the full athlete selector lives.
 *
 * ⚠️ IT APPENDS, IT DOES NOT REPLACE. Same `Athlete.notes` column the ANALYTICS
 * notes tab edits. See quickNote.js for why setting that field from here would
 * silently destroy someone else's writing, and for the last-write-wins window
 * that appending narrows but does not close.
 */

import { useState } from 'react'
import { appendQuickNote } from './quickNote.js'
import './QuickNote.css'

export default function QuickNote({ athlete, rackNumber, accessToken, onLogout }) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  if (!athlete?.id) {
    return (
      <section className="quick-note is-empty">
        <span className="quick-note-eyebrow">Quick note</span>
        <p>
          Nobody has checked in at rack {rackNumber ?? '--'} yet. Notes here follow whoever
          is on the rack; for anyone else, use Analytics.
        </p>
      </section>
    )
  }

  const headers = { Accept: 'application/json', Authorization: `Bearer ${accessToken}` }

  async function save() {
    setBusy(true)
    setStatus('')
    setError('')
    try {
      // Read first, then write. The note is one text column with no version to
      // compare against, so the current value has to come from the server —
      // anything cached here could be older than what another coach just saved.
      const current = await fetch(`/api/athletes/${athlete.id}/`, { headers })
      if (current.status === 401 || current.status === 403) { onLogout(); return }
      if (!current.ok) throw new Error('Could not read this athlete’s notes.')
      const record = await current.json()

      const response = await fetch(`/api/athletes/${athlete.id}/`, {
        method: 'PATCH',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: appendQuickNote(record.notes, draft) }),
      })
      if (response.status === 401 || response.status === 403) { onLogout(); return }
      const body = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(body.detail || 'The note could not be saved.')

      setDraft('')
      setStatus(`Saved to ${athlete.name}.`)
    } catch (saveError) {
      setError(saveError.message || 'The note could not be saved.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="quick-note">
      <header>
        <div>
          <span className="quick-note-eyebrow">Quick note</span>
          <h3>{athlete.name}</h3>
        </div>
        <b>Rack {rackNumber ?? '--'}</b>
      </header>
      <textarea
        aria-label={`Quick note about ${athlete.name}`}
        value={draft}
        rows={2}
        maxLength={2000}
        placeholder="Shoulder looked off on set 3…"
        disabled={busy}
        onChange={(event) => { setDraft(event.target.value); setStatus('') }}
      />
      <div className="quick-note-actions">
        {/* Says "adds to" rather than "saves", because that is the difference
            between this and the ANALYTICS notes tab, and a coach should be able
            to tell without trying it. */}
        <small>Adds to this athlete’s notes — nothing already written is replaced.</small>
        <button type="button" disabled={busy || !draft.trim()} onClick={save}>
          {busy ? 'Saving…' : 'Add note'}
        </button>
      </div>
      {status && <p className="quick-note-status" role="status">{status}</p>}
      {error && <p className="quick-note-error" role="alert">{error}</p>}
    </section>
  )
}
