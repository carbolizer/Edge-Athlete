import { describe, expect, it } from 'vitest'
import {
  base64Url,
  canOfferRecovery,
  controllerCommand,
  controllerHeaders,
  getTabControllerIdentity,
  isControllerLoss,
  shouldAcceptSnapshot,
} from './controller.js'

function memoryStorage() {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    values,
  }
}

describe('rack controller identity', () => {
  it('stores one tab-scoped id and canonical 32-byte base64url token in session storage', () => {
    const storage = memoryStorage()
    const cryptoApi = {
      randomUUID: () => 'tab-uuid',
      getRandomValues: (bytes) => bytes.fill(255),
    }
    const first = getTabControllerIdentity(storage, cryptoApi)
    const second = getTabControllerIdentity(storage, {
      randomUUID: () => 'different',
      getRandomValues: () => { throw new Error('must reuse') },
    })

    expect(first).toEqual(second)
    expect(first.clientInstanceId).toBe('tab-uuid')
    expect(first.controllerToken).toMatch(/^[A-Za-z0-9_-]{43}$/)
    expect(base64Url(new Uint8Array(32).fill(255))).toBe(first.controllerToken)
    expect([...storage.values.keys()]).toEqual(['rack_client_instance_id', 'rack_controller_token'])
  })

  it('creates the exact controller headers and command envelope', () => {
    const capability = {
      deviceId: 'screen-1', clientInstanceId: 'tab-1', controllerToken: 'secret', controllerEpoch: 7,
    }
    expect(controllerHeaders(capability)).toEqual({
      'X-Rack-Device-ID': 'screen-1',
      'X-Client-Instance-ID': 'tab-1',
      'X-Controller-Token': 'secret',
      'X-Controller-Epoch': '7',
    })
    expect(controllerCommand({ phase: 'rest' }, 12, 'command-1')).toEqual({
      phase: 'rest', expected_state_version: 12, command_id: 'command-1',
    })
  })

  it('distinguishes ownership loss from a reconcilable state conflict', () => {
    expect(isControllerLoss({ status: 409, code: 'rack_controller_stale' })).toBe(true)
    expect(isControllerLoss({ status: 409, code: 'rack_recovery_required' })).toBe(true)
    expect(isControllerLoss({ status: 409, code: 'rack_state_changed' })).toBe(false)
    expect(isControllerLoss({ status: 409, code: 'duplicate_checkin' })).toBe(false)
  })

  it('does not let delayed observer responses overwrite newer state', () => {
    const current = { state_version: 8, server_time: '2026-08-05T20:00:02Z' }
    expect(shouldAcceptSnapshot(current, {
      state_version: 7, server_time: '2026-08-05T20:00:03Z',
    })).toBe(false)
    expect(shouldAcceptSnapshot(current, {
      state_version: 8, server_time: '2026-08-05T20:00:01Z',
    })).toBe(false)
    expect(shouldAcceptSnapshot(current, {
      state_version: 9, server_time: '2026-08-05T20:00:01Z',
    })).toBe(true)
  })
})

// ── the offline path ───────────────────────────────────────────────────────────
// Found by Devi on real hardware, testing the way the gym actually fails: instead
// of closing the browser he put the tab offline. That never produces
// `rack_recovery_required` — the lease simply lapses locally — so the first
// version of the button never appeared, while the auto-retry stayed suppressed.
// Stranded, with nothing to press. These pin both routes in.
describe('offering the recovery button', () => {
  const stranded = { controller_active: false, current_set: 41 }

  it('offers it when a claim was refused outright (reboot, closed tab)', () => {
    expect(canOfferRecovery('observer', true, 'rack_recovery_required', null)).toBe(true)
  })

  it('offers it when the lease merely lapsed and a set is still open (network drop)', () => {
    expect(canOfferRecovery('observer', true, 'lease_expired', stranded)).toBe(true)
  })

  it('stays quiet while someone else is genuinely controlling the rack', () => {
    expect(canOfferRecovery('observer', true, 'rack_controller_busy', {
      controller_active: true, current_set: 41,
    })).toBe(false)
  })

  it('stays quiet when the rack is simply idle — nothing to recover', () => {
    expect(canOfferRecovery('observer', true, 'lease_expired', {
      controller_active: false, current_set: null,
    })).toBe(false)
  })

  it('never offers it to a screen that does not own this rack', () => {
    expect(canOfferRecovery('observer', false, 'rack_recovery_required', stranded)).toBe(false)
  })

  it('never offers it while this screen is still the controller', () => {
    expect(canOfferRecovery('controller', true, '', stranded)).toBe(false)
  })
})
