import { describe, expect, it } from 'vitest'
import {
  assignedNodeForRack,
  bleSetupError,
  candidateLabel,
  isVerificationReady,
  normalizeBleCandidates,
} from './nodeSetup.js'

describe('central BLE rack setup', () => {
  it('normalizes candidates, removes repeated handles, and keeps advertised signal details', () => {
    const candidates = normalizeBleCandidates({ candidates: [
      { device_handle: 'scan-a', advertised_label: 'WT901', rssi: -70 },
      { device_handle: 'scan-a', advertised_label: 'WT901', rssi: -45 },
      { device_handle: 'scan-b', name: 'Rack sensor', rssi: -60 },
      { advertised_label: 'Address must not become a handle', rssi: -20 },
    ] })

    expect(candidates).toEqual([
      { device_handle: 'scan-a', label: 'WT901', rssi: -45 },
      { device_handle: 'scan-b', label: 'Rack sensor', rssi: -60 },
    ])
  })

  it('makes duplicate advertised names distinguishable by opaque handle', () => {
    const candidates = normalizeBleCandidates([
      { device_handle: 'opaque-handle-one', label: 'WT901', rssi: -40 },
      { device_handle: 'opaque-handle-two', label: 'WT901', rssi: -42 },
    ])

    expect(candidateLabel(candidates[0], candidates)).toBe('WT901 (ndle-one)')
    expect(candidateLabel(candidates[1], candidates)).toBe('WT901 (ndle-two)')
  })

  it('requires a token and measured movement before assignment is ready', () => {
    expect(isVerificationReady({ verification_token: 'verify-1', movement_g: 0.184 })).toBe(true)
    expect(isVerificationReady({ verification_token: 'verify-1', movement_g: null })).toBe(false)
    expect(isVerificationReady({ movement_g: 0.184 })).toBe(false)
    expect(isVerificationReady({ verification_token: 'verify-1', movement_g: 0.1, verified: false })).toBe(false)
  })

  it('maps retryable central BLE errors to clear recovery actions', () => {
    expect(bleSetupError({ code: 'adapter_unavailable' })).toContain('adapter')
    expect(bleSetupError({ code: 'scan_timeout' })).toContain('scan again')
    expect(bleSetupError({ code: 'device_handle_expired' })).toContain('Scan nearby sensors again')
    expect(bleSetupError({ code: 'verification_expired' })).toContain('verify the sensor again')
    expect(bleSetupError({ code: 'movement_not_confirmed' }))
      .toBe('Sensor movement was not confirmed. Move the sensor, then verify it again.')
    expect(bleSetupError({ code: 'binding_reconciliation_required' })).toContain('assignment changed')
    expect(bleSetupError({ code: 'ble_reconciliation_required' })).toContain('reconcile this rack')
  })

  it('retains only an active physical node for downstream MQTT routing', () => {
    expect(assignedNodeForRack([
      { node_id: 'generated-node', rack_number: 2, is_active: true, is_simulated: false },
      { node_id: 'simulation', rack_number: 2, is_active: true, is_simulated: true },
    ], 2)?.node_id).toBe('generated-node')
  })
})
