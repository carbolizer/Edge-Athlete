# Spec: Edge Athlete — Real-Time Barbell Velocity Tracking — v1
**Stack:** Django (sync `runserver`, DRF) + React (Vite) + PostgreSQL + Mosquitto (MQTT) + Nginx, all in Docker | **Hardware:** Raspberry Pi base station (owns a private WiFi AP) + ESP32 + MPU-6050 sensor nodes | **Served by:** the Pi, no internet, no cloud, no subscription | **Environment:** macOS dev host → deploy target is Raspberry Pi OS (arm64) | **Team:** 4 people | **Timeline:** 6 sprints × 2.5 weeks

## Agent tool compatibility
This file is the project's agent-instructions file regardless of which tool you're running. **Claude Code:** treat this as `CLAUDE.md`. **opencode:** treat this as `AGENTS.md`. Either rename/symlink it accordingly in your own checkout, or just point your tool at this file directly — don't fork a second copy of the instructions.

## IMPORTANT
When doing scaffolding and file-admin work use a more efficient model like **Haiku**. Use **Opus** as the default for the large majority of implementation work. Reach for **Fable** (interchangeably with Opus) on the highest-stakes logical work: rep-detection tuning, MQTT topic routing, auth/security. See **Working Style → Model routing**.

This document is the single source of truth for what Edge Athlete is and how it gets built. If another file contradicts this specification, **this file wins.**

---

## How to Use This Document

Work through each phase in order. **Do not proceed to the next phase until the current one is complete and its exit checklist passes.** Each phase ends with an explicit STOP and a checklist. Paste only the prompt for the current phase into a fresh Claude conversation — do not share future phases ahead of time.

Inspect the current Edge Athlete code, tests, and documentation before writing code. Do not guess at structure or configuration.

Sprints 1–3 (Phases 1–9) are written at full paste-ready depth. Sprints 4–6 (Phases 10–14) are lighter by design — a lot will shift across the first nine phases, so those phases get their full treatment closer to their start.

---

## Known Open Items (read before starting the phase they touch)

These are real gaps, not stretch goals — they were deliberately deferred to get a demo-able slice built in a tight window. Whoever starts the referenced phase should resolve or explicitly re-defer each one rather than being surprised by it mid-phase:

- **Batch-POST failure/retry (affects Phase 7, hardens in Phase 12/14):** if `POST /api/sets/{id}/complete/` fails (e.g. an AP drop at the exact moment a set ends), there is currently no defined retry/backoff — the buffer only clears on success, but nothing describes what happens on failure. Fine for a controlled demo; needs a real answer before unattended/production use.
- **Analytics response contract (affects Phase 4, consumed by Phase 10):** `GET /api/analytics/session/{id}/` and `.../athlete/{id}/` only have a prose description, not an exact field list like every other endpoint. Pin down the actual JSON shape before or during Phase 4 so Phase 10 isn't guessing at what it receives.
- **No rack "unassign" path (affects Phase 10):** only registration + assignment exist; there's no way to free a rack number back to the unassigned pool if a screen is retired or replaced.
- **Clock reliability on the offline Pi (affects Phase 1/RUNBOOK, Phase 14):** the base station never touches the internet, so there's no NTP sync. If it lacks a hardware RTC, a cold boot could start with a wrong system clock, silently corrupting every `timestamp` field. Needs either an RTC module or a manual time-set step documented in the boot procedure.
- **Stale `RackScreen` rows (affects Phase 12):** if a screen's `localStorage` is ever wiped, it registers a brand-new `device_id` and the old row is orphaned at its old rack number with no cleanup.

---

## Working Style

These conventions were established up front and must be followed by any agent working on this project.

### Git branching
- Branches are named for the feature currently being worked on (e.g. `rack-screen-pwa`, `mqtt-topic-routing`, `coach-tablet-auth`), not for phase numbers.
- Commit at the end of each phase — don't cut a new branch per phase.
- If a phase's work continues the same feature as the previous phase, stay on that branch. Only cut a new branch when work moves to a genuinely new feature area.
- At the end of a phase: commit the work, then merge the finished branch into `main`.
- Example: `git checkout main && git merge rack-screen-pwa`

### Commit message style
- Choppy, flow-of-consciousness — a note to yourself, not a filed ticket.
- **NO** `feat:` / `chore:` / `fix:` prefixes.
- **NO `Co-Authored-By:` trailers and no "Generated with" / tool-attribution lines** — commits carry the human author only, nothing that credits an AI or a tool.
- Good: `parse_rep_payload done, drops motion parser, shares contract w/ sim`
- Good: `rack screen buffers reps to IndexedDB, batch POST fires on set end`
- Bad: `feat: add rep payload parser`
- Bad: `chore: implement IndexedDB rep buffering`
- Bad: any message ending in `Co-Authored-By: Claude ...`

### Commit frequently within a phase
- Don't save all commits for the end of a phase.
- Any time a meaningful piece of functionality works or a bug is fixed, commit it.
- Think: "if I had to throw away everything after this point, would I want this saved?" — if yes, commit.

### Step announcement style
- At the beginning of each major step, announce what you are about to do before doing it.
- Example: "I am about to finish `process_pulse_event` — this replaces the `# TODO` stub with a real `Node.update_or_create` keyed on node_id."
- This lets the developer catch a wrong assumption before the work is done, not after.

### Model routing
- **Haiku** — pure scaffolding only: folder structure, boilerplate config stubs, repetitive CRUD shells with no real logic yet, file admin, shell commands.
- **Opus** — the default. Use it for the large majority of implementation work, trivial and non-trivial alike.
- **Fable** — interchangeably with Opus on the highest-stakes logical work: rep-detection tuning, MQTT topic routing, auth/security code, anything expensive to unwind if done wrong.

---

## Project Overview

