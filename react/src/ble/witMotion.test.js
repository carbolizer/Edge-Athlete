import { describe, expect, it } from 'vitest'
import {
  decodeWitMotionFrame,
  webBluetoothCapability,
  WitMotionFrameDecoder,
} from './witMotion.js'

function frame(values = [2048, -4096, 16384, 16384, -8192, 4096, 8192, -16384, 0]) {
  const bytes = new Uint8Array(20)
  bytes.set([0x55, 0x61])
  const view = new DataView(bytes.buffer)
  values.forEach((value, index) => view.setInt16(2 + index * 2, value, true))
  return bytes
}

describe('WT901 browser decoder', () => {
  it('uses the verified WT901 scaling', () => {
    const sample = decodeWitMotionFrame(frame())
    expect(sample.accelerationG).toEqual([1, -2, 8])
    expect(sample.angularVelocityDps).toEqual([1000, -500, 250])
    expect(sample.angleDegrees).toEqual([45, -90, 0])
  })

  it('recovers fragmented, combined, and noise-prefixed frames', () => {
    const decoder = new WitMotionFrameDecoder()
    const first = frame()
    const second = frame([0, 0, 2048, 0, 0, 0, 0, 0, 0])
    expect(decoder.feed(first.slice(0, 7))).toEqual([])
    const result = decoder.feed(new Uint8Array([...first.slice(7), 9, 8, ...second]))
    expect(result).toHaveLength(2)
    expect(result[1].accelerationG[2]).toBe(1)
    expect(decoder.rejectedBytes).toBe(2)
  })

  it('bounds malformed input and rejects non-binary values', () => {
    const decoder = new WitMotionFrameDecoder()
    expect(decoder.feed(new Uint8Array(161))).toEqual([])
    expect(decoder.rejectedBytes).toBe(161)
    expect(() => decoder.feed('raw packet')).toThrow('binary data')
  })

  it('reports secure-context and browser support', () => {
    expect(webBluetoothCapability({ isSecureContext: false, navigator: {} }).supported).toBe(false)
    expect(webBluetoothCapability({
      isSecureContext: true,
      navigator: { bluetooth: { requestDevice() {} } },
    }).supported).toBe(true)
  })
})
