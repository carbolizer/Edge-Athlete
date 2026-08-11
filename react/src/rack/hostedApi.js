const API_ROOT = '/api/rack/v1'

export class HostedRackApiError extends Error {
  constructor(status, body) {
    super(body?.detail || `Rack control plane returned HTTP ${status}.`)
    this.name = 'HostedRackApiError'
    this.status = status
    this.code = body?.code
    this.retryAfterSeconds = body?.retry_after_seconds
  }
}

function cookieValue(name) {
  if (typeof document === 'undefined') return null
  const prefix = `${name}=`
  const part = document.cookie.split(';').map((value) => value.trim())
    .find((value) => value.startsWith(prefix))
  return part ? decodeURIComponent(part.slice(prefix.length)) : null
}

async function request(path, { method = 'GET', body, csrf = false } = {}) {
  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (csrf) {
    const token = cookieValue('ea_rack_csrf')
    if (!token) throw new Error('Rack request verification is unavailable. Refresh and try again.')
    headers['X-CSRFToken'] = token
  }
  const response = await fetch(`${API_ROOT}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
    cache: 'no-store',
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) throw new HostedRackApiError(response.status, payload)
  return payload
}

export function bootstrapRackCsrf() {
  return request('/csrf/')
}

export function getHostedRackStatus() {
  return request('/status/')
}

export function createEndpointPairing() {
  return request('/endpoint-pairings/', { method: 'POST', body: {}, csrf: true })
}

export function inspectEndpointPairing() {
  return request('/endpoint-pairings/status/', { method: 'POST', body: {}, csrf: true })
}

export function createHelperPairing() {
  return request('/helper-pairings/', { method: 'POST', body: {}, csrf: true })
}

export function inspectHelperPairing(pairingId) {
  return request('/helper-pairings/status/', {
    method: 'POST', body: { pairing_id: pairingId }, csrf: true,
  })
}

export function createLaunchIntent() {
  return request('/helper-launch-intents/', { method: 'POST', body: {}, csrf: true })
}

export function inspectLaunchIntent(intentId) {
  return request('/helper-launch-intents/inspect/', {
    method: 'POST', body: { intent_id: intentId }, csrf: true,
  })
}