Edge Athlete is real-time barbell velocity tracking for weight rooms that can't afford GymAware ($3,880) or Perch ($1,995/unit + $3,000/yr). A Raspberry Pi runs the whole stack and broadcasts its own private WiFi network — no internet, no cloud, no subscription. ESP32 + MPU-6050 sensor nodes clip to a bar, waist, or wrist and compute how fast an athlete is moving. Athletes see live feedback on a tablet at their rack. A coach carries a tablet with full control. A shared "bowling-alley scoreboard" display shows the room a leaderboard.

### End-to-end user flow
1. A coach powers on the Pi. It boots the Docker stack and broadcasts its private AP. Every node and screen in the room joins that AP; nothing needs internet.
2. Each **node** (ESP32 + MPU-6050) computes velocity on-device and publishes each completed rep as its own MQTT message, plus a pulse/heartbeat on an interval. It never streams raw accelerometer data.
3. A deferred **rack screen** would subscribe over MQTT-over-WebSockets to its linked node's rep topic and buffer each rep locally while updating its UI.
4. When that deferred rack workflow is implemented, it would batch-POST the completed set — summary + every rep — to the base station in one request.
5. The base station writes that set, its reps, and a monitoring-outbox revision to Postgres in one transaction. A dedicated publisher delivers a privacy-safe retained invalidation event to Mosquitto with QoS 1.
6. The **team dashboard** and **coach tablet** subscribe to `edgeathlete/dashboard/state`, then refetch their privacy-appropriate REST snapshot when its revision increases. PostgreSQL remains authoritative.

---

## Architecture Decisions

These are intentional, locked decisions. They are recorded here so nobody changes core architecture without understanding the tradeoffs.

### MQTT carries sensor traffic and browser invalidation events
Hardware and Django use plain MQTT on port **1883**. The current wall dashboard and coach workspace use MQTT over WebSockets on port **9001** only for `edgeathlete/dashboard/state` invalidations, then refetch authoritative REST snapshots. The rack-tablet browser flow remains deferred.

Rationale: this repository runs synchronous Django with REST, so adding Channels would create a second server stack. Mosquitto already supplies live push. The ESP32 also remains a publisher rather than a web server, avoiding node-IP discovery. **No Channels, no ASGI, no web/WebSocket server on the ESP32.**

### PostgreSQL persists reps in one completed-set transaction
PostgreSQL stores the completed `Set` and all of its `Rep` rows. Reps are not written individually as they occur; the completion service bulk-creates the full rep list together with the set update and monitoring event in one atomic transaction.

### Deferred rack-screen durability design
The proposed rack screen would buffer reps locally and POST a completed set in one batch. The rack-tablet frontend and its local durability mechanism are not included in this handoff.

### MQTT topic scheme is namespaced under `edgeathlete/`
See **Real-Time Layer Reference** for the full table. Key rule: **Django's MQTT subscriber listens ONLY to `edgeathlete/node/+/pulse`** — rep topics never reach Django/Postgres at runtime. Node reassignment = the rack screen resubscribes to a different node topic string. No IP lookup, no socket teardown.

### Six sprints, 2.5 weeks each
The plan uses six sprints. Sprint 3 ends with a formal handoff: RUNBOOK, Mermaid architecture diagram, and an observe-only dry run.

### Coach tablet is one page for this spec
The full vision (separate Room / Athletes / Racks / Analytics tabs) is deferred. This spec builds a single consolidated admin view: live room state, abnormal-performance alerts/suggestions, and basic graphs. Multi-page expansion is future work.

### Local fatigue ML is scaffolded, not trained
Fatigue detection gets a real interface (`ml/inference.py`) and a real call site (fires after set-complete), but the function returns a stub value in this spec. Training a real model is explicitly out of scope.

### Edge Athlete owns its repository and runtime
All services, containers, routes, files, and documentation in this repository use Edge Athlete identities. Legacy project code and runtime names are not part of this product.

---

## Coding Standards (for every file written in this repo)

These rules apply to all code from Phase 1 onward. They will later be copied into per-directory `CLAUDE.md` files as a follow-up task — until those files exist, **this section is their source of truth.**

- **Comments are concise and purposeful.** Add a rationale comment only when a file's purpose or non-obvious behavior needs explanation. Do not add comments that restate the code.
- **No premature abstraction.** If a later phase doesn't need it, don't build it now. Don't build for a phase that isn't here yet.

---

## Current Foundation

| Edge Athlete component | Required behavior |
|---|---|
| `docker-compose.yml` and `.env.example` | Use `edgeathlete-*` container identities and an Edge-specific web port. |
| `mosquitto/mosquitto.conf` | Serve hardware MQTT on 1883 and browser WebSockets on 9001. |
| `setup.sh`, `startup.sh`, and `edgeathlete.service` | Configure the Pi access point and start the stack; kiosk launch remains Phase 8 work. |
| `django/basestation_config/` | Provide REST, JWT authentication, and the Edge Athlete service configuration. |
| `django/event_handler/` | Own nodes, athletes, programs, sessions, sets, reps, pulse ingestion, and monitoring events. |
| `run_mqtt_subscriber.py` | Remain the single inbound pulse subscriber. |
| `publish_monitoring_events.py` | Drain durable dashboard invalidations to MQTT. |
| React dashboard and coach workspace | Reconcile persisted REST snapshots from MQTT revision events. |

---

## Real-Time Layer Reference

### Broker config
`mosquitto/mosquitto.conf` needs two listeners:
```
listener 1883
allow_anonymous true

listener 9001
protocol websockets
allow_anonymous true
```
Expose both in `docker-compose.yml` on the configured bind address; no Nginx proxy is needed:
```yaml
mosquitto:
  ports:
    - "${EDGEATHLETE_BIND_ADDRESS:-127.0.0.1}:1883:1883"
    - "${EDGEATHLETE_BIND_ADDRESS:-127.0.0.1}:9001:9001"
```
Anonymous MQTT is accepted only inside the controlled Pi access-point boundary, which uses a unique generated password. TLS and broker authentication/ACLs remain required before exposing either listener to any broader network.

