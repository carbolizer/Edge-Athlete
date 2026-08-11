import { describe, expect, it } from 'vitest'
import HostedRack from './rack/HostedRack.jsx'
import CoachRackPairing from './coach/CoachRackPairing.jsx'
import { hostedRoute } from './HostedApp.jsx'

describe('hosted application routes', () => {
  it('renders only the hosted Rack and coach surfaces directly', () => {
    expect(hostedRoute('/rack').type).toBe(HostedRack)
    const coachRoute = hostedRoute('/coach/rack-pairing')
    expect(coachRoute.type).toBe(CoachRackPairing)
    expect(coachRoute.props.showCoachWorkspace).toBe(false)
  })

  it('redirects compatibility and unknown paths without mounting local surfaces', () => {
    expect(hostedRoute('/rack/3').props.to).toBe('/rack')
    expect(hostedRoute('/coach').props.to).toBe('/coach/rack-pairing')
    expect(hostedRoute('/connection-test').props.to).toBe('/')
    expect(hostedRoute('/unknown').props.to).toBe('/')
  })
})
