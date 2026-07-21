// rack/CheckInList.jsx — the tap-in / scan-in athlete list.
//
// ── WHY THIS FILE EXISTS (plain version) ───────────────────────────────────────
// The same "who's lifting?" list is needed in two places: the idle check-in screen
// AND the rest screen (a rack is shared — while one athlete rests, the next can tap
// in and take their set). So the list lives here, shared by both.
//
// Each card shows the athlete's LIVE status + a ticking timer, from the room-state
// endpoint (GET /api/sessions/active/status/):
//   • Lifting · 0:48   — how long they've been in the current set
//   • Resting · 1:32   — how long since their last set ended
//   • Ready · 0:20     — how long since they checked in
// The server sends a "since" timestamp per athlete; the tablet turns it into a
// timer by ticking a local clock once a second (so we don't poll the server every
// second). A coach tablet can read the same endpoint later.

import { useEffect, useState } from 'react'
import { T } from '../theme.js'

const LABEL = {
  fontSize: 10, fontWeight: 900, letterSpacing: '.14em',
  textTransform: 'uppercase', color: T.muted,
}

// How each status reads on a card. `not_started` shows nothing.
const STATUS = {
  lifting: { label: 'Lifting', color: T.mint },
  resting: { label: 'Resting', color: T.amber },
  ready: { label: 'Ready', color: T.lime },
}

// A clock that re-renders once a second, so the timers tick without re-fetching.
function useNow() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

// "M:SS" elapsed since an ISO timestamp, or null if there's nothing to count.
function elapsed(sinceISO, now) {
  if (!sinceISO) return null
  const secs = Math.max(0, Math.floor((now - new Date(sinceISO).getTime()) / 1000))
  return `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`
}

function AthleteCard({ athlete, status, now, onSelect }) {
  const st = status && STATUS[status.status]
  const time = st ? elapsed(status.since, now) : null
  return (
    <button onClick={() => onSelect(athlete)} style={ROW}>
      <span style={{ fontSize: 17, fontWeight: 700 }}>{athlete.name}</span>
      {st && (
        <span style={{ ...LABEL, color: st.color }}>
          {st.label}{time ? ` · ${time}` : ''}
        </span>
      )}
    </button>
  )
}

// A titled, scrollable box of athletes. The inner box scrolls (groups can be large)
// while the titles + NFC hint stay put — same box for "At this rack" and the group.
function Group({ title, athletes, statusMap, onSelect, now, accent = T.muted }) {
  if (!athletes || athletes.length === 0) return null
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ ...LABEL, color: accent, marginBottom: 8 }}>{title}</div>
      <div style={{ maxHeight: 360, overflowY: 'auto', display: 'flex', flexDirection: 'column',
        gap: 8, paddingRight: 4 }}>
        {athletes.map((a) => (
          <AthleteCard key={a.athlete_id} athlete={a} status={statusMap?.[a.athlete_id]}
            now={now} onSelect={onSelect} />
        ))}
      </div>
    </div>
  )
}

// A purely-decorative NFC affordance under the list — hints at the future "tap your
// band to sign in" flow (NFC itself is out of scope this phase) and fills the empty
// space on a tall portrait screen. Not interactive.
function NfcHint() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginTop: 40 }}>
      <style>{'@keyframes eaNfcPulse{0%,100%{transform:scale(1);opacity:.5}50%{transform:scale(1.06);opacity:1}}'}</style>
      <div style={{ width: 96, height: 96, borderRadius: '50%', border: `2px dashed ${T.line}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 14,
        animation: 'eaNfcPulse 2.4s ease-in-out infinite' }}>
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke={T.muted}
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 9a4.5 4.5 0 0 1 0 6" />
          <path d="M9.5 6.5a9 9 0 0 1 0 11" />
          <path d="M13 4a13 13 0 0 1 0 16" />
        </svg>
      </div>
      <div style={{ fontSize: 13, color: T.muted, fontWeight: 600, letterSpacing: '-.01em' }}>
        Tap your name — or scan your NFC band
      </div>
    </div>
  )
}

export default function CheckInList({ roster, hotList, groupName, statusMap, onSelect }) {
  const now = useNow()
  const list = roster ?? []
  const hotIds = new Set((hotList ?? []).map((h) => h.athlete_id))
  // Sort by SURNAME (last word of the single name field), full-name tiebreak — a
  // stopgap until athletes have structured first/last names.
  const surname = (a) => a.name.trim().split(/\s+/).pop() || a.name
  const byName = (a, b) => surname(a).localeCompare(surname(b)) || a.name.localeCompare(b.name)
  const hot = list.filter((a) => hotIds.has(a.athlete_id)).sort(byName)
  const rest = list.filter((a) => !hotIds.has(a.athlete_id)).sort(byName)
  return (
    <>
      {list.length === 0 && (
        <div style={{ color: T.muted, fontSize: 14, marginBottom: 18 }}>No athletes in this session.</div>
      )}
      <Group title="At this rack" accent={T.lime} athletes={hot} statusMap={statusMap} onSelect={onSelect} now={now} />
      <Group title={groupName || 'Athletes'} athletes={rest} statusMap={statusMap} onSelect={onSelect} now={now} />
      <NfcHint />
    </>
  )
}

const ROW = { display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  padding: '16px 18px', borderRadius: 12, border: `1px solid ${T.line}`, background: T.panel,
  color: T.ink, cursor: 'pointer', fontFamily: 'inherit', width: '100%' }
