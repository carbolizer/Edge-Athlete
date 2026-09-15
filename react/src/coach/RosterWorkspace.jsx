import { useEffect, useState } from 'react'
import { coachFetch } from './api.js'
import './RosterWorkspace.css'

export default function RosterWorkspace({ accessToken, onLogout, onChanged }) {
  const [athletes, setAthletes] = useState([])
  const [editing, setEditing] = useState(null)
  const [name, setName] = useState('')
  const [tag, setTag] = useState('')
  const [replaceTag, setReplaceTag] = useState(false)
  const [archived, setArchived] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  function failed(err) {
    if (err.status === 401 || err.status === 403) onLogout()
    else setError(err.message || 'The base station could not be reached.')
  }
  async function load() {
    setLoading(true)
    setError('')
    try {
      setAthletes(await coachFetch('/api/athletes/?include_archived=true', { token: accessToken }))
    } catch (err) { failed(err) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [accessToken])

  function reset() {
    setEditing(null)
    setName('')
    setTag('')
    setReplaceTag(false)
  }
  async function save(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const body = { name: name.trim() }
      // Tags are write-only. Editing a name must not silently erase a tag.
      if (!editing || replaceTag) body.nfc_tag_id = tag.trim() || null
      await coachFetch(editing ? `/api/athletes/${editing.id}/` : '/api/athletes/', {
        token: accessToken, method: editing ? 'PATCH' : 'POST', body,
      })
      reset()
      setMessage('Team member saved.')
      await load()
      onChanged()
    } catch (err) { failed(err) }
    finally { setBusy(false) }
  }
  async function remove(athlete) {
    if (!window.confirm(`Remove ${athlete.name} from the roster? Saved workouts and reports will be retained.`)) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await coachFetch(`/api/athletes/${athlete.id}/`, { token: accessToken, method: 'DELETE' })
      if (editing?.id === athlete.id) reset()
      setMessage('Team member removed. Workout history retained.')
      await load()
      onChanged()
    } catch (err) { failed(err) }
    finally { setBusy(false) }
  }

  return <section className="roster-workspace" aria-label="Team member management">
    <h2>Team roster</h2>
    <p>Removing a member archives their record and preserves saved workouts and reports.</p>
    {error && <p role="alert">{error} <button onClick={load} disabled={busy || loading}>Retry</button></p>}
    {message && <p role="status">{message}</p>}
    <form onSubmit={save}>
      <h3>{editing ? `Edit ${editing.name}` : 'Add team member'}</h3>
      <label>Name<input required maxLength={255} value={name} disabled={busy} onChange={e => setName(e.target.value)} /></label>
      {editing && <label><input type="checkbox" checked={replaceTag} onChange={e => setReplaceTag(e.target.checked)} disabled={busy} />Replace or clear NFC tag</label>}
      {(!editing || replaceTag) && <label>NFC tag (optional)<input maxLength={255} value={tag} onChange={e => setTag(e.target.value)} disabled={busy} /></label>}
      <button disabled={busy || !name.trim()}>{busy ? 'Saving…' : editing ? 'Save changes' : 'Add member'}</button>
      {editing && <button type="button" onClick={reset} disabled={busy}>Cancel</button>}
    </form>
    <label><input type="checkbox" checked={archived} onChange={e => setArchived(e.target.checked)} />Show archived members</label>
    {loading ? <p role="status">Loading roster…</p> : <ul>
      {athletes.filter(a => archived || a.is_active).map(athlete => <li key={athlete.id}>
        <span>{athlete.name}{!athlete.is_active && ' (archived)'}</span>
        {athlete.is_active && <div>
          <button disabled={busy} onClick={() => { setEditing(athlete); setName(athlete.name); setTag(''); setReplaceTag(false) }}>Edit</button>
          <button disabled={busy} onClick={() => remove(athlete)}>Remove</button>
        </div>}
      </li>)}
      {!athletes.some(a => archived || a.is_active) && <li>No team members yet.</li>}
    </ul>}
  </section>
}
