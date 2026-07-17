# Spec: Edge Athlete — Real-Time Barbell Velocity Tracking — v2
**Stack:** Django (sync `runserver`, DRF) + React (Vite) + PostgreSQL + Mosquitto (MQTT) + Nginx, all in Docker | **Hardware:** Raspberry Pi base station (owns a private WiFi AP) + ESP32 + MPU-6050 sensor nodes | **Served by:** the Pi, no internet, no cloud, no subscription | **Environment:** macOS dev host → deploy target is Raspberry Pi OS (arm64) | **Team:** 4 people | **Timeline:** 6 sprints × 2.5 weeks

**v2 note:** Phases 1–4 are built and unchanged from v1. Phase 5 onward is
expanded/renumbered to fold in the group/block/session hierarchy, CSV import,
status tracking, makeup flow, athlete max tracking, and insights scaffold
designed after Phase 4 shipped. See the **v2 Changelog** near the end for a
full diff against v1. Where a v1 architecture decision is affected, it's
marked **Revised in v2** in place rather than silently rewritten.

## Agent tool compatibility
This file is the project's agent-instructions file regardless of which tool you're running. **Claude Code:** treat this as `CLAUDE.md`. **opencode:** treat this as `AGENTS.md`. Either rename/symlink it accordingly in your own checkout, or just point your tool at this file directly — don't fork a second copy of the instructions.

## IMPORTANT
When doing scaffolding and file-admin work use a more efficient model like **Haiku**. Use **Opus** as the default for the large majority of implementation work. Reach for **Fable** (interchangeably with Opus) on the highest-stakes logical work: rep-detection tuning, MQTT topic routing, auth/security. See **Working Style → Model routing**.

This document is the single source of truth for what Edge Athlete is and how it gets built. It converts an earlier looser context doc into spec-driven form. If anything else in this repo — or in the Privacy-Dots-V2 reference — contradicts this file, **this file wins.**

---

## How to Use This Document

Work through each phase in order. **Do not proceed to the next phase until the current one is complete and its exit checklist passes.** Each phase ends with an explicit STOP and a checklist. Paste only the prompt for the current phase into a fresh Claude conversation — do not share future phases ahead of time.

When a prompt says "read the reference project," that means use your file tools to inspect the Privacy-Dots-V2 repo's contents before writing any code. Do not guess at structure or config — derive it from what you actually find. The reference lives beside this repo (upstream: `git@github.com:devi-walto/Privacy-Dots-V2.git`); it stays **read-only**.

Phases 1–4 are complete. Phases 5–13 (through the Sprint 4 handoff gate) are written at full paste-ready depth. Phases 14–18 (team-alone work) are also now at full depth — Phase 14 (Coach Tablet) in particular was expanded early because it absorbed the new group/block/session/CSV work, rather than being left light and revisited later as originally planned.

---

## Known Open Items (read before starting the phase they touch)

These are real gaps, not stretch goals — they were deliberately deferred to get a demo-able slice built in a tight window. Whoever starts the referenced phase should resolve or explicitly re-defer each one rather than being surprised by it mid-phase:

- **Batch-POST failure/retry (affects Phase 11, hardens in Phase 16/18):** if `POST /api/sets/{id}/complete/` fails (e.g. an AP drop at the exact moment a set ends), there is currently no defined retry/backoff — the buffer only clears on success, but nothing describes what happens on failure. Fine for a controlled demo; needs a real answer before unattended/production use.
- **Analytics response contract (affects Phase 4, consumed by Phase 14):** `GET /api/analytics/session/{id}/` and `.../athlete/{id}/` only have a prose description, not an exact field list like every other endpoint. Pin down the actual JSON shape before or during Phase 4 so Phase 14 isn't guessing at what it receives.
- **No rack "unassign" path (affects Phase 14):** only registration + assignment exist; there's no way to free a rack number back to the unassigned pool if a screen is retired or replaced.
- **Clock reliability on the offline Pi (affects Phase 1/RUNBOOK, Phase 18):** the base station never touches the internet, so there's no NTP sync. If it lacks a hardware RTC, a cold boot could start with a wrong system clock, silently corrupting every `timestamp` field. Needs either an RTC module or a manual time-set step documented in the boot procedure.
- **Stale `RackScreen` rows (affects Phase 16):** if a screen's `localStorage` is ever wiped, it registers a brand-new `device_id` and the old row is orphaned at its old rack number with no cleanup.
- **Group reassignment mid-flight (affects Phase 5/14):** if an athlete's `group` changes while a `Session` tied to their old group is still in progress (not yet green/marked done), no rule is defined for whether they still appear on that session's roster. Current design snapshots roster at CSV-upload time, so this is likely fine by construction but untested against a live reassignment mid-session.
- **Exercise catalog editing after confirmation (affects Phase 6):** once an `Exercise` is confirmed (`is_stub=False`), there's no defined path to later edit its tags or fix a name typo — only the stub-confirmation flow touches the catalog today.
- **Insights model itself (affects Phase 5/8):** `generate_insights` is a stub returning `[]`. Choosing/training the actual local model and defining what "notable" means for `flagged_for_review` is explicitly out of scope here, same as the fatigue-model stub.
- **Retroactive max entry vs. already-completed Sets (affects Phase 5/7/11):** if an athlete's first-ever AthleteReferenceMax gets entered mid-session (via the Phase 11 inline prompt) AFTER they've already completed earlier sets in that same session using no calculated target (or a stale one), those earlier Sets are not recalculated or flagged — the new reference only affects target-weight display going forward from the moment it's entered. No retroactive recomputation is in scope for this spec. (See the finalization-gate item below, which is the intended long-term home for recomputation.)
- **Coach publish/finalization gate + outlier-robust reference recalc (affects Phase 7/8; UI in Phase 14):** today `AthleteReferenceMax` rows are written only by direct entry (`source=manual`). The intended finalization flow is deferred: a coach reviews a session's data in a filterable/searchable summary, hits "Publish" (an application-level Python service run in a transaction — NOT a Postgres trigger — reusing the `mark-done` hook), and only then are velocity-`estimated` reference maxes computed and written (each linked via `source_session`). Two questions ride on it: (1) the estimation must be robust to a single anomalous set skewing the fit — e.g. drop reps outside the velocity zone or use an outlier-resistant method — since one bad rep could otherwise poison the reference; (2) a coach striking an anomalous set AFTER publish should re-run that service and APPEND corrected rows (append-only supersede, never a mutation). No stored "published" state, no set-strikethrough flag, and no recalc service exist yet — this is the designed-for future, captured so Phase 7/8 build toward it rather than around it.

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

**v2 addition:** a coach now plans training ahead of time — designing workouts in a spreadsheet, exporting a CSV, and uploading it to create a Group → Block → Session → planned-exercise structure before any rack even powers on. See **Phases 5–8** for the full design.

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

**Considered and rejected (v2):** moving durability to the ESP32 node itself (buffer a full set in flash, submit directly to the DB, skip the rack screen as an intermediary). Rejected because (a) the node has no concept of session/athlete/exercise context today — only the rack screen's UI captures that, so the node would need a whole new downstream "assign context" channel to know whose set it's recording, and (b) replicating IndexedDB's free durability would mean hand-rolling a flash-based durable queue in firmware (ack/clear/replay logic, flash-wear considerations) to save a network hop that isn't a bottleneck on a single-Pi LAN. The existing rack-screen-as-durability-boundary design gets both context and durability essentially for free; the node-side alternative pays real engineering cost for a marginal gain at this scale.

