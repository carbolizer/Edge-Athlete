/*
 * DevPanel.jsx — ⚠️ TEMPORARY DEV TOOLING. Delete this file when you're done.
 * ---------------------------------------------------------------------------
 * Two buttons so you can get a demo running without a terminal:
 *
 *   "Seed demo gym"   — rebuilds the whole fake gym (session, four athletes,
 *                       their plans, a couple of completed sets). What you want
 *                       after wiping the database. DESTRUCTIVE to demo data.
 *   "Start empty session" — the real production call. Creates one live session
 *                       with everyone currently registered, and nothing else.
 *
 * WHY BOTH: seeding fabricates a believable gym out of nothing; starting a
 * session is the actual thing a coach does once athletes already exist. They
 * are not interchangeable — an empty session has nobody to lift.
 *
 * DELETING THIS (about 15 seconds):
 *   1. delete this file
 *   2. delete the two DevPanel lines in CoachTablet.jsx (both marked DEV-ONLY)
 *   3. backend: delete django/event_handler/dev_views.py + its one urls.py line
 * Nothing imports this but CoachTablet, and it imports nothing of its own
 * beyond the shared fetch helper — so removal cannot break anything else.
 *
 * Everything here is deliberately self-contained: styles are inline rather than
 * in CoachTablet.css, so deleting the file leaves no orphaned CSS behind.
 */

import { useState } from 'react'
import { coachFetch } from './api.js'

const box = {
  marginTop: 24, padding: 16, borderRadius: 10,
  border: '1px dashed #b45309', background: 'rgba(180, 83, 9, .06)',
}
const row = { display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 10 }
const btn = {
  padding: '8px 14px', borderRadius: 8, border: '1px solid #b45309',
  background: 'transparent', color: 'inherit', cursor: 'pointer', font: 'inherit',
}

export default function DevPanel({ token }) {
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState(null)

  // One handler for both buttons: run the work, report what happened in plain
  // language, and never leave a button stuck spinning if it fails.
  async function run(which, work) {
    setBusy(which)
    setMessage(null)
    try {
      setMessage({ ok: true, text: await work() })
    } catch (error) {
      setMessage({ ok: false, text: error.message || 'failed' })
    } finally {
      setBusy('')
    }
  }

  const seed = () => run('seed', async () => {
    await coachFetch('/api/dev/seed-session/', { token, method: 'POST', body: {} })
    return 'Demo gym rebuilt — session, athletes, plans and sets are in. Reload a rack screen.'
  })

  const startSession = () => run('start', async () => {
    // A session with nobody in it is useless, so pull the current roster and
    // put everyone in. This is the ordinary production endpoint, not a dev one.
    const athletes = await coachFetch('/api/athletes/', { token })
    if (!athletes.length) {
      throw new Error('No athletes registered yet — use "Seed demo gym" first.')
    }
    const label = `Session — ${new Date().toLocaleString()}`
    const created = await coachFetch('/api/sessions/', {
      token, method: 'POST',
      body: { label, athletes: athletes.map((a) => a.id) },
    })
    return `Started "${created.label}" with ${athletes.length} athlete(s).`
  })

  return (
    <section style={box}>
      <h2 style={{ margin: 0, fontSize: 15 }}>⚠️ Dev tools (temporary)</h2>
      <p style={{ margin: '6px 0 0', fontSize: 13, opacity: .75 }}>
        Shortcuts so a demo doesn’t need a terminal. This panel gets deleted before release.
      </p>

      <div style={row}>
        <button type="button" style={btn} onClick={seed} disabled={!!busy}>
          {busy === 'seed' ? 'Seeding…' : 'Seed demo gym'}
        </button>
        <button type="button" style={btn} onClick={startSession} disabled={!!busy}>
          {busy === 'start' ? 'Starting…' : 'Start empty session'}
        </button>
      </div>

      {message && (
        <p style={{ marginTop: 10, fontSize: 13, color: message.ok ? '#15803d' : '#b91c1c' }}>
          {message.text}
        </p>
      )}

      <p style={{ margin: '10px 0 0', fontSize: 12, opacity: .6 }}>
        “Seed demo gym” wipes and recreates the demo athletes — it refuses to run unless the
        server is in debug mode. “Start empty session” is the real endpoint a coach would use.
      </p>
    </section>
  )
}
