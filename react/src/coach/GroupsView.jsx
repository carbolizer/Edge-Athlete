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
import {
  FILTER_ALL, FILTER_UNASSIGNED, filterRoster, indexMembership, isMember, unassignedCount,
} from './roster.js'
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


/*
 * The Groups tab: make a group, see who is in it, and put people in it.
 *
 * The roster below the group cards mirrors the athlete table — EVERY athlete in
 * the system — filtered to a group. That combination is the point: a coach
 * assigning people needs to see the ones who are not in the group yet, and a
 * view scoped to a group's own members structurally cannot show them.
 *
 * ⚠️ TWO THINGS THE API CANNOT DO, so they are absent rather than faked:
 * renaming a group and deleting one. There is no `training-groups/{id}/` detail
 * route — only the list (GET/POST) and the membership sub-route. Adding either
 * is a backend change, which this whole redesign is under instructions not to
 * make. Recorded here so the gap reads as known rather than forgotten.
 */
export default function GroupsView({ accessToken, onLogout }) {
  const [groups, setGroups] = useState([])
  const [athletes, setAthletes] = useState([])
  const [membersByGroup, setMembersByGroup] = useState({})
  const [state, setState] = useState('loading')
  const [openGroup, setOpenGroup] = useState(null)
  const [filter, setFilter] = useState(FILTER_ALL)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const headers = { Accept: 'application/json', Authorization: `Bearer ${accessToken}` }

  // One load for the whole tab. Group rosters are fetched per group — a few
  // requests, not one per athlete — see roster.js.
  async function load() {
    setError('')
    try {
      const json = async (url) => {
        const response = await fetch(url, { headers })
        if (response.status === 401 || response.status === 403) { onLogout(); return null }
        if (!response.ok) throw new Error(url)
        const body = await response.json()
        return Array.isArray(body) ? body : body.results || []
      }
      const [groupList, athleteList] = await Promise.all([json(TRAINING_GROUPS_URL), json('/api/athletes/')])
      if (groupList === null || athleteList === null) return
      const rosters = await Promise.all(groupList.map((group) => json(groupAthletesUrl(group.id))))
      setGroups(groupList)
      setAthletes(athleteList)
      setMembersByGroup(Object.fromEntries(groupList.map((group, i) => [group.id, rosters[i] || []])))
      setState('ready')
    } catch {
      setState('error')
    }
  }

  useEffect(() => { load() }, [accessToken])

  async function createGroup(event) {
    event.preventDefault()
    setBusy('create')
    setError('')
    try {
      const response = await fetch(TRAINING_GROUPS_URL, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName.trim() }),
      })
      if (response.status === 401 || response.status === 403) { onLogout(); return }
      const body = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(body.name?.[0] || body.detail || 'That group could not be created.')
      setNewName('')
      setCreating(false)
      await load()
    } catch (createError) {
      setError(createError.message || 'That group could not be created.')
    } finally {
      setBusy('')
    }
  }

  // Add or remove one athlete. Both are the same route with a different method
  // and the same {athletes:[id]} body — membership is current-state only, so
  // taking someone out never rewrites what they already trained.
  async function setMembership(group, athlete, join) {
    setBusy(`m-${athlete.id}`)
    setError('')
    try {
      const response = await fetch(groupAthletesUrl(group.id), {
        method: join ? 'POST' : 'DELETE',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ athletes: [athlete.id] }),
      })
      if (response.status === 401 || response.status === 403) { onLogout(); return }
      if (!response.ok) throw new Error('That change could not be saved.')
      const updated = await response.json()
      // The endpoint answers with the group's NEW roster, so take it rather than
      // patching local state and hoping the two agree.
      setMembersByGroup((current) => ({ ...current, [group.id]: Array.isArray(updated) ? updated : [] }))
      setGroups((current) => current.map((g) =>
        g.id === group.id ? { ...g, athlete_count: (Array.isArray(updated) ? updated : []).length } : g))
    } catch (membershipError) {
      setError(membershipError.message || 'That change could not be saved.')
    } finally {
      setBusy('')
    }
  }

  if (openGroup) {
    return <div className="groups-view context-tab-content">
      <OpenGroup group={openGroup} accessToken={accessToken} onLogout={onLogout}
        onBack={() => setOpenGroup(null)} />
    </div>
  }

  const index = indexMembership(groups, membersByGroup)
  const rows = filterRoster(athletes, index, filter)
  const stranded = unassignedCount(athletes, index)
  const filterGroup = groups.find((group) => group.id === filter) || null

  return (
    <div className="groups-view context-tab-content">
      <header className="workout-catalog-heading">
        <div>
          <span>Who you are planning for</span>
          <h2>Training groups</h2>
          <p>Blocks are deployed to a group, and the calendar shows a group’s days. An athlete can be in more than one.</p>
        </div>
        <b>{groups.length} group{groups.length === 1 ? '' : 's'} · {athletes.length} athlete{athletes.length === 1 ? '' : 's'}</b>
      </header>

      {state === 'loading' && <p className="monitor-empty" role="status">Loading groups and roster…</p>}
      {state === 'error' && <p className="monitor-empty">Groups could not be loaded.</p>}
      {error && <p className="coach-login-error" role="alert">{error}</p>}

      {state === 'ready' && <>
        <div className="design-create-row">
          {creating
            ? <form className="groups-create" onSubmit={createGroup}>
                <input value={newName} onChange={(e) => setNewName(e.target.value)} maxLength={255}
                  placeholder="Varsity Football" aria-label="New group name" autoFocus />
                <button type="submit" disabled={!newName.trim() || busy === 'create'}>
                  {busy === 'create' ? 'Creating…' : 'Create'}
                </button>
                <button type="button" className="workout-secondary"
                  onClick={() => { setCreating(false); setNewName('') }}>Cancel</button>
              </form>
            : <button type="button" className="groups-create-open" onClick={() => setCreating(true)}>
                + New group
              </button>}
          {/* Not a warning unless it is one — zero stranded athletes says
              nothing at all rather than a green tick nobody needs. */}
          {stranded > 0 && <button type="button" className="groups-stranded"
            onClick={() => setFilter(FILTER_UNASSIGNED)}>
            {stranded} athlete{stranded === 1 ? '' : 's'} in no group
          </button>}
        </div>

        <div className="groups-list">
          {groups.map((group) => (
            <article className="groups-card" key={group.id}>
              <div>
                <span className="groups-eyebrow">Group</span>
                <h3>{group.name}</h3>
                <p>{membersByGroup[group.id]?.length ?? group.athlete_count ?? 0} athlete
                  {(membersByGroup[group.id]?.length ?? group.athlete_count) === 1 ? '' : 's'} · {coachLine(group)}</p>
              </div>
              <button type="button" onClick={() => setOpenGroup(group)}>Open</button>
            </article>
          ))}
        </div>

        {/* The roster. Every athlete in the system, filtered — which is what
            makes assigning possible: you cannot add someone to a group from a
            list that only shows the group's existing members. */}
        <section className="workout-panel groups-roster-panel">
          <header>
            <div>
              <span>Roster</span>
              <h3>Every athlete</h3>
              <p>{filterGroup
                ? `Members of ${filterGroup.name} first, then everyone else — so you can add as well as remove.`
                : 'Pick a group to add or remove people. Athletes are created by importing a roster.'}</p>
            </div>
            <b>{filterGroup
              ? `${membersByGroup[filterGroup.id]?.length ?? 0} of ${athletes.length} in ${filterGroup.name}`
              : `${rows.length} shown`}</b>
          </header>

          <div className="groups-filter" role="group" aria-label="Filter roster by group">
            <button type="button" className={filter === FILTER_ALL ? 'is-on' : ''}
              onClick={() => setFilter(FILTER_ALL)}>All</button>
            {groups.map((group) => (
              <button key={group.id} type="button" className={filter === group.id ? 'is-on' : ''}
                onClick={() => setFilter(group.id)}>{group.name}</button>
            ))}
            <button type="button" className={filter === FILTER_UNASSIGNED ? 'is-on' : ''}
              onClick={() => setFilter(FILTER_UNASSIGNED)}>No group</button>
          </div>

          {rows.length === 0
            ? <p className="monitor-empty">
                {filter === FILTER_UNASSIGNED ? 'Everyone is in at least one group.' : 'Nobody here yet.'}
              </p>
            : <div className="history-table-wrap"><table className="history-table groups-roster-table">
                <caption>Athletes, filtered</caption>
                <thead><tr>
                  <th scope="col">Athlete</th><th scope="col">Groups</th>
                  <th scope="col">{filterGroup ? filterGroup.name : ''}</th>
                </tr></thead>
                <tbody>{rows.map((athlete) => {
                  const memberOf = index.get(athlete.id) || []
                  const inFilterGroup = filterGroup && isMember(index, athlete.id, filterGroup.id)
                  return <tr key={athlete.id} className={inFilterGroup ? 'is-member' : ''}>
                    <td><b>{athlete.name}</b></td>
                    <td>{memberOf.length === 0
                      ? <span className="groups-none">No group</span>
                      : memberOf.map((group) => <span className="groups-chip" key={group.id}>{group.name}</span>)}</td>
                    <td>
                      {/* Only when a real group is selected — "add to All" is
                          not a thing, and neither is "add to No group". */}
                      {filterGroup && <button type="button" className="groups-member-toggle"
                        disabled={busy === `m-${athlete.id}`}
                        onClick={() => setMembership(filterGroup, athlete, !isMember(index, athlete.id, filterGroup.id))}>
                        {busy === `m-${athlete.id}` ? '…' : inFilterGroup ? 'Remove' : 'Add'}
                      </button>}
                    </td>
                  </tr>
                })}</tbody>
              </table></div>}

          {/* A gap, said out loud. */}
          <p className="history-table-note">
            Renaming and deleting groups are not here — the API has no group detail route, only the list
            and its membership. Both would be backend changes.
          </p>
        </section>
      </>}
    </div>
  )
}
