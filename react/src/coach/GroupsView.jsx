/*
 * GroupsView.jsx — PLANNING's "who am I planning for" tab, and the way into one
 * athlete's plan.
 *
 * Two levels:
 *
 *   THE LIST     Every training group: how many athletes, which coaches run it.
 *                It exists because everything else in PLANNING is scoped to a
 *                group — you deploy a block TO a group, the calendar shows a
 *                group's days — and there was nowhere to see what the groups
 *                actually were. The deploy dropdown listed names and nothing more.
 *
 *   ONE GROUP    Its athletes, and for whichever one you pick, their assigned
 *                plans and per-athlete overrides (`AthleteWorkoutPlanning`).
 *
 * WHY THAT COMPONENT LIVES HERE. Assigning an athlete to a plan IS putting them
 * in the group that runs it — `AthleteWorkoutPlanning`'s own header says so, and
 * the server answers with which groups changed. So the screen where a coach
 * changes group membership and the screen where they look at groups should not
 * be two different screens. It used to sit inside ANALYTICS → Programs, where a
 * coach edited group membership from a tab that never mentioned groups.
 *
 * It also makes the card's "28 athletes" mean something. That number was the one
 * thing on a group card a coach could not act on.
 *
 * ⚠️ STILL READ-ONLY ABOUT THE GROUP ITSELF. Creating a group, renaming one,
 * moving an athlete between groups, assigning coaches — none of those exist as
 * UI anywhere today (groups come from importing a roster), and building them
 * here would be new product rather than the re-shelving this phase is. What IS
 * editable is one athlete's plan, which is what the drill-down is for.
 */

import { useEffect, useState } from 'react'
import AthleteWorkoutPlanning from '../AthleteWorkoutPlanning.jsx'
import './GroupsView.css'

const TRAINING_GROUPS_URL = '/api/training-groups/'
const groupAthletesUrl = (groupId) => `${TRAINING_GROUPS_URL}${groupId}/athletes/`

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

// One group opened: its athletes, and the plan of whichever one is selected.
function OpenGroup({ group, accessToken, onLogout, onBack }) {
  const [athletes, setAthletes] = useState([])
  const [state, setState] = useState('loading')
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    let cancelled = false
    setState('loading')
    setSelected(null)
    fetch(groupAthletesUrl(group.id), {
      headers: { Accept: 'application/json', Authorization: `Bearer ${accessToken}` },
    })
      .then((response) => {
        if (response.status === 401 || response.status === 403) { onLogout(); return null }
        if (!response.ok) throw new Error('roster unavailable')
        return response.json()
      })
      .then((body) => {
        if (cancelled || body === null) return
        setAthletes(Array.isArray(body) ? body : body.results || [])
        setState('ready')
      })
      .catch(() => { if (!cancelled) setState('error') })
    return () => { cancelled = true }
  }, [group.id, accessToken, onLogout])

  return (
    <div className="groups-open">
      <header className="workout-catalog-heading">
        <div>
          <span>Group</span>
          <h2>{group.name}</h2>
          <p>{coachLine(group)}</p>
        </div>
        <button type="button" className="workout-secondary" onClick={onBack}>← All groups</button>
      </header>

      {state === 'loading' && <p className="monitor-empty" role="status">Loading the roster…</p>}
      {state === 'error' && <p className="monitor-empty">This group’s athletes could not be loaded.</p>}
      {state === 'ready' && athletes.length === 0 && (
        <p className="monitor-empty">Nobody is in this group yet. Athletes join a group when a roster is imported.</p>
      )}

      {athletes.length > 0 && <section className="workout-panel">
        <header><span>Roster</span><h3>{athletes.length} athlete{athletes.length === 1 ? '' : 's'}</h3><p>Pick one to see the plans they are on and any exceptions written for them.</p></header>
        <div className="groups-roster">
          {athletes.map((athlete) => (
            <button type="button" key={athlete.id}
              className={selected?.id === athlete.id ? 'is-on' : ''}
              aria-pressed={selected?.id === athlete.id}
              onClick={() => setSelected(selected?.id === athlete.id ? null : athlete)}>
              {athlete.name}
            </button>
          ))}
        </div>
      </section>}

      {/* One guard at the boundary rather than one inside every panel below —
          the same collapse the coach screen already did for its four "choose an
          athlete" messages. */}
      {selected
        ? <AthleteWorkoutPlanning athlete={selected} accessToken={accessToken} onLogout={onLogout} />
        : athletes.length > 0 && <p className="monitor-empty">No athlete selected.</p>}
    </div>
  )
}

export default function GroupsView({ accessToken, onLogout }) {
  const [groups, setGroups] = useState([])
  const [state, setState] = useState('loading')
  const [openGroup, setOpenGroup] = useState(null)

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

  if (openGroup) {
    return <div className="groups-view context-tab-content">
      <OpenGroup group={openGroup} accessToken={accessToken} onLogout={onLogout}
        onBack={() => setOpenGroup(null)} />
    </div>
  }

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
            <button type="button" onClick={() => setOpenGroup(group)}>Open</button>
          </article>
        ))}
      </div>
    </div>
  )
}