### Topics — all namespaced under `edgeathlete/`

**Published by the node (plain MQTT, port 1883):**

| Topic | Fires | Payload |
|---|---|---|
| `edgeathlete/node/{node_id}/rep` | once per completed rep | `{node_id, rep_number, mean_velocity, peak_velocity, duration_ms, timestamp}` |
| `edgeathlete/node/{node_id}/pulse` | every ~5s | `{node_id, event_type:"pulse", battery_level, signal_strength, firmware_version, timestamp}` |

**Published by Django (plain MQTT; browsers consume over WS, port 9001):**

| Topic | Fires | Payload |
|---|---|---|
| `edgeathlete/dashboard/state` | committed monitoring revision | `{schema_version, type:"room_state_changed", reason, revision, event_id, occurred_at}` |

**Subscribed by each client:**

| Client | Subscribes to |
|---|---|
| Rack screen (deferred) | Proposed: `edgeathlete/node/{current_linked_node_id}/rep`; final contract is deferred with the rack UI |
| Team dashboard | `edgeathlete/dashboard/state` |
| Coach tablet | `edgeathlete/dashboard/state` |
| Django subscriber | `edgeathlete/node/+/pulse` **only** — never rep topics |

---

## Data Models

Eight models. All live in `django/event_handler/models.py`.

```
Node       — node_id (CharField, unique), rack_number (Int, nullable),
             mount_type (choices: bar/waist/wrist), firmware_version,
             battery_level (Int, nullable), signal_strength (Int, nullable),
             last_seen (DateTime, nullable), is_active (Bool, default True)
RackScreen — device_id (CharField, unique, client-generated at first setup),
             rack_number (Int, nullable — null means "awaiting coach
             assignment"), last_seen (DateTime, auto)
Athlete    — name, nfc_tag_id (unique, nullable), created_at (auto), notes (Text, blank)
Program    — athlete (FK→Athlete), exercise, target_sets (Int), target_reps (Int),
             target_weight_lbs (Float), velocity_zone_min (Float), velocity_zone_max (Float)
Session    — label, started_at (auto), ended_at (nullable), athletes (M2M→Athlete), notes
Set        — session (FK→Session), athlete (FK→Athlete), node (FK→Node, nullable),
             rack_number (Int, nullable snapshot), exercise, set_number (Int),
             weight_lbs (Float, nullable), started_at, ended_at (nullable),
             reps_completed (Int, default 0), avg_velocity (Float, nullable),
             peak_velocity (Float, nullable), is_false_set (Bool, default False)
Rep        — set (FK→Set), rep_number (Int), timestamp, mean_velocity (Float),
             peak_velocity (Float), duration_ms (Int), velocity_color (Char)
MonitoringEvent — event_id (UUID, unique), reason, occurred_at, published_at
                  (nullable), publish_attempts, last_error, is_simulated
```

**`Rep` rows are created ONLY via the batch set-complete endpoint, never one at a time.**
**`RackScreen` is the physical screen's own identity — separate from `Node.rack_number`, which tracks which sensor is linked to a rack. A rack screen and its sensor node are assigned independently.**

---

## REST API

```
POST  /api/auth/login/                 coach login → {access, refresh}  (already wired via simplejwt)
POST  /api/auth/refresh/               → {access}

GET   /api/nodes/                      list nodes                         (open)
PATCH /api/nodes/{node_id}/            reassign rack_number               (coach only)

POST  /api/racks/register/             rack screen announces itself       (open)
      body: { device_id }
      effect: upsert a RackScreen row keyed on device_id, last_seen=now;
              rack_number stays null the first time (awaiting assignment)
GET   /api/racks/racknumber/?device_id={id}  poll while awaiting assignment      (open)
      returns: { rack_number: null | int }
GET   /api/racks/unassigned/           list screens with rack_number=null  (coach only)
PATCH /api/racks/{device_id}/          assign rack_number                  (coach only)

GET   /api/athletes/                   list                               (open read)
POST  /api/athletes/                   create                             (coach only)
PATCH /api/athletes/{id}/              update                             (coach only)

GET   /api/programs/?athlete={id}      list for athlete                   (open read)
POST  /api/programs/                   create                             (coach only)

POST  /api/sessions/                   create session                     (coach only)
PATCH /api/sessions/{id}/              end session                        (coach only)

POST  /api/sets/                       create a set (on set_start)        (open)
POST  /api/sets/{id}/complete/         *** THE BATCH WRITE ***            (open)
      body: { reps_completed, avg_velocity, peak_velocity, is_false_set,
              reps: [ {rep_number, mean_velocity, peak_velocity, duration_ms,
                       timestamp, velocity_color}, ... ] }
      effect: one bulk_create of all Rep rows + one Set update, single transaction

GET   /api/analytics/session/{id}/     summary stats                      (coach only)
GET   /api/analytics/athlete/{id}/     trend data                         (coach only)
```

**Open (no auth):** node/rack/dashboard reads, rack-screen self-registration + assignment polling, and the set-complete write.
**Coach-only (JWT):** athlete/program writes, node reassignment, rack-screen assignment, session create/end, analytics.

---

## Folder Structure (target state after all phases)

