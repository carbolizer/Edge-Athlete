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
