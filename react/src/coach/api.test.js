import { afterEach, describe, expect, it, vi } from 'vitest'
import { claimRackEndpoint, confirmRackHelper, getCoachTrainingGroups } from './api.js'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) }
}

describe('coach hosted Rack API', () => {
  it('uses the coach token and exact tenant-scoped endpoint claim body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ state: 'claimed' }))
    vi.stubGlobal('fetch', fetchMock)
    const body = { pairing_code: 'ABCDEFGH', training_group: 7, display_name: 'Rack 3' }

    await claimRackEndpoint('coach-token', body)

    expect(fetchMock).toHaveBeenCalledWith('/api/coach/v1/rack-endpoint-pairings/claim/', {
      method: 'POST',
      headers: { Authorization: 'Bearer coach-token', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  })

  it('loads scoped TrainingGroups and sends only pairing_id for confirmation', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response([{ id: 7, name: 'Varsity' }]))
      .mockResolvedValueOnce(response({ state: 'confirmed' }))
    vi.stubGlobal('fetch', fetchMock)

    await getCoachTrainingGroups('coach-token')
    await confirmRackHelper('coach-token', 'pairing-id')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/training-groups/')
    expect(fetchMock.mock.calls[1][1].body).toBe('{"pairing_id":"pairing-id"}')
  })

  it('preserves the API detail and stable code on errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ code: 'not_found', detail: 'Not found.' }, 404)))

    await expect(confirmRackHelper('coach-token', 'missing')).rejects.toMatchObject({
      message: 'Not found.', status: 404, code: 'not_found',
    })
  })
})
