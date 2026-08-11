import { useEffect } from 'react'
import HostedRack from './rack/HostedRack.jsx'
import CoachRackPairing from './coach/CoachRackPairing.jsx'
import { setCoachToken } from './coach/api.js'
import { hostedCompatibilityRedirect, hostedRoleHomePath, navigate, usePathname } from './router.js'
import { applyRoleIdentity } from './device.js'
import { Centered } from './ui.jsx'
import { T } from './theme.js'

function Redirect({ to }) {
  useEffect(() => { navigate(to, { replace: true }) }, [to])
  return null
}

function Picker() {
  const choices = [
    { role: 'rack', label: 'Rack Tablet' },
    { role: 'coach', label: 'Coach Admin' },
  ]

  function pick(role) {
    localStorage.setItem('device_role', role)
    applyRoleIdentity(role)
    if (role === 'rack') setCoachToken(null)
    navigate(hostedRoleHomePath(role))
  }

  return (
    <Centered>
      <div style={{ fontSize: 11, fontWeight: 900, letterSpacing: '.18em', textTransform: 'uppercase',
        color: T.lime, marginBottom: 10 }}>Edge Athlete</div>
      <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: '-.03em', marginBottom: 28 }}>Set up this device</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: 300 }}>
        {choices.map((choice) => (
          <button key={choice.role} onClick={() => pick(choice.role)}
            style={{ padding: 18, fontSize: 16, fontWeight: 600, borderRadius: 12,
              border: `1px solid ${T.line}`, background: T.panel, color: T.ink,
              cursor: 'pointer', fontFamily: 'inherit' }}>
            {choice.label}
          </button>
        ))}
      </div>
    </Centered>
  )
}

function Home() {
  const destination = hostedRoleHomePath(localStorage.getItem('device_role'))
  return destination ? <Redirect to={destination} /> : <Picker />
}

export function hostedRoute(pathname) {
  if (pathname === '/rack') return <HostedRack />
  if (pathname === '/coach/rack-pairing') return <CoachRackPairing showCoachWorkspace={false} />
  if (pathname === '/') return <Home />
  return <Redirect to={hostedCompatibilityRedirect(pathname, true) || '/'} />
}

export default function HostedApp() {
  return hostedRoute(usePathname())
}
