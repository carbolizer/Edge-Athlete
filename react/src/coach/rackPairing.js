export function endpointClaimPayload(pairingCode, trainingGroup, displayName) {
  return {
    pairing_code: pairingCode.trim().toUpperCase(),
    training_group: Number(trainingGroup),
    display_name: displayName.trim(),
  }
}

export function helperPairingId(value) {
  return value.trim().toLowerCase()
}

export function endpointClaimErrorMessage(error) {
  if (error?.status !== 429) return error?.message || 'The Rack endpoint could not be claimed.'
  const retry = Number(error?.data?.retry_after_seconds)
  const wait = Number.isInteger(retry) && retry > 0 ? `Wait ${retry} seconds` : 'Wait a few minutes'
  return `${wait}, then create a new pairing code on the Rack and try once.`
}

export function helperConfirmationErrorMessage(error) {
  if (error?.status !== 429) return error?.message || 'The Rack Helper could not be confirmed.'
  const retry = Number(error?.data?.retry_after_seconds)
  const wait = Number.isInteger(retry) && retry > 0 ? `Wait ${retry} seconds` : 'Wait a few minutes'
  return `${wait}, then restart Helper pairing and compare the new six-word phrase before trying once.`
}
