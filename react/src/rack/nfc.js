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

// The rack screen lives on the same laptop as the NFC reader, so it reads taps
// straight from the agent's loopback HTTP endpoint. Django never sees the raw
// reader; it only receives the forwarded tag_id for athlete resolution. A
// missing or down agent reads as "unavailable", never an exception.
export async function pollLocalNfcTap(port = 8766) {
  try {
    const response = await fetch(`http://localhost:${port}/v1/taps/consume`, { cache: 'no-store' })
    if (!response.ok) return { status: 'unavailable' }
    const tap = await response.json()
    if (tap?.status === 'tap' && typeof tap?.tag_id === 'string') {
      return { status: 'tap', tag_id: tap.tag_id }
    }
    return { status: 'none' }
  } catch {
    return { status: 'unavailable' }
  }
}
