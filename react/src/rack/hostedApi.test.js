import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  bootstrapRackCsrf, createLaunchIntent, getHostedRackStatus, inspectLaunchIntent,
} from './hostedApi.js'

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

  it('holds the bootstrap token in memory and sends exact JSON mutation bodies', async () => {
    const csrfToken = 'A'.repeat(43)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ csrf_token: csrfToken }))
      .mockResolvedValueOnce(response({ launch_uri: 'edgeathlete-rack:launch' }, 201))
      .mockResolvedValueOnce(response({ state: 'pending' }))
    vi.stubGlobal('fetch', fetchMock)

    await bootstrapRackCsrf()
    await createLaunchIntent()
    await inspectLaunchIntent('intent-id')

    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
      method: 'POST', body: '{}', credentials: 'same-origin', cache: 'no-store',
      headers: expect.objectContaining({ 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }),
    }))
    expect(fetchMock.mock.calls[2][1].body).toBe('{"intent_id":"intent-id"}')
  })

  it('rejects a malformed bootstrap token', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ csrf_token: 'short' })))
    await expect(bootstrapRackCsrf()).rejects.toThrow('Rack request verification is unavailable.')
  })

  it('rejects noncanonical base64url and clears a previously valid token', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ csrf_token: 'A'.repeat(43) }))
      .mockResolvedValueOnce(response({ csrf_token: `${'A'.repeat(42)}B` }))
    vi.stubGlobal('fetch', fetchMock)

    await bootstrapRackCsrf()
    await expect(bootstrapRackCsrf()).rejects.toThrow('Rack request verification is unavailable.')
    await expect(createLaunchIntent()).rejects.toThrow('Rack request verification is unavailable.')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('shares one request between concurrent bootstrap callers', async () => {
    let resolveBootstrap
    const fetchMock = vi.fn().mockReturnValue(new Promise((resolve) => { resolveBootstrap = resolve }))
    vi.stubGlobal('fetch', fetchMock)

    const first = bootstrapRackCsrf()
    const second = bootstrapRackCsrf()
    resolveBootstrap(response({ csrf_token: 'A'.repeat(43) }))

    await expect(first).resolves.toEqual({ csrf_token: 'A'.repeat(43) })
    await expect(second).resolves.toEqual({ csrf_token: 'A'.repeat(43) })
    expect(fetchMock).toHaveBeenCalledOnce()
  })
})
