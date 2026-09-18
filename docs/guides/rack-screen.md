<!--
this guide — everything about a RACK SCREEN, in one place.

It used to be a section inside base-station.md, which put the tablet's install,
its Bluetooth sensor and its NFC reader inside a document about the server. Two
different machines, two different jobs: the base station runs the stack, a screen
runs a browser. If you add to this file, add inside a dropdown — same rule as the
base station guide.
-->

# Getting started with the rack screen

:::{note}
A rack screen is the **opposite of the base station**. The base station broadcasts
the Wi-Fi and runs the server; a screen is a **client** that joins that Wi-Fi and
boots into a locked full-screen browser. It runs no server and no Docker.

For the base station itself, see {doc}`base-station`. For the decisions behind
this setup, see {doc}`../journal/scripts` and {doc}`../journal/rack-tablet`.
:::

## Install it

```bash
curl -fsSL https://raw.githubusercontent.com/carbolizer/Edge-Athlete/main/scripts/rack-screen/rack-bootstrap.sh | sudo bash
```

**Run the same command again to update it.** It is not one-shot.

No role argument — a rack screen is a rack screen. A **coach tablet** is the one
exception and is provisioned by hand:

```bash
sudo scripts/rack-screen/rack-kiosk-setup.sh coach
```

Two things it will not guess, and both have caught people out:

| | |
|---|---|
| `AP_PASSWORD=` | needed once the base station is off the default password. Without it the screen fails to join and says *"is the base station powered on?"* — which points at the wrong thing entirely. |
| `SCREEN_ROTATE=` | rack screens install **portrait** (`right`) by default. Pass `normal` for a landscape tablet, or fix it afterwards with `ea rotate-left`. |

```bash
curl -fsSL .../rack-bootstrap.sh | sudo AP_PASSWORD='your-password' bash
```

## The short commands

On the screen, from any shell. These are the SCREEN's commands — the base station
has a different set under the same names.

| | |
|---|---|
| `ea-update` | pull latest code and re-provision this screen |
| `ea-restart` | restart the browser, keeping this screen's identity |
| `ea-rotate-<dir>` | turn the screen: `left`, `right`, `normal`, `inverted` |
| `ea-kiosk-log` | the last lines the launcher printed |
| `ea-kiosk-exit` | leave the kiosk for the desktop (Ctrl+Alt+K) |
| `ea-help` | the full list |

`ea rotate-left` takes effect **now and at the next boot** — it writes
`/etc/edgeathlete/screen.conf`, which re-provisioning deliberately leaves alone.
Do not prefix it with `sudo`: it needs your desktop session to reach the display,
and elevates internally for the part that writes `/etc`.

:::{dropdown} Which way is "left"?

`left` and `right` are both portrait; which one depends on how the tablet is
mounted. Try one, and use the other if the picture is upside down.

⚠️ **Check a corner tap, not just the middle.** Rotation remaps touch input to
match the display, and when that goes wrong the picture looks perfect while every
tap lands somewhere else. Pressing near an edge is how you notice.

X11 only. Under Wayland (Raspberry Pi OS Bookworm defaults to labwc) `xrandr` is
not the mechanism and rotation quietly does nothing — it belongs in the
compositor's config there.
:::

## What the installer sets up

:::{dropdown} Wi-Fi: why it joins the right network

The screen joins `EdgeAthlete` as a client, and the connection is given
`connection.autoconnect-priority 100`.

That priority is the whole point. `autoconnect yes` only means *eligible*, not
*preferred* — every NetworkManager connection defaults to priority 0, so a tablet
that has ever joined a home or campus network has that saved and equally eligible.
Without the priority it boots looking perfectly connected, to the wrong network,
and cannot reach the base station at all.

Other networks are deliberately left enabled as a fallback, so the tablet is still
reachable on a bench.

```bash
nmcli -f NAME,DEVICE,STATE connection show --active
```
:::

:::{dropdown} The two hardware agents, and when they are skipped

A rack screen can own two pieces of hardware, each a systemd service:

| | |
|---|---|
| `edgeathlete-rack-agent` | the WT901 Bluetooth sensor |
| `edgeathlete-nfc-agent` | the USB NFC wristband reader |

