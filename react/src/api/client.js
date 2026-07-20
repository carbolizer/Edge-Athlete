// api/client.js — the one place the rack screen talks to Django's REST API.
//
// Everything goes through the same Nginx that served this page, which forwards
// /api/* to Django, so these calls need no host or auth setup. The rack screen
// only ever makes a handful of REST calls (register itself, ask its rack number,
// and ONE active-session fetch at startup) — everything live comes over MQTT.

const API = '/api'

async function jsonFetch(path, opts) {
  const res = await fetch(API + path, opts)
  if (!res.ok) throw new Error(`${(opts && opts.method) || 'GET'} ${path} → HTTP ${res.status}`)
  return res.status === 204 ? null : res.json()
}

// A tablet announces itself so a coach can assign it a rack. Idempotent on the
// server (get-or-create by device_id), so calling it again is harmless.
export function registerRack(deviceId) {
  return jsonFetch('/racks/register/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId }),
  })
}

// "Which rack am I?" — the one poll in the whole system, run while waiting for a
// coach to assign this screen. Returns { rack_number } (null until assigned).
export function getRackNumber(deviceId) {
  return jsonFetch(`/racks/racknumber/?device_id=${encodeURIComponent(deviceId)}`)
}

// The ONE-SHOT startup fetch: the current session's roster, each athlete's
// reference maxes, and the planned exercises with their targets + velocity zones.
// Fired once after rack assignment — never polled.
export function getActiveSession() {
  return jsonFetch('/sessions/active/')
}

// The sensor nodes and their status. Used once at startup to find which node is
// linked to this rack (same rack_number) so we know whose rep topic to subscribe.
export function getNodes() {
  return jsonFetch('/nodes/')
}

// One athlete's DAY VIEW: their planned movements + live per-set progress, derived
// server-side from their Program + Set rows. Fetched when an athlete checks in at
// the rack (Phase 11 Step 2), so any rack shows the same, up-to-date view.
export function getAthleteProgress(athleteId) {
  return jsonFetch(`/sessions/active/athlete/${athleteId}/progress/`)
}

// Record that an athlete signed in at this rack (their "check-in"). This makes the
// rack the athlete's current one for the session (newest-wins) — what a hand tap,
// or a future NFC tap, triggers.
export function checkInAthlete(rackNumber, athleteId) {
  return jsonFetch(`/racks/${rackNumber}/checkin/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ athlete: athleteId }),
  })
}

// This rack's HOT LIST: the athletes it currently "owns" (checked in here, not
// since moved). Surfaced first on the check-in screen for fast re-pick.
export function getRackHotList(rackNumber) {
  return jsonFetch(`/racks/${rackNumber}/checkins/`)
}
