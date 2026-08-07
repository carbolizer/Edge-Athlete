import { useEffect, useState } from 'react'
import { getDeviceId } from '../device.js'

export function requiresRackAgent(node) {
  return node?.acquisition_kind === 'wt901_ble'
}

export function sensorHealthIsReady(health, node) {
  if (!health || health.state !== 'live') return false
  const reportedNodeId = health.node_id || health.assigned_node_id
  if (reportedNodeId && node?.node_id && reportedNodeId !== node.node_id) return false
  if (health.sample_age_ms != null) {
    if (!Number.isInteger(health.sample_age_ms) || health.sample_age_ms < 0 || health.sample_age_ms > 1000) return false
  }
  return true
}

export async function getRackSensorHealth(rackNumber, deviceId) {
  const response = await fetch(`/api/racks/${encodeURIComponent(rackNumber)}/sensor-health/`, {
    cache: 'no-store',
    headers: { 'X-Rack-Device-ID': deviceId },
  })
  if (!response.ok) throw new Error(`Sensor health HTTP ${response.status}`)
  return response.json()
}

export function useRackAgentStatus(node, rackNumber = node?.rack_number) {
  const required = requiresRackAgent(node)
  const [snapshot, setSnapshot] = useState({ health: null, nodeId: null, rackNumber: null })

  useEffect(() => {
    if (!required || rackNumber == null) {
      setSnapshot({ health: null, nodeId: null, rackNumber: null })
      return
    }
    let stopped = false
    const deviceId = getDeviceId()
    const poll = async () => {
      try {
        const next = await getRackSensorHealth(rackNumber, deviceId)
        if (!stopped) setSnapshot({ health: next, nodeId: node?.node_id, rackNumber })
      } catch {
        if (!stopped) setSnapshot({ health: { state: 'unavailable' }, nodeId: node?.node_id, rackNumber })
      }
    }
    poll()
    const interval = setInterval(poll, 1000)
    return () => { stopped = true; clearInterval(interval) }
  }, [required, rackNumber, node?.node_id])

  const healthMatchesRequest = snapshot.nodeId === node?.node_id && snapshot.rackNumber === rackNumber
  const health = healthMatchesRequest ? snapshot.health : null
  return { required, health, ready: !required || sensorHealthIsReady(health, node) }
}