**Their dependencies install separately, and neither failure stops the other.**
`bleak` (Bluetooth) needs Python 3.10+; `pyusb` (NFC) does not. They used to share
one install, so on Raspberry Pi OS Bullseye — which ships Python 3.9 — the
unsatisfiable Bluetooth pin aborted the whole provisioning run: no browser, no
kiosk, and no card reader either, from a library the reader never imports.

So on an older image you get a working screen and a working wristband reader, with
the Bluetooth agent skipped and a message saying why. Reimage to Bookworm if that
machine needs to drive a WT901.

The Bluetooth service also stays disabled until `BLE_ADDRESS` is filled in, because
only a live scan can produce it:

```bash
python3 scripts/hardware/wt901_rack_agent.py --scan
```

Then set it in `/etc/edgeathlete/rack-agent.conf` and
`systemctl enable --now edgeathlete-rack-agent`.
:::

```bash
curl -fsSL https://raw.githubusercontent.com/carbolizer/Edge-Athlete/main/scripts/rack-screen/rack-bootstrap.sh | sudo bash
```

No role argument — a rack screen is a rack screen. A **coach tablet** is the one
exception and is provisioned by hand:
`sudo scripts/rack-screen/rack-kiosk-setup.sh coach`.

:::{dropdown} Bluetooth sensor agent (WT901)

The Agent runs on the central Linux host, outside Docker, so Bleak can use BlueZ.
It owns discovery and connections for every rack. Rack browsers call staff-only
Django endpoints; Django reaches the Agent through `/run/edgeathlete/ble-agent.sock`.
Raw 50 Hz frames and BLE addresses stay in the Agent.

```bash
python3 -m venv .venv-wt901
.venv-wt901/bin/pip install -r scripts/hardware/requirements.txt
AGENT_USER="${SUDO_USER:-$USER}"
AGENT_GROUP="$(id -gn "$AGENT_USER")"
sudo install -d -o "$AGENT_USER" -g "$AGENT_GROUP" -m 0700 /etc/edgeathlete/ble-agent
sudo install -d -o "$AGENT_USER" -g "$AGENT_GROUP" -m 0750 /run/edgeathlete
sudo -u "$AGENT_USER" .venv-wt901/bin/python scripts/hardware/wt901_rack_agent.py \
  --socket-path /run/edgeathlete/ble-agent.sock \
  --state-path /etc/edgeathlete/ble-agent/bindings.json \
  --mqtt-host 127.0.0.1 \
  --mqtt-port 1883
```

Add `--enable-provisional-reps` only for private-AP demo or detector
qualification. It publishes bounded WT901 accepted-rep estimates on the existing
`edgeathlete/node/{node_id}/rep` topic. Leave it off for normal use until MQTT
publisher ACLs or accepted-event replay fencing are implemented.

Legacy single-device diagnostics remain available for hardware troubleshooting:

```bash
.venv-wt901/bin/python scripts/hardware/wt901_rack_agent.py \
  --address '<physically enrolled address>' \
  --node-id wt901_test_1 \
  --allowed-origins 'http://basestation,http://192.168.4.1,http://127.0.0.1:8081'
curl -fsS http://127.0.0.1:8765/health
```

The Agent creates `bindings.json` atomically with mode `0600`; do not pre-create
an empty file. The invoking operator account owns the socket and private state and
must already be allowed to scan/connect through BlueZ; confirm with
`bluetoothctl scan on` before launch. The Django container currently runs as root and receives `/run/edgeathlete` through
`docker-compose.basestation.yml`; no browser or Nginx route exposes the socket.
The central selection flow never sends an address to Django or a browser. Keep
each sensor still while its committed connection calibrates. Rack
check-in remains disabled until server health reports its selected logical node
as `live` with a sample under one second old.

Failure behavior:

- A disconnect or two seconds without notifications forces BLE reconnect and recalibration.
- Rack health polling reads fresh samples through the trusted Unix socket. Django
  rejects MQTT pulses for WT901 nodes, so payload metadata cannot restore freshness.
- MQTT outages do not affect central BLE health. The Agent reconnects each sensor independently.
  Opt-in accepted WT901 reps publish only while the broker is reachable;
  Agent-side replay is not implemented.