```
Edge-Athlete/
├── docker-compose.yml
├── .env                          # gitignored — runtime values
├── .env.example                  # committed — template with stubbed keys
├── RUNBOOK.md                    # started Phase 1, completed by Sprint 3 handoff
├── README.md
├── mosquitto/
│   └── mosquitto.conf            # two listeners: 1883 (mqtt) + 9001 (websockets)
├── nginx/
│   └── nginx.conf                # /api/, /admin/, /static/*, / → react
├── django/
│   ├── Dockerfile
│   ├── manage.py
│   ├── requirements.txt
│   ├── basestation_config/
│   │   ├── settings.py
│   │   ├── urls.py               # simplejwt login/refresh already wired
│   │   ├── wsgi.py
│   │   └── asgi.py
│   └── event_handler/            # app name kept, contents gutted
│       ├── models.py             # Domain models plus durable MonitoringEvent outbox
│       ├── admin.py
│       ├── apps.py
│       ├── serializers.py
│       ├── views.py
│       ├── urls.py
│       ├── permissions.py        # IsCoach (JWT) vs open
│       ├── ml/
│       │   └── inference.py       # fatigue scaffold — real signature, stub return
│       ├── management/commands/
│       │   ├── run_mqtt_subscriber.py   # the ONE listener
│       │   └── simulate_node.py         # fake rep/pulse publisher
│       ├── realtime/
│       │   ├── mqtt_ingester/
│       │   │   ├── parser.py            # parse_pulse_payload + parse_rep_payload
│       │   │   └── subscriber.py        # subscribes edgeathlete/node/+/pulse ONLY
│       │   ├── event_processor/
│       │   │   └── process_pulse.py     # finished, writes to Node
│       │   └── broadcast/
│       │       └── publisher.py         # MonitoringEvent → retained dashboard invalidation
│       └── migrations/
├── react/
│   ├── Dockerfile
│   ├── index.html
│   ├── vite.config.js
│   ├── package.json
│   └── src/
│       ├── main.jsx
│       ├── App.jsx                      # explicit /dashboard, /coach, /connection-test routes
│       ├── Dashboard.jsx                # wall scoreboard and authenticated coach workspace
│       ├── ConnectionTest.jsx           # broker connection diagnostics
│       ├── useLiveRoomState.js          # REST snapshots + MQTT revision reconciliation
│       ├── roomMonitor.js               # monitoring event validation
│       ├── historyView.js               # coach history grouping and rep comparison
│       ├── roomMonitor.test.js
│       ├── historyView.test.js
│       ├── App.css
│       └── index.css
└── esp32/
    └── edge_athlete_node/
        └── edge_athlete_node.ino        # MPU-6050, 0.75s-stillness rep boundary
```

---

# SPRINT 1 — Foundation

## Phase 1 — Repo Bootstrap, Broker WS Upgrade & RUNBOOK

### Goal
Bootstrap the Edge Athlete stack, enforce a single MQTT listener, add the WebSocket broker listener, and start the RUNBOOK the Sprint 3 handoff depends on.

### Prompt to paste into Claude
```
Working directory: the Edge-Athlete repo root.

## 1. Establish Edge Athlete infrastructure
Create and configure these files with Edge Athlete names and behavior:
- docker-compose.yml
- mosquitto/mosquitto.conf
- nginx/nginx.conf   (keep the /api/, /admin/, /static/admin/, /static/rest_framework/, and / blocks as-is)
- .env.example  (committed) and .env (gitignored — add to .gitignore)
- django/Dockerfile, django/manage.py, django/requirements.txt,
  django/basestation_config/{settings.py,urls.py,wsgi.py,asgi.py}
- react/Dockerfile, react/index.html, react/vite.config.js, react/package.json
Use `edgeathlete-*` container names and Edge Athlete Postgres configuration.

## 2. Keep one MQTT listener
Keep exactly one `mqtt-listener` service running `run_mqtt_subscriber`. Do not
add another subscriber process for the same topics.

## 3. Add the WebSocket listener to mosquitto.conf
Final mosquitto.conf must be exactly:
  listener 1883
  allow_anonymous true

  listener 9001
  protocol websockets
  allow_anonymous true
And expose 9001 in docker-compose.yml on the mosquitto service, same pattern as
1883:
   ports:
     - "${EDGEATHLETE_BIND_ADDRESS:-127.0.0.1}:1883:1883"
     - "${EDGEATHLETE_BIND_ADDRESS:-127.0.0.1}:9001:9001"
Do NOT add an Nginx WebSocket proxy — browsers hit 9001 directly.

## 4. Start RUNBOOK.md
Create RUNBOOK.md at repo root with Services, Start/Stop procedure, Config files,
MQTT checks, common failure modes, firmware flashing status, and an architecture
diagram. Mark unverified hardware procedures as deferred rather than inventing
commands.

## 5. Comments
Add concise rationale comments only where purpose or non-obvious behavior needs
explanation. Do not add comments that restate code.
```

### Verify
- `docker compose up --build` starts clean with only Edge Athlete services and names.
- From a browser console, an `mqtt.js` client connected to `ws://<pi-ip>:9001` receives a message published with `mosquitto_pub -t edgeathlete/node/test/pulse -m '{}'`.
- Only ONE MQTT listener service exists in `docker-compose.yml`.

### ✅ Phase 1 Exit Checklist — COMPLETE (2026-07-06)
- [x] `docker compose up --build` starts clean with Edge Athlete identities
- [x] `mosquitto.conf` has both the 1883 and 9001 (websockets) listeners; 9001 exposed in compose
- [x] Browser `mqtt.js` client on `ws://<pi-ip>:9001` receives a test publish
- [x] Exactly one MQTT listener service exists in `docker-compose.yml`
- [x] `RUNBOOK.md` exists and covers all services + start/stop
- [x] `.env` gitignored, `.env.example` committed

**Phase 1 complete.** The broker has a 9001 WebSocket listener, the stack has one
inbound MQTT subscriber, and only Django runs migrations at startup. Proceed to Phase 2.

---

## Phase 2 — Data Models & Migrations

### Goal
Define the seven core domain models. The monitoring outbox model is added later.

