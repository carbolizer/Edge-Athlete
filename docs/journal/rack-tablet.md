# The rack screen

The tablet at each rack. The only surface an athlete actually touches, and the one
part of the system where losing data is unrecoverable.

## What it is

A web app running full-screen on a tablet at each rack. It shows the athlete their
workout, lets them check in, and displays each rep's speed as they lift.

It is also, unusually, **where the system's durability lives**. Not the server.

---

## Decision: the tablet is the durability boundary, not the server

**What forced it.** Reps arrive one at a time over a wireless connection in a room
full of metal, and they are only useful as a complete set. Something has to hold a
partial set safely while it is being built.

**What we chose.** Every rep is written to the browser's own on-device database
**the instant it arrives** — before the screen updates, before the server hears
anything. When the set ends, the whole set is sent to the server in **one request**.
The local copy is cleared only after the server confirms the save.

Think of it as writing each rep in a notebook as it happens, so that even if the
phone line drops before you can call it in, you still have every rep.

**What we rejected, and why.**

*Buffering in the server's memory.* A browser tab surviving a Wi-Fi drop is a far
better bet than a server process surviving a restart while holding unflushed sets for
every active rack. The failure modes are not comparable: one loses a rack, the other
loses the room.

*Buffering on the sensor itself* — storing a full set in the node's flash memory and
submitting it directly. Rejected for two concrete reasons. First, **the node has no
idea whose set it is**: session, athlete and exercise context exists only in the
tablet's UI, so the node would need a whole new downstream channel just to learn who
it is recording. Second, the browser gives durable storage for free; replicating it in
firmware means hand-writing a flash-backed queue with acknowledgement, replay and
flash-wear handling — real engineering cost to save a network hop that is not a
bottleneck on a single-machine network.

**What it cost — stated plainly.** If a specific tablet crashes or loses power
mid-set, **that rack's current set is lost.** This is accepted, not solved. The loss
is isolated to one rack rather than the room, and it was explicitly ruled out of scope
rather than left as an open bug.

---

## Decision: this code is frozen

`react/src/rack/`, `react/src/db/repBuffer.js`, and `react/src/device.js` must not be
edited, reformatted, or tidied.

**What forced it.** Several people were building against this behaviour at once,
during the period it was also the demo. Small "improvements" to a shared contract
produce breakage that is very hard to attribute.

**What we chose.** A named set of files that ship as-is. Build alongside them.

**What it cost — and this is a live problem.** Two known bugs currently sit inside the
frozen boundary:

- The screen's periodic refresh is **switched off during an active set**, so live reps
  have no fallback if a message is missed.
- An athlete's workout is loaded **once** when they check in and never re-read, so a
  coach editing a plan mid-session does not reach the rack.

Neither can be fixed without either unfreezing a file or pushing the recovery into
non-frozen code. That decision has not been made yet, and it should be made
deliberately rather than by whoever hits it first.

---

## The set lifecycle

Worth knowing before changing anything nearby:

1. **Check in.** Tapping a name is the check-in. It is append-only and newest-wins —
   the most recent check-in is what decides which rack "owns" an athlete. This is
   also the path a future tag-scan would call.
2. **Idle.** The athlete's workout for the day is loaded, with a suggested current
   movement and a resolved target weight (or a blank one they can fill in).
3. **Active.** The screen subscribes to its linked sensor **only while a set is
   running**. Reps arriving at any other time are deliberately ignored, so a bumped
   bar between sets does not become data.
4. **Complete.** Exactly one submission per set, guarded so a double-tap cannot
   produce two.
5. **Rest.** The check-in list returns, so the next lifter can take the rack.

---

## Decision: a tablet and a sensor are separate identities

There is **no link** between a tablet and the sensor at the same rack. Both are
independently told "you are rack 3" by a coach.

**Why this is worth stating:** it means a rack showing no data is usually an
**assignment problem, not a hardware problem** — and that is the first thing to check
before anyone starts debugging a sensor.

**What it cost.** There is currently **no way to un-assign a tablet.** Once it has a
rack number, sending it back to setup does not clear that number, and the coach's
list of waiting tablets only shows ones with no number — so the tablet becomes
invisible and cannot be reassigned. Clearing the browser's site data "fixes" it only
because that gives the tablet a brand-new identity the server has never seen.

---

## A trap: this app is not served over HTTPS

The base station serves plain HTTP, which browsers treat as a **non-secure context**.
A handful of browser features are switched off there, and one of them was being used:
the built-in unique-id generator is simply absent, which crashed the screen on first
load in the gym while working perfectly on a laptop — because `localhost` counts as
secure and `http://basestation` does not.

The fix was a small local replacement for that one function, not switching to HTTPS.
**HTTPS is not available as a fix here**: a secure page refuses the plain `ws://`
connection the live rep feed depends on, so turning it on would trade a crash for a
dead sensor feed. See {doc}`real-time`.

This same constraint blocks any browser feature that requires a secure context —
which currently includes both proposed tag-scanning and direct-to-sensor wireless
features.
