import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { RackPairingWorkspace } from './CoachRackPairing.jsx'

describe('coach hosted Rack pairing renders', () => {
  it('renders accessible endpoint and helper confirmation controls', () => {
    const html = renderToStaticMarkup(createElement(RackPairingWorkspace, {
      token: 'coach-token', groups: [{ id: 7, name: 'Varsity' }],
      loadingGroups: false, onAuthLost: () => {},
    }))

    expect(html).toContain('Endpoint code')
    expect(html).toContain('Varsity')
    expect(html).toContain('Rack label')
    expect(html).toContain('Helper code')
    expect(html).toContain('I compared all six words')
    expect(html).toContain('required=""')
  })
})
