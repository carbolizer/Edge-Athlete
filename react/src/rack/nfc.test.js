import { describe, expect, it, vi } from 'vitest'
import { handleNfcPollResult } from './nfc.js'

describe('NFC polling result', () => {
  it('stops after a recognized athlete checks in', async () => {
    const select = vi.fn().mockResolvedValue(true)
    expect(await handleNfcPollResult(
      { status: 'recognized', athlete: { athlete_id: 6, name: 'Braydon Callender' } },
      select,
    )).toEqual({ stop: true, message: 'Welcome, Braydon Callender', delay: 0 })
  })

  it('resumes with retap guidance when fenced check-in fails', async () => {
    const select = vi.fn().mockResolvedValue(false)
    expect(await handleNfcPollResult(
      { status: 'recognized', athlete: { athlete_id: 6, name: 'Braydon Callender' } },
      select,
    )).toEqual({
      stop: false,
      message: 'Check-in did not complete. Remove and retap the wristband.',
      delay: 2000,
    })
  })

  it('keeps unknown and unavailable results passive', async () => {
    const select = vi.fn()
    expect((await handleNfcPollResult({ status: 'unknown' }, select)).message)
      .toBe('Wristband not recognized')
    expect((await handleNfcPollResult({ status: 'unavailable' }, select)).message)
      .toBe('Card reader unavailable')
    expect(select).not.toHaveBeenCalled()
  })
})
