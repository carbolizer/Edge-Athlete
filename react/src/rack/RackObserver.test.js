import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import RackObserver, { formatSnapshot, snapshotTiming } from './RackObserver.jsx'

const snapshot = {
  rack_number: 4,
  controller_active: true,
  phase: 'active',
  selected_athlete: { id: 2, name: 'Jordan' },
  selected_exercise: { id: 3, name: 'Back Squat' },
  current_set: 18,
  rep_count: 5,
  latest_mean_velocity: 0.7,
  latest_peak_velocity: 0.9,
  latest_color: 'green',
  phase_started_at: '2026-08-05T12:00:00Z',
  server_time: '2026-08-05T12:00:04Z',
}

describe('rack observer snapshot', () => {
  it('formats every authoritative live field without controller identity', () => {
    expect(formatSnapshot(snapshot, Date.parse(snapshot.server_time))).toMatchObject({
      rack: 4,
      athlete: 'Jordan',
      exercise: 'Back Squat',
      phase: 'active',
      currentSet: 18,
      reps: 5,
      mean: 0.7,
      peak: 0.9,
      color: 'green',
      timing: 4,
      lease: 'Controller connected',
    })
  })

  it('derives countdown and rest timers from phase start and server time', () => {
    expect(snapshotTiming({ ...snapshot, phase: 'countdown', server_time: '2026-08-05T12:00:02Z' }, Date.parse('2026-08-05T12:00:02Z'))).toBe(1)
    expect(snapshotTiming({ ...snapshot, phase: 'rest', server_time: '2026-08-05T12:00:05Z' }, Date.parse('2026-08-05T12:00:05Z'))).toBe(115)
  })
})

// The dead end: a rack holding an unfinished set refused every claim, so a
// rebooted screen sat here read-only with nothing to press and no reason given.
// A coach release or a base-station restart was the only way out, and neither is
// available to the athlete standing at the rack.
describe('the way out of a stranded rack', () => {
  const stranded = { ...snapshot, phase: 'recovery_required', controller_active: false }

  it('promises to END the set when the claim was refused — it will', () => {
    const html = renderToStaticMarkup(createElement(RackObserver, {
      snapshot: stranded, reason: 'rack_recovery_required', canRecover: true, onRecover: () => {},
    }))
    expect(html).toContain('This rack has an unfinished set')
    expect(html).toContain('Recover this rack')
    expect(html).toContain('ends it')
  })

  it('promises to RESUME the set after a dropped connection — because it does', () => {
    // Verified on the running stack: the tab survived, so the server still
    // recognises this controller and the set comes back with its reps. Telling
    // the athlete we are discarding it would be a lie, and the kind that stops
    // someone pressing the button that fixes their rack.
    const html = renderToStaticMarkup(createElement(RackObserver, {
      snapshot: stranded, reason: 'lease_expired', canRecover: true, onRecover: () => {},
    }))
    expect(html).toContain('This screen lost its connection')
    expect(html).toContain('Reconnect to this rack')
    expect(html).toContain('nothing is lost')
    expect(html).not.toContain('ends it')
  })

  it('offers nothing when this screen is not the one assigned to the rack', () => {
    // Recovery ends someone's set. A screen that does not own this rack must not
    // be shown the button at all — the server refuses it, and offering an action
    // that always fails is worse than staying quiet.
    const html = renderToStaticMarkup(createElement(RackObserver, {
      snapshot: stranded, reason: 'rack_screen_not_assigned', canRecover: false,
    }))
    expect(html).not.toContain('Recover this rack')
    expect(html).toContain('This screen is not assigned to control this rack')
  })

  it('still renders as a plain observer when nothing is wrong', () => {
    const html = renderToStaticMarkup(createElement(RackObserver, { snapshot, reason: '' }))
    expect(html).not.toContain('Recover this rack')
    expect(html).toContain('Read-only observer')
  })
})