### Prompt to paste into Claude
```
Working directory: django/event_handler/. Read the current models and migrations first.

Define these seven core domain models in django/event_handler/models.py.

Node:
  node_id           CharField(max_length=255, unique=True)
  rack_number       IntegerField(null=True, blank=True)
  mount_type        CharField(max_length=10, choices=[("bar","Bar"),("waist","Waist"),("wrist","Wrist")], default="bar")
  firmware_version  CharField(max_length=50, null=True, blank=True)
  battery_level     IntegerField(null=True, blank=True)
  signal_strength   IntegerField(null=True, blank=True)
  last_seen         DateTimeField(null=True, blank=True)
  is_active         BooleanField(default=True)

RackScreen (the physical screen device's own identity, separate from Node):
  device_id    CharField(max_length=255, unique=True)   # client-generated (crypto.randomUUID())
  rack_number  IntegerField(null=True, blank=True)       # null = awaiting coach assignment
  last_seen    DateTimeField(auto_now=True)

Athlete:
  name        CharField(max_length=255)
  nfc_tag_id  CharField(max_length=255, unique=True, null=True, blank=True)
  created_at  DateTimeField(auto_now_add=True)
  notes       TextField(blank=True, default="")

Program:
  athlete            ForeignKey(Athlete, on_delete=CASCADE, related_name="programs")
  exercise           CharField(max_length=255)
  target_sets        IntegerField()
  target_reps        IntegerField()
  target_weight_lbs  FloatField()
  velocity_zone_min  FloatField()
  velocity_zone_max  FloatField()

Session:
  label       CharField(max_length=255)
  started_at  DateTimeField(auto_now_add=True)
  ended_at    DateTimeField(null=True, blank=True)
  athletes    ManyToManyField(Athlete, related_name="sessions")
  notes       TextField(blank=True, default="")

Set:
  session         ForeignKey(Session, on_delete=CASCADE, related_name="sets")
  athlete         ForeignKey(Athlete, on_delete=CASCADE, related_name="sets")
  node            ForeignKey(Node, on_delete=SET_NULL, null=True, blank=True, related_name="sets")
  exercise        CharField(max_length=255)
  set_number      IntegerField()
  started_at      DateTimeField(null=True, blank=True)
  ended_at        DateTimeField(null=True, blank=True)
  reps_completed  IntegerField(default=0)
  avg_velocity    FloatField(null=True, blank=True)
  peak_velocity   FloatField(null=True, blank=True)
  is_false_set    BooleanField(default=False)

Rep:
  set             ForeignKey(Set, on_delete=CASCADE, related_name="reps")
  rep_number      IntegerField()
  timestamp       DateTimeField()
  mean_velocity   FloatField()
  peak_velocity   FloatField()
  duration_ms     IntegerField()
  velocity_color  CharField(max_length=10)   # "green" | "yellow" | "red"

Remove obsolete sensor-alert schema and imports. Register the seven core domain models in admin.

Then run (inside the django container):
  python manage.py makemigrations event_handler
  python manage.py migrate
Copy the generated migration file back into django/event_handler/migrations/ and
commit it.
```

### Verify (Django shell)
```python
a = Athlete.objects.create(name="Test A")
p = Program.objects.create(athlete=a, exercise="Squat", target_sets=3,
    target_reps=5, target_weight_lbs=225, velocity_zone_min=0.5, velocity_zone_max=0.8)
s = Session.objects.create(label="AM Lift"); s.athletes.add(a)
n = Node.objects.create(node_id="rack_1", rack_number=1, mount_type="bar")
st = Set.objects.create(session=s, athlete=a, node=n, exercise="Squat", set_number=1)
r = Rep.objects.create(set=st, rep_number=1, timestamp="2026-01-01T00:00:00Z",
    mean_velocity=0.72, peak_velocity=0.95, duration_ms=850, velocity_color="green")
# FK chain resolves: r.set.session.athletes.first() == a
```

### ✅ Phase 2 Exit Checklist
- [ ] All seven core domain models migrated cleanly
- [ ] Django shell creates one of each and the FK chain `Athlete → Program`, `Session → Set → Rep`, `Set → Node` resolves
- [ ] `Rep` has no direct-creation endpoint anywhere (only ever via set-complete, built Phase 4)
- [ ] Zero obsolete sensor-alert schema references remain anywhere
- [ ] Migration file committed

**STOP. Review the above before moving to Phase 3.**

---

## Phase 3 — MQTT Pulse Pipeline & Node Simulator

### Goal
Finish the pulse pipeline against the new `Node` model, add a rep-payload parser (shared contract for simulator + firmware), lock the subscriber to pulse-only, and ship a `simulate_node` command so all frontend work runs without hardware.

