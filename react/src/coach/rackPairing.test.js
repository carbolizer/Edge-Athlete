import { describe, expect, it } from 'vitest'
import {
  endpointClaimErrorMessage, endpointClaimPayload, helperConfirmationErrorMessage,
  helperConfirmationCode,
} from './rackPairing.js'

describe('coach Rack pairing payloads', () => {
  it('normalizes human input into the exact endpoint claim body', () => {
    expect(endpointClaimPayload(' abcd1234 ', '7', ' Rack 3 ')).toEqual({
      pairing_code: 'ABCD1234', training_group: 7, display_name: 'Rack 3',
    })
  })

  it('trims and canonicalizes the short Helper code', () => {
    expect(helperConfirmationCode(' abcdefgh ')).toBe('ABCDEFGH')
  })
})

describe('endpoint claim errors', () => {
  it('tells the coach how to recover from the accepted per-code throttle', () => {
    expect(endpointClaimErrorMessage({
      status: 429,
      data: { retry_after_seconds: 45 },
    })).toBe('Wait 45 seconds, then create a new pairing code on the Rack and try once.')
  })

  it('preserves non-throttle errors', () => {
    expect(endpointClaimErrorMessage({ status: 404, message: 'Not found.' })).toBe('Not found.')
  })

  it('handles proxy-generated throttles without a JSON response body', () => {
    expect(endpointClaimErrorMessage({ status: 429, data: 'Too Many Requests' }))
      .toBe('Wait a few minutes, then create a new pairing code on the Rack and try once.')
  })

  it('gives helper-specific throttle recovery', () => {
    expect(helperConfirmationErrorMessage({
      status: 429,
      data: { retry_after_seconds: 30 },
    })).toBe('Wait 30 seconds, then restart Helper pairing and compare the new six-word phrase before trying once.')
  })
})
