// coachState.js — "which of the three coach screens am I on?"
//
// The coach admin is a machine with exactly three positions:
//
//   PLANNING    before the training happens — blocks, programs, groups, calendar
//   SESSION     while it happens — the live room
//   ANALYTICS   after it happens — one athlete's summary, history, reports, notes
//
// This file is the only place that knows their names, their order, and how they
// map to a URL. Everything else — the navbar, the router, the body that swaps —
// asks here. Put a fourth state in one day and this is the single edit.
//
// WHY THE URL AND NOT A useState. Three reasons, all of them things a coach
// actually does: reloading the tablet keeps them where they were; the browser's
// Back button moves between states for free; and a screen can be linked to. The
// custom router in ../router.js already makes this nearly free, and nginx
// already serves index.html for any path, so there is no server change either.
//
// ⚠️ The states are ROUTES, but it must not FEEL like page navigation. The
// navbar, the logo and the active-day widget never unmount when the state
// changes — only the body below them swaps. See StateNavbar.jsx.

// Order matters: it is the order they appear in the navbar, left to right, and
// it is the order a coach's day runs in.
export const COACH_STATES = [
  { key: 'planning', label: 'Planning', path: '/coach/planning' },
  { key: 'session', label: 'Session', path: '/coach/session' },
  { key: 'analytics', label: 'Analytics', path: '/coach/analytics' },
]

export const DEFAULT_COACH_STATE = 'planning'

// Where this device was last, so /coach can send a returning tablet back to it
// instead of always dumping it in PLANNING. Survives a reboot; per-device, not
// per-coach, because it is a convenience and not a setting.
const LAST_STATE_KEY = 'coach_state'

/** The state a path belongs to, or null if the path isn't a coach state. */
export function coachStateFromPath(pathname) {
  const found = COACH_STATES.find((state) => state.path === pathname)
  return found ? found.key : null
}

/** The path for a state key. Falls back to PLANNING for anything unknown. */
export function pathForCoachState(key) {
  const found = COACH_STATES.find((state) => state.key === key)
  return (found || COACH_STATES[0]).path
}

export function rememberCoachState(key) {
  try {
    if (coachStateFromPath(pathForCoachState(key)) === key) {
      localStorage.setItem(LAST_STATE_KEY, key)
    }
  } catch {
    // A locked-down browser context can refuse storage. Forgetting where the
    // coach was is a mild annoyance; throwing here would black out the screen.
  }
}

/**
 * Where a bare /coach should land. The remembered state if there is one and it
 * is still a real state, otherwise PLANNING.
 *
 * SESSION is deliberately NOT excluded here even though it can be unavailable —
 * the caller knows whether a day is running and this file does not. See the
 * `dayRunning` handling in Dashboard.jsx.
 */
export function resumeCoachState() {
  try {
    const remembered = localStorage.getItem(LAST_STATE_KEY)
    if (remembered && COACH_STATES.some((state) => state.key === remembered)) {
      return remembered
    }
  } catch {
    // Same as above — fall through to the default.
  }
  return DEFAULT_COACH_STATE
}
