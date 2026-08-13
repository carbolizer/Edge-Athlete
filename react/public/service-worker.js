// service-worker.js — offline resilience for the rack screen.
//
// The gym runs on the Pi's own WiFi, which can blip. This caches the app SHELL
// (index.html + the hashed JS/CSS bundle) so the screen still loads and runs
// after an access-point drop. It deliberately does NOT cache API responses or
// touch MQTT — live data must always be fresh, and reps are protected by the
// IndexedDB buffer, not by the cache. Registered from main.jsx.

const CACHE = 'edgeathlete-shell-v1'

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(['/', '/index.html'])))
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  // Drop any older shell caches on version bump.
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.pathname.startsWith('/api/')) return // never cache the API — always live

  // Network-first, falling back to cache when offline. Successful GETs are cached
  // as they're fetched, so the shell + assets are available after a drop.
  event.respondWith(
    fetch(request)
      .then((res) => {
        const copy = res.clone()
        caches.open(CACHE).then((c) => c.put(request, copy)).catch(() => {})
        return res
      })
      .catch(() => caches.match(request).then((hit) => hit || caches.match('/index.html')))
  )
})
