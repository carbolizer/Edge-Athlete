import { describe, expect, it } from 'vitest'
import {
  base64Url,
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
