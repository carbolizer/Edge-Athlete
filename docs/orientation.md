# Orientation

Everything you need before reading any code. About twenty minutes.

## What this is

Edge Athlete measures **how fast a barbell moves**, and shows that number to the
athlete lifting it while they lift.

Bar speed is the useful signal in strength training. Two athletes can both grind out
five reps at 225 lb, but if one of them is moving the bar noticeably slower than
usual, they are fatiguing — and a coach who can see that can change the session
before it turns into a bad week. Counting reps alone will not tell you that.

Commercial systems that do this cost **$3,880 (GymAware)** or **$1,995 per rack plus
$3,000 a year (Perch)**. A high school or small college program cannot buy eight of
those. Edge Athlete does the same job with a mini PC and roughly $10 of sensor per
rack.

:::{important}
**There is no internet in the gym.** The base station broadcasts its own private
Wi-Fi network and everything joins that. No cloud, no accounts, no subscription,
nothing phoning home.

This one fact explains a surprising number of decisions later on — including a
whole class of browser features we are not allowed to use.
:::

## The four kinds of device

```
   Node (ESP32 + motion sensor)          Browsers (rack tablets, wall, coach)
          │                                        │
          │ MQTT :1883                             │ MQTT over WebSockets :9001
          ▼                                        ▼
   ┌──────────────── Mosquitto (the message broker) ────────────────┐
   │  reps + heartbeats                                             │
   └───────┬────────────────────────────────────────────────────────┘
           │ heartbeats ONLY
           ▼
      Django ──► PostgreSQL          Nginx ──► React app + /api → Django
```

**Node** — a small sensor that clips to the bar (or a waist or wrist strap). An
ESP32 chip plus a motion sensor. It works out the speed of each rep **on the device**
and sends one message per completed rep. It never streams raw sensor data.

**Base station** — a Dell OptiPlex mini PC sitting in the gym. It runs everything:
the database, the web app, the message broker, and the Wi-Fi network itself. (It used
to be a Raspberry Pi; see {doc}`journal/scripts` for why it stopped being one.)

**Rack screen** — a tablet at each rack. Shows the athlete their workout and their
live rep speeds. This is the surface athletes actually touch.

**Wall display and coach tablet** — the same web app in two other modes. The wall is
a room-wide scoreboard; the coach tablet is the admin and planning tool.

## How one rep travels

Follow a single rep end to end and the architecture explains itself:

1. An athlete completes a rep. The **node** computes its velocity on-device and
   publishes one message to the broker.
2. The **rack screen** is subscribed to that node's messages. It receives the rep and
   immediately does two things: writes it to **local browser storage**, then updates
   what is on screen.
3. Reps keep arriving that way until the set ends.
4. When the set ends, the rack screen sends **the whole set at once** — the summary
   and every rep in it — to the base station in a single request.
5. The base station saves that set to the database in one transaction, then announces
   the change so the wall display and coach tablet update.

Two things about that sequence surprise most people, and both are deliberate:

**The server never sees an individual rep.** Reps go from the node to the rack tablet
and nowhere else. The database gets **one write per completed set**, not one per rep.

**The tablet, not the server, is what keeps your data safe.** Reps are written to
browser storage as they arrive, so a Wi-Fi drop mid-set does not lose them. The
reasoning — and the failure this design accepts on purpose — is in
{doc}`journal/rack-tablet`.

## Three things that will confuse you otherwise

**1. A workout plan stores a percentage, not a weight.**
A coach prescribes "Back Squat 5×3 at 80%" once, for a whole group. There is no
target-weight column anywhere. Each athlete's actual bar weight is worked out when
the screen is read, against that athlete's own current reference max.

That max is *what they can do now*, so it can go **down** — and prescribed weights
are meant to follow it down. That is the design, not a bug. The tempting "fix" breaks
real behaviour; {doc}`journal/database` explains what and why.

**2. Part of the codebase is frozen and you must not edit it.**
`react/src/rack/`, `react/src/db/repBuffer.js`, and `react/src/device.js` are a fixed
contract. They ship, they work, and several people build against their exact
behaviour. Build alongside them, not inside them. If a fix seems to require changing
one, that is a conversation, not a commit.

**3. Live updates do not go through the web server.**
The tablets talk **directly** to the message broker. There is no WebSocket layer in
Django, and adding one was explicitly rejected — {doc}`journal/real-time` covers the
reasoning.

## Words you will hit in the first ten minutes

MQTT
: How live messages move. Think of a **radio station**: a sender broadcasts on a named
  channel (a *topic*), and anyone tuned to that channel hears it. The station itself
  is a program called **Mosquitto**, running on the base station.

Topic
: The channel name, e.g. `edgeathlete/node/{id}/rep`. Subscribing to a topic is how a
  screen says "tell me about this sensor."

QoS
: "Quality of Service" — how hard MQTT tries to deliver a message. **QoS 0** is *say
  it once and hope*. **QoS 1** is *keep saying it until the other side confirms*. Most
  of the system is on 0, which is a known source of dropped data.

Pulse (or heartbeat)
: A "still alive" message every node sends every few seconds, carrying battery level
  and signal strength. **This is the only node message the server listens to.**

Reference max
: The most weight an athlete can currently lift for a given movement. Every prescribed
  weight in the system is a percentage of one of these.

Secure context
: Browsers only switch on certain powerful features (Bluetooth, NFC, some crypto) for
  pages served over **HTTPS**. Our app is served over plain **HTTP**, so those features
  are unavailable to us. This has already caused one production bug and currently
  blocks two proposed features.

Frozen files
: The fixed-contract files listed above. Off limits.

## Where to go next

You are oriented. Now read the one journal page for whatever you are about to touch:

**The groundwork — read the relevant one first:**

- Anything touching athletes, plans, or weights → {doc}`journal/database`
- Endpoints, permissions, or auth → {doc}`journal/apis`
- Changing how live data moves → {doc}`journal/real-time`
- The machine, its Wi-Fi, or deployment → {doc}`journal/scripts`

**Then the screen you are working on:**

- The athlete-facing screen → {doc}`journal/rack-tablet`
- The coach's tools, including spreadsheet upload → {doc}`journal/coach-tablet`
- The wall display → {doc}`journal/dashboard`

If you would rather understand how the project got here before changing it, read
{doc}`history` instead.
