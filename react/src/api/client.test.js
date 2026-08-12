import { afterEach, describe, expect, it, vi } from 'vitest'

import { getRackNumber } from './client.js'

afterEach(() => vi.unstubAllGlobals())

describe('getRackNumber', () => {
  it('keeps the stable rack identity out of the URL', async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ rack_number: 1 }),
    })
    vi.stubGlobal('fetch', fetch)

    await getRackNumber('stable-rack-id')

    expect(fetch).toHaveBeenCalledWith('/api/racks/racknumber/', {
      headers: { 'X-Rack-Device-ID': 'stable-rack-id' },
    })
  })
})
