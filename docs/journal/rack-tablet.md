# The rack screen

The tablet at each rack. The only surface an athlete actually touches, and the one
part of the system where losing data is unrecoverable.

:::{admonition} Who built this
:class: note
**Bluetooth sensor acquisition** — the host agent, sensor selection at the rack, and
the NFC groundwork — **Braydon**. The design record behind it is
`docs/_ADR_RACK_BLE_LIVE_WORKFLOW.md`.

**Everything else on this page** — the set lifecycle, on-device rep buffering, the
install and offline work — **Devin**.
:::

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

## Decision: this code was frozen, and the freeze is now lifted

:::{note}
**Lifted on 10 August 2026.** `react/src/rack/`, `react/src/db/repBuffer.js`, and
`react/src/device.js` are ordinary files again and can be edited normally. The rest
of this section is kept because the reasoning still applies the next time several
people build against one contract at once — and because the freeze's cost, described
below, is what eventually ended it.
:::

For most of the project these files must not be edited, reformatted, or tidied.

**What forced it.** Several people were building against this behaviour at once,
during the period it was also the demo. Small "improvements" to a shared contract
produce breakage that is very hard to attribute.

**What we chose.** A named set of files that ship as-is. Build alongside them.

**What it cost — and this is what ended it.** Two known bugs sat inside the frozen
boundary and could not be fixed there:

- The screen's periodic refresh is **switched off during an active set**, so live reps
  have no fallback if a message is missed.
- An athlete's workout is loaded **once** when they check in and never re-read, so a
  coach editing a plan mid-session does not reach the rack.

Neither could be fixed without either unfreezing a file or pushing the recovery into
non-frozen code — and a freeze that prevents fixing known bugs has stopped paying for
itself. **The lesson worth keeping is not "never freeze code."** It is that a freeze
needs an expiry condition stated when it starts, or it outlives its reason and nobody
feels entitled to end it.

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

## Known bug: a tablet can only be assigned once

A tablet and its sensor are separate identities, each told "you are rack 3"
independently by a coach — see {doc}`coach-tablet` for why that is a screen rather
than configuration.

The consequence lands here: **there is no way to un-assign a tablet.** Once it has a
rack number, sending it back to setup does not clear that number, and the coach's list
of waiting tablets only shows ones with *no* number. The tablet becomes invisible and
cannot be reassigned.

Clearing the browser's site data appears to fix it, but that is a coincidence worth
understanding: it erases the tablet's stored identity, so it invents a new one the
server has never seen and gets created fresh with no rack. You are not repairing the
tablet, you are replacing it.

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

The same constraint switches off every other feature that needs a secure context —
offline caching, tag scanning, and direct-to-sensor wireless. Those could not be
polyfilled the way the id generator was, so they stayed blocked until the decision
below.

---

## Decision: tell the browser to trust the origin, rather than switch to HTTPS

**What forced it.** Replacing one missing function papered over the symptom but left
the cause: the origin itself is untrusted, so *everything* gated on a secure context
stayed off. The offline cache had never once worked on a rack screen — and, worse, had
never said so. The registration code checked whether the browser supported the feature,
which it does, and then discarded the error when the browser refused to use it. It
looked healthy and did nothing.

**What we chose.** The kiosk browser is launched with the base station's origin
explicitly marked as trusted. This is a *local* declaration — a statement by that one
screen about one address on a closed network — not a certificate anyone else honours.
It turns on offline caching, tag scanning, and direct-to-sensor wireless in one move.

We also made the failed registration **log a warning that names the cause**, because
the silence was worse than the breakage. A screen that has no offline cache and says
so is a known state; one that pretends otherwise is a debugging trap.

**Why not HTTPS, again.** It remains the wrong answer for the reason above — it would
kill the live rep feed — plus a self-signed certificate warns on every phone that
joins the gym network, and a real certificate needs a public domain the base station
does not have.

**What it cost.** The trust declaration only applies to the browser that was launched
with it. A coach opening the site on their own phone is still in a non-secure context
and still has no offline cache. The gym screens are covered; visiting devices are not,
and that is the honest limit of this fix.

---

