// mqtt/client.js — the rack screen's live wire to the broker.
//
// Wraps mqtt.js. The browser talks STRAIGHT to the Mosquitto broker over
// WebSockets (port 9001) — no server in the middle — which is how reps reach the
// screen in real time. One shared client is reused for every subscription.
// mqtt.js reconnects on its own after a drop; we just re-assert subscriptions.
//
// Topics (all under edgeathlete/, per the message contract):
//   edgeathlete/node/{node_id}/rep     — one message per completed rep (we consume our node's)
//   edgeathlete/rack/{rack_number}/state — Django's broadcasts to THIS rack
//   edgeathlete/rack/command           — shared channel: remote commands to any/all tablets

import mqtt from 'mqtt'

let client = null

export function getClient() {
  if (!client) {
    // location.hostname so it works from whatever device is pointed at the Pi.
    client = mqtt.connect(`ws://${window.location.hostname}:9001`)
  }
  return client
}

// Run `fn` once the client is connected (now if already up, else on connect).
function whenReady(c, fn) {
  if (c.connected) fn()
  else c.on('connect', fn)
}

// Subscribe to one node's rep stream. `onRep` gets each parsed rep object.
// Returns an unsubscribe function. mqtt.js re-subscribes automatically after a
// reconnect because the subscription is remembered on the client.
export function subscribeNodeReps(nodeId, onRep) {
  const c = getClient()
  const topic = `edgeathlete/node/${nodeId}/rep`
  const handler = (t, msg) => {
    if (t !== topic) return
    try { onRep(JSON.parse(msg.toString())) } catch (e) { /* ignore malformed */ }
  }
  c.on('message', handler)
  whenReady(c, () => c.subscribe(topic))
  return () => { c.removeListener('message', handler); c.unsubscribe(topic) }
}

// Subscribe to Django's broadcasts for this rack (set_complete, node_reassigned,
// athlete_checkin). `onState` gets each parsed message. Returns an unsubscribe fn.
export function subscribeRackState(rackNumber, onState) {
  const c = getClient()
  const topic = `edgeathlete/rack/${rackNumber}/state`
  const handler = (t, msg) => {
    if (t !== topic) return
    try { onState(JSON.parse(msg.toString())) } catch (e) { /* ignore malformed */ }
  }
  c.on('message', handler)
  whenReady(c, () => c.subscribe(topic))
  return () => { c.removeListener('message', handler); c.unsubscribe(topic) }
}

// Subscribe to the shared rack COMMAND channel — one topic EVERY tablet listens
// to from boot, whether or not it has been assigned a rack yet (unassigned racks
// have no rack-number topic, so this shared one is how they can still be reached).
// A coach — later, a Django endpoint — publishes here to remotely steer tablets,
// e.g. send them all to the setup screen. `onCommand` gets each parsed
// { type, target, ... } message. Returns an unsubscribe function.
export function subscribeRackCommand(onCommand) {
  const c = getClient()
  const topic = 'edgeathlete/rack/command'
  const handler = (t, msg) => {
    if (t !== topic) return
    try { onCommand(JSON.parse(msg.toString())) } catch (e) { /* ignore malformed */ }
  }
  c.on('message', handler)
  whenReady(c, () => c.subscribe(topic))
  return () => { c.removeListener('message', handler); c.unsubscribe(topic) }
}

// When a coach links a different sensor to this rack: drop the old node's reps
// and start listening to the new one, keeping the same onRep handler.
export function resubscribeNode(oldNodeId, newNodeId, onRep) {
  const c = getClient()
  if (oldNodeId) c.unsubscribe(`edgeathlete/node/${oldNodeId}/rep`)
  return subscribeNodeReps(newNodeId, onRep)
}
