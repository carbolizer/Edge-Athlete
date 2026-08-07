# The scripts

How a blank machine becomes a working base station, and how it stays one.

## What it is

Two sets of scripts, for two completely different devices:

**`scripts/basestation/`** — the machine that runs everything and **broadcasts** the
gym's Wi-Fi. One per gym.

**`scripts/rack-screen/`** — a kiosk client that **joins** that Wi-Fi and boots
straight into full-screen browser. Runs no server.

Installing a base station is one command, and running the same command again is how
you update it. It is not one-shot.

---

## Decision: it is not a Raspberry Pi any more

**What forced it.** The system was designed around a Pi. In practice the Pi's Wi-Fi
was the weak link, and the whole stack — database, web server, broker, static hosting
— is more than that hardware wanted to carry.

**What we chose.** A Dell OptiPlex mini PC. Everything else ported unchanged, because
broadcasting a Wi-Fi network is the operating system's job on any Linux box, not
something Pi-specific.

**What it cost.** Documentation written during the Pi era still says "Pi" in places.
When you find one, it means base station.

---

## Decision: the install does not live in anyone's home directory

**What forced it.** The original scripts hardcoded a path under a specific user's home
folder. Rename that account, or log in as someone else, and the boot service points at
a directory that no longer exists — a base station that silently fails to start, for a
reason nobody would guess.

**What we chose.** The install lives at a fixed system path that belongs to the
machine, not to a person. The scripts also **locate themselves** — they work out where
the project is from their own position on disk, so the same scripts work whether the
repo was cloned to the standard location or somewhere else for testing.

**What it cost.** Almost nothing. This is the cheapest reliability decision in the
project.

---

## Decision: this machine's settings are not in git

**What forced it.** A genuinely bad earlier design: the setup script edited the
*startup script itself* to write in the Wi-Fi interface name. Two consequences, both
serious.

1. **The repository was permanently modified**, so the next update hit a merge
   conflict on a machine with nobody around to resolve it.
2. **The gym's Wi-Fi password was in version control.**

**What we chose.** Per-machine settings — network name, password, interface — live in
a config file outside the repository, written once during setup and never overwritten.
Updates can pull cleanly forever because nothing ever edits a tracked file.

**What it cost.** One more file to know about. It is listed in the runbook, and it is
the file to edit when changing the Wi-Fi by hand.

---

## Decision: a failed access point must not stop the application

**What forced it.** The startup script originally aborted on any error. If bringing up
the Wi-Fi failed, the whole boot stopped and the application never started.

That is the **worst possible outcome**: a base station with no gym Wi-Fi *and* no
running application, which cannot even be reached over a network cable to find out
what went wrong.

**What we chose.** The access point is attempted; failure is logged loudly and
carried. The application still comes up, still answers on the wired network, and the
log says plainly what failed.

**What it cost.** A base station can now be "up" while being useless to tablets. That
is the right trade — a reachable broken machine is fixable, an unreachable one needs a
monitor and a keyboard carried to it.

---

## Decision: a real web server, not the development one

Django's built-in server is a development tool. It is single-threaded by default,
explicitly not intended for production use, and does not serve the admin interface's
own files once debug mode is off.

The stack runs **gunicorn** with a small number of worker processes instead, and the
static files are collected at build time and served properly.

**What to watch.** The worker count is a fixed, small number. If page loads stall
under a handful of simultaneous tablets while the network itself looks healthy, that
count is the first thing to check — it caps how many requests can be handled at once.

---

## Decision: the signing key is generated per machine, at setup

**What forced it.** The key that signs coach login tokens cannot be a shared default
committed to the repository. Every base station would sign with the same secret, and a
token from one gym would be valid at another.

**What we chose.** Each machine generates its own random key during setup, stored
outside the repository. The application **refuses to start** with a missing key when
debug mode is off, rather than falling back to something insecure and starting anyway.

**Why refusing to start is right.** A base station that will not boot gets fixed
immediately. One that boots with a known-insecure key gets used for a season.

---

## Decision: the web container is never allowed to reconfigure the network

**What forced it.** Coaches need to change the gym Wi-Fi password from the app. But the
app runs in a container, and it is the most exposed service on the box.

**What we chose.** A "work order" handshake:

1. The coach app writes the requested change to a **file** in a shared folder. That is
   all it can do.
2. A privileged service on the host machine notices that file appearing, and performs
   the actual network change as root, outside the container.

The container never gains network privileges. The privilege stays on the host, where
it already was.

**The analogy that made this click for the team:** the front desk clerk cannot rewire
the building. They fill out a work order and drop it in a tray. A maintenance worker —
who already has the keys — picks it up and does the job. The clerk never holds the
keys, and that is the point.

**What it cost.** The change is not instant, and it is asynchronous — the app confirms
the request, not the result. It also means a moving part on the host that must be
installed at setup and is easy to forget when debugging.

---

## The thing everybody hits once

**Changing the Wi-Fi password disconnects every device in the gym**, immediately —
every tablet, the wall display, every rack screen. A web application cannot change a
device's operating-system Wi-Fi credentials, so each one must rejoin by hand.

This is a property of Wi-Fi, not a shortcoming of the app. Do it between sessions,
never during one.

---

## A diagnostic worth knowing about

There is a monitoring script that opens three live views on one screen: bandwidth per
connected device, each device's radio health, and how saturated the Wi-Fi channel is.

It exists because bandwidth numbers alone cannot distinguish **"the application is
slow"** from **"the radio cannot push the bits."** Those have completely different
fixes, and guessing wrong wastes a day.