### Prompt to paste into Claude
```
Working directory: django/event_handler/. Read parser.py, subscriber.py,
process_pulse.py, and the management commands first.

## 1. parser.py
Keep parse_pulse_payload almost as-is (it already normalizes heartbeat data).
Repoint it at pulse fields: node_id, event_type, timestamp, battery_level,
signal_strength, firmware_version.
ADD parse_rep_payload(raw_payload: bytes) -> dict returning a normalized:
  { node_id, rep_number, mean_velocity, peak_velocity, duration_ms, timestamp }
This parser is the shared payload contract for the simulator (below) and the
ESP32 firmware (Phase 9) even though reps never reach the Django subscriber.
Keep only pulse and rep payload parsers.

## 2. process_pulse.py — finish the stub
Treat the existing stub as unfinished. Rewrite process_pulse_event(payload) to
update-or-create a Node keyed on node_id, setting
battery_level, signal_strength, firmware_version, last_seen=now(), is_active=True.
It must NOT create Rep rows or write any set data. Remove obsolete event processors.

## 3. subscriber.py — pulse only
Rewire on_connect to subscribe to exactly ONE topic: `edgeathlete/node/+/pulse`
(single-level wildcard). on_message: parse with parse_pulse_payload, hand to
process_pulse_event. The Django subscriber must NEVER subscribe to any /rep topic.
Set MQTT_HOST default "mosquitto", MQTT_PORT default 1883.

## 4. Enforce one subscriber command
Keep `run_mqtt_subscriber.py` as the only inbound MQTT subscriber command.

## 5. simulate_node management command
Create management/commands/simulate_node.py:
  Args: --mode (monitoring|rack), --racks, --rack, --interval, --rest,
        --reps-per-set, --sets, --continuous, --max-cycles, --seed
  Behavior: refuse to run unless `SIMULATOR_ENABLED=True`, connect to the broker
  (paho-mqtt, host from MQTT_HOST env), reserve `sim-rack-*` identities, and loop:
    - publish a pulse to `edgeathlete/node/{node_id}/pulse` every ~5s:
      {node_id, event_type:"pulse", battery_level: <80-100 jitter>,
       signal_strength: <-40..-70>, firmware_version:"sim-1", timestamp: <iso now>}
    - in `rack` mode, simulate sets and publish `reps-per-set` rep messages to
      `edgeathlete/node/{node_id}/rep`, one every `interval` seconds:
      {node_id, rep_number, mean_velocity: <0.4-1.1 jitter>,
       peak_velocity: <mean+0.1..0.3>, duration_ms: <600-1100>, timestamp: <iso now>}
      then pause ~8s (rest) and start the next set with rep numbers reset to 1.
    - in `monitoring` mode, generate the same validated readings without publishing
      rep MQTT, then persist them through the shared atomic set-completion service.
  Print each publish to stdout. This is what unblocks all Sprint 2 frontend work.

```

### Verify
- `mosquitto_pub` a real pulse to `edgeathlete/node/rack_1/pulse` → the `rack_1` `Node` row updates (`last_seen`, `battery_level`).
- `simulate_node --mode rack --racks 1 --sets 1` publishes pulse and rep topics;
  afterward `Rep.objects.count() == 0` and `Set.objects.count() == 0` because the
  Django subscriber never writes rep data.
- `simulate_node --mode monitoring --racks 1 --sets 1` publishes pulses and
  persists one completed set through the shared completion service for wall and
  coach design; it does not publish rep MQTT messages.

### ✅ Phase 3 Exit Checklist
- [ ] A real pulse message updates the correct `Node` row
- [ ] `parse_rep_payload` exists and returns the exact contract above; only pulse and rep parsers remain
- [ ] Subscriber subscribes to `edgeathlete/node/+/pulse` ONLY
- [ ] `run_mqtt_subscriber.py` is the only listener command
- [ ] `simulate_node` publishes realistic rep + pulse streams, persists bounded
  simulation history for wall/coach design, and can clean up reserved records
- [ ] Rep messages are never written to Postgres by the Django subscriber

**STOP. Review the above before moving to Phase 4.**

---

# SPRINT 2 — Real-Time Backbone

## Phase 4 — Full REST API + Batch Set-Complete Write

### Goal
Build every endpoint in the REST API section, with the batch `POST /api/sets/{id}/complete/` write as the centerpiece, plus JWT-gated coach-only permissions.

### Prompt to paste into Claude
```
Working directory: django/event_handler/. JWT login/refresh are already wired in
basestation_config/urls.py via simplejwt — reuse them, do not re-add.

## serializers.py
DRF ModelSerializers for Node, RackScreen, Athlete, Program, Session, Set, Rep.
Add a RepInputSerializer (rep_number, mean_velocity, peak_velocity, duration_ms,
timestamp, velocity_color) and a SetCompleteSerializer with:
  reps_completed, avg_velocity, peak_velocity, is_false_set,
  reps = RepInputSerializer(many=True)

## permissions.py
IsCoach permission: allows the request only if request.user is authenticated
(JWT). Use it on coach-only endpoints below.

## views.py + urls.py — endpoints
Open (AllowAny):
  GET   /api/nodes/
  POST  /api/racks/register/          upsert a RackScreen by device_id, rack_number stays null if new
  GET   /api/racks/racknumber/?device_id=   return {rack_number} for polling while unassigned
  GET   /api/athletes/
  GET   /api/programs/?athlete={id}
  POST  /api/sets/                    create a Set (session, athlete, node, exercise, set_number, weight_lbs, started_at=now)
  POST  /api/sets/{id}/complete/      *** batch write, see below ***
Coach-only (IsCoach):
  PATCH /api/nodes/{node_id}/         reassign rack_number
  GET   /api/racks/unassigned/        list RackScreen rows where rack_number is null
  PATCH /api/racks/{device_id}/       assign rack_number
  POST  /api/athletes/  PATCH /api/athletes/{id}/
  POST  /api/programs/
  POST  /api/sessions/  PATCH /api/sessions/{id}/   (end = set ended_at=now)
  GET   /api/analytics/session/{id}/  aggregate: total sets, reps, avg velocity per athlete
  GET   /api/analytics/athlete/{id}/  velocity trend across that athlete's sets

## The batch write — POST /api/sets/{id}/complete/
Body:
  { "reps_completed": int, "avg_velocity": float, "peak_velocity": float,
    "is_false_set": bool,
    "reps": [ {rep_number, mean_velocity, peak_velocity, duration_ms,
               timestamp, velocity_color}, ... ] }
Effect, inside a SINGLE transaction.atomic():
  1. Validate with SetCompleteSerializer.
  2. Rep.objects.bulk_create([...]) — ALL reps in one query, set FK = this Set.
  3. Update the Set: reps_completed, avg_velocity, peak_velocity, is_false_set,
     ended_at=now().
  4. If is_false_set is True: still record the Set as false, create NO reps.
  5. Create one MonitoringEvent revision for the completed set.
Return the updated Set (200). This is the ONLY code path that creates Rep rows.

No premature abstraction — don't build analytics helpers you don't call.
```

