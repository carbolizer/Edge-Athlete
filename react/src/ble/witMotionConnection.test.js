import { describe, expect, it, vi } from 'vitest'
import { WITMOTION_NOTIFY_UUID, WITMOTION_SERVICE_UUID } from './witMotion.js'
import { WitMotionConnection } from './witMotionConnection.js'

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

function fakeGatt() {
  const listeners = new Map()
  const characteristic = {
    addEventListener: vi.fn((name, fn) => listeners.set(name, fn)),
    removeEventListener: vi.fn((name) => listeners.delete(name)),
    startNotifications: vi.fn(async () => characteristic),
    stopNotifications: vi.fn(async () => characteristic),
  }
  const service = { getCharacteristic: vi.fn(async () => characteristic) }
  const server = { getPrimaryService: vi.fn(async () => service) }
  const device = {
    listeners,
    addEventListener: vi.fn((name, fn) => listeners.set(name, fn)),
    removeEventListener: vi.fn((name) => listeners.delete(name)),
    gatt: {
      connected: true,
      connect: vi.fn(async () => server),
      disconnect: vi.fn(() => { device.gatt.connected = false }),
    },
  }
  const bluetooth = { requestDevice: vi.fn(async () => device) }
  return { bluetooth, characteristic, device, server, service }
}

describe('WitMotionConnection', () => {
  it('requests only the WT901 service and notification characteristic', async () => {
    const fixture = fakeGatt()
    const connection = new WitMotionConnection(fixture.bluetooth)
    await connection.connect({ onValue() {}, onDisconnect() {} })

    expect(fixture.bluetooth.requestDevice).toHaveBeenCalledWith({
      filters: [{ namePrefix: 'WT901' }],
      optionalServices: [WITMOTION_SERVICE_UUID],
    })
    expect(fixture.server.getPrimaryService).toHaveBeenCalledWith(WITMOTION_SERVICE_UUID)
    expect(fixture.service.getCharacteristic).toHaveBeenCalledWith(WITMOTION_NOTIFY_UUID)
    expect(fixture.characteristic.startNotifications).toHaveBeenCalledOnce()
  })

  it('disconnects a device when the page closes during GATT connection', async () => {
    const fixture = fakeGatt()
    const pendingServer = deferred()
    fixture.device.gatt.connect.mockReturnValue(pendingServer.promise)
    const connection = new WitMotionConnection(fixture.bluetooth)
    const connecting = connection.connect({ onValue() {}, onDisconnect() {} })
    await Promise.resolve()

    connection.disconnect()
    pendingServer.resolve(fixture.server)

    await expect(connecting).resolves.toBe(false)
    expect(fixture.device.gatt.disconnect).toHaveBeenCalledOnce()
    expect(fixture.service.getCharacteristic).not.toHaveBeenCalled()
  })

  it('removes listeners after hardware disconnect and reconnect', async () => {
    const first = fakeGatt()
    const second = fakeGatt()
    const bluetooth = {
      requestDevice: vi.fn()
        .mockResolvedValueOnce(first.device)
        .mockResolvedValueOnce(second.device),
    }
    const disconnected = vi.fn()
    const connection = new WitMotionConnection(bluetooth)
    await connection.connect({ onValue() {}, onDisconnect: disconnected })

    first.device.listeners.get('gattserverdisconnected')()
    expect(disconnected).toHaveBeenCalledOnce()
    expect(first.characteristic.removeEventListener).toHaveBeenCalledOnce()
    expect(first.device.removeEventListener).toHaveBeenCalledOnce()

    await connection.connect({ onValue() {}, onDisconnect: disconnected })
    connection.disconnect()
    expect(second.characteristic.stopNotifications).toHaveBeenCalledOnce()
    expect(second.device.gatt.disconnect).toHaveBeenCalledOnce()
  })
})