- `403 origin_not_allowed` means the browser origin must be added explicitly to
  `--allowed-origins`; do not solve it by binding the Agent off-loopback.

Current limitation: launch is manual. Before unattended deployment, add a
supervised system service. WT901 rep detection is provisional until it passes the
100-rep and 10-minute noise qualification protocol. Accepted-event queuing is a
separate later slice.

The current detector uses the 50 Hz acceleration, gyro, and orientation frame.
The configured `0x61` WT901 payload has no altitude channel. A rep must complete a
translation away from and back near its calibrated starting position. A completed
return does not require a long pause between consecutive reps; stillness after an
incomplete return rejects the movement. Pickup, wiggle, and rotation-only motion
must not be used as rep demos.
:::

:::{dropdown} NFC reader

The first NFC slice supports one USB CCID contactless reader (`2ce3:9567`) on
Rack 1. The host Agent uses direct USB through PyUSB because rack browsers cannot
access CCID devices. It sends one-time taps to Django through a mode-`0600` Unix
socket; tag IDs do not cross HTTP, MQTT, URLs, or normal logs.

```bash
python3 -m venv .venv-nfc
.venv-nfc/bin/pip install -r scripts/hardware/requirements.txt
.venv-nfc/bin/python scripts/hardware/ccid_rack_agent.py \
  --socket-path /run/edgeathlete/nfc-agent.sock \
  --rack-number 1
```

The invoking account must have USB access, normally through `plugdev`. Tap a tag
on the contactless face. The Agent waits for CCID slot-change notifications and
limits event processing to five cycles per second. A held tag creates one event;
remove it before tapping again. After USB recovery, remove and retap the tag to
generate a fresh notification. Unknown and off-roster tags both display
`Wristband not recognized`. USB errors close and reopen the reader every two
seconds until it recovers. BLE acquisition and active-set completion do not depend
on NFC.

Store tag mappings through a protected operator workflow or import. Use canonical
uppercase hex without separators, never place a real tag ID in this repository or
terminal logs. NFC Agent startup is manual until a supervised host service is added.
:::

:::{dropdown} Firmware flashing

**There is no firmware in this repository, and no `firmware/` directory.** The ESP32
work was planned as Phases 13 and 17 and never landed here, so there is nothing to
flash and no steps to follow. See {doc}`../history` for where that sits.

This is worth stating plainly rather than leaving as a promise, because every sensor
you can currently drive is either a **WT901 over Bluetooth** (the dropdown above) or
the **software simulator** (`ea-sim`). Both work without flashing anything.
:::

## When something is wrong

:::{dropdown} The screen is blank, or stuck on "waiting for basestation"

```bash
ea-kiosk-log
```

That is where the launcher's own messages go — including the two that matter most,
"waiting for basestation" and the snap warning.
:::

:::{dropdown} The wristband reader does nothing

```bash
systemctl status edgeathlete-nfc-agent
journalctl -u edgeathlete-nfc-agent -n 30
```

**Restarting every five seconds means it never started**, not that the reader is
broken. The usual cause was a missing `/run/edgeathlete` socket directory; the unit
now creates it with `RuntimeDirectory=`, so a screen provisioned before that fix
needs an `ea-update`.

If the service is genuinely running and the screen still says *"Card reader
unavailable"*, the browser is being blocked from reaching it. The page is served
from `http://basestation` but polls `http://localhost:8766`, and Chrome restricts
private-origin requests to loopback. That one is a known open item.
:::

:::{dropdown} It joined the wrong Wi-Fi

```bash
sudo nmcli connection modify "EdgeAthlete-client" connection.autoconnect-priority 100
sudo nmcli connection up "EdgeAthlete-client"
```

Only needed on a screen provisioned before the priority was set.
:::

:::{dropdown} The rack screen shows a set that will not finish

That is `recovery_required` — an open set whose screen is gone, or a controller
lease that got stuck. The rack screen renders it as `active`, so it looks like an
ordinary set with no way out.

A coach clears it from the room layout: **Release screen** on that rack. It ends
the open set as a false set, resets the controller, and sends the tablet back to
setup. The sensor stays on the rack.

⚠️ If a WT901 is linked, unlink the sensor first — the console will tell you.
Re-linking a Bluetooth sensor has to be done standing at the rack.
:::
