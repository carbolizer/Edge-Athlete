import { afterEach, describe, expect, it, vi } from 'vitest'
import { getRackSensorHealth, requiresRackAgent, sensorHealthIsReady } from './rackAgent.js'

const node = { node_id: 'generated-node', acquisition_kind: 'wt901_ble' }

describe('central rack sensor health gate', () => {
  afterEach(() => vi.restoreAllMocks())

  it('requires central health for BLE nodes without changing MQTT nodes', () => {
    expect(requiresRackAgent(node)).toBe(true)
    expect(requiresRackAgent({ node_id: 'rack_1', acquisition_kind: 'mqtt' })).toBe(false)
  })

  it('accepts only live, fresh health for the assigned node', () => {
    const health = { node_id: node.node_id, state: 'live', sample_age_ms: 80 }
    expect(sensorHealthIsReady(health, node)).toBe(true)
    expect(sensorHealthIsReady({ ...health, node_id: 'other' }, node)).toBe(false)
    expect(sensorHealthIsReady({ ...health, state: 'stale' }, node)).toBe(false)
    expect(sensorHealthIsReady({ ...health, sample_age_ms: 1001 }, node)).toBe(false)
  })

  it('sends rack identity only in a header', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ state: 'live' }),
    })

    await getRackSensorHealth(7, 'private-screen-id')

    expect(fetchMock).toHaveBeenCalledWith('/api/racks/7/sensor-health/', {
      cache: 'no-store',
      headers: { 'X-Rack-Device-ID': 'private-screen-id' },
    })
    expect(fetchMock.mock.calls[0][0]).not.toContain('private-screen-id')
  })
})
