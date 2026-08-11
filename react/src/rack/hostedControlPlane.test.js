import { describe, expect, it, vi } from 'vitest'
import {
  HELPER_STATUSES, helperPresentation, launchAcknowledged, runLaunchAttempt,
} from './hostedControlPlane.js'

describe('hosted Rack Helper state', () => {
  it('covers every backend status with the accepted action matrix', () => {
    expect(HELPER_STATUSES).toHaveLength(24)
    for (const status of HELPER_STATUSES) {
      const view = helperPresentation(status)
      expect(view.status).toBe(status)
      expect(view.label).toBeTruthy()
      expect(view.detail).toBeTruthy()
    }

    for (const status of ['pairing_required', 'stale', 'released']) {
      expect(helperPresentation(status).action).toEqual({ label: 'Launch Helper' })
    }
    for (const status of ['launching', 'stopping', 'draining']) {
      expect(helperPresentation(status).action).toBeNull()
    }
    for (const status of HELPER_STATUSES.filter((value) =>
      !['pairing_required', 'stale', 'released', 'launching', 'stopping', 'draining'].includes(value))) {
      expect(helperPresentation(status).action).toEqual({ label: 'Open Helper' })
    }
  })

  it('accepts only the intent-bound later server acknowledgement', () => {
    const created = {
      intent_id: 'intent-1', create_status_cursor: 41,
      expires_at: '2026-08-10T12:05:00.000Z',
    }
    const inspected = {
      intent_id: 'intent-1', state: 'consumed', ack_cursor: 42,
      acknowledged_at: '2026-08-10T12:00:01.000Z',
    }
    expect(launchAcknowledged(created, inspected)).toBe(true)
    expect(launchAcknowledged(created, { ...inspected, intent_id: 'other' })).toBe(false)
    expect(launchAcknowledged(created, { ...inspected, ack_cursor: 41 })).toBe(false)
    expect(launchAcknowledged(created, { ...inspected, acknowledged_at: '2026-08-10T12:00:00.000Z' })).toBe(false)
  })

  it('creates and invokes exactly once, then falls back after five inspections', async () => {
    const create = vi.fn().mockResolvedValue({
      intent_id: 'intent-1', launch_uri: 'edgeathlete-rack:launch',
      create_status_cursor: 1, expires_at: '2026-08-10T12:05:00.000Z',
    })
    const inspect = vi.fn().mockResolvedValue({ intent_id: 'intent-1', state: 'pending' })
    const invoke = vi.fn()
    const wait = vi.fn().mockResolvedValue(undefined)

    const result = await runLaunchAttempt({ create, inspect, invoke, wait })

    expect(result.state).toBe('unconfirmed')
    expect(create).toHaveBeenCalledTimes(1)
    expect(invoke).toHaveBeenCalledTimes(1)
    expect(invoke).toHaveBeenCalledWith('edgeathlete-rack:launch')
    expect(wait).toHaveBeenCalledTimes(5)
    expect(wait).toHaveBeenCalledWith(1000)
    expect(inspect).toHaveBeenCalledTimes(5)
  })

  it('never invokes an unexpected URI from the server', async () => {
    const invoke = vi.fn()
    await expect(runLaunchAttempt({
      create: async () => ({ launch_uri: 'edgeathlete-rack:launch?token=bad' }),
      inspect: vi.fn(), invoke, wait: vi.fn(),
    })).rejects.toThrow('accepted Rack Helper URI')
    expect(invoke).not.toHaveBeenCalled()
  })

  it('keeps inspecting through transient failures for the full five seconds', async () => {
    const inspect = vi.fn().mockRejectedValue(new Error('offline'))
    const wait = vi.fn().mockResolvedValue(undefined)
    const result = await runLaunchAttempt({
      create: async () => ({
        intent_id: 'intent-1', launch_uri: 'edgeathlete-rack:launch',
        create_status_cursor: 1, expires_at: '2026-08-10T12:05:00.000Z',
      }),
      inspect, invoke: vi.fn(), wait,
    })
    expect(result.state).toBe('unconfirmed')
    expect(result.inspectError.message).toBe('offline')
    expect(inspect).toHaveBeenCalledTimes(5)
    expect(wait).toHaveBeenCalledTimes(5)
  })
})
