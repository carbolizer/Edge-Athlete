import { describe, expect, it } from 'vitest'
import { formatSnapshot, snapshotTiming } from './RackObserver.jsx'

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
