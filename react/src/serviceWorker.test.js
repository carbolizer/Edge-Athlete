import { describe, expect, it, vi } from 'vitest'
import { retireLocalOfflineShell } from './serviceWorker.js'

describe('hosted service-worker migration', () => {
  it('unregisters old workers and deletes only local shell caches', async () => {
    const unregister = vi.fn().mockResolvedValue(true)
    const deleteCache = vi.fn().mockResolvedValue(true)
    const serviceWorker = { getRegistrations: vi.fn().mockResolvedValue([{ unregister }]) }
    const cacheStorage = {
      keys: vi.fn().mockResolvedValue(['edgeathlete-shell-v1', 'unrelated-cache']),
      delete: deleteCache,
    }

    await retireLocalOfflineShell(serviceWorker, cacheStorage)

    expect(unregister).toHaveBeenCalledOnce()
    expect(deleteCache).toHaveBeenCalledOnce()
    expect(deleteCache).toHaveBeenCalledWith('edgeathlete-shell-v1')
  })
})
