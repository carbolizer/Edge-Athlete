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

import { useState, useEffect } from 'react'

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
export function usePathname() {
  const [pathname, setPathname] = useState(window.location.pathname)
  useEffect(() => {
    const update = () => setPathname(window.location.pathname)
    window.addEventListener('popstate', update)       // Back/Forward buttons
    window.addEventListener('locationchange', update)  // our own navigate()
    return () => {
      window.removeEventListener('popstate', update)
      window.removeEventListener('locationchange', update)
    }
  }, [])
  return pathname
}
