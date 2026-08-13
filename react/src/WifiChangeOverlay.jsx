// WifiChangeOverlay.jsx — shows the new Wi-Fi password on the wall display and
// rack tablets when a coach changes it.
//
// WHY THIS IS AN APP-LEVEL OVERLAY, not part of the rack screen: the rack screen
// is frozen contract — we don't touch it. But we can float a layer ON TOP of
// whatever screen is showing, the same way the remote-command listener rides
// above every route. So this works over the rack screen and the wall display
// without editing either.
//
// The flow it serves: a coach changes the Wi-Fi password. Django warns every
// screen over MQTT a few seconds before the network drops. This overlay catches
// that warning and puts the new password up big, so the person walking around
// updating each device can read it straight off the screen — because once the
// network drops, nothing can tell these screens anything, and a web page can't
// change a device's Wi-Fi settings for it. It remembers the password locally so
// it stays up through the drop; "Dismiss" clears it once that device is back on.

import { useEffect, useState } from 'react'
import { subscribeWifiChange } from './mqtt/client.js'
import { passwordFromWifiChange } from './wifiChange.js'

const CACHE_KEY = 'ea_wifi_change'

const overlayStyle = {
  position: 'fixed', inset: 0, zIndex: 9999,
  background: 'rgba(0, 0, 0, 0.82)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  padding: '24px', fontFamily: 'system-ui, -apple-system, sans-serif',
}
const cardStyle = {
  maxWidth: 620, width: '100%', textAlign: 'center',
  background: '#10171b', color: '#f5f7f2',
  border: '1px solid #ffb63e', borderRadius: 16, padding: '32px 28px',
}
const pwStyle = {
  display: 'block', margin: '20px 0', padding: '18px',
  fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
  fontSize: 'clamp(24px, 6vw, 44px)', letterSpacing: '1px',
  color: '#a9f04d', background: '#070b0e', borderRadius: 12,
  userSelect: 'all', wordBreak: 'break-all',
}
const btnStyle = {
  padding: '12px 22px', borderRadius: 10, border: '1px solid #263239',
  background: 'transparent', color: '#f5f7f2', font: 'inherit',
  fontSize: 16, cursor: 'pointer',
}

export default function WifiChangeOverlay() {
  // Seed from localStorage so the password stays up if this ever remounts. (The
  // screens don't reload when Wi-Fi drops — the app stays loaded — but this
  // costs nothing and is one less way to lose the password mid-changeover.)
  const [password, setPassword] = useState(() => {
    try { return localStorage.getItem(CACHE_KEY) || null } catch { return null }
  })

  useEffect(() => {
    return subscribeWifiChange((message) => {
      const next = passwordFromWifiChange(message)
      if (!next) return
      try { localStorage.setItem(CACHE_KEY, next) } catch { /* private mode */ }
      setPassword(next)
    })
  }, [])

  if (!password) return null

  function dismiss() {
    try { localStorage.removeItem(CACHE_KEY) } catch { /* private mode */ }
    setPassword(null)
  }

  return (
    <div style={overlayStyle} role="alert">
      <div style={cardStyle}>
        <h1 style={{ margin: '0 0 10px', fontSize: 'clamp(20px, 4vw, 30px)' }}>
          The gym Wi-Fi password is changing
        </h1>
        <p style={{ margin: 0, fontSize: 16, lineHeight: 1.5, color: '#89969d' }}>
          This screen is about to drop off the network. Reconnect it to
          “EdgeAthlete” in this device’s Wi-Fi settings using:
        </p>
        <code style={pwStyle}>{password}</code>
        <button type="button" style={btnStyle} onClick={dismiss}>
          Dismiss (I’m reconnected)
        </button>
      </div>
    </div>
  )
}
