import { useCallback, useEffect, useRef, useState } from 'react'
import {
  acquireRackController,
  getRackState,
  heartbeatRackController,
  patchRackState,
  releaseRackController,
} from '../api/client.js'
import {
  controllerCommand,
  getTabControllerIdentity,
  isControllerLoss,
  shouldAcceptSnapshot,
} from './controllerIdentity.js'

export {
  base64Url,
  controllerCommand,
  controllerHeaders,
  getTabControllerIdentity,
  isControllerLoss,
  shouldAcceptSnapshot,
} from './controllerIdentity.js'

function leaseDuration(response) {
  const expiresAt = Date.parse(response.lease_expires_at)
  const serverTime = Date.parse(response.server_time)
  return Number.isFinite(expiresAt) && Number.isFinite(serverTime)
    ? Math.max(0, expiresAt - serverTime)
    : 0
}

// ── WHEN TO OFFER RECOVERY ─────────────────────────────────────────────────────
// There are TWO ways a screen ends up stranded, and they arrive with different
// reasons. Keying off the reason alone missed one of them:
//
//   REBOOT / closed tab — the session token dies, the next claim is refused, and
//     the server answers `rack_recovery_required`.
//   NETWORK DROP — the tab lives, but heartbeats stop and the lease lapses, so
//     the LOCAL timer flips us to observer with `lease_expired`. Nothing was
//     refused, so nobody ever said `rack_recovery_required`.
//
// The second is the likelier one in a gym, and it was the one that stayed stuck.
//
// So ask the snapshot instead: the rack has an unfinished set and no live
// controller. That is deliberately the SAME condition that suppresses the
// automatic retry — if we refuse to re-claim on our own because a set is open,
// we owe the athlete a button. The two must never disagree.
export function canOfferRecovery(mode, canClaim, reason, snapshot) {
  if (mode !== 'observer' || !canClaim) return false
  if (reason === 'rack_recovery_required') return true
  return Boolean(snapshot && !snapshot.controller_active && snapshot.current_set != null)
}