## Decision: the coach tablet gets the same fix, but is not a kiosk

**What forced it.** The coach tablet needs the offline copy for the same reason the
rack screen does — and more so once note-taking arrives, since notes are written on
the tablet and a dropout mid-note should not lose them. It also needs the app properly
*installed*, which a browser refuses to do outside a trusted context. Both point at the
same fix the rack screens got.

But a coach is not an unattended screen. Full-screen kiosk mode hides the menu, and the
menu is where "install this app" lives — so the mechanism that delivers the fix would
also have blocked the thing it was needed for. A coach also navigates, logs in, and
legitimately puts the tablet down.

**What we chose.** The same launcher, with the *lock* removed rather than the
full-screen. Trusted origin and on-disk profile kept; the cage and the relaunch loop
dropped. A coach tablet is provisioned with a **tappable icon** rather than something
that seizes the screen at every login.

**The word that was doing two jobs.** "Full-screen" turned out to mean two different
things, and conflating them is what made this look like a trade-off in the first place.
One flavour is a *lock*: no toolbar, no window buttons, no way out, and no menu — which
is exactly right for a rack screen an athlete must not be able to leave, and which
hides the very menu the coach needs. The other simply *starts* full-screen while
remaining an ordinary window: hover the top edge and the toolbar returns, and it can be
closed or minimised like anything else.

Once those were separated, the coach did not have to give up full-screen to stay
installable. The first version of this decision made them choose, and it did not need
to.

**The part that makes this cheap.** It is a one-time door. Once the coach installs the
app from the browser menu, the browser writes its *own* launcher — full-screen, its own
name and icon, no browser chrome. The launcher exists to get them through that once,
not to be the daily route in.

**What we deliberately did not do.** Nothing was built for offline *writing*. The
offline cache keeps the app loading without a network; it does not make a coach's edits
survive being made while disconnected. That is a genuinely harder problem — it needs a
queue and a conflict story — and pretending a cache solves it would be the worst
outcome, because it would look like it worked right up until it lost something.

**What it cost.** More launch modes to keep straight, and one more thing that differs
by role. The alternative was giving the coach a kiosk they could not install from, or a
plain browser shortcut with no offline copy at all.

---

## Decision: a kiosk is the opposite of incognito

**What forced it.** The kiosk launcher ran the browser in private mode. It reads as a
sensible default for an unattended screen, and it was quietly destroying the two things
the rack screen is built on.

The tablet's identity — the id that tells the server *which* screen this is, and the
rack number it was assigned — is stored in the browser. Private mode discards that
storage when the browser closes. The launcher also relaunches the browser after any
crash, by design, so a screen would come back **as a device the server had never
seen**, having silently lost its rack assignment. The setup script's own promise that
"every reboot goes straight to the live screen" could not have been true.

Worse, the on-device rep database — the whole reason a Wi-Fi drop mid-set loses nothing
(see the durability decision above) — is held in memory in private mode rather than
written to disk. The guarantee this page opens with was void on every rack screen.

**What we chose.** Private mode removed, with the reasoning written into the script so
it does not get reintroduced by someone applying the same reasonable-sounding default.

**What it cost.** Nothing operationally. The uncomfortable part is what it says about
verification: this was in place for months, and nothing failed loudly enough to catch
it, because a screen that reinvents itself looks identical to a new screen.

---

## Decision: one browser profile per role

**What forced it.** Browser storage is scoped to *(profile, site)*. Everything the app
uses to know what it is — device id, role, rack number — lives there. So two roles
running in one browser profile are not two devices sharing a machine; they are one
device that keeps overwriting its own identity.

This blocked something we wanted: running the rack screen, the coach tablet, and the
wall display on a single machine for a demo, without three pieces of hardware.

**What we chose.** Each role gets its own browser profile directory, named for the role
and the user running it. One machine can now present as several independent devices,
each registering separately with the server, exactly as if they were separate tablets.

**What it cost.** Three profiles means three copies of the browser's cache and three
sets of stored state, and clearing "the" browser data no longer means anything specific
— you have to say which role. Worth it: the alternative was three tablets.

---

## Decision: three manifests, three identities

