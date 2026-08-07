export function assignedNodeForRack(nodes, rackNumber) {
  return (Array.isArray(nodes) ? nodes : []).find((node) =>
    node.rack_number === rackNumber && node.is_active && !node.is_simulated
  ) || null
}

export function normalizeBleCandidates(payload) {
  const rows = Array.isArray(payload)
    ? payload
    : payload?.candidates || payload?.devices || payload?.results || []
  const byHandle = new Map()

  for (const row of Array.isArray(rows) ? rows : []) {
    const deviceHandle = row?.device_handle || row?.handle
    if (typeof deviceHandle !== 'string' || !deviceHandle) continue
    const rssi = Number(row.rssi)
    const candidate = {
      device_handle: deviceHandle,
      label: String(row.advertised_label || row.label || row.name || 'Unnamed sensor'),
      rssi: Number.isFinite(rssi) ? rssi : null,
    }
    const previous = byHandle.get(deviceHandle)
    if (!previous || (candidate.rssi ?? -Infinity) > (previous.rssi ?? -Infinity)) {
      byHandle.set(deviceHandle, candidate)
    }
  }

  return [...byHandle.values()].sort((a, b) =>
    (b.rssi ?? -Infinity) - (a.rssi ?? -Infinity)
      || a.label.localeCompare(b.label)
      || a.device_handle.localeCompare(b.device_handle)
  )
}

export function candidateLabel(candidate, candidates) {
  const label = candidate?.label || 'Unnamed sensor'
  const duplicateCount = (Array.isArray(candidates) ? candidates : [])
    .filter((item) => (item?.label || 'Unnamed sensor') === label).length
  if (duplicateCount < 2) return label
  const handle = String(candidate?.device_handle || '')
  return `${label} (${handle.length > 8 ? handle.slice(-8) : handle})`
}

export function isVerificationReady(verification) {
  const movement = verification?.movement_g
  return Boolean(
    verification
    && typeof verification.verification_token === 'string'
    && verification.verification_token
    && movement != null
    && Number.isFinite(Number(movement))
    && verification.verified !== false
  )
}

export function bleSetupError(error, fallback = 'The sensor setup request failed. Try again.') {
  const code = error?.code || error?.data?.code
  if (['adapter_unavailable', 'ble_adapter_unavailable'].includes(code)) {
    return 'The base station Bluetooth adapter is unavailable. Check the adapter, then scan again.'
  }
  if (['scan_timeout', 'scan_failed'].includes(code)) {
    return 'The sensor scan did not complete. Move closer to the sensor and scan again.'
  }
  if (['scan_expired', 'device_handle_expired', 'unknown_device_handle'].includes(code)) {
    return 'That scan result expired. Scan nearby sensors again.'
  }
  if (['verification_expired', 'verification_token_expired'].includes(code)) {
    return 'Sensor verification expired. Scan and verify the sensor again.'
  }
  if (code === 'movement_not_confirmed') {
    return 'Sensor movement was not confirmed. Move the sensor, then verify it again.'
  }
  if (['device_unavailable', 'verification_lost'].includes(code)) {
    return 'The sensor stopped responding. Move it near the rack and verify again.'
  }
  if (['device_assigned', 'device_assigned_elsewhere', 'rack_assignment_conflict'].includes(code)) {
    return 'That sensor is assigned to another rack. Scan and choose a different sensor.'
  }
  if (code === 'binding_reconciliation_required') {
    return 'The rack sensor assignment changed. Scan and verify the sensor again.'
  }
  if (code === 'ble_reconciliation_required') {
    return 'The BLE binding could not be restored. Stop setup and reconcile this rack before retrying.'
  }
  return error?.message || fallback
}

export function assignedSensorLabel(node, health) {
  return health?.advertised_label || health?.label || node?.advertised_label || node?.label
    || (node?.acquisition_kind === 'wt901_ble' ? 'Assigned BLE sensor' : node?.node_id)
    || 'Assigned sensor'
}