export function useRackController(rackNumber, deviceId, enabled, canClaim = true) {
  const identityRef = useRef(null)
  const capabilityRef = useRef(null)
  const snapshotRef = useRef(null)
  const leaseTimerRef = useRef(null)
  const leaseDeadlineRef = useRef(0)
  const mountedRef = useRef(false)
  const recoverRef = useRef(false)
  const [mode, setMode] = useState('checking')
  const [snapshot, setSnapshot] = useState(null)
  const [reason, setReason] = useState('')
  const [claimAttempt, setClaimAttempt] = useState(0)

  const consumeSnapshot = useCallback((next) => {
    if (!next) return
    const current = snapshotRef.current
    if (!shouldAcceptSnapshot(current, next)) return
    const received = { ...next, _received_at: Date.now() }
    snapshotRef.current = received
    setSnapshot(received)
  }, [])

  const reconcile = useCallback(async () => {
    try {
      const next = await getRackState(rackNumber)
      if (mountedRef.current) consumeSnapshot(next)
      return next
    } catch {
      return null
    }
  }, [rackNumber, consumeSnapshot])

  const becomeObserver = useCallback((error, fallbackReason = '') => {
    capabilityRef.current = null
    leaseDeadlineRef.current = 0
    clearTimeout(leaseTimerRef.current)
    if (error?.snapshot) consumeSnapshot(error.snapshot)
    if (mountedRef.current) {
      setMode('observer')
      setReason(error?.code || fallbackReason)
    }
    reconcile()
  }, [consumeSnapshot, reconcile])

  const armLeaseDeadline = useCallback((response) => {
    clearTimeout(leaseTimerRef.current)
    const duration = leaseDuration(response)
    leaseDeadlineRef.current = Date.now() + duration
    leaseTimerRef.current = setTimeout(() => {
      if (mountedRef.current) becomeObserver(null, 'lease_expired')
    }, duration)
  }, [becomeObserver])

  const runMutation = useCallback(async (operation) => {
    const capability = capabilityRef.current
    const current = snapshotRef.current
    if (!capability || !current || Date.now() >= leaseDeadlineRef.current) {
      becomeObserver(null, 'lease_expired')
      throw new Error('Rack is read-only')
    }
    try {
      const result = await operation(capability, current.state_version)
      await reconcile()
      return result
    } catch (error) {
      if (error?.snapshot) consumeSnapshot(error.snapshot)
      if (isControllerLoss(error)) becomeObserver(error)
      else if (error?.status === 409) await reconcile()
      throw error
    }
  }, [becomeObserver, consumeSnapshot, reconcile])

  const runControlled = useCallback(async (operation) => {
    const capability = capabilityRef.current
    if (!capability || Date.now() >= leaseDeadlineRef.current) {
      becomeObserver(null, 'lease_expired')
      throw new Error('Rack is read-only')
    }
    try {
      return await operation(capability)
    } catch (error) {
      if (isControllerLoss(error)) becomeObserver(error)
      throw error
    }
  }, [becomeObserver])

  const updateState = useCallback((fields) => runMutation((capability, version) => (
    patchRackState(rackNumber, controllerCommand(fields, version), capability)
      .then((next) => { consumeSnapshot(next); return next })
  )), [rackNumber, runMutation, consumeSnapshot])

  useEffect(() => {
    mountedRef.current = true
    if (!enabled) return () => { mountedRef.current = false }
    if (!canClaim) {
      setMode('observer')
      setReason('screen_not_assigned')
      reconcile()
      return () => { mountedRef.current = false }
    }
    let cancelled = false
    setMode('checking')
    identityRef.current = getTabControllerIdentity()
    // Consumed by THIS attempt only. Recovery is a one-shot answer to a prompt
    // the athlete actually saw, never a standing property of the screen — if
    // this claim fails for some other reason, the next one asks again.
    const recoverThisAttempt = recoverRef.current
    recoverRef.current = false

    async function acquire() {
      try {
        const response = await acquireRackController(rackNumber, {
          device_id: deviceId,
          client_instance_id: identityRef.current.clientInstanceId,
          controller_token: identityRef.current.controllerToken,
          ...(recoverThisAttempt ? { recover: true } : {}),
        })
        if (cancelled) return
        capabilityRef.current = {
          deviceId,
          ...identityRef.current,
          controllerEpoch: response.controller_epoch,
        }
        consumeSnapshot(response.snapshot)
        setMode('controller')
        setReason('')
        armLeaseDeadline(response)
      } catch (error) {
        if (!cancelled) becomeObserver(error, error?.code || 'acquire_failed')
      }
    }
    acquire()

    return () => {
      cancelled = true
      mountedRef.current = false
      clearTimeout(leaseTimerRef.current)
      leaseDeadlineRef.current = 0
      const capability = capabilityRef.current
      const current = snapshotRef.current
      capabilityRef.current = null
      if (capability && current && current.current_set == null) {
        releaseRackController(
          rackNumber,
          controllerCommand({}, current.state_version),
          capability,
        ).catch(() => {})
      }
    }
  }, [rackNumber, deviceId, enabled, canClaim, claimAttempt, armLeaseDeadline, becomeObserver, consumeSnapshot, reconcile])

  useEffect(() => {
    if (mode !== 'controller') return
    const heartbeat = async () => {
      const capability = capabilityRef.current
      if (!capability) return
      try {
        const response = await heartbeatRackController(rackNumber, capability)
        if (mountedRef.current) armLeaseDeadline(response)
      } catch (error) {
        if (isControllerLoss(error)) becomeObserver(error)
      }
    }
    const interval = setInterval(heartbeat, 5000)
    return () => clearInterval(interval)
  }, [mode, rackNumber, armLeaseDeadline, becomeObserver])

  useEffect(() => {
    if (mode !== 'observer') return
    reconcile()
    const interval = setInterval(reconcile, 750)
    return () => clearInterval(interval)
  }, [mode, reconcile])

  useEffect(() => {
    if (
      mode !== 'observer'
      || !canClaim
      || !snapshot
      || snapshot.controller_active
      || snapshot.current_set != null
    ) return
    const retry = setTimeout(() => setClaimAttempt((attempt) => attempt + 1), 2000)
    return () => clearTimeout(retry)
  }, [mode, canClaim, snapshot?.controller_active, snapshot?.current_set])

  // The rack is holding a set nobody can finish, and THIS screen is the one
  // bolted to it. Offer the way out rather than sitting read-only forever.
  const canRecover = canOfferRecovery(mode, canClaim, reason, snapshot)

  const recover = useCallback(() => {
    recoverRef.current = true
    setClaimAttempt((attempt) => attempt + 1)
  }, [])

  return {
    mode,
    reason,
    snapshot,
    canControl: mode === 'controller',
    canRecover,
    recover,
    runMutation,
    runControlled,
    updateState,
    reconcile,
  }
}