### Verify (curl, through nginx)
```bash
# get a token
curl -sX POST localhost:8081/api/auth/login/ -d 'username=coach&password=...' | jq .access
# full lifecycle
curl -sX POST localhost:8081/api/sessions/ -H "Authorization: Bearer $T" ...       # create session
curl -sX POST localhost:8081/api/sets/ -d '{...}'                                   # create set (open)
curl -sX POST localhost:8081/api/sets/1/complete/ -d '{"reps":[...5 reps...],...}'  # batch write
# Rep.objects.count() == 5 after ONE complete call; check it was one bulk_create
curl -sX PATCH localhost:8081/api/nodes/rack_1/ -d '{"rack_number":2}'              # 401 without token
# rack screen registration + assignment
curl -sX POST localhost:8081/api/racks/register/ -d '{"device_id":"abc123"}'       # 200, rack_number null (open)
curl -sX GET  'localhost:8081/api/racks/racknumber/?device_id=abc123'                    # {rack_number: null}
curl -sX PATCH localhost:8081/api/racks/abc123/ -H "Authorization: Bearer $T" -d '{"rack_number":3}'
curl -sX GET  'localhost:8081/api/racks/racknumber/?device_id=abc123'                    # {rack_number: 3}
```

### ✅ Phase 4 Exit Checklist
- [ ] Full lifecycle via curl: create session → create set → complete set with 5 reps in ONE POST → `Rep.objects.count()` matches, created by a single `bulk_create`
- [ ] `complete/` runs in one `transaction.atomic()`; false set records the set and creates zero reps
- [ ] Coach-only endpoints return 401 without a token; open endpoints work without one
- [ ] Rack registration + assignment-polling round-trip works: register (open) → unassigned shows null → coach PATCH assigns → poll reflects the new rack_number

**STOP. Review the above before moving to Phase 5.**

---

## Phase 5 — Durable MonitoringEvent Outbox

### Goal
Deliver committed room-state revisions without coupling broker availability to the set-completion request.

### Implemented behavior

- The set-completion transaction updates the `Set`, bulk-creates all `Rep` rows, and creates one pending `MonitoringEvent` revision atomically.
- `publish_monitoring_events` drains pending revisions in order and publishes privacy-safe events to retained QoS 1 topic `edgeathlete/dashboard/state`.
- An event is marked published only after the broker acknowledges it. Failed or unacknowledged events remain pending and the worker retries them.
- The wall and coach clients validate the event and refetch their role-appropriate REST snapshot only for a revision newer than the snapshot they hold. Duplicate and older revisions are ignored.
- Rack-specific publishing remains deferred with the rack-tablet UI/PWA.

### Verify
- `python manage.py test` covers completed-set/outbox creation, retained QoS 1 publication, broker acknowledgment, pending failures, and revision order. The shared completion service supplies the transaction boundary.
- `npm test -- --run` covers monitoring-event validation and reconciliation only for increasing revisions, including duplicate and stale revisions.
- Broker-outage retry and two-second browser reconciliation remain end-to-end deployment checks; automated unit tests do not establish those claims.

### ✅ Phase 5 Exit Checklist
- [x] Set completion creates its `MonitoringEvent` in the same transaction as the completed set and reps
- [x] The publisher uses retained QoS 1 `edgeathlete/dashboard/state` and marks events only after acknowledgment
- [x] Failed and unacknowledged publishes remain pending for retry
- [x] Wall and coach clients ignore duplicate or stale revisions and refetch REST for newer revisions
- [ ] Broker-outage retry and two-second reconciliation verified end to end

**STOP. Review the above before moving to Phase 6.**

---

## Phase 6 — Rack Tablet UI/PWA (Deferred)

The rack-tablet UI and installable PWA are not included in this handoff. The current frontend provides only the wall dashboard, authenticated coach workspace, and connection test. Rack-tablet requirements, persistence, installation behavior, and validation must be specified and implemented in a future phase.

---

# SPRINT 3 — First Vertical Slice + Handoff

## Phase 7 — Rack Screen End-to-End (Deferred)

The end-to-end rack workflow depends on the deferred rack-tablet frontend and is not part of this handoff. Define fresh acceptance criteria against the current API before implementation.

---

## Phase 8 — Team Dashboard Kiosk

### Goal
Build the base station's own kiosk display — the read-only room scoreboard — subscribing to `edgeathlete/dashboard/state`.

### Prompt to paste into Claude
```
Working directory: react/src/. The read-only `/dashboard` route is selected by
`App.jsx` and rendered by `Dashboard.jsx`.

## Sections (per the product's dashboard scope)
1. Rack status grid — one tile per rack, color-coded green/yellow/red using the
   SAME velocity color system used everywhere else. Updates from the REST snapshot
   after a dashboard revision invalidation.
2. Live leaderboard — athletes ranked by best saved set average velocity. A
   `room_state_changed` event triggers a REST snapshot reconciliation.
3. Fun facts / insights — VISUALLY PROMINENT (bigger than in earlier drafts).
   Rotating room insights (e.g. "fastest rep of the session", "most reps").
4. Summary block — room-wide session stats (total sets, total reps, athletes active).
5. Measured room records — fastest saved set, highest saved peak, and most reps.
   Unsupported fatigue/readiness/form/load guidance must not appear.

Subscribe once on mount; validate increasing revisions and refetch REST. Preserve
the last valid snapshot during reconnects and mark it stale after 15 seconds.
Kiosk styling: large type, high contrast, readable across a room. No interactivity.

## Boot-time kiosk launch
Extend `edgeathlete.service`: after the Docker stack step, add (a) a wait/retry loop
that polls the dashboard URL until it responds, then (b) launch Chromium in
kiosk mode against it: `chromium-browser --kiosk --app=http://localhost:8081/dashboard
--noerrdialogs --disable-infobars`. This is what actually makes the base
station boot into the dashboard; frontend routing alone does not launch Chromium.
```

