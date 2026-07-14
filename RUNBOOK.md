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
| `postgres` | 5432 (internal) | PostgreSQL database — the single source of durable data. Only set-level data is ever written here. |
| `mosquitto` | 1883 (MQTT), 9001 (MQTT-over-WebSockets) | The message broker. Nodes + Django use 1883; browsers connect directly to 9001. |
| `django` | 8000 (internal) | The web/REST server (sync `runserver`). Handles all `/api/` and `/admin/` requests. |
| `mqtt-listener` | — | The ONE MQTT subscriber process. Listens to node pulse topics and updates node health. |
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

First boot builds the Django and React images and runs database migrations
automatically (via the Dockerfile / listener command). The app is reachable at
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

## Coach tablet (Room Layout)

The coach assignment page lives at **`http://<pi-ip>/coach`**. It is a separate
PWA shell (`react/public/manifest.coach.json`, `react/public/coach-icon.svg`)
with a JWT login gate and a **dropdown-and-assign** Room Layout (not
drag-and-drop). Files: `react/src/coach/`.

**Flow:**

1. Open `/coach` and sign in (`POST /api/auth/login/` → Bearer token). Demo account:
   `coach` / `coachpass`. Django seeds it on boot via `ensure_demo_coach`
   (or run `docker exec edgeathlete-django python manage.py ensure_demo_coach`).
2. **Assign rack screen:** pick an Unassigned Screen (`GET /api/racks/unassigned/`)
   and a rack slot → `PATCH /api/racks/{device_id}/` with `{ "rack_number": N }`.
3. **Assign node:** pick a node (`GET /api/nodes/`) and a rack slot →
   `PATCH /api/nodes/{node_id}/` with `{ "rack_number": N }`.

A waiting rack tablet polling `GET /api/racks/racknumber/?device_id=` should see
the new number within about **3 seconds** of a successful coach assign.

### Verify assign round-trip (API)

```bash
# register a waiting tablet (open)
curl -sX POST localhost/api/racks/register/ -H 'Content-Type: application/json' \
  -d '{"device_id":"coach_verify_dev"}'

# coach login
T=$(curl -sX POST localhost/api/auth/login/ -H 'Content-Type: application/json' \
  -d '{"username":"coach","password":"coachpass"}' | jq -r .access)

# assign screen → slot 3
curl -sX PATCH "localhost/api/racks/coach_verify_dev/" \
  -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -d '{"rack_number":3}'

# poll should return 3 immediately (tablet polls ~every few seconds)
curl -s 'localhost/api/racks/racknumber/?device_id=coach_verify_dev'

# assign a node the same way
curl -sX PATCH "localhost/api/nodes/<node_id>/" \
  -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -d '{"rack_number":3}'
```

Django regression coverage: `CoachAssignApiTests` in
`django/event_handler/tests.py`.

Out of scope on this page: group/block/session drill-down and the fuller Phase 10
coach admin (live MQTT room state, graphs, alerts).

## Wall display (team kiosk)

The gym-wall scoreboard is a read-only page at **`http://<pi-ip>/dashboard`**. It is
a separate app from the tablet UI — its own name ("Edge Athlete — Wall Display"),
its own icon, and its own web-app manifest (`react/public/wall-display.webmanifest`)
so it installs/launches full-screen on its own.

**How it works (in one breath):** the page opens one MQTT-over-WebSockets
connection straight to the broker on port `9001` and subscribes once to
`edgeathlete/dashboard/state`. It never polls the server. Every incoming
broadcast is folded into a single state object by one hook
(`react/src/dashboard/useDashboardFeed.js`) — the ONE place any data is touched.
That hook hands ready-to-render slices to four fixed areas, which are pure
display and never fetch anything themselves:

| Area | Shows | Updates on |
|---|---|---|
| Rack Status | one tile per rack, green/yellow/red by bar speed | every `leaderboard_update` |
| Leaderboard | athletes ranked by best average velocity | every `leaderboard_update` |
| Summary | room totals — sets, reps, athletes, racks | every `leaderboard_update` |
| Insights | rotating, prominent room facts + PR call-outs | every `leaderboard_update` |

Files live in `react/src/dashboard/`. The container serves the route via the
SPA-fallback `react/nginx.conf` (copied in by `react/Dockerfile`).

### Boot straight into the wall display (kiosk)

The manifest's `fullscreen` setting does NOT launch a browser on its own — a
systemd unit does. Two files in `deploy/`:

- `deploy/wait-and-launch-kiosk.sh` — polls `/dashboard` until nginx answers,
  then opens Chromium in kiosk mode (`--kiosk --app=http://localhost/dashboard
  --noerrdialogs --disable-infobars`).
- `deploy/edgeathlete-kiosk.service` — runs that script on boot after the Docker
  stack. If this Pi already runs the reference `privacy-dots.service` to start
  the stack, chain to it with `After=privacy-dots.service` instead of relying on
  `docker.service` (see the note in the unit file).

Install on the Pi:

```bash
sudo cp deploy/wait-and-launch-kiosk.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/wait-and-launch-kiosk.sh
sudo cp deploy/edgeathlete-kiosk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now edgeathlete-kiosk.service
```

A cold reboot should now land directly on the fullscreen dashboard with no
keyboard or mouse.

### Verify the wall display updates live

Open `http://<pi-ip>/dashboard` (the connection pill top-right should read
"Live"), then publish a fake dashboard broadcast and watch the screen change on
its own — no refresh:

```bash
mosquitto_pub -h localhost -t edgeathlete/dashboard/state -m '{
  "type": "leaderboard_update",
  "athlete": {"id": 4, "name": "Jordan Lee"},
  "rack_number": 3,
  "avg_velocity": 0.82,
  "peak_velocity": 0.95,
  "reps_completed": 5,
  "is_false_set": false,
  "is_velocity_pr": true,
  "is_weight_pr": false
}'
```

Rack 3 lights up green, "Jordan Lee" appears on the leaderboard, the summary
totals tick up, and the Insights panel calls out the new velocity PR — all within
a couple of seconds.

### Scripted demo (recommended)

For a repeatable walkthrough, use the built-in test cases in
`react/src/dashboard/demoCases.js` and the publisher in
`react/scripts/demo-wall-display.js`. It sends real MQTT messages on the same
topic the wall display uses in production.

```bash
# 1. Start the stack
docker compose up --build

# 2. Open the wall display in a browser
#    http://localhost/dashboard

# 3. In another terminal, replay the full ~45s demo
cd react
npm run demo:wall

# Shorter smoke test (~6s)
npm run demo:wall -- --playlist quick

# One specific case
npm run demo:wall -- --case velocity-pr

# See every case + what you should see on screen
npm run demo:wall:list
```

Each case documents the expected on-screen result (`expect` field). Use `--loop`
to keep replaying the full playlist for kiosk testing.

When a real set is completed via `POST /api/sets/{id}/complete/`, Django now
publishes the same `leaderboard_update` message automatically — the wall display
at `/dashboard` should update without running the demo script.

## Common failure modes

TODO — fill in during Sprint 3 (AP not broadcasting, broker unreachable, clock
skew on a Pi with no RTC / no NTP, batch-POST failures, etc.).

## Firmware flashing

TODO — Phase 9 (ESP32 + MPU-6050 firmware flashing steps).

## Architecture diagram

TODO — Sprint 3 handoff (Mermaid diagram: nodes → broker → Django/Postgres, and
broker → browser clients over WebSockets).
