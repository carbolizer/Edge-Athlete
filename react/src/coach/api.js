/*
 * Coach REST helpers — JWT Bearer calls against the base-station /api.
 * Token lives in localStorage so a refresh does not kick the coach out mid-demo.
 */

const TOKEN_KEY = 'coach_access_token'

function responseError(data, status) {
  if (typeof data === 'string') return `HTTP ${status}`
  if (data?.error || data?.detail) return data.error || data.detail
  if (!data) return `HTTP ${status}`
  return Object.entries(data).map(([key, value]) => {
    const label = key === 'non_field_errors' ? '' : `${key}: `
    return label + (Array.isArray(value) ? value.join(' ') : String(value))
  }).join(' ') || `HTTP ${status}`
}

export function getCoachToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setCoachToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

function rateLimitError(res) {
  const seconds = Number(res.headers?.get('Retry-After'))
  const wait = Number.isFinite(seconds) && seconds > 0
    ? `Try again in ${Math.ceil(seconds)} seconds.`
    : 'Please wait before trying again.'
  const error = new Error(`Too many login attempts. ${wait}`)
  error.status = 429
  return error
}

export async function coachLogin(username, password, { persist = true } = {}) {
  const res = await fetch('/api/auth/login/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  // Nginx can return HTML; Django returns JSON and an exact retry interval.
  if (res.status === 429) throw rateLimitError(res)
  const data = await res.json().catch(() => ({}))
  if (res.status === 401) throw new Error('The username or password was not accepted.')
  if (!res.ok || !data.access) {
    const detail = data.detail || data.error || `HTTP ${res.status}`
    throw new Error(typeof detail === 'string' ? detail : 'login failed')
  }
  if (persist) setCoachToken(data.access)
  return data.access
}

export async function coachFetch(path, { token, method = 'GET', body } = {}) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (res.status === 429) throw rateLimitError(res)
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    const detail = responseError(data, res.status)
    const error = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    error.status = res.status
    error.code = data && data.code
    error.data = data
    throw error
  }
  return data
}

/** Who is signed in, whether they administer the box, and whether they must
 *  change their temporary password before the rest of the app opens. */
export function fetchCurrentCoach(token) {
  return coachFetch('/api/auth/me/', { token })
}

export function changePassword(token, currentPassword, newPassword) {
  return coachFetch('/api/auth/password/', {
    token,
    method: 'POST',
    body: { current_password: currentPassword, new_password: newPassword },
  })
}

export function listCoaches(token) {
  return coachFetch('/api/coaches/', { token })
}

export function createCoach(token, username, password) {
  return coachFetch('/api/coaches/', {
    token,
    method: 'POST',
    body: password ? { username, password } : { username },
  })
}

export function updateCoach(token, id, changes) {
  return coachFetch(`/api/coaches/${id}/`, { token, method: 'PATCH', body: changes })
}

export function resetCoachPassword(token, id) {
  return coachFetch(`/api/coaches/${id}/reset/`, { token, method: 'POST' })
}

/** Short slice shown on waiting tablets / coach dropdowns (not a full UUID wall). */
export function shortId(id) {
  if (!id) return '—'
  const s = String(id)
  return s.length <= 8 ? s : s.slice(-8)
}
