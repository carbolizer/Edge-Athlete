import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import {
  DevelopmentPackageGuidance, EndpointPairingPanel, HelperPairingPanel, HelperStatusPanel,
} from './HostedRack.jsx'

describe('hosted Rack control plane renders', () => {
  it('renders endpoint setup with a coach-mediated pairing action', () => {
    const html = renderToStaticMarkup(createElement(EndpointPairingPanel, {
      pairing: null, busy: false, error: '', onStart: () => {},
    }))
    expect(html).toContain('Pair this browser')
    expect(html).toContain('Create pairing code')
  })

  it('renders the Helper status, launch action, and cloud evidence', () => {
    const html = renderToStaticMarkup(createElement(HelperStatusPanel, {
      helper: { status: 'stale', freshness: 'stale', status_cursor: 44 },
      attempt: null, disabled: false, onLaunch: () => {},
    }))
    expect(html).toContain('Check-in stale')
    expect(html).toContain('Launch Helper')
    expect(html).toContain('Status cursor')
  })

  it('renders the exact five-second fallback guidance and retry', () => {
    const html = renderToStaticMarkup(createElement(HelperStatusPanel, {
      helper: { status: 'pairing_required', freshness: 'not_applicable' },
      attempt: { state: 'unconfirmed' }, disabled: false, onLaunch: () => {},
    }))
    expect(html).toContain('Rack Helper has not checked in.')
    expect(html).toContain('If Rack Helper opened and asks to pair, continue setup.')
    expect(html).toContain('Try Launch Helper Again')
  })

  it('renders the six-word comparison when the Helper claims its code', () => {
    const html = renderToStaticMarkup(createElement(HelperPairingPanel, {
      pairing: {
        pairing_id: '00000000-0000-0000-0000-000000000001',
        pairing_code: 'ABCDEFGH',
        confirmation_phrase: ['amber', 'bench', 'clean', 'drive', 'edge', 'force'],
      },
      busy: false, error: '', onStart: () => {},
    }))
    expect(html).toContain('ABCDEFGH')
    expect(html).toContain('Coach confirmation ID')
    expect(html).toContain('00000000-0000-0000-0000-000000000001')
    expect(html).toContain('amber')
    expect(html).toContain('exactly match')
  })

  it('offers no unsafe download when the backend has no release catalog', () => {
    const html = renderToStaticMarkup(createElement(DevelopmentPackageGuidance))
    expect(html).toContain('No verified package is published')
    expect(html).toContain('offers no download')
    expect(html).not.toContain('href=')
  })
})
