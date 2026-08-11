// router.js — the whole client-side router, no library (not React Router).
//
// This app is a "single-page app": the server only ever hands the browser ONE
// html file. So moving to /rack/1 or /setup can't fetch a new page from the
// server — the switch has to happen right here in the browser. This does it with
// the browser's built-in History API:
//   • navigate(path)   changes the address bar WITHOUT reloading the page
//   • usePathname()     re-renders the app whenever the path changes
//
// Nginx is already set up to serve the app's index.html for any path, so if
// someone refreshes or types /rack/1 directly, they still land in this same app,
// which then reads the path and shows the right screen. That's why we don't need
// React Router or any nginx change — just these few lines.

import { useSyncExternalStore } from 'react'

// Go to a new path and re-render. `replace: true` swaps the current history entry
// instead of adding one — used for automatic boot-time redirects so the browser's
// Back button doesn't get stuck bouncing through a redirect.
export function navigate(path, { replace = false } = {}) {
  if (path === window.location.pathname) return
  window.history[replace ? 'replaceState' : 'pushState']({}, '', path)
  // Changing history via pushState/replaceState does NOT fire the browser's
  // 'popstate' event, so we announce the change ourselves; every usePathname()
  // below is listening for it and re-reads the path.
  window.dispatchEvent(new Event('locationchange'))
}

// A React hook: returns the current URL path, and re-renders the component using
// it whenever the path changes — whether from navigate() above or the browser's
// own Back/Forward buttons.
//
// ⚠️ THIS MUST NOT BE useState + useEffect, and the reason is a real bug we
// shipped and had to chase twice.
//
// React runs a CHILD's effects before its PARENT's. The router lives in <App>,
// but a <Redirect> is rendered as its child — so on a first page load at a
// redirecting URL (a bare /rack, an unknown path, or a configured tablet
// landing on "/"), the order was:
//
//    1. <Redirect> mounts, its effect calls navigate() and fires the event
//    2. <App>'s effect THEN registers the listener for that event
//
// The event fired into an empty room. `pathname` stayed on the old value,
// <Redirect> kept returning null, and the screen stayed BLACK forever — with
// nothing in the console and nothing for an error boundary to catch, because
// nothing actually threw.
//
// useSyncExternalStore closes that race by design: after subscribing, React
// re-reads the snapshot and re-renders if it changed while it wasn't looking.
// A navigation that happens before the subscription is no longer lost.
function subscribe(onChange) {
  window.addEventListener('popstate', onChange)       // Back/Forward buttons
  window.addEventListener('locationchange', onChange)  // our own navigate()
  return () => {
    window.removeEventListener('popstate', onChange)
    window.removeEventListener('locationchange', onChange)
  }
}

export function usePathname() {
  return useSyncExternalStore(subscribe, () => window.location.pathname)
}

export function matchRackPath(pathname) {
  if (pathname === '/rack') return { kind: 'hosted' }
  if (pathname === '/rack/setup') return { kind: 'setup' }
  if (!pathname.startsWith('/rack/')) return null
  const rest = pathname.slice('/rack/'.length)
  const rackNumber = Number(rest)
  return rest !== '' && Number.isInteger(rackNumber) && rackNumber > 0
    ? { kind: 'live', rackNumber }
    : { kind: 'invalid' }
}

export function matchCoachPath(pathname) {
  if (pathname === '/coach/rack-pairing') return { kind: 'rack-pairing' }
  return null
}

export function hostedRoleHomePath(role) {
  if (role === 'rack') return '/rack'
  if (role === 'coach') return '/coach/rack-pairing'
  return null
}

export function hostedCompatibilityRedirect(pathname, hosted = false) {
  if (!hosted) return null
  if (pathname === '/coach' || pathname === '/coach/setup') return '/coach/rack-pairing'
  if (pathname === '/rack/setup' || /^\/rack\/[1-9]\d*$/.test(pathname)) return '/rack'
  if (pathname === '/dashboard' || pathname === '/connection-test') return '/'
  return null
}