**What forced it.** The app ships three installable versions — rack, coach, wall —
each with its own name and icon, and the page swaps between them depending on the
screen's role. Installing more than one never worked, and the reason was not obvious.

A browser identifies an installed web app by an explicit identity string, and falls
back to the app's start address when none is given. All three declared the same start
address and none declared an identity, so **all three were the same app**. Installing
the coach version after the rack version did not add a second icon; it renamed the
first one in place.

**What we chose.** Each version declares its own identity string, so the browser can
tell them apart. Coach and wall also got their own start addresses, so launching an
installed app lands on the right screen instead of routing through the picker. The rack
version deliberately kept the shared start address: a rack's number is not known at
install time, so it still goes through the dispatcher.

**The bug this uncovered.** The code that points the page at the right version only ran
when a device *changed* role — at the picker, at setup. None of those happen on a
reboot. So a wall display that restarted was still advertising itself as the rack app,
and giving the three versions distinct identities would have achieved nothing without
fixing that first. It now updates on every navigation, which also matches what the
router already claimed about itself: the address decides what the screen is.

**What it cost.** Nothing yet. The risk to know about is that changing an installed
app's identity or start address **orphans existing installations** — the browser treats
it as a different app. That was free this time only because the offline cache had never
worked, so nothing was installed anywhere to orphan. It will not be free next time.

---

## Decision: sensors can talk two different ways, and a node says which

**What forced it.** The original sensors report over Wi-Fi, through the message broker.
A second kind of sensor was added that reports over **Bluetooth** instead. The obvious
framings were both wrong: "switch to Bluetooth" throws away working hardware, and
"support Bluetooth as a mode" implies the whole gym is one or the other.

**What we chose.** Each sensor records **its own** transport, in the database, as an
ordinary field. Rack 1 can be on Bluetooth while rack 2 is on Wi-Fi, in the same
session, with no setting anywhere that says which the gym is using. New sensors default
to Wi-Fi, so nothing that existed before had to change or even know.

**Why this is the important sentence in this whole page.** Bluetooth did not *replace*
anything. Reading the code and assuming one transport won is the single easiest way to
misunderstand this system.

---

## Decision: a program on the base station owns the radio, not the browser

**What forced it.** The natural place to put Bluetooth is the rack screen — it is right
there, it already shows the reps. Browsers can speak Bluetooth. It does not survive
contact with this product.

Three reasons, and the first one alone is fatal:

- Browser Bluetooth needs a **secure context**, the same gate that blocks the offline
  cache (see above). The gym is served over plain HTTP.
- It requires **a human tap to pair, every single time**. A rack screen boots
  unattended into a locked full-screen browser. There is nobody to tap it.
- It only exists in Chrome-family browsers, and never on iPhone or iPad.

**What we chose.** A small program running on the base station owns the radio for every
rack: it finds sensors, connects, decodes their frames, and decides what counts as a
rep. The rack screen never touches Bluetooth — it gets finished reps the same way it
always did.

**The consequence worth stating plainly.** That program is now a **single point of
failure for every Bluetooth rack at once**, where before each rack failed on its own.
That is a real cost, accepted deliberately in exchange for the three problems above,
which have no workaround.

**What it also bought.** Raw motion data never leaves the base station. Sending it to
the server was considered and rejected: high-rate private data, a dependence on the
network for something that works fine locally, and a much larger surface to get wrong.
The server sees confirmed reps, never the stream they came from.

---

## Decision: sensors are chosen at the rack, by a coach, before anyone signs in

**What forced it.** Bluetooth sensors are discovered as anonymous nearby radios. You
cannot tell from a list which physical box is bolted to rack 3 — you have to be standing
at rack 3, watch a sensor produce movement, and confirm *that* is the one.

**What we chose.** Sensor selection happens **on the rack screen it belongs to**,
requires a coach login, and is only available before an athlete has signed in. Selection
shows scan-scoped handles rather than hardware addresses, so a Bluetooth identity never
reaches the browser or the database.

