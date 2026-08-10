export const WITMOTION_SERVICE_UUID = '0000ffe5-0000-1000-8000-00805f9a34fb'
export const WITMOTION_NOTIFY_UUID = '0000ffe4-0000-1000-8000-00805f9a34fb'

const FRAME_HEADER = [0x55, 0x61]
const FRAME_SIZE = 20
const MAX_BUFFER_BYTES = FRAME_SIZE * 8
const MAX_COUNTER = 999_999_999

function addBounded(current, increment) {
  return Math.min(MAX_COUNTER, current + increment)
}

function notificationBytes(value) {
  if (value instanceof Uint8Array) return value
  if (value instanceof DataView) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength)
  }
  if (value instanceof ArrayBuffer) return new Uint8Array(value)
  throw new TypeError('BLE notification must be binary data')
}

export function decodeWitMotionFrame(value) {
  const bytes = notificationBytes(value)
  if (bytes.byteLength !== FRAME_SIZE || bytes[0] !== FRAME_HEADER[0] || bytes[1] !== FRAME_HEADER[1]) {
    throw new Error('invalid WT901 data frame')
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const values = Array.from({ length: 9 }, (_, index) => view.getInt16(2 + index * 2, true))
  return {
    accelerationG: values.slice(0, 3).map((sample) => sample / 32768 * 16),
    angularVelocityDps: values.slice(3, 6).map((sample) => sample / 32768 * 2000),
    angleDegrees: values.slice(6, 9).map((sample) => sample / 32768 * 180),
  }
}

export class WitMotionFrameDecoder {
  #buffer = new Uint8Array()

  rejectedBytes = 0

  feed(value) {
    const chunk = notificationBytes(value)
    const combined = new Uint8Array(this.#buffer.byteLength + chunk.byteLength)
    combined.set(this.#buffer)
    combined.set(chunk, this.#buffer.byteLength)
    this.#buffer = combined

    if (this.#buffer.byteLength > MAX_BUFFER_BYTES) {
      this.rejectedBytes = addBounded(this.rejectedBytes, this.#buffer.byteLength)
      this.#buffer = new Uint8Array()
      return []
    }

    const samples = []
    while (true) {
      let headerIndex = -1
      for (let index = 0; index < this.#buffer.byteLength - 1; index += 1) {
        if (this.#buffer[index] === FRAME_HEADER[0] && this.#buffer[index + 1] === FRAME_HEADER[1]) {
          headerIndex = index
          break
        }
      }
      if (headerIndex < 0) {
        const keepHeaderByte = this.#buffer.at(-1) === FRAME_HEADER[0]
        this.rejectedBytes = addBounded(
          this.rejectedBytes,
          this.#buffer.byteLength - (keepHeaderByte ? 1 : 0),
        )
        this.#buffer = keepHeaderByte ? this.#buffer.slice(-1) : new Uint8Array()
        break
      }
      if (headerIndex > 0) {
        this.rejectedBytes = addBounded(this.rejectedBytes, headerIndex)
        this.#buffer = this.#buffer.slice(headerIndex)
      }
      if (this.#buffer.byteLength < FRAME_SIZE) break
      samples.push(decodeWitMotionFrame(this.#buffer.slice(0, FRAME_SIZE)))
      this.#buffer = this.#buffer.slice(FRAME_SIZE)
    }
    return samples
  }
}

export function webBluetoothCapability(environment = globalThis) {
  if (!environment.isSecureContext) {
    return { supported: false, reason: 'Web Bluetooth requires HTTPS or localhost.' }
  }
  if (!environment.navigator?.bluetooth?.requestDevice) {
    return { supported: false, reason: 'This browser does not provide Web Bluetooth.' }
  }
  return { supported: true, reason: '' }
}
