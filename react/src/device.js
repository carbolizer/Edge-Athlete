// device.js — this tablet's identity helpers, shared across screens.
//
// Two small jobs that more than one screen needs: giving the device a stable id,
// and pointing the browser at the right per-role "chrome" (PWA manifest, iOS
// home-screen icon, and app title) for whichever role this tablet was set up as.

// Everything that differs per role, in one place. When a device is set up as a
// rack / coach / dashboard, we point the page's install-related tags at that
// role's files so an "Add to Home Screen" install gets the right icon + name.
const ROLES = {
  rack:      { manifest: '/manifest.rack.json',      title: 'EA Rack',  appleIcon: '/icon-rack-180.png' },
  dashboard: { manifest: '/manifest.dashboard.json', title: 'EA Wall',  appleIcon: '/icon-dashboard-180.png' },
  coach:     { manifest: '/manifest.coach.json',     title: 'EA Coach', appleIcon: '/icon-coach-180.png' },
}

// Find a <link>/<meta> tag by selector, creating it if the page doesn't have one,
// so this works even on a cold boot before any tag exists.
function ensureTag(selector, make) {
  let el = document.head.querySelector(selector)
  if (!el) { el = make(); document.head.appendChild(el) }
  return el
}

// Point the page's role-specific tags at this role's files. Android reads the
// manifest; iOS Safari ignores the manifest and instead uses the apple-touch-icon
// (a real PNG — it won't use SVG) and the apple-mobile-web-app-title. We set all
// three so an install looks right no matter the device.
export function applyRoleIdentity(role) {
  const r = ROLES[role] || ROLES.rack

  const manifest = ensureTag('link[rel="manifest"]', () => {
    const l = document.createElement('link'); l.rel = 'manifest'; return l
  })
  manifest.href = r.manifest

  const appleIcon = ensureTag('link[rel="apple-touch-icon"]', () => {
    const l = document.createElement('link'); l.rel = 'apple-touch-icon'; return l
  })
  appleIcon.href = r.appleIcon

  const appleTitle = ensureTag('meta[name="apple-mobile-web-app-title"]', () => {
    const m = document.createElement('meta'); m.name = 'apple-mobile-web-app-title'; return m
  })
  appleTitle.content = r.title
}

// Which role a URL belongs to, or null if the path does not name one.
//
// WHY THIS EXISTS. applyRoleIdentity used to be called only at the moments a
// device CHANGED role — the picker, rack setup, the coach tablet mounting. None
// of those happen on a cold boot, so a wall display that rebooted straight into
// /dashboard kept index.html's default rack manifest and would have installed
// itself as "EA Rack". App.jsx now calls this on every navigation instead, which
// also matches what that file already says about itself: the URL is the source
// of truth for what is on screen, so it should decide the install identity too.
//
// Returns null rather than guessing, so the caller can fall back to the stored
// role for paths like '/' that belong to no role in particular.
// Matches on whole path SEGMENTS, not a bare prefix: '/rack' and '/rack/setup'
// are rack screens, '/rackets' is not. A plain startsWith would claim it was.
export function roleFromPath(pathname) {
  const first = String(pathname || '').split('/')[1]
  if (first === 'dashboard') return 'dashboard'
  if (first === 'coach') return 'coach'
  if (first === 'rack') return 'rack'
  return null
}

// This device's stable id — generated once and kept forever, so the screen never
// re-registers across reloads/reboots.
export function getDeviceId() {
  let id = localStorage.getItem('device_id')
  if (!id) { id = crypto.randomUUID(); localStorage.setItem('device_id', id) }
  return id
}

// This TAB's id. Stable for the life of the tab, different in every other tab.
//
// ── WHY THIS IS NOT getDeviceId() ────────────────────────────────────────────
// MQTT requires every client id connected to a broker to be UNIQUE, and it does
// not fail politely when they collide: a second connection arriving with an id
// that is already in use causes the broker to DISCONNECT THE FIRST ONE. Both
// sides then reconnect, evict each other again, and keep doing that.
//
// getDeviceId() lives in localStorage, which is shared by every tab on the same
// browser profile and origin. So two tabs of the same screen hand the broker the
// same id and knock each other offline in a loop. Opening a second tab to check
// something is a completely normal thing to do, which is what makes this worth
// guarding against rather than documenting.
//
// ── WHY sessionStorage, AND NOT JUST A RANDOM VALUE ──────────────────────────
// sessionStorage is scoped per TAB, which is the uniqueness we need. The part
// that matters just as much is that it SURVIVES A RELOAD of that tab — a plain
// random id regenerated on every load would be unique, but it would also
// abandon the broker-side session on every refresh.
//
// That session is the whole point of the feature: mqtt/client.js connects with
// clean:false so the broker holds QoS 1 messages for us while we are away, and
// it files them under this exact id. A new id per reload means reconnecting as
// a stranger with an empty queue, silently undoing what the persistent session
// was added to do.
//
// The three kiosk launchers each run in their own Chromium profile, so they were
// never at risk from this. Hand-opened tabs are.
export function getTabId() {
  let id = sessionStorage.getItem('tab_id')
  if (!id) { id = crypto.randomUUID().slice(0, 8); sessionStorage.setItem('tab_id', id) }
  return id
}
