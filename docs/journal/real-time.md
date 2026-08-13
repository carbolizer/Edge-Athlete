# The real-time layer

Everything that updates a screen without someone pressing refresh.

## What it is

One message broker — **Mosquitto** — sits on the base station, and everything talks
to it. Sensors publish to it. Browsers subscribe to it. Django both publishes to it
and listens to a narrow slice of it.

It runs two doors into the same building:

- **port 1883** — plain MQTT, for the sensors and Django
- **port 9001** — the same MQTT wrapped in WebSockets, because a web page cannot
  speak the plain protocol

Same broker, same messages, two doors.

For the exact message shapes, see {doc}`../reference/message-contract`. This page is
about *why* it is built this way.

---

## Decision: one transport for everything, and it is MQTT

**What forced it.** Screens need to update live. The obvious approach in a Django
project is Django Channels — an add-on that gives Django real WebSocket support.

**What we chose.** Every live path runs over MQTT: node → rack screen, and server →
every screen. Browsers use MQTT-over-WebSockets against the same broker the hardware
uses.

**What we rejected, and why.**

*Django Channels / ASGI.* This would have been the single largest piece of net-new
infrastructure in the project — a different server model, a channel layer to run and
operate, and a second way for messages to move. Django already ships with an MQTT
client library, and we already needed a broker for the sensors. Publishing to the
broker we already had got live updates for free.

*Each sensor running its own small web server.* Rejected for a specific reason worth
remembering: it creates a **device-discovery problem**. Every time a sensor is moved
to a different rack, something has to find its new IP address. Subscribing to a topic
name solves that for free — reassignment is just "listen to a different string."
There is no IP lookup and no connection to tear down.

**What it cost.** Browsers hold a direct connection to the broker, so the broker is
now a component the front end depends on, not just a back-end detail. And because the
browser connection is plain `ws://`, the app **cannot be served over HTTPS** without
breaking it — a secure page refuses an insecure socket. That constraint reaches
further than it looks; see the secure-context problems in
{doc}`rack-tablet` and {doc}`scripts`.

---

## Decision: the server never sees an individual rep

**What forced it.** A node emits one message per rep. Several racks lifting at once,
several reps a minute each. Every one of those could have been written to the
database.

**What we chose.** Django subscribes to **`edgeathlete/node/+/pulse` only** — the
heartbeats. Rep topics never reach Django at runtime. Reps travel from the node to
the rack tablet and stop there. The database gets **one write per completed set**.

**What we rejected, and why.** Per-rep database writes. The base station also runs
the broker, the web server, and the static hosting on modest hardware. Per-rep writes
across many racks is real load in exchange for durability nobody needs — the useful
unit of training data is the set, not the individual rep.

**What it cost.** The wall display and coach screens cannot show a rep counter ticking
up live from server data, because the server does not have it. Anything genuinely
live has to come from the broker directly. This is also why moving reps to a
different transport (a recurring proposal) is less disruptive than it first appears
for reps, and *more* disruptive than it appears for pulses — the pulse path is the one
the server actually depends on.

:::{admonition} If you are evaluating a change to how nodes communicate
:class: important
Read the split above carefully first. **Reps and pulses go to different places for
different reasons.** A proposal that moves "node data" without separating the two
will either break sensor-health monitoring or quietly leave a second radio running.
:::

---

## Decision: topics are namespaced under `edgeathlete/`

**What forced it.** Two earlier reference documents disagreed — one used
`edgeathlete/*`, the other `rack/{n}/*`. Two naming schemes for the same thing is how
a subscriber silently listens to nothing.

**What we chose.** Everything under `edgeathlete/`, with the node's own id in the
topic rather than the rack number: `edgeathlete/node/{node_id}/rep`.

**Why the node id and not the rack number.** A rack number is an assignment a coach
can change; a node id is the hardware. Keying the topic to hardware means reassigning
a sensor is a subscription change on the screen, not a re-addressing of the sensor.

---

## Known weakness: delivery is not guaranteed

This is current, unresolved, and worth understanding before you trust the live path.

Most subscriptions in the browser are **QoS 0** — send once, no confirmation, no
retry. Combined with a connection that gets a **new random client name** on every
reconnect, the broker has no obligation to hold anything for a screen that briefly
drops. A message lost to a Wi-Fi blip is lost permanently.

The broker also has no persistence configured, so nothing survives a broker restart.

Three details make this less bad than it sounds, and one makes it worse:

- Django **publishes** at QoS 1 already.
- The wall display's room-state subscription is already QoS 1 — the one place it was
  done right, and the model to copy.
- Reps that *do* arrive are safe immediately, because the tablet writes them to local
  storage before anything else (see {doc}`rack-tablet`).
- **But** the sensor firmware uses an MQTT library that can only *publish* at QoS 0.
  Raising the guarantee on the node → broker leg is not a settings change; it needs a
  different library. This is the part most likely to be underestimated.
