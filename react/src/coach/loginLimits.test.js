import { afterEach, expect, it, vi } from 'vitest'
import { coachLogin, coachFetch } from './api.js'

afterEach(() => vi.unstubAllGlobals())

it('shows the server retry interval without persisting credentials', async () => {
  const setItem = vi.fn()
  vi.stubGlobal('localStorage', { setItem })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', {
    status: 429, headers: { 'Retry-After': '600' },
  })))
  await expect(coachLogin('coach', 'secret')).rejects.toMatchObject({
    status: 429, message: 'Too many login attempts. Try again in 600 seconds.',
  })
  expect(setItem).not.toHaveBeenCalled()
})

it('handles nginx HTML throttling without inventing a wait interval', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>Limited</html>', { status: 429 })))
  await expect(coachFetch('/api/auth/setup/', { method: 'POST' })).rejects.toMatchObject({
    status: 429, message: 'Too many login attempts. Please wait before trying again.',
  })
})
