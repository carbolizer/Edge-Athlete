// Keeps one browser tab responsible for a rack's shared rep buffer.
// The short origin lease works on the base station's plain-HTTP tablet URL.
import { useCallback, useEffect, useRef, useState } from 'react'

const LEASE_MS = 120000
const HEARTBEAT_MS = 5000
const STABILIZE_MS = 50

export function collectorLockName(rackNumber) {
  return `edgeathlete-rack-${rackNumber}-rep-collector`
}

export function canClaimCollectorLease(lease, owner, now = Date.now()) {
  return lease?.owner === owner || !Number.isFinite(Number(lease?.expiresAt)) || Number(lease.expiresAt) <= now
}

export function useRackCollectorLock(rackNumber, enabled) {
  const [held, setHeld] = useState(false)
  const heldRef = useRef(false)
  const ownerRef = useRef(null)
  if (ownerRef.current == null) {
    ownerRef.current = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
  }

  useEffect(() => {
    heldRef.current = false
    setHeld(false)
    if (!enabled || !globalThis.localStorage) return
    const key = collectorLockName(rackNumber)
    const owner = ownerRef.current
    let cancelled = false
    let retryTimer
    let stabilizeTimer
    let heartbeatTimer

    const readLease = () => {
      try {
        return JSON.parse(globalThis.localStorage.getItem(key))
      } catch {
        return null
      }
    }
    const writeLease = () => {
      globalThis.localStorage.setItem(key, JSON.stringify({
        owner,
        expiresAt: Date.now() + LEASE_MS,
      }))
    }
    const scheduleRetry = (delay = LEASE_MS) => {
      clearTimeout(retryTimer)
      retryTimer = setTimeout(claim, Math.max(STABILIZE_MS, delay))
    }
    const heartbeat = () => {
      const lease = readLease()
      if (lease?.owner !== owner) {
        heldRef.current = false
        setHeld(false)
        clearInterval(heartbeatTimer)
        scheduleRetry(lease ? lease.expiresAt - Date.now() : STABILIZE_MS)
        return
      }
      try {
        writeLease()
      } catch {
        heldRef.current = false
        setHeld(false)
        clearInterval(heartbeatTimer)
      }
    }
    function claim() {
      if (cancelled) return
      const lease = readLease()
      if (!canClaimCollectorLease(lease, owner)) {
        scheduleRetry(lease.expiresAt - Date.now())
        return
      }
      try {
        writeLease()
      } catch {
        heldRef.current = false
        setHeld(false)
        return
      }
      stabilizeTimer = setTimeout(() => {
        if (cancelled) return
        if (readLease()?.owner !== owner) {
          scheduleRetry()
          return
        }
        heldRef.current = true
        setHeld(true)
        heartbeatTimer = setInterval(heartbeat, HEARTBEAT_MS)
      }, STABILIZE_MS)
    }
    const storageChanged = (event) => {
      if (event.key !== key || readLease()?.owner === owner) return
      heldRef.current = false
      setHeld(false)
      clearInterval(heartbeatTimer)
      const lease = readLease()
      scheduleRetry(lease ? lease.expiresAt - Date.now() : STABILIZE_MS)
    }
    globalThis.addEventListener?.('storage', storageChanged)
    claim()

    return () => {
      cancelled = true
      heldRef.current = false
      clearTimeout(retryTimer)
      clearTimeout(stabilizeTimer)
      clearInterval(heartbeatTimer)
      globalThis.removeEventListener?.('storage', storageChanged)
      if (readLease()?.owner === owner) globalThis.localStorage.removeItem(key)
    }
  }, [rackNumber, enabled])

  const ownsLease = useCallback(() => {
    if (!heldRef.current) return false
    try {
      const lease = JSON.parse(globalThis.localStorage.getItem(collectorLockName(rackNumber)))
      return lease?.owner === ownerRef.current && Number(lease.expiresAt) > Date.now()
    } catch {
      return false
    }
  }, [rackNumber])

  return { held, ownsLease }
}
