const CLIENT_INSTANCE_KEY = 'rack_client_instance_id'
const CONTROLLER_TOKEN_KEY = 'rack_controller_token'

export const CONTROLLER_LOSS_CODES = new Set([
  'rack_controller_busy',
  'rack_controller_required',
  'rack_controller_stale',
  'rack_recovery_required',
  'rack_screen_not_assigned',
])

export function base64Url(bytes) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
  let output = ''
  for (let i = 0; i < bytes.length; i += 3) {
    const value = (bytes[i] << 16) | ((bytes[i + 1] || 0) << 8) | (bytes[i + 2] || 0)
    output += alphabet[(value >>> 18) & 63] + alphabet[(value >>> 12) & 63]
    if (i + 1 < bytes.length) output += alphabet[(value >>> 6) & 63]
    if (i + 2 < bytes.length) output += alphabet[value & 63]
  }
  return output
}

export function getTabControllerIdentity(storage = sessionStorage, cryptoApi = crypto) {
  let clientInstanceId = storage.getItem(CLIENT_INSTANCE_KEY)
  let controllerToken = storage.getItem(CONTROLLER_TOKEN_KEY)
  if (!clientInstanceId) {
    clientInstanceId = cryptoApi.randomUUID()
    storage.setItem(CLIENT_INSTANCE_KEY, clientInstanceId)
  }
  if (!controllerToken) {
    controllerToken = base64Url(cryptoApi.getRandomValues(new Uint8Array(32)))
    storage.setItem(CONTROLLER_TOKEN_KEY, controllerToken)
  }
  return { clientInstanceId, controllerToken }
}

export function controllerHeaders(capability) {
  return {
    'X-Rack-Device-ID': capability.deviceId,
    'X-Client-Instance-ID': capability.clientInstanceId,
    'X-Controller-Token': capability.controllerToken,
    'X-Controller-Epoch': String(capability.controllerEpoch),
  }
}

export function controllerCommand(fields, stateVersion, commandId = crypto.randomUUID()) {
  return { ...fields, expected_state_version: stateVersion, command_id: commandId }
}

export function shouldAcceptSnapshot(current, next) {
  if (!current) return true
  if (next.state_version !== current.state_version) return next.state_version > current.state_version
  return Date.parse(next.server_time) >= Date.parse(current.server_time)
}

export function isControllerLoss(error) {
  return error?.status === 409 && CONTROLLER_LOSS_CODES.has(error.code)
}
