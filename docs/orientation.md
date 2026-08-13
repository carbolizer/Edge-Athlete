<!--
this page — the shortest thing that lets someone read the code.

It used to be twenty minutes: the pitch, the devices, the rep path, a glossary, and
a tour of every service. The service talk now lives one page per service under this
one, so this page can stay the thing you actually read first. If you are about to
explain a tool here, write it in stack/ instead and link to it.
-->

# Orientation

What the system is, in about five minutes.

## What it does

Edge Athlete measures **how fast a barbell moves**, and shows that number to the
athlete while they lift.

Bar speed is the useful signal in strength training. Two athletes can both grind out
five reps at 225 lb, but if one is moving the bar slower than usual they are
fatiguing — and a coach who sees that can change the session before it becomes a bad
week. Counting reps will not tell you that.

Commercial systems that do this cost **$3,880** (GymAware) or **$1,995 per rack plus
$3,000 a year** (Perch). Edge Athlete does the same job with a mini PC and about $10
of sensor per rack.

:::{important}
**There is no internet in the gym.** The base station broadcasts its own Wi-Fi and
everything joins that. No cloud, no accounts, nothing phoning home.

This one fact explains a surprising number of decisions later — including a whole
class of browser features we are not allowed to use.
:::

## The four devices

| | |
|---|---|
| **Node** | a sensor on the bar. Works out each rep's speed **on the device** and sends one message per rep. Never streams raw data. |
| **Base station** | a mini PC. Runs the database, the web app, the broker, and the Wi-Fi itself. |
| **Rack screen** | a tablet at each rack. What athletes touch. |
| **Wall display / coach tablet** | the same web app in two other modes — a room scoreboard, and the admin tool. |

## How one rep travels

```
node ──► broker ──► rack screen ──► browser storage
                                        │  reps pile up here during the set
                                        ▼  ONE post when the set ends
                                     django ──► postgres ──► broker ──► wall + coach
```

Two things in that line surprise people, and both are deliberate:

**The server never sees a single rep.** Reps go node → broker → tablet and stop
there. The database gets one write per completed **set**.

**The tablet is what keeps the data safe**, not the server. Reps are written to
browser storage as they arrive, so a Wi-Fi drop mid-set loses nothing.

## Three things that will confuse you otherwise

**A plan stores a percentage, not a weight.** "Back Squat 5×3 at 80%" is written
once for a whole group; each athlete's bar is worked out against their own current
max when the screen is read. That max can go **down**, and prescribed weights follow
it down. That is the design — {doc}`journal/database`.

**Some files are frozen.** `react/src/rack/`, `react/src/db/repBuffer.js` and
`react/src/device.js` are a fixed contract. Build alongside them, not inside them.

**Live updates do not go through the web server.** Screens talk to the broker
directly. Adding a WebSocket layer to Django was considered and rejected —
{doc}`journal/real-time`.

## The stack, one page each

What every service is, how we use it, and where it lives. Short on purpose.

```{toctree}
:maxdepth: 1

stack/mosquitto
stack/django
stack/postgres
stack/react
stack/nginx
stack/docker
stack/networkmanager
stack/systemd
stack/chromium
stack/hardware-agents
stack/sphinx
```

## Then read one journal page

Whichever part you are about to touch — that is where the *why* lives.

- athletes, plans, weights → {doc}`journal/database`
- endpoints, permissions, auth → {doc}`journal/apis`
- how live data moves → {doc}`journal/real-time`
- the machine, its Wi-Fi, deployment → {doc}`journal/scripts`
- the athlete's screen → {doc}`journal/rack-tablet`
- the coach's tools → {doc}`journal/coach-tablet`
- the wall display → {doc}`journal/dashboard`

For how the project got here instead, read {doc}`history`.
