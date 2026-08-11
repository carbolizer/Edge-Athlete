export const HELPER_STATUSES = [
  'pairing_required', 'launching', 'no_sensor', 'scanning', 'verifying', 'ready',
  'active_online', 'active_offline', 'stopping', 'draining', 'released', 'stale',
  'credential_revoked', 'authentication_blocked', 'sensor_reconnecting',
  'queue_full', 'queue_corrupt', 'keychain_unavailable', 'update_required',
  'queue_unsafe', 'queue_read_only', 'queue_write_failed', 'endpoint_reassigned',
  'recovery_required',
]

const TRANSITIONAL = new Set(['launching', 'stopping', 'draining'])
const LAUNCH = new Set(['pairing_required', 'stale', 'released'])

const STATUS_COPY = {
  pairing_required: ['Pairing required', 'This Rack has no active Helper installation.', 'attention'],
  launching: ['Launching', 'The Helper accepted this Rack launch request.', 'progress'],
  no_sensor: ['No sensor', 'The development Helper is connected to the control plane. Sensor access is not enabled.', 'attention'],
  scanning: ['Scanning', 'The Helper is looking for its assigned sensor.', 'progress'],
  verifying: ['Verifying sensor', 'The Helper is checking the selected sensor.', 'progress'],
  ready: ['Ready', 'The Helper is ready for an authorized workout.', 'healthy'],
  active_online: ['Active and online', 'The Helper has an active context and cloud connection.', 'healthy'],
  active_offline: ['Active and offline', 'The Helper reports an active context without cloud connectivity.', 'attention'],
  stopping: ['Stopping', 'The Helper is closing capture and its sensor connection.', 'progress'],
  draining: ['Draining queue', 'The Helper is finishing committed work before release.', 'progress'],
  released: ['Released', 'The cloud acknowledged Helper release.', 'neutral'],
  stale: ['Check-in stale', 'The cloud has not received a fresh Helper heartbeat.', 'attention'],
  credential_revoked: ['Credential revoked', 'This Helper credential is no longer authorized.', 'blocked'],
  authentication_blocked: ['Authentication blocked', 'The Helper could not authenticate to the control plane.', 'blocked'],
  sensor_reconnecting: ['Sensor reconnecting', 'The Helper is restoring its sensor connection.', 'attention'],
  queue_full: ['Queue full', 'The Helper cannot safely accept more queued work.', 'blocked'],
  queue_corrupt: ['Queue corrupt', 'The Helper queue requires operator recovery.', 'blocked'],
  keychain_unavailable: ['Keychain unavailable', 'The Helper cannot safely access its credential store.', 'blocked'],
  update_required: ['Update required', 'This Helper version is not accepted for new work.', 'blocked'],
  queue_unsafe: ['Queue unsafe', 'The Helper cannot prove safe queue durability.', 'blocked'],
  queue_read_only: ['Queue read-only', 'The Helper cannot write to its durable queue.', 'blocked'],
  queue_write_failed: ['Queue write failed', 'The Helper could not durably save queued work.', 'blocked'],
  endpoint_reassigned: ['Rack reassigned', 'This Helper no longer matches the Rack endpoint assignment.', 'blocked'],
  recovery_required: ['Recovery required', 'An authorized operator must resolve the Helper state.', 'blocked'],
}

export function helperPresentation(status) {
  const normalized = HELPER_STATUSES.includes(status) ? status : 'pairing_required'
  const [label, detail, tone] = STATUS_COPY[normalized]
  return {
    status: normalized,
    label,
    detail,
    tone,
    action: TRANSITIONAL.has(normalized) ? null : {
      label: LAUNCH.has(normalized) ? 'Launch Helper' : 'Open Helper',
    },
  }
}

export function launchAcknowledged(created, inspected) {
  if (!created || !inspected || inspected.intent_id !== created.intent_id) return false
  if (inspected.state !== 'consumed' || inspected.ack_cursor == null || !inspected.acknowledged_at) return false
  if (Number(inspected.ack_cursor) <= Number(created.create_status_cursor)) return false

  const expiresAt = Date.parse(created.expires_at)
  const acknowledgedAt = Date.parse(inspected.acknowledged_at)
  if (!Number.isFinite(expiresAt) || !Number.isFinite(acknowledgedAt)) return false
  return acknowledgedAt > expiresAt - 5 * 60 * 1000
}

export async function runLaunchAttempt({ create, inspect, invoke, wait }) {
  const created = await create()
  if (created?.launch_uri !== 'edgeathlete-rack:launch') {
    throw new Error('The launch response did not contain the accepted Rack Helper URI.')
  }
  invoke('edgeathlete-rack:launch')

  let lastInspectError = null
  for (let second = 1; second <= 5; second += 1) {
    await wait(1000)
    let inspected
    try {
      inspected = await inspect(created.intent_id)
      lastInspectError = null
    } catch (error) {
      lastInspectError = error
      continue
    }
    if (launchAcknowledged(created, inspected)) return { state: 'confirmed', created, inspected }
    if (inspected?.state && inspected.state !== 'pending') {
      return { state: 'unconfirmed', created, inspected }
    }
  }
  return { state: 'unconfirmed', created, inspectError: lastInspectError }
}
