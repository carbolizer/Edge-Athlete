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

// This device's stable id — generated once and kept forever, so the screen never
// re-registers across reloads/reboots.
export function getDeviceId() {
  let id = localStorage.getItem('device_id')
  if (!id) { id = crypto.randomUUID(); localStorage.setItem('device_id', id) }
  return id
}
