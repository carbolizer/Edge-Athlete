# Spec: Edge Athlete — Real-Time Barbell Velocity Tracking — v1
**Stack:** Django (sync `runserver`, DRF) + React (Vite) + PostgreSQL + Mosquitto (MQTT) + Nginx, all in Docker | **Hardware:** Raspberry Pi base station (owns a private WiFi AP) + ESP32 + MPU-6050 sensor nodes | **Served by:** the Pi, no internet, no cloud, no subscription | **Environment:** macOS dev host → deploy target is Raspberry Pi OS (arm64) | **Team:** 4 people | **Timeline:** 6 sprints × 2.5 weeks

## Agent tool compatibility
This file is the project's agent-instructions file regardless of which tool you're running. **Claude Code:** treat this as `CLAUDE.md`. **opencode:** treat this as `AGENTS.md`. Either rename/symlink it accordingly in your own checkout, or just point your tool at this file directly — don't fork a second copy of the instructions.

## IMPORTANT
When doing scaffolding and file-admin work use a more efficient model like **Haiku**. Use **Opus** as the default for the large majority of implementation work. Reach for **Fable** (interchangeably with Opus) on the highest-stakes logical work: rep-detection tuning, MQTT topic routing, auth/security. See **Working Style → Model routing**.

This document is the single source of truth for what Edge Athlete is and how it gets built. It converts an earlier looser context doc into spec-driven form. If anything else in this repo — or in the Privacy-Dots-V2 reference — contradicts this file, **this file wins.**

---

## How to Use This Document

Work through each phase in order. **Do not proceed to the next phase until the current one is complete and its exit checklist passes.** Each phase ends with an explicit STOP and a checklist. Paste only the prompt for the current phase into a fresh Claude conversation — do not share future phases ahead of time.

