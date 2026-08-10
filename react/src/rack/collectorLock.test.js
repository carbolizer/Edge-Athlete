import { describe, expect, it } from 'vitest'
import { canClaimCollectorLease, collectorLockName } from './collectorLock.js'

describe('collectorLockName', () => {
  it('isolates the cross-tab collector lock by rack', () => {
    expect(collectorLockName(1)).toBe('edgeathlete-rack-1-rep-collector')
    expect(collectorLockName(2)).toBe('edgeathlete-rack-2-rep-collector')
  })

  it('allows only the owner or an expired lease to claim', () => {
    expect(canClaimCollectorLease({ owner: 'a', expiresAt: 200 }, 'a', 100)).toBe(true)
    expect(canClaimCollectorLease({ owner: 'a', expiresAt: 200 }, 'b', 100)).toBe(false)
    expect(canClaimCollectorLease({ owner: 'a', expiresAt: 100 }, 'b', 100)).toBe(true)
    expect(canClaimCollectorLease(null, 'b', 100)).toBe(true)
  })
})
