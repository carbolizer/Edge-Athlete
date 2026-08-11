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

## Decision: two minutes of every boot were spent waiting for nothing

**What forced it.** Every boot stalled for around two minutes on a service whose job is
to wait for the network to come up. On the console it looked like this, and the "no
limit" is what made people assume it was hung rather than slow:

```
Job systemd-networkd-wait-online.service/start running (56s / no limit)
```

**What was actually happening.** Linux here has *two* network managers, and this
machine deliberately uses only one of them: the setup script hands every device to
NetworkManager, because that is the only way the Wi-Fi adapter becomes visible to the
tool that builds the access point. The other manager is left with nothing to manage —
and its "wait until the network is up" service sat there waiting for an interface it
was never going to be given, until it timed out. Every boot. For nothing.

The proof was already on screen, two lines apart in the boot log: NetworkManager's own
wait-service **finished** normally, while the orphaned one was still counting.

**What we chose.** Make sure the working one is enabled, then disable the orphan. The
application still waits for the network before it starts — that guarantee comes from
the manager that actually owns the hardware.

**Why this is not an independent fix.** It is only safe *because* of the decision to
give NetworkManager the devices. Undo that, and this turns from removing dead weight
into silently deleting a real safety check. The two travel together, and the script
says so at both ends.

**The lesson worth keeping.** Nothing was broken and nothing logged an error — a
service was simply waiting for a condition that could not occur. That failure shape
does not announce itself; it just looks like the machine being slow, and people build
a habit around it. It is worth occasionally asking what a boot is actually waiting for.

---

## Decision: the radio is not allowed to nap

**What forced it.** Wi-Fi adapters save power by sleeping between packets. That is
sensible on a laptop and wrong here: it adds delay to exactly the traffic that cannot
absorb it, which is a live rep travelling from a barbell to a screen while someone is
watching.

**The obvious command does not work.** The standard one-liner for switching power
saving off returns *"Operation not supported"* on this machine — power saving is a
concept for devices that *join* a network, and this adapter is busy *being* one. The
setting has to be made at the layers that do apply: the network manager's own
configuration, and for Intel adapters a driver-level option, since those ignore the
generic setting in some modes.

**What it cost.** It only takes effect after a reboot, and it is two more files. In
exchange it survives one — which the failing command would not have done even if it
had worked.

---

## Decision: the browser is installed on the machine, not in a container

**What forced it.** Everything else on the base station runs in a container, so a
browser in one looked like the consistent choice. It is not.

**What we chose.** The browser is installed directly on the machine, alongside Docker
and at the same point in setup.

A container is a good fit for a *service* — something that listens on a port and has
no opinion about the machine it is on. A browser on a kiosk is the opposite: it exists
to draw on **this machine's physical screen** and read **this machine's keyboard**.
Putting it in a container means handing that container access to the display system,
the graphics hardware, and input devices — more access to the host than the entire
rest of the stack has combined, in exchange for nothing. The consistency would have
been cosmetic.

**What it cost.** One package installed the ordinary way, and one honest exception to
"everything is containerised" that is worth being able to explain. Setup does **not**
fail if the browser cannot be installed: a base station with no monitor attached does
not need one, and a headless install should not die at that step.

---

## Decision: the base station can be its own screen

**What forced it.** The wall display was assumed to be a separate machine. But the base
station already has a video output, and demonstrating the system meant carrying three
tablets to show three kinds of screen.

**What we chose.** The base station can run any of the screens itself — the wall
display on its own monitor, or all three at once for a demo, each as a separate
identity (see {doc}`rack-tablet` on why one browser profile per role is what makes
that possible).

**The detail that makes this better than it looks.** When the browser and the server
are on the same machine, the app can be reached at `localhost` — and browsers treat
`localhost` as trusted. Every feature that is switched off elsewhere on the gym network
(offline caching, tag scanning, direct-to-sensor wireless, installing the app to the
desktop) simply works here, with no certificate and no browser flags.

**The trap inside that detail.** This only applies to the literal name `localhost`.
Using the machine's own hostname does **not** work, even though it resolves to the
same loopback address, because the browser judges the address you typed and never
looks at where it points. Same machine, same server, different answer.

