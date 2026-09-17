/*
 * GroupHistory.jsx — ANALYTICS → History, turned sideways.
 *
 * One row per member of a group instead of one row per training day of one
 * athlete. It answers the question a coach with a hundred athletes actually
 * has: not "what is Jordan doing" but "who has stopped showing up".
 *
 * ⚠️ THE EXPENSIVE ONE. See groupHistory.js — this costs 1 + N requests because
 * no group-scoped analytics route exists. It fetches in small batches rather
 * than firing twenty-eight requests at a Raspberry Pi at once, and it says on
 * screen what it cost, so the decision about adding `?group=` gets made on
 * evidence instead of vibes.
 */

import { useEffect, useState } from 'react'
import { BEHIND_DOWN_DAYS, BEHIND_OF_LAST, buildGroupRows } from './groupHistory.js'
import { rangeLabel } from './historyRange.js'

const groupAthletesUrl = (groupId) => `/api/training-groups/${groupId}/athletes/`
const athleteAnalyticsUrl = (athleteId) => `/api/analytics/athlete/${athleteId}/`

// Four at a time. The base station is a Raspberry Pi serving rack tablets that
// are mid-set — a burst of twenty-eight parallel analytics queries is a real
// way to make someone's live velocity feed stutter. Four keeps it responsive
// without making a squad take a minute to load.
const BATCH = 4

async function fetchInBatches(ids, load) {
  const results = {}
  for (let i = 0; i < ids.length; i += BATCH) {
    const slice = ids.slice(i, i + BATCH)
    const loaded = await Promise.all(slice.map((id) => load(id).catch(() => null)))
    slice.forEach((id, index) => { results[id] = loaded[index] })
  }
  return results
}

function velocityLabel(value) {
  return value === null || value === undefined ? '--' : Number(value).toFixed(2)
}

function signedLabel(value) {
  if (value === null || value === undefined) return ''
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}`
}

// `range` comes from the ANALYTICS bar and is shared with the athlete view —
// this used to own a window dropdown of its own, which meant the two halves of
// History could be looking at different stretches of time and neither said so.
export default function GroupHistory({ group, range, accessToken, onLogout }) {
  const [members, setMembers] = useState([])
  const [analytics, setAnalytics] = useState({})
  const [state, setState] = useState('loading')
  const [requestCount, setRequestCount] = useState(0)

  useEffect(() => {
    if (!group?.id) return undefined
    let cancelled = false
    setState('loading')
    setRequestCount(0)

    const headers = { Accept: 'application/json', Authorization: `Bearer ${accessToken}` }
    const json = async (url) => {
      const response = await fetch(url, { headers })
      if (response.status === 401 || response.status === 403) { onLogout(); return null }
      if (!response.ok) throw new Error(url)
      return response.json()
    }

    ;(async () => {
      try {
        const roster = await json(groupAthletesUrl(group.id))
        if (cancelled || roster === null) return
        const list = Array.isArray(roster) ? roster : roster.results || []
        setMembers(list)
        const loaded = await fetchInBatches(list.map((a) => a.id), (id) => json(athleteAnalyticsUrl(id)))
        if (cancelled) return
        setAnalytics(loaded)
        setRequestCount(1 + list.length)
        setState('ready')
      } catch {
        if (!cancelled) setState('error')
      }
    })()

    return () => { cancelled = true }
  }, [group?.id, accessToken, onLogout])

  if (!group) {
    return <p className="monitor-empty">Choose a group to see how its athletes are tracking.</p>
  }

  const rows = buildGroupRows(members, analytics, { range })
  const behindCount = rows.filter((row) => row.behind).length

  return (
    <div className="group-history">
      <div className="group-history-controls">
        {state === 'ready' && <span className="group-history-count">
          {rows.length} athlete{rows.length === 1 ? '' : 's'} · {rangeLabel(range).toLowerCase()}
          {behindCount > 0 && <b> · {behindCount} behind</b>}
        </span>}
      </div>

      {state === 'loading' && <p className="monitor-empty" role="status">
        Reading each athlete’s history…
      </p>}
      {state === 'error' && <p className="monitor-empty">This group’s history could not be loaded.</p>}

      {state === 'ready' && rows.length === 0 && (
        <p className="monitor-empty">Nobody is in this group yet.</p>
      )}

      {state === 'ready' && rows.length > 0 && <>
        <div className="history-table-wrap"><table className="history-table group-history-table">
          <caption>{group.name} — how each athlete is tracking</caption>
          <thead><tr>
            <th scope="col">Athlete</th><th scope="col">Last trained</th><th scope="col">Sets</th>
            <th scope="col">Avg velocity</th><th scope="col">Trend</th><th scope="col"><span className="visually-hidden">Status</span></th>
          </tr></thead>
          <tbody>{rows.map((row) => (
            <tr key={row.athlete.id} className={row.behind ? 'is-behind' : ''}>
              <td><b>{row.athlete.name}</b></td>
              <td>{row.lastTrainedLabel}</td>
              <td>{row.failed ? '--' : row.sets}</td>
              <td>{velocityLabel(row.avgVelocity)} <small>m/s</small></td>
              <td>
                {row.trend === 'up' && <span className="history-trend up">▲ {signedLabel(row.change)}</span>}
                {row.trend === 'down' && <span className="history-trend down">▼ {signedLabel(row.change)}</span>}
                {row.trend === 'flat' && <span className="history-trend flat">{signedLabel(row.change)}</span>}
                {!row.trend && <span className="history-trend flat">—</span>}
              </td>
              <td>
                {/* The count is on the tag on purpose — "Behind" alone invites
                    "behind on what?", and 4/5 answers it without a tooltip. */}
                {row.behind && <span className="group-history-tag" title={`Slower on ${row.downCount} of their last ${row.judgedOver} training days`}>
                  Behind {row.downCount}/{row.judgedOver}
                </span>}
                {row.failed && <span className="group-history-tag is-unknown">No data</span>}
                {!row.failed && row.noHistory && <span className="group-history-tag is-unknown">No history</span>}
              </td>
            </tr>
          ))}</tbody>
        </table></div>

        {/* Said out loud on purpose. Phase H's open decision is whether to add a
            `?group=` parameter, and that should be settled by a number a coach
            can see rather than by how it feels on a four-athlete demo. */}
        <p className="history-table-note">
          <b>Behind</b> means slower than the session before on at least {BEHIND_DOWN_DAYS} of the
          last {BEHIND_OF_LAST} training days — a pattern, not a bad night. Judged on the athlete’s whole
          history, so it does not move when the window does.
        </p>
        <p className="history-table-note">
          Built from <b>{requestCount} requests</b> — the group roster, then one per athlete. There is no
          group-scoped analytics route, so this is the cost today. Velocity pools every movement, the same
          caveat as the per-athlete view.
        </p>
      </>}
    </div>
  )
}
