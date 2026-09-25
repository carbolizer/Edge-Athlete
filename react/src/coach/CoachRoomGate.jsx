import { useCallback, useEffect, useState } from 'react'
import { fetchCurrentCoach, getCoachToken, setCoachToken } from './api.js'
import CoachAccess from './CoachAccess.jsx'
import ChangePassword from './ChangePassword.jsx'
import { navigate } from '../router.js'

// No private children mount until the server confirms the current assignment.
export default function CoachRoomGate({ roomId, canonical = false, children }) {
  const [token, setToken] = useState(() => getCoachToken())
  const [session, setSession] = useState(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [changingPassword, setChangingPassword] = useState(false)
  const reload = () => { setSession(null); setRevision(n => n + 1) }
  const logout = useCallback(() => {
    setCoachToken(null)
    setToken(null)
    setSession(null)
    setChangingPassword(false)
  }, [])
  useEffect(() => {
    let current = true
    setSession(null)
    setError('')
    if (token) fetchCurrentCoach(token).then(me => {
      if (current) setSession({ token, me })
    }).catch(err => {
      if (!current) return
      if (err.status === 401) logout()
      else setError(err.message || 'The base station could not confirm your account.')
    })
    return () => { current = false }
  }, [token, revision])
  const me = session?.token === token ? session.me : null
  const room = me?.weight_room
  const wrongRoom = roomId != null && String(roomId) !== String(room?.id)
  useEffect(() => {
    if (canonical && room && !wrongRoom && !me.must_change_password && !changingPassword && roomId == null) {
      navigate(room.dashboard_path, { replace: true })
    }
  }, [canonical, room, wrongRoom, me, changingPassword, roomId])

  if (!token) return <CoachAccess onLoggedIn={setToken} />
  if (error) return <main className="monitor coach-login-screen"><section className="coach-login-card">
    <h1>Coach view unavailable</h1><p role="alert">{error}</p><button onClick={reload}>Retry</button><button onClick={logout}>Sign out</button>
  </section></main>
  if (!me) return <main className="monitor"><p role="status">Checking your account…</p></main>
  if (me.must_change_password || changingPassword) return <ChangePassword accessToken={token}
    forced={me.must_change_password} onChanged={() => { setChangingPassword(false); reload() }} onLogout={logout} />
  if (!room || wrongRoom) return <main className="monitor coach-login-screen"><section className="coach-login-card">
    <h1>{wrongRoom && room ? 'Dashboard access denied' : 'No weight room assigned'}</h1>
    <p>{wrongRoom && room ? 'This dashboard is not assigned to your account.' : 'Ask your administrator to assign your account to this weight room.'}</p>
    {room && <button onClick={() => navigate(room.dashboard_path)}>Open my dashboard</button>}
    {!room && <button onClick={reload}>Check assignment again</button>}
    <button onClick={logout}>Sign out</button>
  </section></main>
  if (canonical && roomId == null) return <p role="status">Opening your dashboard…</p>
  return <><div className="coach-room-identity" role="note">{room.school.name} · {room.name}</div>
    {children({ token, me, logout, changePassword: () => setChangingPassword(true) })}</>
}
