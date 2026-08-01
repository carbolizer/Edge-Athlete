/*
 * GroupsView.jsx — PLANNING's "who am I planning for" tab.
 *
 * A read-only list of the training groups in the department: how many athletes
 * are in each, and which coaches run it. It exists because every other thing in
 * PLANNING is scoped to a group — you deploy a block TO a group, the calendar
 * shows a group's days — and there was nowhere to see what the groups actually
 * were. The deploy dropdown listed their names and nothing else.
 *
 * ⚠️ IT ONLY LOOKS. Creating groups, moving athletes between them and assigning
 * coaches are not here, because none of those exist as UI anywhere yet and
 * inventing them would be new product rather than the re-shelving this phase is.
 * Groups are currently made by importing a spreadsheet or in the Django admin.
 *
 * SEVERAL COACHES RUN ONE GROUP. `coaches` is a list, not one name — that
 * replaced a single `coach` field in P11. `head_coach` is the one who answers
 * for the group and can be null if nobody holds the role, so this never assumes
 * there is one.
 */

import { useEffect, useState } from 'react'
import './GroupsView.css'

const TRAINING_GROUPS_URL = '/api/training-groups/'

// "Sarah Kemp (head), Mike Ross" — the head first, because on a screen a coach
// scans rather than reads, the name that matters is the one who answers for it.
function coachLine(group) {
  const head = group.head_coach?.name || null
  const others = (group.coaches || [])
    .map((link) => link.coach_name || link.name || link.coach?.username)
    .filter((name) => name && name !== head)
  if (!head && others.length === 0) return 'No coaches assigned'
  return [head && `${head} (head)`, ...others].filter(Boolean).join(', ')
}

export default function GroupsView({ accessToken, onLogout }) {
  const [groups, setGroups] = useState([])
  const [state, setState] = useState('loading')

  useEffect(() => {
    let cancelled = false
    fetch(TRAINING_GROUPS_URL, {
      headers: { Accept: 'application/json', Authorization: `Bearer ${accessToken}` },
    })
      .then((response) => {
        if (response.status === 401 || response.status === 403) { onLogout(); return null }
        if (!response.ok) throw new Error('groups unavailable')
        return response.json()
      })
      .then((body) => {
        if (cancelled || body === null) return
        setGroups(Array.isArray(body) ? body : body.results || [])
        setState('ready')
      })
      .catch(() => { if (!cancelled) setState('error') })
    return () => { cancelled = true }
  }, [accessToken, onLogout])

  return (
    <div className="groups-view context-tab-content">
      <header className="workout-catalog-heading">
        <div>
          <span>Who you are planning for</span>
          <h2>Training groups</h2>
          <p>Blocks are deployed to a group, and the calendar shows a group’s days. Groups are created by importing a roster.</p>
        </div>
        <b>{groups.length} group{groups.length === 1 ? '' : 's'}</b>
      </header>

      {state === 'loading' && <p className="monitor-empty" role="status">Loading groups…</p>}
      {state === 'error' && <p className="monitor-empty">Groups could not be loaded.</p>}
      {state === 'ready' && groups.length === 0 && (
        <p className="monitor-empty">
          No groups yet. Import a roster from the Design tab and a group is created from it.
        </p>
      )}

      <div className="groups-list">
        {groups.map((group) => (
          <article className="groups-card" key={group.id}>
            <div>
              <span className="groups-eyebrow">Group</span>
              <h3>{group.name}</h3>
              <p>{group.athlete_count ?? 0} athlete{group.athlete_count === 1 ? '' : 's'} · {coachLine(group)}</p>
            </div>
          </article>
        ))}
      </div>
    </div>
  )
}
