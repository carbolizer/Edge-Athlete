export async function retireLocalOfflineShell(serviceWorker, cacheStorage) {
  const registrations = await serviceWorker.getRegistrations()
  const cacheNames = cacheStorage ? await cacheStorage.keys() : []
  await Promise.all([
    ...registrations.map((registration) => registration.unregister()),
    ...cacheNames
      .filter((name) => name.startsWith('edgeathlete-shell-'))
      .map((name) => cacheStorage.delete(name)),
  ])
}
