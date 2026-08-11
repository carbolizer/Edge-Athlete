import { describe, expect, it } from 'vitest'
import { matchCoachPath, matchRackPath } from './router.js'

describe('Rack route matching', () => {
  it('keeps the hosted control plane distinct from setup and live Rack routes', () => {
    expect(matchRackPath('/rack')).toEqual({ kind: 'hosted' })
    expect(matchRackPath('/rack/setup')).toEqual({ kind: 'setup' })
    expect(matchRackPath('/rack/3')).toEqual({ kind: 'live', rackNumber: 3 })
  })

  it('preserves invalid Rack route handling', () => {
    expect(matchRackPath('/rack/')).toEqual({ kind: 'invalid' })
    expect(matchRackPath('/rack/0')).toEqual({ kind: 'invalid' })
    expect(matchRackPath('/rack/3/extra')).toEqual({ kind: 'invalid' })
    expect(matchRackPath('/coach')).toBeNull()
  })
})

describe('Coach route matching', () => {
  it('exposes the hosted Rack pairing surface without matching Rack routes', () => {
    expect(matchCoachPath('/coach/rack-pairing')).toEqual({ kind: 'rack-pairing' })
    expect(matchRackPath('/coach/rack-pairing')).toBeNull()
    expect(matchCoachPath('/coach')).toBeNull()
  })
})