**What it cost.** The base station now needs to boot to a desktop for this to fire,
which is a heavier configuration than a server needs. It is optional — a gym running a
separate wall display should leave it off.

---

## Decision: kiosk state belongs to the machine, not to a user

**What forced it.** The same mistake the install path made, in a new place. The kiosk
scripts wrote the browser's stored data into one specific user's home folder, and
registered the auto-start entry there too. Log in as anyone else and the screen starts
nothing.

**What we chose.** Both moved to machine-owned locations: the browser profiles to a
system state directory, the auto-start entry to the system-wide location every desktop
session reads. The profile directory is shared in the same way `/tmp` is — anyone can
create their own inside it, nobody can delete anyone else's — so no part of this needs
to know or care who is logged in.

**What it cost.** Nothing. This is the same cheap reliability decision as the install
path, applied a second time. That it had to be made twice is the interesting part:
**the fix was documented, and the pattern was still repeated in a neighbouring script.**
Writing down a lesson does not propagate it.

---

## Decision: the everyday commands live in the repo, not in a dotfile

**What forced it.** Three things get done on this machine over and over — update it,
load demo data, start the fake sensor — and each is a long command that is easy to get
subtly wrong. Typing them by hand is how a demo ends up running old code without anyone
noticing.

**What we chose.** Short named commands, defined in a file **inside the repository**
and linked into the system's shell startup. Because it is a link rather than a copy,
updating the base station updates the commands too.

That last part is the whole point. A copied helper file rots: it keeps wrapping the
old behaviour of a script that has since changed, and nothing indicates the drift. A
link cannot get out of step with the thing it wraps.

**What it cost.** One bootstrapping wrinkle — the commands arrive *via* an update, so
the very first update on a machine still uses the long form.

---

## Decision: a rack screen installs with one command too

**What forced it.** The base station had a one-command install. A rack screen did not:
you installed git, cloned the repository, changed directory, and ran a script with the
right argument. Four chances to get it wrong — on the device there are the most of.

**What we chose.** The same shape as the base station's installer, so the two are
learned once rather than twice. One command, and running it again is how you update.

**It takes no role argument, on purpose.** A rack screen is a rack screen. This is the
path you run on a dozen identical devices, and an argument on that path is a way to end
up with a wall display bolted to a squat rack. The other roles are deliberate, one-off
acts, and go through the provisioner directly.

**What it cost.** A rack screen clones the whole repository to get two shell scripts.
That is not free, but it means one update mechanism instead of two, and it keeps the
screens on exactly the code the base station is running.

---

## Decision: the base station defaults to the wall display, and carries every screen

**What forced it.** The base station is the one machine that is always powered, has a
monitor within reach, and can reach the app at `localhost`. Wanting a wall display on
it is the common case. Wanting to open a *rack* screen on it — to answer "is this
broken, or is that tablet broken?" — is the debugging case, and it used to mean walking
to a rack.

**What we chose.** It boots into the wall display, and carries a clickable launcher for
every role. Opening the coach console or a rack screen for a minute is a double-click,
not a reprovision.

**Why this machine specifically.** `localhost` is a trusted origin, so every role opens
here with the offline cache, the app install, and Bluetooth all working — with no
browser flags and no certificate. None of that is true of a screen reaching the base
station over the network, so the debugging copy is strictly better behaved than the
thing it is standing in for. Worth remembering when a bug reproduces on a rack but not
on the base station: those are not the same browser conditions.

**What it cost, and the rule that saved it.** The installer runs again on every update,
so writing the boot setting each time would silently undo a deliberate change —
somebody who pointed the machine at the coach screen for a week would find it back on
the wall display after the next update, for no visible reason. It is written only if
absent. That is the same rule the container log settings already follow, and it is
worth applying to anything an update touches: **set it if it is missing, never correct
it if it is present.**

---

## Decision: the screen unlocks itself, the machine does not

**What forced it.** Plug a monitor into the base station and you want to see the wall
display — not a login prompt. Typing a password to look at a scoreboard is friction
with nothing behind it, and in a gym nobody will do it.

