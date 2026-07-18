// main.jsx — mounts the React app and registers the service worker.
//
// The service worker caches the app shell so a rack screen survives WiFi drops
// (see public/service-worker.js). Registration is best-effort: if it fails, the
// app still runs, it just won't have the offline shell.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js').catch(() => {})
  })
}
