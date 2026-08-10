import { WITMOTION_NOTIFY_UUID, WITMOTION_SERVICE_UUID } from './witMotion.js'

function cleanup(resource) {
  if (!resource) return
  if (resource.characteristic && resource.onValue) {
    resource.characteristic.removeEventListener('characteristicvaluechanged', resource.onValue)
  }
  if (resource.device && resource.onDisconnect) {
    resource.device.removeEventListener('gattserverdisconnected', resource.onDisconnect)
  }
  try {
    resource.characteristic?.stopNotifications?.().catch(() => {})
  } catch {}
  try {
    if (resource.device?.gatt?.connected) resource.device.gatt.disconnect()
  } catch {}
}

export class WitMotionConnection {
  #bluetooth
  #generation = 0
  #resource = null

  constructor(bluetooth) {
    this.#bluetooth = bluetooth
  }

  async connect({ onValue, onDisconnect }) {
    this.disconnect()
    const generation = this.#generation
    const resource = {}

    try {
      resource.device = await this.#bluetooth.requestDevice({
        filters: [{ namePrefix: 'WT901' }],
        optionalServices: [WITMOTION_SERVICE_UUID],
      })
      if (!this.#isCurrent(generation)) return cleanup(resource), false
      this.#resource = resource

      const server = await resource.device.gatt.connect()
      if (!this.#isCurrent(generation)) return cleanup(resource), false
      const service = await server.getPrimaryService(WITMOTION_SERVICE_UUID)
      if (!this.#isCurrent(generation)) return cleanup(resource), false
      resource.characteristic = await service.getCharacteristic(WITMOTION_NOTIFY_UUID)
      if (!this.#isCurrent(generation)) return cleanup(resource), false

      resource.onValue = onValue
      resource.onDisconnect = () => {
        if (!this.#isCurrent(generation)) return
        resource.characteristic.removeEventListener('characteristicvaluechanged', resource.onValue)
        resource.device.removeEventListener('gattserverdisconnected', resource.onDisconnect)
        this.#resource = null
        onDisconnect()
      }
      resource.characteristic.addEventListener('characteristicvaluechanged', resource.onValue)
      resource.device.addEventListener('gattserverdisconnected', resource.onDisconnect)
      await resource.characteristic.startNotifications()
      if (!this.#isCurrent(generation)) return cleanup(resource), false
      return true
    } catch (error) {
      if (this.#resource === resource) this.#resource = null
      cleanup(resource)
      if (!this.#isCurrent(generation)) return false
      throw error
    }
  }

  disconnect() {
    this.#generation += 1
    const resource = this.#resource
    this.#resource = null
    cleanup(resource)
  }

  #isCurrent(generation) {
    return generation === this.#generation
  }
}
