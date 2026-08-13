// polyfills.js — small gaps to fill so the app runs over plain HTTP.
//
// The base station serves at http://basestation, which browsers treat as a
// NON-secure context (only https and localhost count as secure). A handful of
// web APIs are switched off outside a secure context, and the app hit one of
// them hard: crypto.randomUUID() is simply undefined over plain HTTP, so
// getDeviceId() threw and the ErrorBoundary took the whole screen down. On the
// laptop it never showed because http://localhost DOES count as secure.
//
// crypto.getRandomValues() is NOT gated — it works over plain HTTP — so we build
// a proper random UUID (v4) from it whenever randomUUID is missing. A device id
// is a stable local label, not a secret, so this is more than strong enough.
//
// The alternative was serving HTTPS, which on an offline AP means a cert warning
// on every phone AND breaks the ws:// MQTT connection (an https page refuses a
// plain-ws socket as mixed content). This one file sidesteps all of that and
// keeps everything on plain HTTP.
//
// Imported FIRST in main.jsx so it is in place before any code calls it.

// Exported so it can be unit-tested directly (in Node/jsdom, randomUUID already
// exists, so the install below is skipped there).
export function uuidV4FromCrypto() {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  // RFC 4122: pin the version (4) and variant bits.
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'))
  return (
    hex.slice(0, 4).join('') + '-' +
    hex.slice(4, 6).join('') + '-' +
    hex.slice(6, 8).join('') + '-' +
    hex.slice(8, 10).join('') + '-' +
    hex.slice(10, 16).join('')
  )
}

if (typeof crypto !== 'undefined' &&
    typeof crypto.randomUUID !== 'function' &&
    typeof crypto.getRandomValues === 'function') {
  crypto.randomUUID = uuidV4FromCrypto
}
