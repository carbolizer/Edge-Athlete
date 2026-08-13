// main.jsx — mounts the React app and registers the service worker.
//
// The service worker caches the app shell so a rack screen survives WiFi drops
// (see public/service-worker.js). Registration is best-effort: if it fails, the
// app still runs, it just won't have the offline shell.
// FIRST — installs crypto.randomUUID for the plain-HTTP (non-secure) context the
// base station serves in, before anything calls getDeviceId(). See polyfills.js.
import './polyfills.js'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Inter, bundled into the app (not fetched from a CDN) so it renders on the Pi's
// offline network. This is the font the whole UI uses via theme.js.
import '@fontsource-variable/inter'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// Registration is best-effort, but it must not be SILENT. The old `.catch(() => {})`
// hid a failure that happens on every rack screen: `'serviceWorker' in navigator` is
// true over plain HTTP because the API object exists, so this guard passes — and then
// register() rejects with a SecurityError, because http://basestation is not a secure
// context. The offline shell has therefore never existed on a rack screen, and nothing
// said so. Same root cause polyfills.js documents for crypto.randomUUID, except a
// service worker cannot be polyfilled: the origin has to be trusted.
//
// The fix is on the kiosk side — Chromium is launched with the origin marked secure
// (see scripts/rack-screen/kiosk.sh). This log is how you tell whether that worked,
// instead of guessing.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js').catch((err) => {
      console.warn(
        '[sw] offline shell unavailable — the app still works, it just will not ' +
        'survive a reload while offline. Over plain HTTP this is expected unless the ' +
        'browser was told to trust this origin. Reason:', err,
      )
    })
  })
}
