// device.js — this tablet's identity helpers, shared across screens.
//
// Two small jobs that more than one screen needs: giving the device a stable id,
// and pointing the browser at the right PWA manifest for its role.

const MANIFESTS = {
  rack: '/manifest.rack.json',
  dashboard: '/manifest.dashboard.json',
  coach: '/manifest.coach.json',
}

// Point the page's <link rel="manifest"> at this role's manifest so an install
// gets the right icon/name. Creates the tag if the page doesn't have one.
export function swapManifest(role) {
  let link = document.querySelector('link[rel="manifest"]')
  if (!link) {
    link = document.createElement('link')
    link.rel = 'manifest'
    document.head.appendChild(link)
  }
  link.href = MANIFESTS[role] || MANIFESTS.rack
}

// This device's stable id — generated once and kept forever, so the screen never
// re-registers across reloads/reboots.
export function getDeviceId() {
  let id = localStorage.getItem('device_id')
  if (!id) { id = crypto.randomUUID(); localStorage.setItem('device_id', id) }
  return id
}
