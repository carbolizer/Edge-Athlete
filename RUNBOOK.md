<!--
RUNBOOK.md — the operator's manual for the base station.
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
| `postgres` | 5432 (internal) | PostgreSQL database — the source of durable sessions, sets, reps, and room state. |
| `mosquitto` | 1883 (MQTT), 9001 (MQTT-over-WebSockets) | The message broker. Nodes + Django use 1883; browsers connect directly to 9001. |
| `django` | 8000 (internal) | The web/REST server (sync `runserver`). Handles all `/api/` and `/admin/` requests. |
| `mqtt-listener` | — | The ONE MQTT subscriber process. Listens to node pulse topics and updates node health. |
| `monitoring-publisher` | — | Publishes durable room-state invalidations after database commits. |
| `simulator` | — | Optional, profile-gated development traffic; never starts in the normal profile. |
| `react` | 80 (internal) | Builds the front-end to static files and serves them via its own Nginx. |
| `nginx` | 80 (published) | The front door. Routes `/api/`, `/admin/`, `/static/*` to Django and everything else to React. |

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

First boot builds the Django and React images; the Django service runs database
migrations before starting the server. The app is reachable at
`http://<pi-ip>/` (or `http://localhost/` on the dev host).

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

## Simulated live readings

Use the opt-in simulator when sensor hardware is unavailable. `monitoring` mode
persists generated reps through the same atomic completion service as rack REST
requests, which drives wall, coach, history, and analytics screens. `rack` mode
publishes rep MQTT payloads without persistence, allowing a rack client to own
set boundaries and submit each set exactly once. Both modes publish node pulses.

```bash
# Start the normal stack plus four simulated racks (capped at 100 set cycles)
docker compose --profile simulation up --build -d

# Watch generated readings and completed sets
docker compose logs -f simulator

# Stop only the simulator; saved simulation history remains available
docker compose --profile simulation stop simulator

# Delete all records owned by reserved simulation identities
docker compose run --rm -e SIMULATOR_ENABLED=True django \
  python manage.py clear_simulation_data --confirm

# Run one fast, repeatable set on one rack, then exit
docker compose run --rm -e SIMULATOR_ENABLED=True django \
  python manage.py simulate_node --mode monitoring --racks 1 --rack 1 --sets 1 \
  --interval 0.25 --rest 0 --seed 42

# Exercise a rack client's MQTT and set-completion path without pre-saving reps
docker compose run --rm -e SIMULATOR_ENABLED=True django \
  python manage.py simulate_node --mode rack --racks 1 --rack 1 --sets 10
```

The default session is named `[SIMULATION] Live training`. Generated records carry
durable simulation ownership fields; prefixes remain human-readable labels only.
The cleanup command deletes only records marked as simulated and refuses to race
a running simulator. The command refuses to run while
a non-simulation session is active. Continuous mode requires a nonzero cadence,
has a maximum of 1,000 cycles, and uses 100 cycles by default. Do not put names or
other personal information in a simulation session label.

## Common failure modes

TODO — fill in during Sprint 3 (AP not broadcasting, broker unreachable, clock
skew on a Pi with no RTC / no NTP, batch-POST failures, etc.).

## Firmware flashing

TODO — Phase 9 (ESP32 + MPU-6050 firmware flashing steps).

## Architecture diagram

TODO — Sprint 3 handoff (Mermaid diagram: nodes → broker → Django/Postgres, and
broker → browser clients over WebSockets).