When a prompt says "read the reference project," that means use your file tools to inspect the Privacy-Dots-V2 repo's contents before writing any code. Do not guess at structure or config — derive it from what you actually find. The reference lives beside this repo (upstream: `git@github.com:devi-walto/Privacy-Dots-V2.git`); it stays **read-only**.

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
3. A **rack screen** (tablet PWA) subscribes over MQTT-over-WebSockets to its linked node's rep topic. As each rep arrives it buffers the rep in IndexedDB and live-updates its UI.
4. When the set ends (0.75s stillness on the node closes the last rep; the athlete/coach confirms end on the screen), the rack screen batch-POSTs the whole set — summary + every rep — to the base station in one request.
5. The base station writes that one set (and its reps) to Postgres in a single transaction, then publishes broadcast events to Mosquitto: leaderboard changes, rack-state changes, and coach alerts.
6. The **team dashboard** (the Pi's own kiosk browser) and the **coach tablet** subscribe to their broadcast topics and update live — a room-wide scoreboard and a single coach admin view.

---

## Architecture Decisions

These are intentional, locked decisions. Several are deliberate divergences from the Privacy-Dots-V2 reference. **If you are an agent reading this, do not override these decisions by mirroring the reference project.** They were the open questions that blocked this spec; they are recorded here so nobody re-litigates them three sprints from now without knowing why.

### One transport for everything: MQTT (raw + over WebSockets)
Every live-update path — node → rack screen, base station → rack/coach/dashboard screens — runs over MQTT. Hardware and Django speak plain MQTT on port **1883** (exactly like Privacy-Dots-V2 does today). All three browser clients speak **MQTT over WebSockets** on port **9001** using `mqtt.js`, against the same Mosquitto broker.

Rationale: the earlier plans assumed a Django Channels/ASGI WebSocket layer that **does not exist** in the reference repo (it runs plain sync `runserver` + REST polling). Standing up Channels would have been the single largest net-new infrastructure item in the project. Publishing events to Mosquitto instead — Django already ships `paho-mqtt` — gets live push for free. The rejected ESP32-runs-its-own-web-server alternative also loses: it forces an unfamiliar `ESPAsyncWebServer` pattern plus a node-IP-discovery problem on every reassignment, which topic subscription solves for free. **No Channels, no ASGI, no web/WebSocket server on the ESP32.**

### The base station only ever writes set-level data to Postgres, never per-rep
Only set-level data crosses into Postgres — **one write per completed set**, not one per rep. The Pi runs the entire stack (broker, web server, database, static hosting) on modest hardware; per-rep writes across many racks are needless load for data that doesn't need per-rep durability. Only the final set summary does.

### The rack screen is the durability boundary, not the base station
The rack screen buffers every rep it receives (over MQTT-over-WS) into IndexedDB as it arrives, live-updates its own UI immediately, and POSTs the full buffered set to the base station in **one batch** when the set ends. This beats buffering in Django's memory: a browser tab surviving a WiFi drop is a much better bet than a Django process surviving a restart with unflushed sets for every active rack in memory. **Accepted failure mode:** if a specific tab crashes or the screen loses power mid-set, that one rack's current set is lost — isolated to that rack, not the whole room. Do not try to solve this in this spec.

### MQTT topic scheme is namespaced under `edgeathlete/`
This resolves an old naming conflict between reference docs (`edgeathlete/*` vs. `rack/{n}/*`). See **Real-Time Layer Reference** for the full table. Key rule: **Django's MQTT subscriber listens ONLY to `edgeathlete/node/+/pulse`** — rep topics never reach Django/Postgres at runtime. Node reassignment = the rack screen resubscribes to a different node topic string. No IP lookup, no socket teardown.

### Six sprints, 2.5 weeks each; Devin is present for Sprints 1–3 only
Not 8 sprints, not exit-after-4 — those earlier numbers are wrong. Six sprints, full team for 1–3, team alone for 4–6. Sprint 3 ends with a formal handoff (RUNBOOK + Mermaid architecture diagram + an observe-only dry run), after which Devin exits.

### Coach tablet is one page for this spec
The full vision (separate Room / Athletes / Racks / Analytics tabs) is deferred. This spec builds a single consolidated admin view: live room state, abnormal-performance alerts/suggestions, and basic graphs. Multi-page expansion is future work.

### Local fatigue ML is scaffolded, not trained
Fatigue detection gets a real interface (`ml/inference.py`) and a real call site (fires after set-complete), but the function returns a stub value in this spec. Training a real model is explicitly out of scope.

### Fresh start in the Edge-Athlete repo
Do **not** rename or port Privacy-Dots-V2's git history. Privacy-Dots-V2 stays untouched as a read-only reference; Edge Athlete is bootstrapped clean, pulling **patterns (not history)** from the reference.

---

## Coding Standards (for every file written in this repo)

These rules apply to all code from Phase 1 onward. They will later be copied into per-directory `CLAUDE.md` files as a follow-up task — until those files exist, **this section is their source of truth.**

- **Every source file opens with a short comment (2–4 lines) explaining WHY the file exists** — its purpose, not a line-by-line description of what it does. A short plain-language analogy earns bonus points. Write it so a complete beginner understands the file's purpose with no prior context.
  > Example:
  > `// This file is the mail carrier for rep data — it doesn't decide what a`
  > `// rep means, it just makes sure each one gets from the sensor to the`
  > `// screen without getting lost.`
- **Inline comments are rare and short** — only the non-obvious "why," never the obvious "what." If a comment just restates the code, delete it.
- **No premature abstraction.** If a later phase doesn't need it, don't build it now. Don't build for a phase that isn't here yet.

---

## What Carries Over From Privacy-Dots-V2 (reuse, don't rewrite)

Read the reference repo to get these exactly right. Rename `privacydots-*` service/container prefixes to `edgeathlete-*` throughout.

| Privacy-Dots-V2 piece | Edge Athlete fate |
|---|---|
| `docker-compose.yml` structure, `.env` / `.env.example` pattern | Reuse directly; rename service/container prefixes `privacydots-*` → `edgeathlete-*`, DB name and keys to `edgeathlete`. |
| `mosquitto/mosquitto.conf` (currently `listener 1883` only) | Reuse and **add a second WebSockets listener on 9001** (see Real-Time Layer Reference). |
| WiFi AP setup bash script (configures the Pi's onboard WiFi device into AP mode) | Reuse as-is. Already solved in the reference — don't re-implement or re-research this in Phase 1, just copy it over and adjust naming/SSID as needed. |
| `privacy-dots.service` (systemd unit that launches the Docker stack on boot) | Reuse and **extend**, don't replace. This becomes the base station's kiosk-launch mechanism too — add a "wait until the dashboard responds" step, then a kiosk-mode browser launch, either appended to this same unit or as a second unit with `After=privacy-dots.service`. See Phase 8. |
| `django/basestation_config/` (settings, urls, wsgi, asgi) | Reuse; rename app references. `urls.py` already wires `simplejwt` `TokenObtainPairView` at `/api/auth/login/` and refresh at `/api/auth/refresh/` — reuse as-is. |
| `django/event_handler/` app | **Keep the app name** — gut its contents. Renaming is unnecessary churn; "handles events" still fits. |
| `Device` model | Rename to `Node`; extend with `mount_type`, `rack_number` (see Data Models). |
| `MotionEvent` model | **Delete.** Replaced by `Athlete` / `Program` / `Session` / `Set` / `Rep`. |
| `notification_flow/mqtt_ingester/parser.py` | Reuse `parse_pulse_payload` nearly as-is (already normalizes heartbeat data cleanly). **Add `parse_rep_payload`. Delete `parse_motion_payload`.** |
| `notification_flow/event_processor/process_pulse.py` | Header still reads `# TODO: @Brayd-n implement`. **Treat it as unfinished** — finish/verify it in Phase 3 against the new `Node` model; do not assume it's done. Also delete `process_motion.py`. |
| `notification_flow/mqtt_ingester/subscriber.py` | Reuse the connect/subscribe/route pattern. Rewire it to subscribe to **`edgeathlete/node/+/pulse` only** — reps never reach Django's subscriber. |
| `management/commands/run_mqtt_subscriber.py` **and** `start_mqtt_listener.py` | **Reference bug:** `docker-compose.yml` runs BOTH (`mqtt-listener` service runs `run_mqtt_subscriber`; `mosquitto-subscriber` service runs `start_mqtt_listener`), double-subscribing to the same topics. **Keep exactly one** — `run_mqtt_subscriber` — and delete `start_mqtt_listener.py` and the `mosquitto-subscriber` service. |
| JWT auth (`djangorestframework-simplejwt`, already installed & wired) | Reuse directly for coach login. |
| `django-cors-headers` | Reuse. |
| `nginx/nginx.conf` `/api/`, `/admin/`, `/static/*` proxy blocks | Reuse as-is. **No WebSocket proxy block needed** — browsers hit Mosquitto's `9001` listener directly, same pattern as the existing `1883:1883` mapping. |
| `ntfy` container | Optional. Keep only as an ops-alert channel independent of in-app coach alerts; not required for the core product. |
| React `Dashboard.jsx` 5-second polling pattern | **Delete** — replaced by MQTT-over-WS push. |
| PIR / motion firmware (`esp32/privacy_dots_node/`) | **Delete/replace** with the MPU-6050 firmware in Phase 9. |

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
Expose both in `docker-compose.yml`, same pattern as today's `1883:1883` — no Nginx proxy needed:
```yaml
mosquitto:
  ports:
    - "1883:1883"
    - "9001:9001"
```
Anonymous access is fine through Sprint 3. Broker auth/ACLs are a Sprint 5 hardening item (Phase 12), not a demo blocker.

### Topics — all namespaced under `edgeathlete/`

**Published by the node (plain MQTT, port 1883):**

| Topic | Fires | Payload |
|---|---|---|
| `edgeathlete/node/{node_id}/rep` | once per completed rep | `{node_id, rep_number, mean_velocity, peak_velocity, duration_ms, timestamp}` |
| `edgeathlete/node/{node_id}/pulse` | every ~5s | `{node_id, event_type:"pulse", battery_level, signal_strength, firmware_version, timestamp}` |

**Published by Django (plain MQTT; browsers consume over WS, port 9001):**

| Topic | Fires | Payload |
|---|---|---|
| `edgeathlete/rack/{rack_number}/state` | athlete checked in, node reassigned, queue changed, coach override, set complete | `{type, ...event-specific fields}` |
| `edgeathlete/dashboard/state` | leaderboard / session / insight changes | `{type, ...}` |
| `edgeathlete/coach/state` | fatigue alert, session-wide events | `{type, ...}` |

**Subscribed by each client:**

| Client | Subscribes to |
|---|---|
| Rack screen | `edgeathlete/node/{current_linked_node_id}/rep`, `edgeathlete/rack/{its_rack_number}/state` |
| Team dashboard | `edgeathlete/dashboard/state` |
| Coach tablet | `edgeathlete/coach/state` |
| Django subscriber | `edgeathlete/node/+/pulse` **only** — never rep topics |

---

## Data Models (extend the reference's Postgres schema)

Seven models. All live in `django/event_handler/models.py`.

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
             exercise, set_number (Int), weight_lbs (Float, nullable), started_at, ended_at (nullable),
             reps_completed (Int, default 0), avg_velocity (Float, nullable),
             peak_velocity (Float, nullable), is_false_set (Bool, default False)
Rep        — set (FK→Set), rep_number (Int), timestamp, mean_velocity (Float),
             peak_velocity (Float), duration_ms (Int), velocity_color (Char)
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
│       ├── models.py             # Node, RackScreen, Athlete, Program, Session, Set, Rep
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
│       ├── notification_flow/
│       │   ├── mqtt_ingester/
│       │   │   ├── parser.py            # parse_pulse_payload + parse_rep_payload
│       │   │   └── subscriber.py        # subscribes edgeathlete/node/+/pulse ONLY
│       │   ├── event_processor/
│       │   │   └── process_pulse.py     # finished, writes to Node
│       │   └── broadcast/
│       │       └── publisher.py         # Django → rack/dashboard/coach topics
│       └── migrations/
├── react/
│   ├── Dockerfile
│   ├── index.html
│   ├── vite.config.js
│   ├── package.json
│   ├── public/
│   │   ├── manifest.rack.json
│   │   ├── manifest.dashboard.json
│   │   ├── manifest.coach.json
│   │   └── service-worker.js
│   └── src/
│       ├── main.jsx
│       ├── App.jsx                      # root "/" device-role picker; routes to /rack/:n, /coach, /dashboard once role+id are known
│       ├── mqtt/client.js               # mqtt.js over ws://<pi>:9001
│       ├── db/repBuffer.js              # IndexedDB rep buffer
│       ├── api/client.js                # REST client (batch POST lives here)
│       ├── rack/                        # RackScreen + subcomponents
│       ├── coach/                       # CoachTablet (one page)
│       └── dashboard/                   # TeamDashboard kiosk
└── esp32/
    └── edge_athlete_node/
        └── edge_athlete_node.ino        # MPU-6050, 0.75s-stillness rep boundary
```

---

# SPRINT 1 — Foundation

## Phase 1 — Repo Bootstrap, Broker WS Upgrade & RUNBOOK · Owner: Devin

### Goal
Bootstrap the Edge Athlete stack from Privacy-Dots-V2 patterns (not history), fix the reference's duplicate-listener bug, add the WebSocket broker listener, and start the RUNBOOK the Sprint 3 handoff depends on.

### Prompt to paste into Claude
```
Read the reference project Privacy-Dots-V2 (read-only, sibling directory) before
writing anything. We are bootstrapping a FRESH repo — do NOT copy its git history.

Working directory: the Edge-Athlete repo root.

## 1. Copy + rename infrastructure from the reference
Bring over and adapt these files, renaming every "privacydots"/"privacy_dots"
reference to "edgeathlete":
- docker-compose.yml
- mosquitto/mosquitto.conf
- nginx/nginx.conf   (keep the /api/, /admin/, /static/admin/, /static/rest_framework/, and / blocks as-is)
- .env.example  (committed) and .env (gitignored — add to .gitignore)
- django/Dockerfile, django/manage.py, django/requirements.txt,
  django/basestation_config/{settings.py,urls.py,wsgi.py,asgi.py}
- react/Dockerfile, react/index.html, react/vite.config.js, react/package.json
Rename all container_name values privacydots-* → edgeathlete-*. Rename the
Postgres DB / user env keys to edgeathlete.

## 2. Fix the duplicate MQTT listener bug (reference bug — call it out)
The reference docker-compose.yml runs TWO listener services that double-subscribe:
  - "mqtt-listener" runs `python manage.py run_mqtt_subscriber`
  - "mosquitto-subscriber" runs `python manage.py start_mqtt_listener`
Keep EXACTLY ONE. Keep the `mqtt-listener` service running `run_mqtt_subscriber`.
Delete the `mosquitto-subscriber` service. (The start_mqtt_listener.py command
file is deleted in Phase 3 when we gut the app.)

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
    - "1883:1883"
    - "9001:9001"
Do NOT add an Nginx WebSocket proxy — browsers hit 9001 directly.

## 4. Start RUNBOOK.md
Create RUNBOOK.md at repo root. Sections (fill what's known now, leave TODO
markers for the rest): Services (one line each: postgres, mosquitto, django,
mqtt-listener, react, nginx — port + purpose), Start/Stop procedure, Config
files and where they live, MQTT test commands, Common failure modes (TODO),
Firmware flashing (TODO — Phase 9), Architecture diagram (TODO — Sprint 3).

## 5. File-purpose comments
Every file you create or meaningfully change gets a 2-4 line top comment
explaining WHY it exists (a beginner-readable analogy is a bonus). Not a
line-by-line description.

Every source file opens with a short WHY comment (see coding standards).
```

### Verify
- `docker compose up --build` starts clean; **zero** `privacydots` references remain (`grep -ri privacydots .` returns nothing outside the reference repo).
- From a browser console, an `mqtt.js` client connected to `ws://<pi-ip>:9001` receives a message published with `mosquitto_pub -t edgeathlete/node/test/pulse -m '{}'`.
- Only ONE MQTT listener service exists in `docker-compose.yml`.

### ✅ Phase 1 Exit Checklist — COMPLETE (2026-07-06)
- [x] `docker compose up --build` starts clean, no `privacydots` references remain
- [x] `mosquitto.conf` has both the 1883 and 9001 (websockets) listeners; 9001 exposed in compose
- [x] Browser `mqtt.js` client on `ws://<pi-ip>:9001` receives a test publish
- [x] Exactly one MQTT listener service in `docker-compose.yml`; `mosquitto-subscriber` service gone
- [x] `RUNBOOK.md` exists and covers all services + start/stop
- [x] `.env` gitignored, `.env.example` committed
- [x] Every new/changed file has a WHY comment

**Phase 1 complete.** Bootstrap ported from Privacy-Dots-V2; broker upgraded with a
9001 websockets listener, duplicate `mosquitto-subscriber` service removed, and the
listener's redundant `migrate` dropped to fix a boot-time migration race. Django
models / REST / React and the MQTT subscriber remain the ported motion+pulse shape —
reshaped to spec in Phases 2–4 (subscriber → pulse-only in Phase 3). Proceed to Phase 2.

---

## Phase 2 — Data Models & Migrations · Owner: Carl

### Goal
Replace the reference's `Device`/`MotionEvent` schema with the seven Edge Athlete models. No endpoints yet — models + migrations + a shell-verified FK chain.

### Prompt to paste into Claude
```
Working directory: django/event_handler/. Read the reference models.py first.

Rewrite django/event_handler/models.py to define exactly these seven models. Open
the file with a 2-4 line WHY comment (beginner-readable analogy encouraged).

Node (rename of the reference `Device`):
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

Delete the MotionEvent model entirely. Delete any lingering MotionEvent imports.
Update admin.py to register the seven new models and unregister Device/MotionEvent.

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
- [ ] All seven models migrated cleanly
- [ ] Django shell creates one of each and the FK chain `Athlete → Program`, `Session → Set → Rep`, `Set → Node` resolves
- [ ] `Rep` has no direct-creation endpoint anywhere (only ever via set-complete, built Phase 4)
- [ ] Zero `MotionEvent` and zero `Device` references remain anywhere
- [ ] Migration file committed

**STOP. Review the above before moving to Phase 3.**

---

## Phase 3 — MQTT Pulse Pipeline & Node Simulator · Owner: Derrilon

### Goal
Finish the pulse pipeline against the new `Node` model, add a rep-payload parser (shared contract for simulator + firmware), lock the subscriber to pulse-only, and ship a `simulate_node` command so all frontend work runs without hardware.

### Prompt to paste into Claude
```
Working directory: django/event_handler/. Read the reference parser.py,
subscriber.py, process_pulse.py, and the two management commands first.

## 1. parser.py
Keep parse_pulse_payload almost as-is (it already normalizes heartbeat data).
Repoint it at pulse fields: node_id, event_type, timestamp, battery_level,
signal_strength, firmware_version.
ADD parse_rep_payload(raw_payload: bytes) -> dict returning a normalized:
  { node_id, rep_number, mean_velocity, peak_velocity, duration_ms, timestamp }
This parser is the shared payload contract for the simulator (below) and the
ESP32 firmware (Phase 9) even though reps never reach the Django subscriber.
DELETE parse_motion_payload.

## 2. process_pulse.py — finish the stub
The header says `# TODO: @Brayd-n implement` — treat it as UNFINISHED. Rewrite
process_pulse_event(payload) to update-or-create a Node keyed on node_id, setting
battery_level, signal_strength, firmware_version, last_seen=now(), is_active=True.
It must NOT create Rep rows or write any set data. Delete process_motion.py.

## 3. subscriber.py — pulse only
Rewire on_connect to subscribe to exactly ONE topic: `edgeathlete/node/+/pulse`
(single-level wildcard). on_message: parse with parse_pulse_payload, hand to
process_pulse_event. The Django subscriber must NEVER subscribe to any /rep topic.
Set MQTT_HOST default "mosquitto", MQTT_PORT default 1883.

## 4. Delete the duplicate command
Delete management/commands/start_mqtt_listener.py (the compose service that ran
it was already removed in Phase 1). Keep run_mqtt_subscriber.py as the only one.

## 5. simulate_node management command
Create management/commands/simulate_node.py:
  Args: --node-id (required), --rack (int, optional), --interval (float, default 3.0),
        --reps-per-set (int, default 5)
  Behavior: connect to the broker (paho-mqtt, host from MQTT_HOST env). Loop:
    - publish a pulse to `edgeathlete/node/{node_id}/pulse` every ~5s:
      {node_id, event_type:"pulse", battery_level: <80-100 jitter>,
       signal_strength: <-40..-70>, firmware_version:"sim-1", timestamp: <iso now>}
    - simulate sets: publish `reps-per-set` rep messages to
      `edgeathlete/node/{node_id}/rep`, one every `interval` seconds:
      {node_id, rep_number, mean_velocity: <0.4-1.1 jitter>,
       peak_velocity: <mean+0.1..0.3>, duration_ms: <600-1100>, timestamp: <iso now>}
      then pause ~8s (rest) and start the next set with incrementing rep_numbers reset to 1.
  Print each publish to stdout. This is what unblocks all Sprint 2 frontend work.

Every file opens with a WHY comment.
```

### Verify
- `mosquitto_pub` a real pulse to `edgeathlete/node/rack_1/pulse` → the `rack_1` `Node` row updates (`last_seen`, `battery_level`).
- `python manage.py simulate_node --node-id rack_1 --rack 1` publishes both topics; a `mosquitto_sub -t 'edgeathlete/#' -v` terminal shows rep + pulse messages on a realistic cadence.
- After running the simulator for a minute, `Rep.objects.count() == 0` and `Set.objects.count() == 0` — the Django subscriber never wrote rep data.

### ✅ Phase 3 Exit Checklist
- [ ] A real pulse message updates the correct `Node` row
- [ ] `parse_rep_payload` exists and returns the exact contract above; `parse_motion_payload` deleted
- [ ] Subscriber subscribes to `edgeathlete/node/+/pulse` ONLY
- [ ] `start_mqtt_listener.py` deleted; `run_mqtt_subscriber` is the only listener command
- [ ] `simulate_node` publishes realistic rep + pulse streams visible in `mosquitto_sub`
- [ ] Rep messages are never written to Postgres by the Django subscriber

**STOP. Review the above before moving to Phase 4.**

---

# SPRINT 2 — Real-Time Backbone

## Phase 4 — Full REST API + Batch Set-Complete Write · Owner: Carl

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
Return the updated Set (200). This is the ONLY code path that creates Rep rows.
(Phase 5 will hook a broadcast publish onto the end of this view — leave a clearly
marked `# Phase 5: publish rack/dashboard state here` comment at the success point.)

Every file opens with a WHY comment. No premature abstraction — don't build
analytics helpers you don't call.
```

### Verify (curl, through nginx)
```bash
# get a token
curl -sX POST localhost/api/auth/login/ -d 'username=coach&password=...' | jq .access
# full lifecycle
curl -sX POST localhost/api/sessions/ -H "Authorization: Bearer $T" ...       # create session
curl -sX POST localhost/api/sets/ -d '{...}'                                   # create set (open)
curl -sX POST localhost/api/sets/1/complete/ -d '{"reps":[...5 reps...],...}'  # batch write
# Rep.objects.count() == 5 after ONE complete call; check it was one bulk_create
curl -sX PATCH localhost/api/nodes/rack_1/ -d '{"rack_number":2}'              # 401 without token
# rack screen registration + assignment
curl -sX POST localhost/api/racks/register/ -d '{"device_id":"abc123"}'       # 200, rack_number null (open)
curl -sX GET  'localhost/api/racks/racknumber/?device_id=abc123'                    # {rack_number: null}
curl -sX PATCH localhost/api/racks/abc123/ -H "Authorization: Bearer $T" -d '{"rack_number":3}'
curl -sX GET  'localhost/api/racks/racknumber/?device_id=abc123'                    # {rack_number: 3}
```

### ✅ Phase 4 Exit Checklist
- [ ] Full lifecycle via curl: create session → create set → complete set with 5 reps in ONE POST → `Rep.objects.count()` matches, created by a single `bulk_create`
- [ ] `complete/` runs in one `transaction.atomic()`; false set records the set and creates zero reps
- [ ] Coach-only endpoints return 401 without a token; open endpoints work without one
- [ ] Rack registration + assignment-polling round-trip works: register (open) → unassigned shows null → coach PATCH assigns → poll reflects the new rack_number
- [ ] `# Phase 5: publish ...` marker left at the complete-view success point
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 5.**

---

## Phase 5 — Django Broadcast Publisher · Owner: Derrilon

### Goal
Give Django a single publish helper and fire broadcast events to the rack / dashboard / coach topics on the relevant model changes, so browsers get live push without polling.

### Prompt to paste into Claude
```
Working directory: django/event_handler/notification_flow/broadcast/.

## publisher.py
Create a module-level paho-mqtt client (host MQTT_HOST env, port 1883) connected
once and reused (loop_start). Expose:
  publish_rack_state(rack_number: int, payload: dict) -> publishes to
      edgeathlete/rack/{rack_number}/state
  publish_dashboard_state(payload: dict) -> edgeathlete/dashboard/state
  publish_coach_state(payload: dict) -> edgeathlete/coach/state
Each payload is JSON with a required "type" string plus event fields. Publish is
fire-and-forget; log failures, never raise into the request path.

## Wire the publishers onto these events
1. Set complete (POST /api/sets/{id}/complete/, the Phase 4 marker):
     publish_rack_state(rack_number, {type:"set_complete", set_id, athlete,
       reps_completed, avg_velocity, peak_velocity, is_false_set})
     publish_dashboard_state({type:"leaderboard_update", ...set summary...})
2. Node reassignment (PATCH /api/nodes/{node_id}/):
     publish_rack_state(new_rack_number, {type:"node_reassigned", node_id})
3. Athlete check-in (however a Set/Session ties an athlete to a rack — publish on
   set create): publish_rack_state(rack_number, {type:"athlete_checkin", athlete, rack_number})

Import the publisher into views.py and replace the Phase 4 marker comment with
the real calls. Every file opens with a WHY comment.
```

### Verify
- `mosquitto_sub -t 'edgeathlete/rack/#' -v` and `-t 'edgeathlete/dashboard/state' -v` in two terminals.
- PATCH a node's `rack_number` → a `node_reassigned` `rack/{n}/state` message appears within 1s.
- POST a set-complete → both a `rack/{n}/state` (`set_complete`) and a `dashboard/state` (`leaderboard_update`) message appear.

### ✅ Phase 5 Exit Checklist
- [ ] `publisher.py` exposes the three publish helpers, single reused client
- [ ] Reassigning a node produces a `rack/{n}/state` message within 1s
- [ ] Completing a set produces both a `rack/{n}/state` and a `dashboard/state` message
- [ ] Publish failures are logged, never raised into the HTTP response
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 6.**

---

## Phase 6 — Rack Screen PWA Shell · Owner: Braydon

### Goal
Stand up the shared device-role picker every screen type boots into, the installable rack-screen PWA behind it (manifest, service worker, IndexedDB rep buffer, an `mqtt.js` client wired to the Phase 3 simulator), and the rack-registration/assignment-wait flow — driving a live rep counter with no real hardware. Layout logic (full flow, batch POST) comes in Phase 7.

### Prompt to paste into Claude
```
Working directory: react/. There is a starting-point layout draft at
`edge_athlete_rack_ui.html` in the wider project folder — treat it as a flow/
layout REFERENCE, not a spec to copy verbatim.

## src/App.jsx — Device Role Picker (root route "/", shared by all device types)
On load: check localStorage for `device_role`. If present, immediately swap
the page's `<link rel="manifest">` tag to that role's manifest file and
render straight into that role's view (rack screen this phase; dashboard/
coach views are stubs until Phase 8/10). If absent, render a plain three-
button picker: "Rack Tablet" / "Base Station Display" / "Coach Admin" — honor
system, no verification. On pick:
  - Save `device_role` to localStorage.
  - Swap the manifest link to the matching file (manifest.rack.json /
    manifest.dashboard.json / manifest.coach.json) so the browser's install
    flow installs the correct specialized PWA icon.
  - If role === "rack": proceed to Rack Registration below before rendering
    RackScreen.jsx. Other roles proceed straight to their (stub) view.

## Rack registration + assignment-wait state (rack role only)
On first pick of "Rack Tablet": generate a random local device_id (e.g.
`crypto.randomUUID()`) and save it to localStorage alongside device_role —
this persists across reloads/reboots so the screen never re-registers.
POST /api/racks/register/ { device_id } once.
Then poll GET /api/racks/racknumber/?device_id={id} every ~3s — this is the ONLY
polling anywhere in the system; everything else stays MQTT push.
While rack_number is null: render a plain "Waiting for coach to assign a
rack" screen that prominently displays this device's own id (or a short,
readable slice of the UUID) in large text — this is exactly what the coach
picks off of in the Phase 10 drag-and-drop assignment UI, so it must be easy
to read at a glance, not a wall of full-UUID text.
Once rack_number comes back non-null: save it to localStorage, stop polling,
and proceed into RackScreen.jsx at the rack's number as normal.

## public/manifest.rack.json
name "Edge Athlete — Rack", display "fullscreen", start_url "/",
orientation "landscape", icons + theme/background colors. (start_url is root,
not a hardcoded rack number — the picker + localStorage above determine
routing, not the URL. Note: this manifest controls how the app LOOKS once
installed and opened — it does not make a device boot into it automatically.
Actual boot-time kiosk launch is an OS-level systemd/autostart concern,
handled separately — see Phase 8 and the RUNBOOK.)

## public/service-worker.js
Cache the app shell (index.html, JS/CSS bundle) for offline resilience to AP
drops. Do NOT cache API responses or MQTT. Register it from main.jsx.

## src/mqtt/client.js
Wrap mqtt.js. connect(`ws://${location.hostname}:9001`). Export:
  subscribeNodeReps(nodeId, onRep)  -> subscribes edgeathlete/node/{nodeId}/rep, parses JSON, calls onRep(rep)
  subscribeRackState(rackNumber, onState) -> subscribes edgeathlete/rack/{rackNumber}/state
  resubscribeNode(oldNodeId, newNodeId, onRep) -> for reassignment: unsubscribe old, subscribe new
Reconnect automatically on drop (mqtt.js does this; verify it fires).

## src/db/repBuffer.js  (IndexedDB — the durability boundary)
Open a DB "edgeathlete", store "reps" keyed by autoincrement. Export:
  addRep(rep), getBufferedReps(), clearBuffer()
Every incoming rep is written here IMMEDIATELY on arrival (before any UI concern).

## src/rack/RackScreen.jsx  (shell only this phase)
Once assigned a rack number: subscribeNodeReps for the rack's linked node, and
on each rep -> addRep(rep) AND update a live in-memory rep count + latest
velocity color shown on screen. Render a minimal live panel: rep count, last
mean_velocity, velocity color chip. No set lifecycle / no POST yet (Phase 7).

Delete the reference's Dashboard.jsx 5-second polling pattern — we push, not poll.
Every file opens with a WHY comment (the repBuffer.js comment is a great place
for the "durability boundary" analogy).
```

### Verify
- On first load with no `device_role` set, the picker renders; picking "Rack Tablet" registers the device and shows its id on a "waiting for assignment" screen.
- Manually PATCHing that device's rack_number (simulating the Phase 10 coach action) causes the polling screen to pick it up within ~3s and move into the live rep panel.
- Chrome shows an install prompt once a role is picked; installed app launches fullscreen.
- Running `simulate_node --node-id rack_1` drives the on-screen rep counter and velocity color live.
- Every simulated rep lands in IndexedDB (`getBufferedReps()` grows); killing WiFi mid-stream and reconnecting does not lose already-buffered reps and the mqtt client reconnects.

### ✅ Phase 6 Exit Checklist
- [ ] Device role picker renders on first load; choice persists across reload via localStorage
- [ ] Picking a role swaps the manifest link tag to the matching file
- [ ] Rack registration generates a device_id, POSTs it once, and displays it clearly while awaiting assignment
- [ ] Assignment polling picks up a coach-assigned rack_number within ~3s and stops polling
- [ ] Chrome shows an install prompt once a role is chosen
- [ ] Service worker registered; app shell loads offline
- [ ] Running the Phase 3 simulator drives the rep counter and velocity color live
- [ ] Each rep is written to IndexedDB on arrival; killing WiFi mid-set loses no buffered reps and the client reconnects
- [ ] Reference `Dashboard.jsx` polling pattern deleted
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 7.**

---

# SPRINT 3 — First Vertical Slice + Handoff (Devin's last sprint)

## Phase 7 — Rack Screen End-to-End · Owner: Braydon

### Goal
Turn the shell into the full rack flow: idle → countdown → active set → summary → rest, with the real batch POST at set end, false-set undo, and a rest timer.

### Prompt to paste into Claude
```
Working directory: react/src/rack/. Build on the Phase 6 shell. The batch endpoint
is POST /api/sets/{id}/complete/ (see below). edge_athlete_rack_ui.html is a
layout reference only.

## Athlete + exercise selection (manual — the baseline; NFC is a future shortcut
## onto this same selection, not a separate path)
Before a set can start, "idle" needs a selected athlete and exercise — nothing
upstream provides this yet. Add a simple picker reachable from "idle":
  - GET /api/athletes/, render as a searchable list/dropdown. Selecting one
    stores { athlete_id, athlete_name } in local component state (not
    persisted — reselect each session/rotation).
  - GET /api/programs/?athlete={id} for the selected athlete, render as a
    second dropdown (exercise names from their programs). If they have no
    programs yet, fall back to a plain text input for exercise name.
  - "idle" now shows the selected athlete + exercise instead of a placeholder,
    and set start is disabled until both are chosen.
This is intentionally the simplest thing that works — a coach can also just
select the athlete on the athlete's behalf. Do NOT build NFC in this phase;
leave the athlete-id this picker produces as the one thing an NFC tap would
shortcut into later (see Known Open Items at the top of this doc).

## Screen states (single RackScreen state machine)
  "idle"      -> athlete/exercise picker (above) if not yet selected, otherwise
                 shows linked node + selected athlete/exercise, waiting to start
  "countdown" -> 3-2-1 before a set
  "active"    -> live reps streaming in (from Phase 6 subscribe + repBuffer)
  "summary"   -> set just ended; shows reps_completed, avg/peak velocity
  "rest"      -> rest timer counting down to next set, then back to idle/countdown

## Set lifecycle
1. On set start (coach/athlete taps start, or first rep arrives after countdown):
   POST /api/sets/ with { session, athlete: selected athlete_id, node, exercise:
   selected exercise, set_number } to create the Set, keep the returned set_id.
2. During "active": each rep arrives over MQTT -> addRep(rep) to IndexedDB AND
   update live UI (rep count, velocity color per rep).
3. On set end (0.75s stillness upstream ends the last rep; athlete taps "End Set"):
   - read getBufferedReps()
   - compute reps_completed, avg_velocity (mean of mean_velocity),
     peak_velocity (max), assign velocity_color per rep if not already set
   - POST /api/sets/{set_id}/complete/ with body:
     { reps_completed, avg_velocity, peak_velocity, is_false_set:false,
       reps:[ {rep_number, mean_velocity, peak_velocity, duration_ms, timestamp,
               velocity_color}, ... ] }
   - on success: clearBuffer(), go to "summary"
   EXACTLY ONE complete POST per set.

## False-set undo
A "False Set" button available in active/summary. It POSTs complete with
is_false_set:true and an EMPTY reps array (server records the false set, writes no
reps), clears the buffer, and returns to "idle". No rep rows written.

## Rest timer
After "summary", a configurable rest countdown (default 120s) in "rest" state;
on expiry (or a "Next Set" tap) return to "idle"/"countdown". Increment set_number.
Keep the same athlete/exercise selection across sets in the same rotation;
only clear it if the coach/athlete explicitly changes it.

Every file opens with a WHY comment.
```

### Verify
- With no athlete/exercise selected, "idle" shows the picker and set start is disabled.
- Selecting an athlete + exercise, then running a full simulated session (idle → countdown → active → summary → rest) produces **exactly one** `POST /api/sets/{id}/complete/`, and the created `Set` row has the correct `athlete`/`exercise` values.
- The server's rep count for that set matches what streamed in.
- The False-Set button returns to idle and writes zero reps (`Rep.objects.filter(set=...).count() == 0`, `Set.is_false_set == True`).
- Rest timer counts down and returns to idle, keeping the same athlete/exercise selected for the next set.

### ✅ Phase 7 Exit Checklist
- [ ] Athlete + exercise picker works from "idle"; set start is disabled until both are chosen
- [ ] Full flow idle → countdown → active → summary → rest works against the simulator
- [ ] Exactly one `complete/` POST per set, with correct rep count, summary stats, athlete, and exercise
- [ ] IndexedDB buffer cleared only after a successful POST
- [ ] False-set undo returns to idle and writes no reps
- [ ] Rest timer works; set_number increments; athlete/exercise selection persists across sets in the same rotation
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 8.**

---

## Phase 8 — Team Dashboard Kiosk · Owner: Devin

### Goal
Build the base station's own kiosk display — the read-only room scoreboard — subscribing to `edgeathlete/dashboard/state`.

### Prompt to paste into Claude
```
Working directory: react/src/dashboard/. Route /dashboard. No login, read-only.
Subscribe over mqtt.js (Phase 6 client) to edgeathlete/dashboard/state.

## Sections (per the product's dashboard scope)
1. Rack status grid — one tile per rack, color-coded green/yellow/red using the
   SAME velocity color system used everywhere else. Updates on rack/dashboard state.
2. Live leaderboard — athletes ranked by a session metric (e.g. best avg velocity),
   updates on "leaderboard_update" messages.
3. Fun facts / insights — VISUALLY PROMINENT (bigger than in earlier drafts).
   Rotating room insights (e.g. "fastest rep of the session", "most reps").
4. Summary block — room-wide session stats (total sets, total reps, athletes active).
5. Coach alerts — its OWN section, visually separated from everything above.

Subscribe once on mount; update the relevant section per incoming message "type".
Kiosk styling: large type, high contrast, readable across a room. No interactivity.
Every file opens with a WHY comment.

## Boot-time kiosk launch
Extend the reused `privacy-dots.service` (don't create a separate, unrelated
autostart mechanism): after the Docker stack step, add (a) a wait/retry loop
that polls the dashboard URL until it responds, then (b) launch Chromium in
kiosk mode against it: `chromium-browser --kiosk --app=http://localhost/dashboard
--noerrdialogs --disable-infobars`. This is what actually makes the base
station boot into the dashboard — the manifest.json fullscreen setting from
Phase 6 does not do this on its own.
```

### Verify
- With the simulator + a rack screen running, completing a set updates the rack status grid within 2s and moves the leaderboard.
- Coach alerts render in their own visually separated section.
- Rebooting the Pi lands directly on the fullscreen dashboard with no manual steps.

### ✅ Phase 8 Exit Checklist
- [ ] Rack status grid updates within 2s of a simulated set completing
- [ ] Leaderboard, fun-facts/insights (prominent), and summary block all update live
- [ ] Coach alerts render in their own separated section
- [ ] Read-only, no login, kiosk-legible
- [ ] A cold reboot of the Pi auto-launches the dashboard fullscreen with no manual steps, via the extended `privacy-dots.service`
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 9.**

---

## Phase 9 — Real ESP32 Firmware v1 · Owner: Derrilon

### Goal
Replace the simulator with real hardware: MPU-6050 velocity computation on-device, a 0.75s-stillness rep boundary, and MQTT publish matching the `parse_rep_payload` contract from Phase 3.

### Prompt to paste into Claude
```
Working directory: esp32/edge_athlete_node/. Delete the reference PIR/motion
firmware. This is Arduino/C++ for ESP32 + MPU-6050.

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

Top-of-file comment: 2-4 lines, WHY this firmware exists, beginner-readable.
```

### Verify
- A physical barbell rep produces exactly one `rep` MQTT message with a plausible velocity value (`mosquitto_sub -t 'edgeathlete/node/+/rep' -v`).
- The same rep appears on the rack screen within 1s (swap the simulator for the real node in the Phase 6/7 flow).
- Pulse messages update the node's `Node` row via the Django subscriber.

### ✅ Phase 9 Exit Checklist
- [ ] A physical rep produces one `rep` message with a plausible velocity
- [ ] Payload shape exactly matches `parse_rep_payload`
- [ ] Same rep appears on the rack screen within 1s
- [ ] Pulse updates the `Node` row
- [ ] Noise-reduction hook clearly marked, not implemented
- [ ] Top-of-file WHY comment present

**STOP. Do not continue past the handoff gate until it fully passes.**

---

## Sprint 3 Handoff Gate · Owner: Devin

This is the gate before Devin exits. All of it must pass.

- [ ] `RUNBOOK.md` complete: start/stop, firmware flashing, MQTT test commands, full integration-test steps, common failure modes
- [ ] Architecture diagram present (Mermaid, in `RUNBOOK.md`) showing nodes → broker → Django/Postgres and broker → browser clients over WS
- [ ] A dry run of the full session flow with **Devin observing only, not helping**
- [ ] Every teammate has flashed firmware once and run the integration test once

**STOP. Devin exits. Sprints 4–6 run without him.**

---

# SPRINTS 4–6 — Team Alone (lighter detail — full treatment closer to start)

These phases are intentionally lighter. A lot will shift across Phases 1–9; each of these gets expanded to full paste-ready depth at the start of its sprint.

## Phase 10 — Coach Tablet (one page) · Owner: Braydon
Same PWA shell, `public/manifest.coach.json`, route `/coach`, JWT login gate. ONE consolidated admin view: live room state (subscribe `edgeathlete/coach/state`), abnormal-performance alerts/suggestions, basic graphs. Coach-only writes (athlete/program, node reassignment, session create/end) go through the JWT-gated endpoints from Phase 4. Multi-page expansion stays deferred.

**Room Layout (drag-and-drop assignment):** one section of the consolidated view — a grid of rack slots (1..N) plus two source pools: "Unassigned Screens" (`GET /api/racks/unassigned/`, each shown by its short device id — the same id that rack screen displays on its own "waiting for assignment" state) and nodes available for reassignment (`GET /api/nodes/`). Dragging a screen onto a rack slot calls `PATCH /api/racks/{device_id}/` with the rack number; dragging a node onto a rack slot calls the existing `PATCH /api/nodes/{node_id}/` from Phase 4. Same drag-and-drop interaction for both entity types — one shared component, not two separate admin patterns.

## Phase 11 — Fatigue Scaffold · Owner: Carl
`django/event_handler/ml/inference.py` with a REAL function signature (e.g. `predict_fatigue(set_summary: dict) -> dict`) and a real call site firing after set-complete (Phase 4/5). Returns a **stub** value. Not a trained model — training is explicitly out of scope.

## Phase 12 — Security Hardening · Owner: whole team
Verify JWT covers all coach-only endpoints (should already be true from Phase 4). Move Mosquitto off `allow_anonymous true` to ACLs/auth on both listeners. Rate-limit login. Confirm no coach-only path is reachable unauthenticated.

## Phase 13 — Firmware Hardening & Additional Mounts · Owner: Derrilon
Waist and wrist mount thresholds, WiFi reconnect logic, enclosure v1. Resolve (or keep hooked) the noise-reduction location decision.

## Phase 14 — Full Integration Test & Demo Prep · Owner: whole team
Seed script, one-command `start.sh`, `DEMO_SCRIPT.md`, screen-recording backup. The full session script must run clean at least twice in a row before demo day.

---

## Stretch Goals / Explicitly Deferred (only after all phases complete)

Don't let these block a phase — they're intentionally punted:

- **Noise-reduction location** (ESP32 firmware vs. rack screen) — leave a hook on both sides; whichever gets built first wins.
- **Real trained fatigue model** — Phase 11 is a scaffold only.
- **Coach tablet multi-page expansion** (separate Room / Athletes / Racks / Analytics tabs).
- **Consumer "One Device" mode / PvP BLE mode** — not in this spec at all.
- **3D bar-path tracing** — future hardware, not this project.