But the same machine is the server. Anything *other* than looking at that screen must
still cost a password.

**What we chose.** A dedicated account that exists only to look at a web page. It logs
in automatically; it has no administrative rights; and its password is **locked**, which
is stronger than blank — it cannot be authenticated against at all, only auto-started.
Physical access gets you a wall display and nothing else. Real accounts still prompt for
ssh and for anything privileged, exactly as before.

**The wrong version of this, and why it is tempting.** Turning on automatic login for a
normal admin account is one setting and gets you the same screen. It also leaves an
unattended machine in a public room with a logged-in session that can administer the
server, which anyone walking past inherits. The question worth asking was never
*whether* to require a password — it was **who** logs in.

**What it cost.** The base station's browser data now lives under that account rather
than yours, so an app installed on the wall display belongs to it. Which is arguably
right, and confusing exactly once.

**Where it does not apply.** A base station with no browser installed — a genuinely
headless one — is skipped rather than given an account that can never log in anywhere.

---

## Decision: the same command on two devices, from two separate files

**What forced it.** A screen and the base station both want a short "update this
device" command. But they are not the same operation: the base station rebuilds a
server stack and reconfigures a Wi-Fi access point; a screen installs a browser and a
launcher. Running the base station's version on a rack tablet would install a server
it has no use for **and** stand up a second access point competing with the real one
for the air the gym runs on.

**What we chose.** Each device type gets its own file of short commands, and
`ea-update` means the same *thing* on both — update this device — while resolving to
the right installer for each. One verb to teach, two implementations.

**Why not one shared file with a check for which device it is.** Because the wrong
branch of that check is a silent disaster, and two separate files are just two
separate files. The failure mode of getting it wrong is not "the command errors" — it
is a rack tablet quietly becoming a competing access point. Each file names the
machine it belongs to in its first three lines.

**A smaller thing that came with it.** The launcher now writes what it says to a log
file, but **only when it was started automatically**. Run by hand it still prints to
the terminal. Launched at boot there is no terminal, so everything it reported — what
it was waiting for, why the browser profile fell back — went nowhere, which is exactly
the situation where somebody is standing in front of a blank screen wanting to know
what it tried to do.

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

---

## Where these decisions live in the code

| File | What it does | Which decision |
|---|---|---|
| `scripts/basestation/bootstrap.sh` | One command to install **or** update. Not one-shot | install path, settings out of git |
| `scripts/basestation/setup.sh` | Installs Docker, the browser, the boot service, the shell commands | browser on the machine, commands in the repo |
| `scripts/basestation/startup.sh` | Runs on every boot: access point first, then the stack | a failed AP must not stop the app |
| `scripts/basestation/apply-wifi.sh` | The privileged Wi-Fi agent on the host | container never reconfigures the network |
| `scripts/basestation/aliases.sh` | **New.** `ea-update`, `ea-seed`, `ea-sim` — linked into shell startup | commands in the repo |
| `scripts/basestation/basestation-kiosk.sh` | **New.** Runs a screen on the base station itself, via `localhost` | the base station as its own screen |
| `scripts/basestation/update-via-hotspot.sh` | Updates a box with no wired internet, by borrowing a phone | — |
| `scripts/rack-screen/rack-bootstrap.sh` | **New.** One command to install **or** update a rack screen | a rack screen installs with one command |
| `scripts/rack-screen/rack-kiosk-setup.sh` | Provisions a screen; run directly only for a coach tablet | a rack screen installs with one command |
| `scripts/rack-screen/aliases.sh` | **New.** The screen's short commands. A *separate file* from the base station's, on purpose | one verb, two devices |
| `scripts/netmon.sh` | The three-pane radio diagnostic described below | — |

:::{admonition} The pattern underneath most of these
:class: tip
Nearly every decision on this page is the same one restated: **nothing may depend on
who is logged in, and nothing the machine owns may live in the repository.** The
install path, the settings file, the browser profiles, the auto-start entry — each was
a separate outage waiting to happen, and each has the same shape. When you add
something to a base station, that is the question to ask of it.
:::