### MQTT topic scheme is namespaced under `edgeathlete/`
This resolves an old naming conflict between reference docs (`edgeathlete/*` vs. `rack/{n}/*`). See **Real-Time Layer Reference** for the full table. Key rule: **Django's MQTT subscriber listens ONLY to `edgeathlete/node/+/pulse`** — rep topics never reach Django/Postgres at runtime. Node reassignment = the rack screen resubscribes to a different node topic string. No IP lookup, no socket teardown.

### Six sprints, 2.5 weeks each; Devin is present through the Sprint 4 handoff gate
Not 8 sprints, not exit-after-4 — those earlier numbers are wrong. Six sprints, full team through the handoff, team alone after.

**Revised in v2:** the original plan had the handoff (and Devin's exit) land at the end of "Sprint 3," when Sprint 3 covered Phases 7–9. After the Phase 5–8 group/session/CSV work was inserted following Phase 4, the ESP32 firmware phase that the handoff depends on moved from Phase 9 to Phase 13, which now falls in **Sprint 4**. The handoff gate and Devin's exit point move with it — see the updated Sprint breakdown below. Total sprint count is unchanged (still six); each sprint simply carries a different phase distribution than originally planned. **The team should confirm the 2.5-week-per-sprint cadence still holds now that four extra phases exist** — this spec does not resolve that scheduling question, it only keeps the phase content and sprint labels internally consistent.

### Coach tablet is one page for this spec
The full vision (separate Room / Athletes / Racks / Analytics tabs) is deferred. This spec builds a single consolidated admin view: live room state, abnormal-performance alerts/suggestions, and basic graphs. Multi-page expansion is future work.

**Revised in v2:** Phase 14 now includes group/block/session drill-down navigation (Groups list → Block detail → Session detail) and a CSV upload flow, which are additional views/routes beyond the original single consolidated page. This is a narrower kind of multi-view growth than the originally-deferred "separate Room/Athletes/Racks/Analytics tabs" vision — it's drill-down navigation into planning data, not a general tabbed admin app — but it does mean "one page" no longer describes the coach tablet literally. The live-room-state + alerts + basic-graphs portion, and the Room Layout drag-and-drop assignment section, remain exactly as originally specified and stay consolidated in one view.

### Local fatigue ML is scaffolded, not trained
Fatigue detection gets a real interface (`ml/inference.py`) and a real call site (fires after set-complete), but the function returns a stub value in this spec. Training a real model is explicitly out of scope.

**v2 note:** a second, separate ML scaffold is introduced in Phase 5/8 — `ml/analyze_session.py` / `generate_insights`. These are two distinct stubs with separate trigger points (fatigue fires per-set, insights fires per-session-done) — do not merge them into one function or call site. See Phase 15 for the explicit clarifying note.

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
| `privacy-dots.service` (systemd unit that launches the Docker stack on boot) | Reuse and **extend**, don't replace. This becomes the base station's kiosk-launch mechanism too — add a "wait until the dashboard responds" step, then a kiosk-mode browser launch, either appended to this same unit or as a second unit with `After=privacy-dots.service`. See Phase 12. |
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
| PIR / motion firmware (`esp32/privacy_dots_node/`) | **Delete/replace** with the MPU-6050 firmware in Phase 13. |

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
Anonymous access is fine through the Sprint 4 handoff. Broker auth/ACLs are a Phase 16 hardening item, not a demo blocker.

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

No new MQTT topics were introduced by the v2 group/session/CSV work — the active-session and roster data the rack screen needs is fetched over plain REST (see Phase 10), not pushed over a new topic.

---

## Data Models (extend the reference's Postgres schema)

### Original seven (Phase 2 — built)

All live in `django/event_handler/models.py`.

```
Node       — node_id (CharField, unique), rack_number (Int, nullable),
             mount_type (choices: bar/waist/wrist), firmware_version,
             battery_level (Int, nullable), signal_strength (Int, nullable),
             last_seen (DateTime, nullable), is_active (Bool, default True)
RackScreen — device_id (CharField, unique, client-generated at first setup),
             rack_number (Int, nullable — null means "awaiting coach
             assignment"), last_seen (DateTime, auto)
Athlete    — name, nfc_tag_id (unique, nullable), created_at (auto), notes (Text, blank)
Program    — athlete (FK→Athlete), exercise (FK→Exercise), target_sets (Int), target_reps (Int),
             target_weight_lbs (Float), velocity_zone_min (Float), velocity_zone_max (Float)
Session    — label, started_at (auto), ended_at (nullable), athletes (M2M→Athlete), notes
Set        — session (FK→Session), athlete (FK→Athlete), node (FK→Node, nullable),
             exercise (FK→Exercise), set_number (Int), weight_lbs (Float, nullable), started_at, ended_at (nullable),
             reps_completed (Int, default 0), avg_velocity (Float, nullable),
             peak_velocity (Float, nullable), is_false_set (Bool, default False)
Rep        — set (FK→Set), rep_number (Int), timestamp, mean_velocity (Float),
             peak_velocity (Float), duration_ms (Int), velocity_color (Char)
```

**`Rep` rows are created ONLY via the batch set-complete endpoint, never one at a time.**
**`RackScreen` is the physical screen's own identity — separate from `Node.rack_number`, which tracks which sensor is linked to a rack. A rack screen and its sensor node are assigned independently.**
**Exercise-identity note (built early, sprint of 2026-07-17, branch `exercise-catalog`):** `Program.exercise`, `Set.exercise`, and `AthleteReferenceMax.exercise` are all `FK→Exercise` (the catalog below), not free text. This deliberately goes one step past canon, which introduced the catalog but left `Program`/`Set` on text — half-normalizing breaks the rack endpoint's id-vs-name lookup, so all three were converted together via a reversible backfill migration (`0005_link_models_to_exercise_catalog`). See `MINISPEC-exercise-catalog.md`.

### Extended in Phase 5+ (Group/Session Hierarchy & Athlete Max Layer)

New models, built in Phase 5, plus extensions to three of the original seven.
Full field-level detail lives in the Phase 5 prompt below — this is the
summary view:

```
TrainingGroup — coach (FK→User), name, created_at
Block         — training_group (FK→TrainingGroup), name, order (Int)
Tag           — name (unique)
Exercise      — name (unique), tags (M2M→Tag), is_stub (Bool), created_at
                (standard auto-increment PK — no custom ID assignment logic)
SessionExercise — session (FK→Session), exercise (FK→Exercise), target_sets,
                target_reps, target_weight_percent (Float — % of the
                athlete's own max, not an absolute weight), velocity_zone_min,
                velocity_zone_max, coach_notes
SessionInsight  — session (FK→Session), athlete (FK→Athlete, nullable = team-
                level), content (Text), source (choices: local_model/coach_note),
                flagged_for_review (Bool), created_at
AthleteReferenceMax — athlete (FK→Athlete), exercise (FK→Exercise),
                reference_weight_lbs (Float), rep_basis (Int, default 1),
                source (choices: manual/estimated), source_session (FK→Session,
                nullable, SET_NULL), recorded_at (auto) — APPEND-ONLY history,
                never overwritten; "current reference" = latest recorded_at row.
                This is an athlete's CURRENT WORKING reference (what they can do
                NOW), so it can go DOWN as well as up — it is NOT a lifetime best.
                Lifetime bests stay derivable from Set history and the
                is_velocity_pr / is_weight_pr flags; do not conflate the two.
                `source` distinguishes a coach-entered value from a future
                velocity-ESTIMATED one (so you can graph estimate vs. actual);
                `source_session` links an estimate back to the session that
                produced it so a coach publish/re-publish can supersede it
                without mutating history. (Referred to as `AthleteMax` /
                `max_weight_lbs` in the Phase 7/10/11/14 prompts below — SAME
                table, renamed for clarity. `exercise` is an `FK→Exercise` — the
                catalog was built early this sprint; see the exercise-identity
                note above.)

Athlete  EXTENDED — group (FK→TrainingGroup, nullable, SET_NULL). Current
           group only; reassigning it never rewrites historical Session/Set
           data, which stays attached to whatever Block/Session it actually
           happened under.
Session  EXTENDED — block (FK→Block, nullable), schedule_date (DateTime,
           nullable — planning only, decoupled from started_at/ended_at).
Set      EXTENDED — is_makeup (Bool, default False) — excluded from
           team_completion_time calculations.
```

---

## REST API

### Original endpoints (Phase 4 — built)

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

### Extended in Phase 5+ endpoints

```
POST  /api/sessions/upload/            CSV import — creates/reuses the full   (coach only)
                                        Group → Block → Session →
                                        SessionExercise chain in one
                                        transaction; stubs unrecognized
                                        exercises rather than rejecting

PATCH /api/exercises/{id}/confirm/     confirm or reject a stubbed exercise   (coach only)

GET   /api/sessions/{id}/roster-status/  per-athlete has_data flags for a     (coach only)
                                        session's roster

GET   /api/groups/                     list groups, rolled-up status dot     (coach only)
GET   /api/blocks/?group={id}          list blocks in a group, rolled-up     (coach only)
                                        status dot
GET   /api/sessions/?block={id}        list sessions in a block, status dot  (coach only)

PATCH /api/sessions/{id}/mark-done/    explicit override to trigger          (coach only)
                                        insights generation

GET   /api/sessions/active/            one-shot fetch for a rack screen:     (open)
                                        current session + roster (with
                                        has_data + maxes) + planned exercises

POST  /api/athlete-maxes/              record a new AthleteMax entry         (open — same
                                        (append-only, never overwrites)      trust tier as
                                                                              POST /api/sets/)
GET   /api/athlete-maxes/?athlete={id}&exercise={id}   full max history,     (coach only)
                                        ordered by recorded_at — powers the
                                        Phase 14 progression chart
```

`GET /api/sessions/active/` being open (not JWT-gated) matches the existing
open/coach-only split: it's read by an unauthenticated rack tablet, the same
trust tier as the other rack-facing endpoints above it.

---

## Folder Structure (target state after all phases)

```
Edge-Athlete/
├── docker-compose.yml
├── .env                          # gitignored — runtime values
├── .env.example                  # committed — template with stubbed keys
├── RUNBOOK.md                    # started Phase 1, completed by Sprint 4 handoff
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
│       ├── models.py             # original 7 models + TrainingGroup, Block,
│       │                         # Tag, Exercise, SessionExercise,
│       │                         # SessionInsight, AthleteMax (Phase 5)
│       ├── admin.py
│       ├── apps.py
│       ├── serializers.py
│       ├── views.py
│       ├── urls.py
│       ├── permissions.py        # IsCoach (JWT) vs open
│       ├── ml/
│       │   ├── inference.py       # fatigue scaffold — real signature, stub return
│       │   └── analyze_session.py # insights scaffold — real signature, stub return (Phase 5)
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
│       ├── coach/                       # CoachTablet
│       │   ├── RoomLayout.jsx           # drag-and-drop rack/node assignment (Phase 14)
│       │   ├── GroupsList.jsx           # (Phase 14)
│       │   ├── BlockDetail.jsx          # (Phase 14)
│       │   ├── SessionDetail.jsx        # (Phase 14)
│       │   ├── StatusDot.jsx            # shared red/yellow/green component (Phase 14)
│       │   ├── CsvUploadModal.jsx       # + stub-exercise confirmation (Phase 14)
│       │   └── AthleteMaxChart.jsx      # progression chart (Phase 14)
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
Firmware flashing (TODO — Phase 13), Architecture diagram (TODO — Sprint 4).

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
ESP32 firmware (Phase 13) even though reps never reach the Django subscriber.
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
(Phase 9 will hook a broadcast publish onto the end of this view — leave a clearly
marked `# Phase 9: publish rack/dashboard state here` comment at the success point.)

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
- [ ] `# Phase 9: publish ...` marker left at the complete-view success point
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 5.**

---

# SPRINT 2 (EXTENDED) — Group/Session Data Layer

Phases 5–8 extend the models and API Phase 4 already built. They run before
the broadcast/rack-screen phases because Phase 10's rack screen and Phase 14's
coach tablet both consume this data — building it first means those phases
get written once, correctly, instead of built naive-then-redone.

**Parallelization note:** a bare "node sends data, rack screen shows it live"
proof of concept does NOT require any of Phases 5–8 — it only needs Phase 1
(broker), Phase 3 (simulator), and Phase 4 (registration endpoints), since
live rep/pulse display goes node → broker → rack screen directly over MQTT,
never through Django. If a visible rack-screen demo is wanted before Phases
5–8 finish, split the team: **Track A** — Phase 9 (broadcast) → Phase 10
excluding its active-session-fetch subsection; **Track B** — Phases 5–8,
fully independent of Track A. **Convergence point:** Phase 11 needs both
tracks finished, since its picker and target-weight calculation depend on
the `/api/sessions/active/` response shape Track B builds.

## Phase 5 — Group/Block/Session Hierarchy, Exercise Catalog, Athlete Max & Insights Scaffold · Owner: TBD

### Goal
Introduce the coach → group → block → session hierarchy, replace free-text
exercise names with a real catalog + tag system, add append-only athlete max
tracking, and scaffold the local-insights model (real schema, no real ML yet
— same pattern as the existing fatigue stub from Phase 15).

### Prompt to paste into Claude
```
Working directory: django/event_handler/. Read models.py first — these are
ADDITIONS and EXTENSIONS to the existing seven models from Phase 2, not
replacements.

## New models

TrainingGroup:
  coach       ForeignKey(settings.AUTH_USER_MODEL, on_delete=CASCADE, related_name="training_groups")
  name        CharField(max_length=255)
  created_at  DateTimeField(auto_now_add=True)

Block:
  training_group  ForeignKey(TrainingGroup, on_delete=CASCADE, related_name="blocks")
  name            CharField(max_length=255)
  order           IntegerField(default=0)

Tag:
  name  CharField(max_length=100, unique=True)

Exercise (the catalog — replaces free-text exercise names going forward):
  name        CharField(max_length=255, unique=True)
  tags        ManyToManyField(Tag, related_name="exercises", blank=True)
  is_stub     BooleanField(default=False)   # True = auto-created from an
                                             # unrecognized CSV row, awaiting
                                             # coach confirmation
  created_at  DateTimeField(auto_now_add=True)
Use Django's default auto-incrementing BigAutoField primary key — do not
hand-roll ID assignment. Gaps left by deleted stub rows are expected and fine
(Postgres sequence increments are already the cheapest correct approach here;
no walk-the-table or reorganize-on-delete logic is needed or wanted).

SessionExercise:
  session                ForeignKey(Session, on_delete=CASCADE, related_name="session_exercises")
  exercise                ForeignKey(Exercise, on_delete=PROTECT, related_name="session_exercises")
  target_sets             IntegerField(null=True, blank=True)
  target_reps             IntegerField(null=True, blank=True)
  target_weight_percent   FloatField(null=True, blank=True)
  velocity_zone_min       FloatField(null=True, blank=True)
  velocity_zone_max       FloatField(null=True, blank=True)
  coach_notes             TextField(blank=True, default="")
(Nullable target fields because a stub Exercise's SessionExercise row may be
created before the coach fills in real numbers. target_weight_percent is a
PERCENTAGE of each athlete's own AthleteMax on this exercise, not an absolute
weight — see the CSV format note in Phase 6 and the per-athlete calculation
in the Phase 10 patch.)

SessionInsight:
  session             ForeignKey(Session, on_delete=CASCADE, related_name="insights")
  athlete             ForeignKey(Athlete, on_delete=CASCADE, null=True, blank=True,
                                  related_name="insights")   # null = team-level insight
  content             TextField()
  source              CharField(max_length=20, choices=[("local_model","Local Model"),
                                                          ("coach_note","Coach Note")])
  flagged_for_review  BooleanField(default=False)   # marks this for a future
                                                      # remote-LLM sweep; nothing
                                                      # reads this flag yet
  created_at          DateTimeField(auto_now_add=True)

AthleteMax:
  athlete         ForeignKey(Athlete, on_delete=CASCADE, related_name="maxes")
  exercise        ForeignKey(Exercise, on_delete=CASCADE, related_name="athlete_maxes")
  max_weight_lbs  FloatField()
  recorded_at     DateTimeField(auto_now_add=True)
  # HISTORY table, not a single overwritten value — every entry creates a new
  # row rather than updating one in place. "Current max" for an athlete on an
  # exercise is whichever row has the latest recorded_at. This is deliberate:
  # it means max progression over time falls out for free later (e.g. for the
  # Phase 8 insights scaffold) instead of needing a separate history table
  # bolted on after the fact. No manual entry ever overwrites a prior row.

## Extend existing models (do not remove existing fields)

Athlete: ADD
  group  ForeignKey(TrainingGroup, on_delete=SET_NULL, null=True, blank=True,
                     related_name="athletes")
  # This is the athlete's CURRENT group only. Historical Sessions/Sets stay
  # attached to whatever Block/Session they were actually created under —
  # reassigning group here must never rewrite past records. See Phase 7 for
  # how session rosters snapshot membership at creation time instead of
  # querying this field live.

Session: ADD
  block          ForeignKey(Block, on_delete=CASCADE, null=True, blank=True,
                             related_name="sessions")
  schedule_date  DateTimeField(null=True, blank=True)
  # schedule_date is PLANNING ONLY — when this session is meant to happen.
  # started_at/ended_at (already on Session) remain execution-only and stay
  # unset until someone actually runs the session. Do not conflate the two.

Set: ADD
  is_makeup  BooleanField(default=False)
  # True when this Set was recorded retroactively for an athlete who missed
  # the session's original run. Excluded from team_completion_time (Phase 7).

## ml/analyze_session.py — insights scaffold
Real function signature, stub body — same pattern as the existing fatigue
scaffold in ml/inference.py (Phase 15):
  def generate_insights(session_id: int) -> list[dict]:
      # TODO: replace with a real local model call. For now, returns an
      # empty list so the call site has something real to invoke.
      return []
This gets wired to a real call site in Phase 8. Every new model and file gets
a 2-4 line WHY comment.

Run makemigrations/migrate, copy the migration file back, commit.
```

### Verify
- `TrainingGroup → Block → Session` FK chain resolves in the Django shell.
- `Athlete.group` can be reassigned without altering any existing `Session`/`Set`/`Rep` rows tied to that athlete's history.
- Creating an `Exercise` with `is_stub=True` and no tags works; deleting it removes it cleanly with no ID-reuse logic anywhere.
- `generate_insights(session_id)` is callable and returns `[]`.

### ✅ Phase 5 Exit Checklist
- [ ] All new models migrated; no existing model's prior fields removed or renamed
- [ ] `Athlete.group` reassignment does not touch historical Session/Set data
- [ ] `Exercise` uses standard auto-increment; no custom ID-walking logic anywhere in the codebase
- [ ] `generate_insights` has a real signature, stub return, no call site yet (that's Phase 8)
- [ ] Every new model/file has a WHY comment

**STOP. Review the above before moving to Phase 6.**

---

## Phase 6 — CSV Import Pipeline · Owner: TBD

### Goal
Let a coach upload the CSV export (one row per planned exercise) and have it
create/reuse the full Group → Block → Session → SessionExercise chain in one
transaction, stubbing unrecognized exercises rather than rejecting the row.

### Prompt to paste into Claude
```
Working directory: django/event_handler/. Builds on Phase 5 models.

## CSV column format
  group_name, block_name, session_label, schedule_date, exercise_name,
  target_sets, target_reps, target_weight_percent, velocity_zone_min,
  velocity_zone_max, coach_notes
target_weight_percent is a PERCENTAGE OF EACH ATHLETE'S OWN MAX on that
exercise (e.g. 75.0), not an absolute weight — the coach sets one percentage
that applies to the whole roster; the actual pounds get computed per-athlete
client-side using their individual AthleteMax (Phase 5) at pick time (see the
Phase 10 patch below). velocity_zone_min/max stay absolute values, same for
every athlete. One row per planned exercise; session-level fields (group_name,
block_name, session_label, schedule_date) repeat across every row belonging
to that session.

## POST /api/sessions/upload/  (coach-only, JWT)
Body: multipart file upload (the CSV).
Inside a SINGLE transaction.atomic():
  1. Parse the CSV (Python's csv module).
  2. Group rows by (group_name, block_name, session_label, schedule_date).
  3. For each group of rows:
     a. get_or_create TrainingGroup by (coach=request.user, name=group_name)
     b. get_or_create Block by (training_group, name=block_name)
     c. create Session (block=block, label=session_label,
        schedule_date=schedule_date). Snapshot the roster onto Session's
        existing `athletes` M2M from TrainingGroup.athletes AT THIS MOMENT —
        this is the "history stays where it happened" guarantee. Do not
        query group.athletes again later for this session; the M2M IS the
        snapshot.
     d. For each row: look up Exercise by name (case-insensitive). If not
        found, create it with is_stub=True and no tags. Create a
        SessionExercise linking this session to the exercise, filling in
        target_sets/target_reps/target_weight_percent/velocity_zone_min/max/
        coach_notes from the row (leave null if the row's exercise was a
        fresh stub with no numbers provided — do not error). Note
        SessionExercise's weight field is target_weight_percent (Phase 5),
        not an absolute weight.
  4. Return a summary: sessions created, exercises stubbed (with their new
     ids and names so the frontend can immediately prompt confirmation).

## PATCH /api/exercises/{id}/confirm/   (coach-only, JWT)
Body: either full catalog details (tags, description fields) to confirm, OR
empty/absent body treated as reject.
  - Confirm: set is_stub=False, apply provided fields.
  - Reject: DELETE the Exercise row AND its SessionExercise rows.
Every file opens with a WHY comment.
```

### Verify
- Uploading a CSV with a brand-new group/block/session/exercise combination creates all four levels in one call.
- Uploading a second CSV for the same group/block reuses the existing `TrainingGroup`/`Block` rows rather than duplicating them.
- An exercise name not in the catalog creates a stub `Exercise` (`is_stub=True`) and the response lists it for confirmation.
- Confirming a stub sets `is_stub=False`; rejecting it deletes the `Exercise` and its `SessionExercise` rows with no orphaned references left behind.
- Session roster (`Session.athletes`) matches the group's membership at upload time, unaffected by later `Athlete.group` reassignment.

### ✅ Phase 6 Exit Checklist
- [ ] Full CSV upload creates/reuses Group → Block → Session → SessionExercise correctly in one transaction
- [ ] Repeat upload for the same group/block reuses existing rows, no duplication
- [ ] Unrecognized exercises stub cleanly; confirm/reject both work with no orphaned rows
- [ ] Session roster snapshot taken at creation time, not computed live
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 7.**

---

## Phase 7 — Session Status, Roster, Makeup Flow & Athlete Max Entry · Owner: TBD

### Goal
Compute red/yellow/green completion status at the Session/Block/Group level
(derived, not stored), support the retroactive makeup-session flow, implement
the team_completion_time rule, and open the athlete-max write/read endpoints.

### Prompt to paste into Claude
```
Working directory: django/event_handler/. Builds on Phases 5/6.

## GET /api/sessions/{id}/roster-status/   (coach-only, JWT)
Returns each athlete on the session's roster (Session.athletes, the snapshot
from Phase 6) alongside whether a completed Set exists for them:
  { athletes: [ {athlete_id, name, has_data: bool}, ... ] }

## Status computation (derived — do NOT add a stored status field anywhere)
  - Session status: red = zero non-makeup completed Sets exist; green = every
    roster athlete has one; yellow = some but not all.
  - Block status: rolls up from child Sessions (red if all red, green if all
    green, yellow otherwise).
  - TrainingGroup status: same rollup, one level up from Block.
Expose status on GET /api/sessions/, GET /api/blocks/ (new, coach-only), and
GET /api/groups/ (new, coach-only) — computed at request time, never cached.

## Makeup flow support
POST /api/sets/ (existing, Phase 4) already accepts session/athlete/node/
exercise/set_number — no new endpoint needed to START a makeup set, it just
targets an already-ended session's id. ADD an is_makeup boolean param
(default false) to POST /api/sets/ and the complete/ flow so the flag carries
through.

## team_completion_time
Add to GET /api/analytics/session/{id}/ (Phase 4):
  team_completion_time = MAX(ended_at - started_at) across Sets in this
  session where is_makeup = False and ended_at is not null. Null if no
  qualifying Sets exist — do not default to zero.

## POST /api/athlete-maxes/   (open, no auth — same trust tier as POST /api/sets/)
Body: { athlete: athlete_id, exercise: exercise_id, max_weight_lbs: float }
Effect: creates ONE new AthleteMax row (Phase 5). Never updates/overwrites an
existing row — this is an append-only history table, so entering a new max
just adds a newer-dated row; "current max" is always whichever row for that
(athlete, exercise) pair has the latest recorded_at. No endpoint to edit or
delete a past AthleteMax row is needed for this spec.

## GET /api/athlete-maxes/?athlete={id}&exercise={id}   (coach-only, JWT)
Returns the full max history for that athlete/exercise pair, ordered by
recorded_at ascending: [ {max_weight_lbs, recorded_at}, ... ]. This is a
pure read over the same AthleteMax rows POST /api/athlete-maxes/ creates —
no new model, no new write path. Powers the progression chart in the Phase
14 patch below.
Every file opens with a WHY comment.
```

### Verify
- A session with 0 of N roster athletes completed reports red; some-but-not-all reports yellow; all reports green.
- A `Block` with a mix of red/green child `Session`s reports yellow; a `TrainingGroup` reflects the same rollup one level up.
- Roster-status endpoint correctly flags athletes with no completed Set.
- A makeup Set (`is_makeup=True`) completes normally but does not affect `team_completion_time`; a session where every Set is a makeup returns `team_completion_time: null`.
- `POST /api/athlete-maxes/` creates a new row without touching any prior row for the same athlete/exercise pair; `GET /api/athlete-maxes/?athlete=&exercise=` returns the full ordered history.

### ✅ Phase 7 Exit Checklist
- [ ] Status is computed at request time at all three levels (Session/Block/Group), never stored
- [ ] Roster-status endpoint correctly identifies missing athletes
- [ ] `is_makeup` flows through set creation and completion correctly
- [ ] `team_completion_time` uses max(), excludes makeups, returns null when no qualifying Sets exist
- [ ] `POST`/`GET /api/athlete-maxes/` both work; POST never overwrites a prior row
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 8.**

---

## Phase 8 — Wire Insights Generation · Owner: TBD

### Goal
Call the Phase 5 insights scaffold at the point a session is considered
"done," and persist the (currently empty) result as `SessionInsight` rows.

### Prompt to paste into Claude
```
Working directory: django/event_handler/. Builds on Phase 5's
ml/analyze_session.py and Phase 7's status computation.

Define "session done" as: computed status (Phase 7) reaches green, OR a coach
explicitly marks it via PATCH /api/sessions/{id}/mark-done/ (coach-only, JWT)
— some sessions may never cleanly reach green.

At that trigger, call generate_insights(session_id) and bulk_create() any
returned dicts as SessionInsight rows (source="local_model"). Since the
function returns [] today, this call site no-ops now and will start producing
real rows the moment Phase 5's stub is replaced with a real model — nothing
here should need to change when that happens.

Every file opens with a WHY comment.
```

### Verify
- Marking a session done (either via reaching green status or the explicit endpoint) calls `generate_insights` exactly once and creates zero rows today (since it returns `[]`), with no errors.
- Re-marking an already-done session done again does not duplicate the call unnecessarily (idempotent or guarded).

### ✅ Phase 8 Exit Checklist
- [ ] Both trigger paths (auto-green and explicit mark-done) call `generate_insights` correctly
- [ ] Call is safely no-op today, requires no future code changes at the call site when a real model is added
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 9.**

---

# SPRINT 3 — Real-Time Backbone

## Phase 9 — Django Broadcast Publisher · Owner: Derrilon

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

### ✅ Phase 9 Exit Checklist
- [ ] `publisher.py` exposes the three publish helpers, single reused client
- [ ] Reassigning a node produces a `rack/{n}/state` message within 1s
- [ ] Completing a set produces both a `rack/{n}/state` and a `dashboard/state` message
- [ ] Publish failures are logged, never raised into the HTTP response
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 10.**

---

## Phase 10 — Rack Screen PWA Shell · Owner: Braydon

### Goal
Stand up the shared device-role picker every screen type boots into, the installable rack-screen PWA behind it (manifest, service worker, IndexedDB rep buffer, an `mqtt.js` client wired to the Phase 3 simulator), the rack-registration/assignment-wait flow, and a one-shot fetch of the active session's roster/exercise/max data — driving a live rep counter with no real hardware. Picker/lifecycle logic (full flow, batch POST) comes in Phase 11.

### Prompt to paste into Claude
```
Working directory: react/. There is a starting-point layout draft at
`edge_athlete_rack_ui.html` in the wider project folder — treat it as a flow/
layout REFERENCE, not a spec to copy verbatim.

## src/App.jsx — Device Role Picker (root route "/", shared by all device types)
On load: check localStorage for `device_role`. If present, immediately swap
the page's `<link rel="manifest">` tag to that role's manifest file and
render straight into that role's view (rack screen this phase; dashboard/
coach views are stubs until Phase 12/14). If absent, render a plain three-
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
picks off of in the Phase 14 drag-and-drop assignment UI, so it must be easy
to read at a glance, not a wall of full-UUID text.
Once rack_number comes back non-null: save it to localStorage, stop polling,
and proceed into RackScreen.jsx at the rack's number as normal.

## Active session fetch — one-shot, no polling
Once rack_number is assigned and known, fire ONE fetch to
GET /api/sessions/active/ (open, no auth) and store the result in component
state before rendering RackScreen.jsx's live panel:
  { session_id, label,
    roster: [ {athlete_id, name, has_data,
               maxes: {exercise_id: max_weight_lbs, ...}}, ... ],
    session_exercises: [ {exercise_id, name, target_sets, target_reps,
                           target_weight_percent, velocity_zone_min,
                           velocity_zone_max}, ... ] }
"Active" = schedule_date is today or earlier, parent session's ended_at is
null — pick the most recent qualifying Session; document whatever tie-break
rule you choose in a code comment. Do NOT poll this endpoint — same one-shot
pattern as rack registration itself. roster[].maxes is each athlete's CURRENT
AthleteMax (Phase 5/7 — latest recorded_at row) per exercise_id, keyed for
O(1) lookup once an athlete and exercise are both picked. An athlete/exercise
pair with no AthleteMax row yet simply has no key in that map — this is the
normal "no max on file yet" case, not an error, and is what triggers the
inline entry prompt in the Phase 11 patch below. This fetched data is what
Phase 11's athlete/exercise picker consumes — do not build an open-list
picker in this phase, that comes fully scoped in Phase 11 directly.

## public/manifest.rack.json
name "Edge Athlete — Rack", display "fullscreen", start_url "/",
orientation "landscape", icons + theme/background colors. (start_url is root,
not a hardcoded rack number — the picker + localStorage above determine
routing, not the URL. Note: this manifest controls how the app LOOKS once
installed and opened — it does not make a device boot into it automatically.
Actual boot-time kiosk launch is an OS-level systemd/autostart concern,
handled separately — see Phase 12 and the RUNBOOK.)

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
mean_velocity, velocity color chip. No set lifecycle / no POST yet (Phase 11).

Delete the reference's Dashboard.jsx 5-second polling pattern — we push, not poll.
Every file opens with a WHY comment (the repBuffer.js comment is a great place
for the "durability boundary" analogy).
```

### Verify
- On first load with no `device_role` set, the picker renders; picking "Rack Tablet" registers the device and shows its id on a "waiting for assignment" screen.
- Manually PATCHing that device's rack_number (simulating the Phase 14 coach action) causes the polling screen to pick it up within ~3s and move into the live rep panel.
- Chrome shows an install prompt once a role is picked; installed app launches fullscreen.
- Running `simulate_node --node-id rack_1` drives the on-screen rep counter and velocity color live.
- Every simulated rep lands in IndexedDB (`getBufferedReps()` grows); killing WiFi mid-stream and reconnecting does not lose already-buffered reps and the mqtt client reconnects.
- `/api/sessions/active/` is fetched exactly once after rack assignment, result stored in state, no polling.

### ✅ Phase 10 Exit Checklist
- [ ] Device role picker renders on first load; choice persists across reload via localStorage
- [ ] Picking a role swaps the manifest link tag to the matching file
- [ ] Rack registration generates a device_id, POSTs it once, and displays it clearly while awaiting assignment
- [ ] Assignment polling picks up a coach-assigned rack_number within ~3s and stops polling
- [ ] `/api/sessions/active/` fetched exactly once after rack assignment, result stored in state, no polling
- [ ] Chrome shows an install prompt once a role is chosen
- [ ] Service worker registered; app shell loads offline
- [ ] Running the Phase 3 simulator drives the rep counter and velocity color live
- [ ] Each rep is written to IndexedDB on arrival; killing WiFi mid-set loses no buffered reps and the client reconnects
- [ ] Reference `Dashboard.jsx` polling pattern deleted
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 11.**

---

# SPRINT 4 — First Vertical Slice + Handoff (Devin's last sprint)

## Phase 11 — Rack Screen End-to-End · Owner: Braydon

### Goal
Turn the shell into the full rack flow: idle → countdown → active set → summary → rest, with the real batch POST at set end, false-set undo, rest timer, a session/group-scoped athlete/exercise picker, automatic makeup detection, and per-athlete target-weight calculation.

### Prompt to paste into Claude
```
Working directory: react/src/rack/. Build on the Phase 10 shell. The batch
endpoint is POST /api/sets/{id}/complete/ (see below). edge_athlete_rack_ui.html
is a layout reference only.

## Athlete + exercise selection — sourced from the Phase 10 active-session fetch
Before a set can start, "idle" needs a selected athlete and exercise. Do NOT
call GET /api/athletes/ or GET /api/programs/?athlete={id} for this picker —
source both dropdowns from the Phase 10 active-session fetch already sitting
in state:
  - Athlete dropdown sources from session.roster. Athletes with
    has_data=true are visually marked (e.g. a checkmark) but still
    selectable.
  - Exercise dropdown sources from session.session_exercises.
  - "idle" shows the selected athlete + exercise instead of a placeholder,
    and set start is disabled until both are chosen.
This is intentionally the simplest thing that works — a coach can also just
select the athlete on the athlete's behalf. Do NOT build NFC in this phase;
leave the athlete-id this picker produces as the one thing an NFC tap would
shortcut into later (see Known Open Items at the top of this doc).

## Screen states (single RackScreen state machine)
  "idle"      -> athlete/exercise picker (above) if not yet selected, otherwise
                 shows linked node + selected athlete/exercise, waiting to start
  "countdown" -> 3-2-1 before a set
  "active"    -> live reps streaming in (from Phase 10 subscribe + repBuffer)
  "summary"   -> set just ended; shows reps_completed, avg/peak velocity
  "rest"      -> rest timer counting down to next set, then back to idle/countdown

## Makeup auto-detection
If the selected athlete has has_data=true, the Set created in step 1 of the
set lifecycle (POST /api/sets/) automatically includes is_makeup: true — no
separate UI toggle. The frontend infers this purely from has_data.

## Target weight calculation + missing-max entry
Once BOTH an athlete and exercise are selected, look up
roster[athlete].maxes[exercise_id] from the Phase 10 fetch:
  - If present: compute displayed target weight client-side as
    session_exercises[exercise].target_weight_percent * max_weight_lbs / 100
    and show it alongside the velocity zone. No network call.
  - If ABSENT (no AthleteMax on file for this athlete/exercise pair yet):
    do NOT block set start. Instead show a small inline "Set starting
    weight" numeric field in place of the calculated target. Submitting it
    calls POST /api/athlete-maxes/ (Phase 7) with
    { athlete: athlete_id, exercise: exercise_id, max_weight_lbs: <value> },
    then immediately computes and displays the target the same way as the
    present case above using the just-entered value (no refetch of
    /api/sessions/active/ needed — update local state directly). The set can
    proceed normally right after.

## Set lifecycle
1. On set start (coach/athlete taps start, or first rep arrives after countdown):
   POST /api/sets/ with { session: session_id (from Phase 10 fetch), athlete:
   selected athlete_id, node, exercise: selected exercise, set_number,
   is_makeup } to create the Set, keep the returned set_id.
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
- With no athlete/exercise selected, "idle" shows the picker (sourced from the active session, not open lists) and set start is disabled.
- Selecting an athlete + exercise, then running a full simulated session (idle → countdown → active → summary → rest) produces **exactly one** `POST /api/sets/{id}/complete/`, and the created `Set` row has the correct `athlete`/`exercise` values.
- Selecting an athlete with `has_data: true` automatically creates a Set with `is_makeup: true`.
- An athlete/exercise pair with no AthleteMax shows the inline entry field; submitting it posts to `/api/athlete-maxes/` and immediately displays a computed target with no refetch.
- The server's rep count for that set matches what streamed in.
- The False-Set button returns to idle and writes zero reps (`Rep.objects.filter(set=...).count() == 0`, `Set.is_false_set == True`).
- Rest timer counts down and returns to idle, keeping the same athlete/exercise selected for the next set.
- No repeated calls to `/api/sessions/active/` occur during a full cycle.

### ✅ Phase 11 Exit Checklist
- [ ] Athlete/exercise picker sources only from the active session's roster/exercises, never the open list endpoints; set start is disabled until both are chosen
- [ ] Full flow idle → countdown → active → summary → rest works against the simulator
- [ ] Exactly one `complete/` POST per set, with correct rep count, summary stats, athlete, and exercise
- [ ] Selecting a `has_data: true` athlete automatically sets `is_makeup: true`, no manual toggle
- [ ] Target weight calculates correctly when a max exists; missing-max entry posts and displays immediately with no refetch
- [ ] IndexedDB buffer cleared only after a successful POST
- [ ] False-set undo returns to idle and writes no reps
- [ ] Rest timer works; set_number increments; athlete/exercise selection persists across sets in the same rotation
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 12.**

---

## Phase 12 — Team Dashboard Kiosk · Owner: Devin

### Goal
Build the base station's own kiosk display — the read-only room scoreboard — subscribing to `edgeathlete/dashboard/state`.

### Prompt to paste into Claude
```
Working directory: react/src/dashboard/. Route /dashboard. No login, read-only.
Subscribe over mqtt.js (Phase 10 client) to edgeathlete/dashboard/state.

## Sections (per the product's dashboard scope)
1. Rack status grid — one tile per rack, color-coded green/yellow/red using the
   SAME velocity color system used everywhere else. Updates on rack/dashboard state.
2. Live leaderboard — athletes ranked by a session metric (e.g. best avg velocity),
   updates on "leaderboard_update" messages.
3. Fun facts / insights — VISUALLY PROMINENT (bigger than in earlier drafts).
   Rotating room insights (e.g. "fastest rep of the session", "most reps").
4. Summary block — room-wide session stats (total sets, total reps, athletes
   active). Optionally surface the active group/session label here (e.g.
   "Varsity Lifting — Week 3, Day 2") by reusing GET /api/sessions/active/
   (Phase 10) — no new endpoint needed. Skip this if time-boxed; it's cosmetic.
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
Phase 10 does not do this on its own.
```

### Verify
- With the simulator + a rack screen running, completing a set updates the rack status grid within 2s and moves the leaderboard.
- Coach alerts render in their own visually separated section.
- Rebooting the Pi lands directly on the fullscreen dashboard with no manual steps.

### ✅ Phase 12 Exit Checklist
- [ ] Rack status grid updates within 2s of a simulated set completing
- [ ] Leaderboard, fun-facts/insights (prominent), and summary block all update live
- [ ] Coach alerts render in their own separated section
- [ ] Read-only, no login, kiosk-legible
- [ ] A cold reboot of the Pi auto-launches the dashboard fullscreen with no manual steps, via the extended `privacy-dots.service`
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 13.**

---

## Phase 13 — Real ESP32 Firmware v1 · Owner: Derrilon

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
- The same rep appears on the rack screen within 1s (swap the simulator for the real node in the Phase 10/11 flow).
- Pulse messages update the node's `Node` row via the Django subscriber.

### ✅ Phase 13 Exit Checklist
- [ ] A physical rep produces one `rep` message with a plausible velocity
- [ ] Payload shape exactly matches `parse_rep_payload`
- [ ] Same rep appears on the rack screen within 1s
- [ ] Pulse updates the `Node` row
- [ ] Noise-reduction hook clearly marked, not implemented
- [ ] Top-of-file WHY comment present

**STOP. Do not continue past the handoff gate until it fully passes.**

---

## Sprint 4 Handoff Gate · Owner: Devin

This is the gate before Devin exits. All of it must pass.

- [ ] `RUNBOOK.md` complete: start/stop, firmware flashing, MQTT test commands, full integration-test steps, common failure modes
- [ ] Architecture diagram present (Mermaid, in `RUNBOOK.md`) showing nodes → broker → Django/Postgres and broker → browser clients over WS
- [ ] A dry run of the full session flow with **Devin observing only, not helping**
- [ ] Every teammate has flashed firmware once and run the integration test once

**STOP. Devin exits. Sprints 5–6 run without him.**

---

# SPRINTS 5–6 — Team Alone

## Phase 14 — Coach Tablet · Owner: Braydon

### Goal
Build the coach tablet: PWA shell (`manifest.coach.json`, route `/coach`, JWT
login gate), the consolidated live-room-state view (subscribe
`edgeathlete/coach/state`, alerts, basic graphs), the Room Layout drag-and-drop
rack/screen assignment section, group/block/session browsing, CSV upload with
stub-exercise confirmation, red/yellow/green status dots, athlete max entry,
and the max progression chart.

### Prompt to paste into Claude
```
Working directory: react/src/coach/. Builds on Phase 9 (broadcast), Phase 4
(coach-only endpoints), and Phases 6/7 (CSV import, status, roster-status,
athlete maxes).

## Shell
Same PWA pattern as the rack screen: manifest.coach.json, route /coach, JWT
login gate reusing simplejwt from Phase 4.

## Live room state
Subscribe to edgeathlete/coach/state (Phase 9). Render abnormal-performance
alerts/suggestions and basic graphs in one consolidated view — no multi-page
tabs for this section, per the original spec's deferred "separate Room/
Athletes/Racks/Analytics tabs" scope, which stays deferred.

## Room Layout — drag-and-drop
Grid of rack slots (1..N) plus two source pools: "Unassigned Screens"
(GET /api/racks/unassigned/, shown by short device id — the same id the rack
screen displays on its own waiting-for-assignment state) and nodes available
for reassignment (GET /api/nodes/). Dragging a screen onto a slot calls
PATCH /api/racks/{device_id}/; dragging a node calls PATCH /api/nodes/{node_id}/.
One shared drag-and-drop component for both entity types.

## Group/Block/Session browsing
1. Groups list — GET /api/groups/, each row shows a rolled-up status dot.
2. Group detail — GET /api/blocks/?group={id}, same status-dot pattern.
3. Block detail — GET /api/sessions/?block={id}, same status-dot pattern,
   plus a roster-completion summary per session (e.g. "3/8 athletes") from
   GET /api/sessions/{id}/roster-status/.
4. Session detail — full roster from roster-status/; clicking a "no data"
   athlete is the entry point for a makeup hand-off — reuse the SAME
   drag-and-drop/assignment pattern built above (assign this athlete+session
   to a rack), not a new interaction pattern.

## CSV upload flow
"Upload Session CSV" action (from Group or Block view) posts to
/api/sessions/upload/ (Phase 6). On response, if any exercises were stubbed,
show a confirmation modal per stubbed exercise (tags, target numbers,
Confirm/Reject), calling PATCH /api/exercises/{id}/confirm/ (Phase 6).

## Status dots
One reusable StatusDot.jsx ("red"|"yellow"|"green"), used identically at
Group/Block/Session levels — same one-component principle as the shared
drag-and-drop component above.

## Athlete max entry
On an athlete's profile/roster view, add a simple form (exercise picker +
weight input) that POSTs to /api/athlete-maxes/ (Phase 7) — the same
endpoint the rack screen's inline prompt uses. This lets a coach pre-load
maxes ahead of a session instead of only entering them reactively mid-set at
the rack. Show the athlete's current max per exercise (latest AthleteMax row)
alongside the entry form for reference.

## Max progression chart
On the same athlete profile view, once an exercise is selected, fetch
GET /api/athlete-maxes/?athlete={id}&exercise={id} (Phase 7) and render a
simple line chart (max_weight_lbs over recorded_at) showing that athlete's
full max history for the exercise — this is a pure read, reuses data already
being written by the entry form above, no new backend work beyond the Phase 7
GET endpoint.

Every file opens with a WHY comment.
```

### Verify
- Login gate, live room state, and Room Layout drag-and-drop rack/node assignment all work as originally specified.
- Navigating Group → Block → Session shows correctly rolled-up status dots at every level, matching the backend's computed status.
- Uploading a CSV with one new exercise surfaces exactly one confirmation modal; confirming updates the catalog, rejecting removes the stub and its SessionExercise link with no leftover references in the UI.
- Selecting a "no data" athlete from a session's roster successfully routes a makeup set to a chosen rack, reusing the existing assignment pattern.
- Athlete max entry form posts correctly; progression chart renders full history for a selected exercise.

### ✅ Phase 14 Exit Checklist
- [ ] Login gate, live room state, and original drag-and-drop rack/node assignment all work
- [ ] Groups/Blocks/Sessions browsable with correctly rolled-up status dots
- [ ] CSV upload + stub-exercise confirmation works end-to-end, no orphaned records after rejection
- [ ] Makeup-athlete hand-off reuses the existing assignment pattern, not a new one
- [ ] `StatusDot` is a single shared component used at all three levels
- [ ] Athlete max entry form posts correctly; progression chart renders full history for a selected exercise
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 15.**

---

## Phase 15 — Fatigue Scaffold · Owner: Carl

### Goal
`django/event_handler/ml/inference.py` with a REAL function signature (e.g. `predict_fatigue(set_summary: dict) -> dict`) and a real call site firing after set-complete (Phase 4/9). Returns a **stub** value. Not a trained model — training is explicitly out of scope.

**Note — do not conflate with the Phase 5/8 insights scaffold:** this fatigue
scaffold fires **per set**, immediately after set-complete.
`ml/analyze_session.py` / `generate_insights` (Phase 5/8) fires **per
session**, at session-done. They are two separate stubs with separate
trigger points — do not merge them into one function or one call site.

**STOP. Review before moving to Phase 16.**

---

## Phase 16 — Security Hardening · Owner: whole team
Verify JWT covers all coach-only endpoints (should already be true from Phase 4 and the Phase 5–8/14 coach-only additions). Move Mosquitto off `allow_anonymous true` to ACLs/auth on both listeners. Rate-limit login. Confirm no coach-only path is reachable unauthenticated.

**STOP. Review before moving to Phase 17.**

---

## Phase 17 — Firmware Hardening & Additional Mounts · Owner: Derrilon
Waist and wrist mount thresholds, WiFi reconnect logic, enclosure v1. Resolve (or keep hooked) the noise-reduction location decision.

**STOP. Review before moving to Phase 18.**

---

## Phase 18 — Full Integration Test & Demo Prep · Owner: whole team
Seed script, one-command `start.sh`, `DEMO_SCRIPT.md`, screen-recording backup. The full session script must run clean at least twice in a row before demo day.

Add to the seed script and `DEMO_SCRIPT.md`: seed at least one TrainingGroup
with a Block and a CSV-uploaded Session (including at least one intentionally
unrecognized exercise name, to demo the stub-confirmation flow), and include
one deliberately "missing" athlete to demo the makeup flow and its effect
(or non-effect) on team_completion_time. The full session script (already
required to run clean twice before demo day) should now also cover: CSV
upload → stub confirm → run session → one athlete makeup → status dots
updating correctly at all three hierarchy levels.

---

## Stretch Goals / Explicitly Deferred (only after all phases complete)

Don't let these block a phase — they're intentionally punted:

- **Noise-reduction location** (ESP32 firmware vs. rack screen) — leave a hook on both sides; whichever gets built first wins.
- **Real trained fatigue model** — Phase 15 is a scaffold only.
- **Real trained insights model** — Phase 5/8 is a scaffold only (same status as the fatigue model, separate stub).
- **Coach tablet multi-page expansion** (separate Room / Athletes / Racks / Analytics tabs for the live-room-state section) — the group/block/session drill-down built in Phase 14 is a different, narrower kind of multi-view growth (planning-data navigation, not a general tabbed admin app); the original Room/Athletes/Racks/Analytics tab vision for the live-state section itself remains deferred.
- **Consumer "One Device" mode / PvP BLE mode** — not in this spec at all.
- **3D bar-path tracing** — future hardware, not this project.

---

## v2 Changelog (summary)

For quick reference — the full detail for each item lives in its phase above.

- **Phases 1–4:** unchanged from v1, already built.
- **Phases 5–8 (new):** Group/Block/Session hierarchy, Exercise catalog + Tag
  system, CSV import pipeline, red/yellow/green status computation, makeup
  flow + `team_completion_time`, append-only `AthleteMax` tracking, and the
  `generate_insights` scaffold.
- **Phase 9 (was Phase 5):** Django Broadcast Publisher — unchanged content, renumbered.
- **Phase 10 (was Phase 6):** Rack Screen PWA Shell — unchanged content, plus one addition: the one-shot `/api/sessions/active/` fetch.
- **Phase 11 (was Phase 7):** Rack Screen End-to-End — athlete/exercise picker rebuilt scoped to the active session from the start (not built open then redone); added makeup auto-detection and target-weight calculation + missing-max inline entry.
- **Phase 12 (was Phase 8):** Team Dashboard Kiosk — unchanged content, renumbered, one optional cosmetic addition (active session/group label).
- **Phase 13 (was Phase 9):** Real ESP32 Firmware v1 — unchanged content, renumbered.
- **Sprint 4 Handoff Gate (was Sprint 3):** unchanged content; moved sprints because the firmware phase it depends on moved from Phase 9 to Phase 13.
- **Phase 14 (was Phase 10):** Coach Tablet — original scope (shell, live room state, Room Layout drag-and-drop) unchanged, merged with group/block/session browsing, CSV upload + stub confirmation, status dots, athlete max entry, and the max progression chart. Expanded to full depth now instead of being left light for later.
- **Phases 15–18 (were Phases 11–14):** unchanged content, renumbered; Phase 15 gained a clarifying note distinguishing it from the Phase 5/8 insights scaffold; Phase 18 gained a light patch to include the CSV/group/session/makeup flow in the demo script.
- **Architecture Decisions:** two entries revised in place — sprint/handoff timing (moved from end of Sprint 3 to end of Sprint 4) and the "coach tablet is one page" decision (narrowed to describe what's still true after Phase 14's drill-down views). One new entry added documenting the rejected node-side-durability alternative considered during design.
- **Known Open Items:** four new items added (group reassignment mid-flight, exercise catalog editing post-confirmation, the insights model itself being unbuilt, retroactive max entry not recalculating earlier sets); five original items had their phase-number cross-references corrected for the renumbering.