### Verify
- Completing a simulated persisted set updates the rack status grid within 2s and moves the leaderboard.
- Coach alerts render in their own visually separated section.
- Rebooting the Pi lands directly on the fullscreen dashboard with no manual steps.

### ✅ Phase 8 Exit Checklist
- [ ] Rack status grid updates within 2s of a simulated set completing
- [ ] Leaderboard, fun-facts/insights (prominent), and summary block all update live
- [ ] Coach alerts render in their own separated section
- [ ] Read-only, no login, kiosk-legible
- [ ] A cold reboot of the Pi auto-launches the dashboard fullscreen with no manual steps via `edgeathlete.service`

**STOP. Review the above before moving to Phase 9.**

---

## Phase 9 — Real ESP32 Firmware v1

### Goal
Replace the simulator with real hardware: MPU-6050 velocity computation on-device, a 0.75s-stillness rep boundary, and MQTT publish matching the `parse_rep_payload` contract from Phase 3.

### Prompt to paste into Claude
```
Working directory: esp32/edge_athlete_node/. This is Arduino/C++ for ESP32 + MPU-6050.

## Behavior
- Connect to the Pi's AP (SSID/pass as #define constants for now).
- MQTT connect to the broker at the Pi's IP, port 1883.
- Read the MPU-6050 accelerometer in a tight loop; compute velocity on-device by
  integrating acceleration over the movement (start simple — single-axis vertical
  velocity is fine for v1). NEVER publish raw accelerometer samples.
- Rep boundary: 0.75 SECONDS of stillness (accel magnitude below a threshold)
  closes the current rep. On rep close, publish ONE message to
  edgeathlete/node/{node_id}/rep with EXACTLY this shape (matches parse_rep_payload):
    {node_id, rep_number, mean_velocity, peak_velocity, duration_ms, timestamp}
- Publish a pulse every ~5s to edgeathlete/node/{node_id}/pulse:
    {node_id, event_type:"pulse", battery_level, signal_strength, firmware_version, timestamp}
- node_id is a compile-time constant per node for v1.
- Leave a clearly marked hook for noise reduction (this is UNDECIDED — ESP32 vs.
  rack screen; whichever gets built first wins; do not block on it).

```

### Verify
- A physical barbell rep produces exactly one `rep` MQTT message with a plausible velocity value (`mosquitto_sub -t 'edgeathlete/node/+/rep' -v`).
- Rack-screen display verification is deferred until the Phase 6/7 rack UI exists.
- Pulse messages update the node's `Node` row via the Django subscriber.

### ✅ Phase 9 Exit Checklist
- [ ] A physical rep produces one `rep` message with a plausible velocity
- [ ] Payload shape exactly matches `parse_rep_payload`
- [ ] Rack-screen display verified after the deferred rack UI is implemented
- [ ] Pulse updates the `Node` row
- [ ] Noise-reduction hook clearly marked, not implemented

**STOP. Do not continue past the handoff gate until it fully passes.**

---

## Sprint 3 Handoff Gate

All handoff checks must pass.

- [ ] `RUNBOOK.md` complete: start/stop, MQTT checks, common failures, architecture, and an explicit firmware-flashing deferral until hardware instructions are verified
- [ ] Architecture diagram present (Mermaid, in `RUNBOOK.md`) showing nodes → broker → Django/Postgres and broker → browser clients over WS
- [ ] An observe-only dry run of the full session flow
- [ ] Firmware flashing completed after the board/toolchain procedure is verified; each contributor has run the integration test once

**STOP. Do not continue until the handoff is complete.**

---

# SPRINTS 4–6 — Team Alone (lighter detail — full treatment closer to start)

These phases are intentionally lighter. A lot will shift across Phases 1–9; each of these gets expanded to full paste-ready depth at the start of its sprint.

## Phase 10 — Coach Tablet (one page)
The `/coach` route uses `Dashboard.jsx` in coach mode with a JWT login gate, REST snapshots, and MQTT revision reconciliation. It provides read-only room monitoring, athlete history, programs, and versioned coach notes; rack assignment and other administrative mutation workflows remain deferred.

**Room layout assignment (deferred):** the current coach workspace does not assign rack screens or nodes. The existing rack and node endpoints can support a future assignment workflow after the rack-tablet requirements are defined.

## Phase 11 — Fatigue Scaffold
`django/event_handler/ml/inference.py` with a REAL function signature (e.g. `predict_fatigue(set_summary: dict) -> dict`) and a real call site firing after set-complete (Phase 4/5). Returns a **stub** value. Not a trained model — training is explicitly out of scope.

## Phase 12 — Security Hardening
Verify JWT covers all coach-only endpoints (should already be true from Phase 4). Move Mosquitto off `allow_anonymous true` to ACLs/auth on both listeners. Rate-limit login. Confirm no coach-only path is reachable unauthenticated.

## Phase 13 — Firmware Hardening & Additional Mounts
Waist and wrist mount thresholds, WiFi reconnect logic, enclosure v1. Resolve (or keep hooked) the noise-reduction location decision.

## Phase 14 — Full Integration Test & Demo Prep
Seed script, one-command `start.sh`, `DEMO_SCRIPT.md`, screen-recording backup. The full session script must run clean at least twice in a row before demo day.

---

## Stretch Goals / Explicitly Deferred (only after all phases complete)

Don't let these block a phase — they're intentionally punted:

- **Noise-reduction location** (ESP32 firmware vs. rack screen) — leave a hook on both sides; whichever gets built first wins.
- **Real trained fatigue model** — Phase 11 is a scaffold only.
- **Coach tablet multi-page expansion** (separate Room / Athletes / Racks / Analytics tabs).
- **Consumer "One Device" mode / PvP BLE mode** — not in this spec at all.
- **3D bar-path tracing** — future hardware, not this project.
