import { describe, expect, it } from 'vitest'
import { persistentRackHost, shouldClearCoachToken } from './persistentRack.js'

describe('persistentRackHost', () => {
  it('keeps the assigned rack mounted across coach and dashboard routes', () => {
    expect(persistentRackHost('/rack/1', 'rack', '1')).toEqual({
      rackNumber: 1,
      path: '/rack/1',
      visible: true,
    })
    expect(persistentRackHost('/coach', 'rack', '1')).toEqual({
      rackNumber: 1,
      path: '/rack/1',
      visible: false,
    })
    expect(persistentRackHost('/dashboard', 'rack', '1')).toEqual({
      rackNumber: 1,
      path: '/rack/1',
      visible: false,
    })
  })

  it('does not retain a rack during setup, role changes, or another rack route', () => {
    expect(persistentRackHost('/rack/setup', 'rack', '1')).toBeNull()
    expect(persistentRackHost('/coach', 'coach', '1')).toBeNull()
    expect(persistentRackHost('/rack/2', 'rack', '1')).toBeNull()
    expect(persistentRackHost('/coach', 'rack', 'invalid')).toBeNull()
  })

  it('clears coach access when a rack-role device returns to a rack route', () => {
    expect(shouldClearCoachToken('/rack/1', 'rack')).toBe(true)
    expect(shouldClearCoachToken('/coach', 'rack')).toBe(false)
    expect(shouldClearCoachToken('/rack/1', 'coach')).toBe(false)
  })
})
