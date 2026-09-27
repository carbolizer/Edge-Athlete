import { useEffect, useState } from 'react'
import { coachFetch } from './api.js'
import './RosterWorkspace.css' // Reuse roster CSS

export default function GroupsWorkspace({ accessToken, onLogout }) {
  const [groups, setGroups] = useState([])
  const [athletes, setAthletes] = useState([])
  const [selectedGroupId, setSelectedGroupId] = useState('')
  const [groupAthletes, setGroupAthletes] = useState([])
  
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  function failed(err) {
    if (err.status === 401 || err.status === 403) onLogout()
    else setError(err.message || 'The base station could not be reached.')
  }

  async function loadData() {
    setLoading(true)
    setError('')
    try {
      const [grpData, athData] = await Promise.all([
        coachFetch('/api/training-groups/', { token: accessToken }),
        coachFetch('/api/athletes/', { token: accessToken })
      ])
      setGroups(Array.isArray(grpData) ? grpData : grpData.results || [])
      setAthletes(Array.isArray(athData) ? athData : athData.results || [])
    } catch (err) { failed(err) }
    finally { setLoading(false) }
  }

  async function loadGroupAthletes(groupId) {
    if (!groupId) {
      setGroupAthletes([])
      return
    }
    try {
      const data = await coachFetch(`/api/training-groups/${groupId}/athletes/`, { token: accessToken })
      setGroupAthletes(data)
    } catch (err) { failed(err) }
  }

  useEffect(() => { loadData() }, [accessToken])
  
  useEffect(() => {
    loadGroupAthletes(selectedGroupId)
  }, [selectedGroupId, accessToken])

  async function createGroup(event) {
    event.preventDefault()
    if (busy || !name.trim()) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await coachFetch('/api/training-groups/', {
        token: accessToken, method: 'POST', body: { name: name.trim() }
      })
      setName('')
      setMessage('Training group created.')
      await loadData()
    } catch (err) { failed(err) }
    finally { setBusy(false) }
  }

  async function toggleAthlete(athleteId, inGroup) {
    if (!selectedGroupId || busy) return
    setBusy(true)
    setError('')
    try {
      await coachFetch(`/api/training-groups/${selectedGroupId}/athletes/`, {
        token: accessToken, 
        method: inGroup ? 'DELETE' : 'POST', 
        body: { athletes: [athleteId] }
      })
      await loadGroupAthletes(selectedGroupId)
    } catch (err) { failed(err) }
    finally { setBusy(false) }
  }

  return <section className="roster-workspace" aria-label="Training group management">
    <h2>Training Groups</h2>
    <p>A Training Group is a named subset of athletes who train the same plan. You can deploy workout blocks to a group.</p>
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    
    <form onSubmit={createGroup}>
      <h3>Create new group</h3>
      <label>Name<input required maxLength={255} value={name} disabled={busy} onChange={e => setName(e.target.value)} placeholder="Varsity" /></label>
      <button disabled={busy || !name.trim()}>{busy ? 'Saving…' : 'Create group'}</button>
    </form>

    {loading ? <p role="status">Loading groups…</p> : (
      <>
        <div style={{ marginTop: '20px' }}>
          <label>Manage Group Members: 
            <select value={selectedGroupId} onChange={e => setSelectedGroupId(e.target.value)} disabled={busy}>
              <option value="">Select a group...</option>
              {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          </label>
        </div>

        {selectedGroupId && (
          <ul style={{ marginTop: '20px' }}>
            {athletes.filter(a => a.is_active).map(athlete => {
              const inGroup = groupAthletes.some(ga => ga.id === athlete.id);
              return (
                <li key={athlete.id}>
                  <span>{athlete.name}</span>
                  <div>
                    <button disabled={busy} onClick={() => toggleAthlete(athlete.id, inGroup)}>
                      {inGroup ? 'Remove from group' : 'Add to group'}
                    </button>
                  </div>
                </li>
              )
            })}
            {athletes.filter(a => a.is_active).length === 0 && <li>No active athletes on the roster.</li>}
          </ul>
        )}
      </>
    )}
  </section>
}
