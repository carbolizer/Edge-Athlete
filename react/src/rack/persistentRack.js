// Decides when a configured rack must stay mounted behind another app screen.
// Keeping that host alive prevents route changes from dropping live rep effects.
export function persistentRackHost(pathname, role, storedRackNumber) {
  const rackNumber = Number(storedRackNumber)
  if (role !== 'rack' || !Number.isInteger(rackNumber) || rackNumber < 1) return null

  const path = `/rack/${rackNumber}`
  if (pathname === '/rack') return null
  if (pathname === '/rack/setup') return null
  if (pathname.startsWith('/rack/') && pathname !== path) return null

  return { rackNumber, path, visible: pathname === path }
}

export function shouldClearCoachToken(pathname, role) {
  return role === 'rack' && pathname.startsWith('/rack/')
}
