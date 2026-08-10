export async function handleNfcPollResult(result, selectAthlete) {
  if (result.status === 'recognized') {
    const checkedIn = await selectAthlete(result.athlete)
    return checkedIn
      ? { stop: true, message: `Welcome, ${result.athlete.name}`, delay: 0 }
      : { stop: false, message: 'Check-in did not complete. Remove and retap the wristband.', delay: 2000 }
  }
  if (result.status === 'unknown') {
    return { stop: false, message: 'Wristband not recognized', delay: 2000 }
  }
  if (result.status === 'unavailable') {
    return { stop: false, message: 'Card reader unavailable', delay: 2000 }
  }
  return { stop: false, message: 'Ready for wristband', delay: 500 }
}
