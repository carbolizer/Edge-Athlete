# The APIs

How everything talks to the server. For the exact request and response shapes, see
{doc}`../reference/index`; this page is about the rules behind them.

## The shape of it

Roughly fifty endpoints under `/api/`, split unevenly:

- **~15 are open to anyone** on the gym network
- **~36 require a coach login**

That split is not an accident, and it is the first thing to understand.

---

## Decision: rack tablets have no login, so their endpoints are open

**What forced it.** A rack tablet is a kiosk. It boots unattended into full-screen
mode, nobody signs in to it, and there is no keyboard in front of a squat rack. But it
still has to register itself, ask which rack it is, read an athlete's plan, and submit
a completed set.

**What we chose.** Everything a rack tablet needs is **open** — no authentication.
Everything that *changes the plan or the room* is **coach-only**.

Open, roughly: register a screen, ask which rack am I, read the active session, read
an athlete's plan for today, check an athlete in, create and complete a set.

Coach-only: creating athletes, editing plans, assigning racks and sensors, ending
sessions, all analytics with names attached, spreadsheet import, and every system
setting.

**What we rejected, and why.** Giving each tablet its own credential. That means
provisioning, storing and rotating a secret on a device that lives in a public room
and is periodically wiped and reimaged — real operational cost for a network that is
already private, offline, and has no route to the internet.

**What it cost — say this out loud.** **Anyone who joins the gym Wi-Fi can read
training data and submit sets.** That is an accepted trade, and it is why the Wi-Fi
password matters more than it looks, and why the wall display deliberately shows no
names (see {doc}`dashboard`). If this system ever runs on a network that is not
private, this is the decision to revisit first.

---

## Decision: "coach" means "logged in," and nothing more

The permission check is deliberately one line: is this request authenticated? If yes,
it is a coach.

**What we rejected, and why.** A role system — coach, assistant, athlete, admin. There
is exactly one kind of privileged user in a weight room running this, and a role
system that is never exercised is a system that is wrong the first time someone
actually needs it. It can be added when a second role genuinely exists.

**What it cost.** Any authenticated account has full coach powers. Fine for one gym
with one or two staff logins; not fine the moment athletes get accounts.

---

## Decision: one path through authentication

Every authenticated request from the front end goes through a single helper. If you
are adding a coach screen, import that helper rather than writing another fetch
wrapper.

**Why it matters.** Scattered token handling is how one screen quietly ends up
unauthenticated, or how a token refresh fixes three screens and misses the fourth.
The token lives in browser storage on purpose, so a page refresh does not sign a coach
out mid-session — which matters more than it sounds when it happens in front of a
room.

---

## Decision: reps reach the database in exactly one way

There is **one** endpoint that writes rep data, and it takes a whole set at once — the
summary plus every rep in it, in a single request, written in a single transaction.

There is no endpoint that accepts an individual rep. There is no streaming path. The
server's MQTT subscriber ignores rep topics entirely (see {doc}`real-time`).

**Why this is worth stating as an API rule:** it means the database can never hold a
half-written set. Either the whole set landed or none of it did. Anything that tries
to add a per-rep write path is fighting the design in {doc}`rack-tablet`, not
extending it.

---

## The trap: route order is load-bearing

Some routes are catch-alls — `racks/<device_id>/` will match almost anything in that
position, including the literal word `register`.

**Those routes are placed last on purpose.** The specific routes above them
(`register`, `racknumber`, `unassigned`, `list`) must match first, or they get
swallowed by the catch-all and every one of them breaks at once.

If you add a route, add it **above** the catch-alls. This is the kind of bug that
produces a confusing 404 on an endpoint you can see in the file.

---

## Why the health endpoint is first and open

There is a `health/` endpoint at the very top of the list, available to anyone. It
answers one question: can this container serve a request and reach the database?

It is deliberately first and deliberately unauthenticated, because **nothing else
should have to be working for it to answer**. It is what the container orchestration
uses to decide whether the app is up, and a health check that needs a login or a
working session is a health check that lies during exactly the outage you built it
for.

---

## Known gap

The assignment endpoint only ever *sets* a rack number — **nothing clears one**, so a
tablet can never be returned to the waiting list. See the deadlock this creates in
{doc}`rack-tablet`.