**What it cost, and this bit has already bitten us.** It **replaced** the old
coach-side "assign this sensor to that rack" screen, and the endpoint behind it was
removed. Work written against the old endpoint compiles, merges without conflict, and
then fails at runtime — which is exactly what happened to the sensor-linking task built
from an older branch. If you are reading old code or an old task description that
assigns a node from the coach console, it is describing a system that no longer exists.

---

## Decision: reps in progress are not results

**What forced it.** Live reps have to appear instantly, and a sensor on a bar that
somebody bumped between sets produces movement that looks exactly like lifting.

**What we chose.** Two different things with two different standards. Reps arriving
*during* a set are **live activity** — shown immediately, kept only as a recoverable
snapshot, and never counted as anything. Records, rankings and history are written only
when a set is **completed**, from the saved set.

The rule: nothing becomes a number anyone is judged on until a human ends the set.

**What it cost.** Two representations of the same reps, and a real chance of confusing
them when reading the code. The alternative was letting a knocked barbell set a personal
record, which is the kind of bug that destroys trust in the whole system.

---

## Decision: tell screens that something changed, do not tell them what

**What forced it.** When anything in the room changes, several screens need to catch up.
The obvious approach is to broadcast the new state to everyone.

**What we chose.** Broadcasts carry only **"something changed, here is the new revision
number."** Each screen then asks the server for the real answer through the normal API.

Two reasons, and the second is the one that generalises:

- Those broadcasts are **not private**. Athlete names and numbers must not be on a
  channel anything on the gym Wi-Fi can subscribe to. A revision number leaks nothing.
- It keeps **one source of truth**. Pushing state means the same facts exist in two
  places that can disagree, and reconnecting screens have to guess which is right.
  Asking the server always converges, including after a disconnection.

**What it cost.** Every change that a screen might care about has to remember to emit
one of these notices, in the same transaction as the change itself. Miss one and a
screen silently shows stale data — a known live bug of exactly this shape is described
in {doc}`dashboard`.

---

## Where these decisions live in the code

The kiosk work above touched two areas: the scripts that launch a screen, and the
handful of app files that decide what a screen *claims to be*.

| File | What changed | Which decision |
|---|---|---|
| `scripts/rack-screen/kiosk.sh` | Takes a **role** instead of a URL; private mode removed; per-role profile; marks the origin trusted; three launch modes, only one of which is a cage | kiosk vs incognito, profile per role, trusted origin, coach is not a kiosk |
| `scripts/rack-screen/rack-kiosk-setup.sh` | Autostart entry is system-wide; no hardcoded user; creates the shared profile directory; a coach gets a tappable icon instead of an autostart | profile per role, coach is not a kiosk |
| `react/public/manifest.*.json` | Each declares its own identity; coach and wall get their own start addresses | three manifests, three identities |
| `react/src/device.js` | New `roleFromPath()` — works out a screen's role from the address | three manifests, three identities |
| `react/src/App.jsx` | Applies the role's identity on **every** navigation, not only on role change | three manifests, three identities |
| `react/src/main.jsx` | Offline-cache registration failure now logs why instead of vanishing | trusted origin |
| `react/src/roleFromPath.test.js` | **New.** Pins the address-to-role mapping | three manifests, three identities |
| `django/event_handler/services/ble_agent.py` | The program that owns the radio and turns frames into reps | a program on the base station owns the radio |
| `react/src/rack/RackNodeSetup.jsx` | Choosing a sensor at the rack, coach-gated | sensors are chosen at the rack |
| `django/event_handler/models.py` | `Node.acquisition_kind` — per-sensor transport | sensors can talk two different ways |
| `docs/_ADR_RACK_BLE_LIVE_WORKFLOW.md` | The original decision record, in its formal form | all of the above |

:::{admonition} If you only remember one thing
:class: tip
Two of these bugs — the discarded identity and the silently failed offline cache —
had been live for months without anyone noticing, because **both failure modes look
exactly like normal operation**. A screen that reinvents itself looks like a new
screen. A cache that never installed looks like a cache that is working. When a
feature has no visible failure state, that is the feature to go and verify by hand.

The Bluetooth work has the same shape in a different place: an endpoint was replaced,
and code written against the old one still merges cleanly and only fails when someone
presses the button.
:::
