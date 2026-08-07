# The wall display

The big screen on the gym wall. Also, in a second mode, the coach's working tool —
they are the same file.

## What it is

`mode="wall"` is a room-scale scoreboard: current movement, a leaderboard, how the
room is doing. Read-only, no login, mounted high on a wall where anyone in the gym can
see it.

`mode="coach"` is the same live room feed plus everything the wall deliberately leaves
out — names, history, planning, notes, reports — behind a login.

---

## Decision: one file, two screens

**What forced it.** The wall and the coach view show the same room, changing at the
same moments, from the same data.

**What we chose.** One component with a `mode` prop. They share a file because **they
share a heartbeat** — both are driven by the same live-room hook, and both ask the
same endpoint for different amounts of detail.

**What we rejected, and why.** Two separate screens. They would have drifted: the same
event would have needed handling twice, and the two views would eventually disagree
about what the room looked like — which is exactly the failure a coach would notice
and lose trust over.

**What it cost.** One file carries two audiences, so every change has to be considered
twice. The mode check is load-bearing, not cosmetic.

---

## Decision: the wall shows no names

**What forced it.** A wall display in a weight room is **public**. Anyone walking past
sees it — other athletes, visiting teams, parents, whoever is in the building.

**What we chose.** The wall gets an **anonymous** snapshot. Names, ids and personal
history are only in the coach view, and only behind a login.

**How it is enforced.** Both views call the same endpoint; the coach view adds a flag
that asks for the extra detail, and that flag requires the login. The wall cannot
accidentally receive names, because it never asks for them and could not authenticate
if it did.

This is the counterweight to the open-API decision in {doc}`apis`. Read access is
broad, so the surface that is *literally on public display* is where the line gets
drawn.

---

## Decision: MQTT says "look again," never "here is the data"

This is the most important design choice on this page, and the least obvious.

**What forced it.** The screen needs to update live. The obvious approach is to
broadcast the new room state over MQTT and render whatever arrives.

**What we chose.** The broadcast carries **no data at all**. It says only *"something
changed, revision 47."* The browser then asks the database what the truth is.

**Two reasons, both load-bearing:**

1. **The database stays the single source of truth.** There is exactly one authority,
   and screens converge on it. A message that carried data would be a second, competing
   version of reality that could arrive late or out of order.
2. **No athlete's name or numbers ever travel over a broadcast channel** that a gym
   display is subscribed to. The broker allows anonymous connections; anything on the
   network can listen. So nothing sensitive is ever put on it.

**What it cost.** Every change costs a round trip — a message, then a fetch. On a
local network that is cheap, and it buys correctness and privacy together.

---

## The careful part: not lying to the room

Most of the complexity in the live-room hook exists to stop a screen displaying
something untrue. Each guard came from a specific way it could go wrong:

**A fetch already in flight blocks a second one** — but remembers that a newer
revision arrived, and re-fetches once the first lands. Without this, a burst of
changes could leave the screen settled on an older answer that happened to return
last.

**Answers meant for a previous mode or login are discarded.** Switching from wall to
coach fires a new request; without a generation guard, the old reply could land after
the new one and overwrite it.

**A failed refresh keeps the last good snapshot** and marks the connection stale,
rather than blanking a wall screen in the middle of a session. Stale-but-readable
beats empty.

**Incoming messages are validated hard before they are trusted** — schema version,
message type, a revision that is a sane positive integer, an id matching a strict
pattern, and a size cap. The broker is anonymous, so a malformed or hostile message is
possible; it is rejected rather than acted on.

**Revisions only move forward.** A reconcile happens only when the incoming revision
is *greater* than the current one, so a replayed or out-of-order message cannot rewind
the screen.

**If the broker goes quiet for 15 seconds, the connection is shown as stale** — on the
principle that *a frozen scoreboard that looks live is worse than one that admits it*.

---

## Known bug: it can freeze, and the freshness label will not save it

This screen refreshes **only** when a message tells it to. There is **no timer
anywhere** in the live-room hook.

That is efficient when messages arrive, and a dead end when one goes missing — and
under the QoS 0 delivery described in {doc}`real-time`, messages do go missing. The
screen then sits on stale data indefinitely.

The trap for whoever fixes it: **the 15-second staleness constant looks like a refresh
timer and is not.** It only changes a status label. The screen still never re-fetches.

The fix is a slow backup timer calling the refresh function that already exists — the
duplicate-request protection above means a timer cannot cause a pile-up. Unlike the
same bug on the rack tablet, **this file is not frozen**, so it can be fixed directly.

---

## The settings cog

The wall display has a small settings control holding "change device role."

**Why it exists.** A wall-mounted screen has no keyboard and often no easy physical
access. Without an on-screen way to change what the device is, repurposing it means
getting a keyboard to a screen mounted above head height. The cog is the difference
between a two-minute change and a ladder.

---

## Deliberately not here

Assigning athletes or workouts to a rack **ahead of time** is not part of this screen,
on purpose. A rack's occupant is decided by who checks in at it, not by a plan made
earlier — see the check-in model in {doc}`rack-tablet`.
