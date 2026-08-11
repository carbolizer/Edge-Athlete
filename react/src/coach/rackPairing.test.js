import { describe, expect, it } from 'vitest'
import { endpointClaimPayload, helperPairingId } from './rackPairing.js'

describe('coach Rack pairing payloads', () => {
  it('normalizes human input into the exact endpoint claim body', () => {
    expect(endpointClaimPayload(' abcd1234 ', '7', ' Rack 3 ')).toEqual({
      pairing_code: 'ABCD1234', training_group: 7, display_name: 'Rack 3',
    })
  })

  it('trims and canonicalizes the helper pairing ID', () => {
    expect(helperPairingId(' ABCD-1234 ')).toBe('abcd-1234')
  })
})
