/*
 * Coach REST helpers — JWT Bearer calls against the base-station /api.
 * Token lives in localStorage so a refresh does not kick the coach out mid-demo.
 */

const TOKEN_KEY = 'coach_access_token'

export function getCoachToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setCoachToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export async function coachLogin(username, password) {
  const res = await fetch('/api/auth/login/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok || !data.access) {
    const detail = data.detail || data.error || `HTTP ${res.status}`
    throw new Error(typeof detail === 'string' ? detail : 'login failed')
  }
  setCoachToken(data.access)
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
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    const detail = (data && (data.error || data.detail)) || `HTTP ${res.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data
}

/** Short slice shown on waiting tablets / coach dropdowns (not a full UUID wall). */
export function shortId(id) {
  if (!id) return '—'
  const s = String(id)
  return s.length <= 8 ? s : s.slice(-8)
}
