import { afterEach, describe, expect, it, vi } from 'vitest'
import { createLaunchIntent, getHostedRackStatus, inspectLaunchIntent } from './hostedApi.js'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

describe('hosted Rack API client', () => {
  it('uses same-origin credentials and no-store for status reads', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ endpoint: {}, helper: {} }))
    vi.stubGlobal('fetch', fetchMock)

    await getHostedRackStatus()

    expect(fetchMock).toHaveBeenCalledWith('/api/rack/v1/status/', expect.objectContaining({
      method: 'GET', credentials: 'same-origin', cache: 'no-store',
    }))
  })

  it('sends the readable CSRF cookie and exact JSON bodies on mutations', async () => {
    vi.stubGlobal('document', { cookie: 'other=x; ea_rack_csrf=csrf-token' })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ launch_uri: 'edgeathlete-rack:launch' }, 201))
      .mockResolvedValueOnce(response({ state: 'pending' }))
    vi.stubGlobal('fetch', fetchMock)

    await createLaunchIntent()
    await inspectLaunchIntent('intent-id')

    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({
      method: 'POST', body: '{}', credentials: 'same-origin', cache: 'no-store',
      headers: expect.objectContaining({ 'Content-Type': 'application/json', 'X-CSRFToken': 'csrf-token' }),
    }))
    expect(fetchMock.mock.calls[1][1].body).toBe('{"intent_id":"intent-id"}')
  })
})
