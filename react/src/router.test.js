import { describe, expect, it } from 'vitest'
import {
  hostedCompatibilityRedirect, hostedRoleHomePath, matchCoachPath, matchRackPath,
} from './router.js'

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

describe('deployment-profile routing', () => {
  it('sends hosted role choices to hosted surfaces', () => {
    expect(hostedRoleHomePath('rack')).toBe('/rack')
    expect(hostedRoleHomePath('coach')).toBe('/coach/rack-pairing')
    expect(hostedRoleHomePath('dashboard')).toBeNull()
  })

  it('redirects compatibility-only paths in hosted builds', () => {
    expect(hostedCompatibilityRedirect('/coach', true)).toBe('/coach/rack-pairing')
    expect(hostedCompatibilityRedirect('/coach/setup', true)).toBe('/coach/rack-pairing')
    expect(hostedCompatibilityRedirect('/rack/setup', true)).toBe('/rack')
    expect(hostedCompatibilityRedirect('/rack/3', true)).toBe('/rack')
    expect(hostedCompatibilityRedirect('/dashboard', true)).toBe('/')
    expect(hostedCompatibilityRedirect('/connection-test', true)).toBe('/')
    expect(hostedCompatibilityRedirect('/rack/not-a-number', true)).toBeNull()
    expect(hostedCompatibilityRedirect('/rack/setup', false)).toBeNull()
  })
})
