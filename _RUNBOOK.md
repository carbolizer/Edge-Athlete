<!--
_RUNBOOK.md — the operator's manual for the base station.
This is the "what do I actually type to run this thing" guide for a human sitting
in front of the Pi. It grows across the project: started here in Phase 1 with the
services and start/stop steps, and completed by the Sprint 3 handoff with failure
modes, firmware flashing, and the architecture diagram. If you're on-call, start here.
-->

# Edge Athlete — Base Station RUNBOOK

The whole system runs as one Docker stack on the Raspberry Pi. There is no cloud,
no internet dependency, and no subscription — the Pi broadcasts its own private
WiFi and serves everything itself.

> **Just bringing up a fresh box?** [`QUICKSTART.md`](QUICKSTART.md) is the short
> path — clean Linux install to a running base station in six steps. This runbook
> is the deeper reference for operating one once it's up.

## Services

Every service is defined in `docker-compose.yml` and shares one private Docker
network, so services reach each other by name (e.g. `postgres`, `mosquitto`).

| Service | Port(s) | Purpose |
|---|---|---|
| `postgres` | 5432 (internal) | PostgreSQL database — the single source of durable data. Only set-level data is ever written here. |
| `mosquitto` | 1883 (MQTT), 9001 (MQTT-over-WebSockets) | The message broker. Nodes + Django use 1883; browsers connect directly to 9001. |
| `django` | 8000 (internal) | The web/REST server (sync `runserver`). Handles all `/api/` and `/admin/` requests. |
| `mqtt-listener` | — | The ONE MQTT subscriber process. Listens to node pulse topics and updates node health. |
| `react` | 80 (internal) | Builds the front-end to static files and serves them via its own Nginx. |
| `nginx` | 80 (published) | The front door. Routes `/api/`, `/admin/`, `/static/*` to Django and everything else to React. |
| `seed` | — | **On demand only.** Fills an empty database with a demo gym. Profile-gated, so `docker compose up` never starts it. See [Seeding demo data](#seeding-demo-data). |
| `simulator` | — | **On demand only.** A fake rack sensor for demos without hardware. Also profile-gated. See [Running a demo without hardware](#running-a-demo-without-hardware). |

> There is exactly ONE MQTT listener service (`mqtt-listener`). The reference
> project ran a second, duplicate listener — it has been removed here.

## Installing a base station

The step-by-step version — including prerequisites and the optional demo data —
is [`QUICKSTART.md`](QUICKSTART.md). The essentials:

One command on a fresh machine. It installs Docker, pulls the code, writes the
boot service, and builds the stack:

```bash
curl -fsSL https://raw.githubusercontent.com/carbolizer/Edge-Athlete/SprintBranch/scripts/basestation/bootstrap.sh | sudo bash
```

Run the **same command again** to update a base station later — it is not
one-shot.

| | Path |
|---|---|
| The install | `/srv/edge-athlete/Edge-Athlete` |
| This machine's Wi-Fi settings | `/etc/edgeathlete/basestation.conf` (**not** in git) |
| Boot service | `edgeathlete.service` |

Then, before the gym uses it:

```bash
sudo nano /etc/edgeathlete/basestation.conf   # AP_PASSWORD is still the default
sudo systemctl restart edgeathlete.service
```

Nothing depends on which user is logged in, and the scripts work from wherever
the repo was cloned. Full detail — including what to do when the access point
won't start — is in [`scripts/README.md`](scripts/README.md).

A coach can also change the Wi-Fi password from the coach admin page. It applies
live via a host agent, and **disconnects every device** — tablets, wall display,
and each rack Pi — which must then rejoin by hand. It's a walk-around; do it
between sessions. See "Changing the Wi-Fi password" in
[`scripts/README.md`](scripts/README.md).

## Start / Stop procedure

From the repo root (where `docker-compose.yml` lives):

```bash
# Start the whole stack (build images the first time or after changes)
docker compose up --build          # add -d to run detached in the background

# Stop it (containers stop, data volumes persist)
docker compose down

# Stop AND wipe the database volume (destructive — fresh start)
docker compose down -v

# Watch logs for one service
docker compose logs -f django
docker compose logs -f mqtt-listener
```

First boot builds the Django and React images and runs database migrations
automatically (via the Dockerfile / listener command). The app is reachable at
`http://<pi-ip>/` (or `http://localhost/` on the dev host).

## Seeding demo data

A freshly migrated database is empty — no athletes, no session, and no coach
login, so `/coach` cannot even be signed into. One command fills it:

```bash
docker compose run --rm seed
```

That gives you a live training day ("Thursday — Lower + Push"), four athletes,
the plan they train, recorded reference maxes, two already-finished sets, and the
demo coach login (`coach` / `coachpass`).

**`seed` is a one-shot, and it is invisible to `docker compose up`.** It carries a
Compose *profile*, which means the service does not exist unless you name it —
demo data can never appear on its own at boot.

Running it again is safe. The seeder converges instead of piling up: it closes
whatever day was left open, reuses the group's existing plan rather than
deploying a second one, and matches its own rows by name. Two runs leave exactly
**one** open session, which is the rule the whole app depends on (canon D18).

> ⚠️ **`--reset` is not passed, on purpose.** The seeder's reset flag deletes the
> rows it thinks are its own, but it matches them **by name** — on a real base
> station that would take out a group genuinely called "Varsity", plus any athlete
> sharing a name with the demo four, and their sets with them. On a laptop, where
> that is fine, ask for it explicitly:
>
> ```bash
> docker compose run --rm seed python manage.py seed_active_session --reset
> ```

## Running a demo without hardware

The `simulator` service is a fake rack sensor. It publishes the same pulse and
rep messages a real node would, on the same topics, so the tablet and the wall
display can be demoed with nothing bolted to a rack.

```bash
docker compose --profile demo up -d simulator     # runs until you stop it
docker compose logs -f simulator                  # watch it decide
docker compose --profile demo down simulator      # stop it
```

**It stays quiet until the rack is actually being used.** By default the rep
stream is gated on a set being open at the linked rack, so a demo reads like
this:

| What the room is doing | What the node publishes |
|---|---|
| No training day running | pulses only |
| Day running, nobody at the rack | pulses only |
| Athlete checked in, between sets | pulses only |
| **Set open at that rack** | **pulses + reps** |
| Set ended | pulses only |

The heartbeat never stops, on purpose — pulses are how Django knows the node is
alive, so going quiet on those would make an idle rack look like a dead one.

The rack it watches comes from the **node's own database row**, re-read every
couple of seconds. Link the sensor to a rack mid-demo and it wakes up on its
own; there is nothing to restart.

Loosen the gate with `--active-when` if you want a chattier demo:

| Mode | Publishes reps when |
|---|---|
| `lifting` *(default)* | a set is open at the rack |
| `checkin` | anyone is checked in there, set or no set |
| `always` | never pauses — the behaviour from before the gate existed |

Simulating a second rack needs no compose edit:

```bash
docker compose run --rm simulator python manage.py simulate_node --node-id rack_2
```

> The gate reads the database directly rather than calling
> `GET /api/sessions/active/status/`. It is a management command, so it is
> already inside the ORM — the HTTP route would be the same rows with a web
> server and a base URL in the way. It reuses `active_session()` for "which day
> is live", so it can never disagree with the screens about that (canon D18).

## Database migrations & rollback

Migrations apply automatically on Django boot. To roll one back, migrate the app
to the migration you want to land on — Django reverses everything after it:

```bash
# Roll back to a specific migration (undoes every later one for this app).
# Example: undo the AthleteReferenceMax table (0003) and land on 0002.
docker exec edgeathlete-django python manage.py migrate event_handler 0002_set_weight_lbs

# See what's applied / what a rollback would undo
docker exec edgeathlete-django python manage.py showmigrations event_handler
```

There are no separate "down" files — each migration reverses itself. Schema
migrations (add/drop a table or column) roll back cleanly. The one thing to
watch: a **data** migration (one that moves or backfills rows, `RunPython`) only
reverses if someone wrote its reverse step — otherwise it's one-way.

**There are six data migrations.** Four restore or safely discard generated data;
`0018` and `0019` deliberately cannot reconstruct cleared legacy mappings:

| | What it moves | Reverse |
|---|---|---|
| `0005` | Text exercise names → catalog links | Writes the names back |
| `0009` | Seeds the starter movement catalog | Deletes exactly the rows it added |
| `0013` | Backfills "last edited" from "created" | `noop` — rolling back drops the column anyway |
| `0015` | Each group's single coach → the staff table | Puts the head coach back |
| `0018` | Clears duplicate rack-node mappings before adding uniqueness | Leaves current explicit mappings intact; cleared legacy mappings must be restored from a pre-migration database backup and reselected at each rack |
| `0019` | Clears MQTT-unsafe assigned node IDs before adding its constraint | Leaves current explicit mappings intact; cleared legacy mappings must be restored from backup and reselected after correcting the node ID |

Anything you add from here needs the same treatment — see
[`docs/_MIGRATION_PLAYBOOK.md`](docs/_MIGRATION_PLAYBOOK.md), which is the full
guide to changing this schema safely.

## Config files and where they live

| File | What it controls |
|---|---|
| `.env` | Real runtime values (DB login, MQTT host, Django secret). **Gitignored.** |
| `.env.example` | Committed template of `.env` with blank values. |
| `docker-compose.yml` | Which services run and how they're wired together. |
| `mosquitto/mosquitto.conf` | The broker's two listeners: 1883 (MQTT) + 9001 (WebSockets). |
| `nginx/nginx.conf` | Reverse-proxy routing: `/api/`, `/admin/`, `/static/*` → Django, `/` → React. |
| `django/basestation_config/settings.py` | Django configuration (reads everything from `.env`). |

## MQTT test commands

The broker allows anonymous connections through Sprint 3, so these work with no auth.

```bash
# Watch every Edge Athlete topic (run in its own terminal)
mosquitto_sub -h localhost -t 'edgeathlete/#' -v

# Publish a fake pulse and confirm the subscriber above sees it
mosquitto_pub -h localhost -t edgeathlete/node/test/pulse -m '{}'
```

Browser check (proves the 9001 WebSockets door works — this is the path all
three screen types use). In a browser JS console with an `mqtt.js` client:

```js
const c = mqtt.connect(`ws://${location.hostname}:9001`);
c.on('connect', () => c.subscribe('edgeathlete/node/test/pulse'));
c.on('message', (t, m) => console.log(t, m.toString()));
// then, from a terminal:
//   mosquitto_pub -t edgeathlete/node/test/pulse -m '{}'
// the console should log the message.
```

## Common failure modes

TODO — fill in during Sprint 3 (AP not broadcasting, broker unreachable, clock
skew on a Pi with no RTC / no NTP, batch-POST failures, etc.).

## Central WT901BLE Agent

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
- A configured rack tablet keeps its active rep collector mounted while showing
  `/coach` or `/dashboard`. The original rack tab keeps buffering after its
  controller lease expires in the background and reclaims that lease when visible.
  Closing, fully suspending, or disconnecting that browser can still lose messages
  because accepted-event replay is not implemented.
- `403 origin_not_allowed` means the browser origin must be added explicitly to
  `--allowed-origins`; do not solve it by binding the Agent off-loopback.

Current limitation: launch is manual. Before unattended deployment, add a
supervised system service. WT901 rep detection is provisional until it passes the
100-rep and 10-minute noise qualification protocol. Accepted-event queuing is a
separate later slice.

The current detector uses the 50 Hz acceleration, gyro, and orientation frame.
Filtered acceleration gates movement, while gravity-compensated raw acceleration,
including the four confirmed onset samples, drives velocity and displacement. The
configured `0x61` WT901 payload has no altitude channel. A rep must complete a
translation away from and back near its calibrated starting position. A completed
return does not require a long pause between consecutive reps; stillness after an
incomplete return rejects the movement. Pickup, wiggle, and rotation-only motion
must not be used as rep demos.

## Rack 1 NFC reader

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

## Firmware flashing

TODO — Phase 9 (ESP32 + MPU-6050 firmware flashing steps).

## Architecture diagram

TODO — Sprint 3 handoff (Mermaid diagram: nodes → broker → Django/Postgres, and
broker → browser clients over WebSockets).
