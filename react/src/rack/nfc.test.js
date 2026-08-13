import { describe, expect, it, vi } from 'vitest'
import { handleNfcPollResult, pollLocalNfcTap } from './nfc.js'

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

describe('local NFC tap polling', () => {
  it('returns a tap with the raw tag id', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ schema_version: 1, status: 'tap', tag_id: '044DF23A1F1D91' }),
    })
    const result = await pollLocalNfcTap(8766)
    expect(result).toEqual({ status: 'tap', tag_id: '044DF23A1F1D91' })
    expect(fetch).toHaveBeenCalledWith(
      'http://localhost:8766/v1/taps/consume', { cache: 'no-store' },
    )
  })

  it('reads none when no card is on the reader', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ schema_version: 1, status: 'none' }),
    })
    expect(await pollLocalNfcTap()).toEqual({ status: 'none' })
  })

  it('is unavailable when the agent is down or rejects', async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    expect(await pollLocalNfcTap()).toEqual({ status: 'unavailable' })

    global.fetch = vi.fn().mockResolvedValue({ ok: false })
    expect(await pollLocalNfcTap()).toEqual({ status: 'unavailable' })
  })
})
