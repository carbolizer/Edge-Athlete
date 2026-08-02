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

**There are four data migrations**, and all four roll back:

| | What it moves | Reverse |
|---|---|---|
| `0005` | Text exercise names → catalog links | Writes the names back |
| `0009` | Seeds the starter movement catalog | Deletes exactly the rows it added |
| `0013` | Backfills "last edited" from "created" | `noop` — rolling back drops the column anyway |
| `0015` | Each group's single coach → the staff table | Puts the head coach back |

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

## Firmware flashing

TODO — Phase 9 (ESP32 + MPU-6050 firmware flashing steps).

## Architecture diagram

TODO — Sprint 3 handoff (Mermaid diagram: nodes → broker → Django/Postgres, and
broker → browser clients over WebSockets).
