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

**This is the single authority for the system.** Read it before changing anything;
when it disagrees with a comment in the code, this wins and the comment gets fixed.

| Document | What it holds |
|---|---|
| **`_SPEC.md`** (this) | The system: architecture, hierarchy, schema, and the derivation rules |
| `_MESSAGE_CONTRACT.md` | Exact request/response shapes for every endpoint |
| `docs/_PATCH_NOTES.md` | What changed on the merge branch, by phase, with a click path each |
| `_RUNBOOK.md` | Operating the base station |

> **The merge canon was folded into this document on 2026-07-30** and its files
> were deleted. Sections carrying a **§ number** (§2 … §10) came from it and are
> current.
>
> ⚠️ **Code comments say "the merge canon". They mean this document.** Roughly
> eighty comments across `django/` and `react/` cite it by section (`canon §6.3`)
> or by decision number (`merge canon D15`). Both numbering systems were preserved
> verbatim in the fold precisely so those references still resolve — look them up
> in §2–§10 and the decision log (§9) below.

**⚠️ The Phase 1–18 plan below is historical.** It was the original build order,
kept for provenance. For what is actually built, read "Where the build actually is"
just below. Do not work through those phases as a to-do list.

The original instruction, which still applies if you are running a phase from that
plan: work through each phase in order, do not proceed until the current one's exit
checklist passes, and paste only the current phase into a fresh conversation.

When a prompt says "read the reference project," that means use your file tools to inspect the Privacy-Dots-V2 repo's contents before writing any code. Do not guess at structure or config — derive it from what you actually find. The reference lives beside this repo (upstream: `git@github.com:devi-walto/Privacy-Dots-V2.git`); it stays **read-only**.

Phases 1–4 are complete. Phases 5–13 (through the Sprint 4 handoff gate) are written at full paste-ready depth. Phases 14–18 (team-alone work) are also now at full depth — Phase 14 (Coach Tablet) in particular was expanded early because it absorbed the new group/block/session/CSV work, rather than being left light and revisited later as originally planned.

---

---

## ⚑ Where the build actually is (2026-07-30)

**This document is now the single authority for the system.** The merge canon was
folded into it on 2026-07-30 and its files were removed. The two companions stay
separate on purpose: `_MESSAGE_CONTRACT.md` holds
exact request/response shapes, and `docs/_PATCH_NOTES.md` holds what changed on the
merge branch with a click path for each thing.

Everything below the "Data Models" heading that carries a **§ number** came from
the merge canon and is current. The **Phase 1–18 plan further down is historical**
— it was the original build order and is kept for provenance, not as a to-do list.

**The full timeline — original phases and the merge interleaved, with what is
genuinely left — is in "The build, in the order it actually happened" below.**
Short version, verified against the repo rather than from memory:

| Original phase | State |
|---|---|
| 1 Repo bootstrap · broker · RUNBOOK | ✅ built |
| 2 Data models & migrations | ✅ built — and since extended; see §4/§5 |
| 3 MQTT pulse pipeline & simulator | ✅ built (`realtime/`) |
| 4 REST API + batch set-complete | ✅ built |
| 5–10 Planning, groups, CSV, reports | ✅ built — **reshaped by the merge**, see §4 and `docs/_PATCH_NOTES.md` |
| 11 Rack screen end-to-end | ✅ built · **FROZEN**, see §2.1 |
| 12 Team dashboard kiosk | ✅ built (`/dashboard`) |
| 13 Real ESP32 firmware v1 | ⛔ **not in this repo** — no `firmware/` directory exists |
| 14 Coach tablet | ✅ built — this is what the merge landed |
| 15 Fatigue scaffold | ⛔ not built — still a stub, deliberately |
| 16 Security hardening | ⚠️ **partial** — unscoped coach APIs require active staff; tenant scoping and MQTT authentication remain open |
| 17 Firmware hardening & mounts | ⛔ not built |
| 18 Full integration test & demo prep | ⛔ not done |

**The merge's own phases (P0–P15) are all complete**, tagged `p1-complete` …
`p15-complete`. 280 backend tests, 131 frontend, migrations `0008`→`0017`.


## Known Open Items (read before starting the phase they touch)

These are real gaps, not stretch goals — they were deliberately deferred to get a demo-able slice built in a tight window. Whoever starts the referenced phase should resolve or explicitly re-defer each one rather than being surprised by it mid-phase:

- **Batch-POST failure/retry (affects Phase 11, hardens in Phase 16/18):** if `POST /api/sets/{id}/complete/` fails (e.g. an AP drop at the exact moment a set ends), there is currently no defined retry/backoff — the buffer only clears on success, but nothing describes what happens on failure. Fine for a controlled demo; needs a real answer before unattended/production use.
- **Live cross-rack progress refresh (RESOLVED — retired 2026-07-20):** was deferred as "2b" — pushing a live update to a rack already displaying an athlete when that same athlete completes a set at a *different* rack. **Retired** by the Phase 11 Step 2 **single-rack ownership rule**: an athlete can only be checked in at one rack at a time (checking in elsewhere transfers ownership via a newer `RackCheckIn`), so their progress can't change anywhere else while they're displayed here. Fetch-on-check-in is sufficient; no live cross-rack push is needed. Kept here as a record of the decision.
- ✅ **RESOLVED for the athlete route (merge P13, 2026-07-29): Analytics response contract.** `.../athlete/{id}/` now has an exact field list in `_MESSAGE_CONTRACT.md` — athlete, summary, per-exercise aggregates, and per-set reps. The worry recorded here was real and came true in the other direction: the coach front end was written against a shape nobody had pinned down, and it broke on arrival. **`GET /api/analytics/session/{id}/` is still prose-only** — same trap, still unsprung.
- ⚠️ **The `edgeathlete/coach/state` channel is unused at both ends (found 2026-07-30).** `_MESSAGE_CONTRACT.md` documents the topic, and `publish_coach_state()` exists in `realtime/broadcast/publisher.py` — but **nothing ever calls it**, and no client subscribes to it. The coach view takes its live updates from `edgeathlete/dashboard/state` like the wall does. This is plausibly deliberate headroom: the contract reserves the topic for fatigue alerts, which are Phase 15 and not built. **The decision to make:** wire it up when Phase 15 lands, or delete the helper and the contract entry. Leaving a documented topic that no code path reaches is how someone later spends an afternoon debugging a message that was never sent.
- **No rack "unassign" path (affects Phase 14):** only registration + assignment exist; there's no way to free a rack number back to the unassigned pool if a screen is retired or replaced.
- **Clock reliability on the offline Pi (affects Phase 1/RUNBOOK, Phase 18):** the base station never touches the internet, so there's no NTP sync. If it lacks a hardware RTC, a cold boot could start with a wrong system clock, silently corrupting every `timestamp` field. Needs either an RTC module or a manual time-set step documented in the boot procedure.
- **Stale `RackScreen` rows (affects Phase 16):** if a screen's `localStorage` is ever wiped, it registers a brand-new `device_id` and the old row is orphaned at its old rack number with no cleanup.
- ✅ **RESOLVED (merge D12/D13): Group reassignment mid-flight.** Athlete↔TrainingGroup is a many-to-many, an athlete can be in several groups at once, and what they train is the MERGED plan of the groups participating in the session — see §6.2. Membership is current-state only and never rewrites history: past sessions and sets stay attached to whatever they ran under. Original note:  if an athlete's `group` changes while a `TrainingSession` tied to their old group is still in progress (not yet green/marked done), no rule is defined for whether they still appear on that session's roster. Current design snapshots roster at CSV-upload time, so this is likely fine by construction but untested against a live reassignment mid-session.
- **Exercise catalog editing after confirmation (affects Phase 6):** once an `Exercise` is confirmed (`is_stub=False`), there's no defined path to later edit its tags or fix a name typo — only the stub-confirmation flow touches the catalog today.
- **Insights model itself (affects Phase 5/8):** `generate_insights` is a stub returning `[]`. Choosing/training the actual local model and defining what "notable" means for `flagged_for_review` is explicitly out of scope here, same as the fatigue-model stub.
- **Retroactive max entry vs. already-completed Sets (affects Phase 5/7/11):** if an athlete's first-ever AthleteReferenceMax gets entered mid-session (via the Phase 11 inline prompt) AFTER they've already completed earlier sets in that same session using no calculated target (or a stale one), those earlier Sets are not recalculated or flagged — the new reference only affects target-weight display going forward from the moment it's entered. No retroactive recomputation is in scope for this spec. (See the finalization-gate item below, which is the intended long-term home for recomputation.)
- ⚠️ **PARTLY RESOLVED (merge P4): Coach publish/finalization gate + outlier-robust reference recalc.** Ending a training day now recalculates reference maxes from what athletes actually lifted and writes them with `source=estimated` and a `source_session` link (canon D10) — so the "written only by direct entry" half of this item is no longer true. **What is still open:** there is no coach *review-then-publish* gate (recalculation happens on end-of-day, unreviewed), no outlier-robust fitting, and no way to strike an anomalous set and re-run. The original note follows, still accurate on those points.
  - today `AthleteReferenceMax` rows are written only by direct entry (`source=manual`). The intended finalization flow is deferred: a coach reviews a session's data in a filterable/searchable summary, hits "Publish" (an application-level Python service run in a transaction — NOT a Postgres trigger — reusing the `mark-done` hook), and only then are velocity-`estimated` reference maxes computed and written (each linked via `source_session`). Two questions ride on it: (1) the estimation must be robust to a single anomalous set skewing the fit — e.g. drop reps outside the velocity zone or use an outlier-resistant method — since one bad rep could otherwise poison the reference; (2) a coach striking an anomalous set AFTER publish should re-run that service and APPEND corrected rows (append-only supersede, never a mutation). No stored "published" state, no set-strikethrough flag, and no recalc service exist yet — this is the designed-for future, captured so Phase 7/8 build toward it rather than around it.

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

**WT901 central-host override:** For nodes provisioned with
`acquisition_kind="wt901_ble"`, `docs/_ADR_RACK_BLE_LIVE_WORKFLOW.md` supersedes
the ESP32/node transport below. One central Pi/laptop owns BlueZ discovery and
connections; rack screens are browser clients and TVs mirror the dashboard.
Discovery and health are accepted. WT901 rep detection, accepted-event transport,
and eight-sensor adapter capacity remain deferred. The MQTT flow below still
describes nodes provisioned with `acquisition_kind="mqtt"`.

**Hosted Rack Helper direction:** Product direction selects a native Rack Helper as
the primary hosted BLE path and delegates its requirements
to [`docs/_RACK_HELPER_SPEC.md`](docs/_RACK_HELPER_SPEC.md). Its architecture and
implementation contracts remain draft, not accepted implementation behavior. The
local/Pi decisions below stay authoritative until an ADR resolves the proposal's
open platform, endpoint, ingestion API, permanent `Rep` creation boundary,
retention, and release decisions.

### End-to-end user flow
1. A coach powers on the Pi. It boots the Docker stack and broadcasts its private AP. Every node and screen in the room joins that AP; nothing needs internet.
2. Each **node** (ESP32 + MPU-6050) computes velocity on-device and publishes each completed rep as its own MQTT message, plus a pulse/heartbeat on an interval. It never streams raw accelerometer data.
3. A **rack screen** (tablet PWA) subscribes over MQTT-over-WebSockets to its linked node's rep topic. As each rep arrives it buffers the rep in IndexedDB and live-updates its UI.
4. When the set ends (0.75s stillness on the node closes the last rep; the athlete/coach confirms end on the screen), the rack screen batch-POSTs the whole set — summary + every rep — to the base station in one request.
5. The base station writes that one set (and its reps) to Postgres in a single transaction, then publishes broadcast events to Mosquitto: leaderboard changes, rack-state changes, and coach alerts.
6. The **team dashboard** (the Pi's own kiosk browser) and the **coach tablet** subscribe to their broadcast topics and update live — a room-wide scoreboard and a single coach admin view.

**v2 addition:** a coach now plans training ahead of time — designing workouts in a spreadsheet, exporting a CSV, and uploading it to create a Group → Block → TrainingSession → planned-exercise structure before any rack even powers on. See **Phases 5–8** for the full design.

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

**Revised in v2:** Phase 14 now includes group/block/session drill-down navigation (Groups list → Block detail → TrainingSession detail) and a CSV upload flow, which are additional views/routes beyond the original single consolidated page. This is a narrower kind of multi-view growth than the originally-deferred "separate Room/Athletes/Racks/Analytics tabs" vision — it's drill-down navigation into planning data, not a general tabbed admin app — but it does mean "one page" no longer describes the coach tablet literally. The live-room-state + alerts + basic-graphs portion, and the Room Layout drag-and-drop assignment section, remain exactly as originally specified and stay consolidated in one view.

### Local fatigue ML is scaffolded, not trained
Fatigue detection gets a real interface (`ml/inference.py`) and a real call site (fires after set-complete), but the function returns a stub value in this spec. Training a real model is explicitly out of scope.

**v2 note:** a second, separate ML scaffold is introduced in Phase 5/8 — `ml/analyze_session.py` / `generate_insights`. These are two distinct stubs with separate trigger points (fatigue fires per-set, insights fires per-session-done) — do not merge them into one function or call site. See Phase 15 for the explicit clarifying note.

### Fresh start in the Edge-Athlete repo
Do **not** rename or port Privacy-Dots-V2's git history. Privacy-Dots-V2 stays untouched as a read-only reference; Edge Athlete is bootstrapped clean, pulling **patterns (not history)** from the reference.

---

---

## §2. Hard constraints (never violated)

### §2.1 Rack files — preserve behavior unless an approved feature spec changes it

```
react/src/rack/RackScreen.jsx      react/src/rack/Idle.jsx
react/src/rack/CheckInList.jsx     react/src/rack/RackSetup.jsx
react/src/rack/WeightPad.jsx       react/src/rack/velocity.js
react/src/db/repBuffer.js          react/src/device.js
react/src/ (service worker + manifest.* + icons)
```

The merge-era freeze is lifted only for behavior governed by an accepted feature
spec and ADR. `docs/_RACK_BLE_LIVE_WORKFLOW_SPEC.md` and its ADR authorize the
rack-local sensor gate, rack-mode credential cleanup, and the minimal
`RackScreen.jsx` set-start integration. It also authorizes the controller/observer
changes required by AC16-AC24: one fenced controller and read-only mirrors.
Unrelated cleanup or redesign of these files remains out of scope.

### §2.2 Frozen API contracts
These endpoints keep their **exact response shape** (key names, nesting, types). Their *internals* may be
rewritten and their *coverage* may widen, but a rack tablet must not be able to tell the difference:
`/sessions/active/`, `/sessions/active/status/`, `/sessions/active/athlete/{id}/progress/`, `/sets/`,
`/sets/{id}/complete/`, `/racks/{n}/checkin/`. The exact frozen shape of the progress endpoint is written out
in §6.3 — that one is the highest-risk seam in the merge.

Rack controller rollout may add required controller headers/envelopes and stable
`409` responses to rack mutations while preserving every successful response shape.

### §2.3 Other hard constraints
- **The role splash / device-role picker stays.** The boot screen every role lands on is ours and remains the
  entry point (it must survive the `App.jsx` reconciliation in P7).
- **Braydon's root-level `react/src/RackScreen.jsx` is dropped from the run path.** It is his own separate
  file; it does **not** replace ours, and ours does not move.
- **Carl's dashboard page stays near-untouched**, preserved as `/coach/setup`. Integration may *reach* it
  (§6.4); its internals are not rewritten.

If a resolution would change any of the above, **the resolution is wrong.**

---

---

## §3. Governing principles (apply in order when a case isn't spelled out)

1. **Protected set (§2) always wins.** No exceptions.
2. **Rack / athlete-facing runtime → ours.** Adopt none of his rack-side reimplementation.
3. **Coach / dashboard / reports / planning front end → his.** Bend our backend to serve it rather than
   reshaping his UI.
4. **Derived over stored.** If a coach screen needs data we can *compute* from tables we already own, build a
   **derived endpoint in `services/`** — do **not** add a table to store it. New tables are only for data that
   is genuinely *authored* and not derivable.
5. **Backend style & docs → ours.** Refactor his features to our conventions and document every new route in
   `_SPEC.md` + `_MESSAGE_CONTRACT.md`.
6. **Database → additive union.** Tack columns onto existing tables; where two tables collide, keep whichever
   is least work and drop the other. One table at a time.
7. **Still tied → keep the canon** (clean / documented / reusable). Prefer deleting *duplicated* effort over
   deleting *distinct* capability.

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
| `MotionEvent` model | **Delete.** Replaced by `Athlete` / `Program` / `TrainingSession` / `Set` / `Rep`. |
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
             acquisition_kind (provisioning-owned mqtt/wt901_ble; mqtt default),
             mount_type (choices: bar/waist/wrist), firmware_version,
             battery_level (Int, nullable), signal_strength (Int, nullable),
             last_seen (DateTime, nullable), is_active (Bool, default True)
RackScreen — device_id (CharField, unique, client-generated at first setup),
             rack_number (Int, nullable — null means "awaiting coach
             assignment"), last_seen (DateTime, auto)
Athlete    — organization, name, nfc_tag_id (organization-local unique, nullable), created_at (auto), notes (Text, blank)
Program    — athlete (FK→Athlete), exercise (FK→Exercise), target_sets (Int), target_reps (Int),
             target_weight_lbs (Float), velocity_zone_min (Float), velocity_zone_max (Float)
TrainingSession    — label, started_at (NULLABLE since merge P14), ended_at (nullable),
                athletes (M2M→Athlete), notes
                ⚠️ started_at NULL means created-but-not-started: a day a coach
                set up ahead of time. So "the active session" means STARTED and
                not ended, never merely un-ended. One place decides that:
                services/active_session.py. Never order sessions by -started_at
                without excluding nulls — Postgres sorts NULLs FIRST descending,
                so an unstarted future day would read as the newest thing.
ScheduledSession — training_program (FK), training_program_workout (FK),
                date, session (FK→TrainingSession, NULLABLE), created_at
                unique(training_program, date). The calendar. A slot is a PLAN;
                `session` fills in when a coach creates that day. Generated when
                a block is deployed (cadence picks weekdays, duration_weeks
                stops it) and FROZEN after — editing the block's cadence later
                moves no existing slot. Moving a slot is one `date` write.
Set        — session (FK→TrainingSession), athlete (FK→Athlete), node (FK→Node, nullable),
             exercise (FK→Exercise), set_number (Int), weight_lbs (Float, nullable), started_at, ended_at (nullable),
             reps_completed (Int, default 0), avg_velocity (Float, nullable),
             peak_velocity (Float, nullable), is_false_set (Bool, default False)
Rep        — set (FK→Set), rep_number (Int), timestamp, mean_velocity (Float),
             peak_velocity (Float), duration_ms (Int), velocity_color (Char)
```

**`Rep` rows are created ONLY via the batch set-complete endpoint, never one at a time.**
**`RackScreen` is the physical screen's own identity — separate from `Node.rack_number`, which tracks which sensor is linked to a rack. A rack screen and its sensor node are assigned independently.**
**Exercise-identity note (built early, sprint of 2026-07-17, branch `exercise-catalog`):** every movement reference is `FK→Exercise` (the catalog below), never free text. At the time that meant `Program.exercise`, `Set.exercise`, and `AthleteReferenceMax.exercise`, converted together via a reversible backfill migration (`0005_link_models_to_exercise_catalog`) — deliberately one step further than the original plan, which would have left `Program`/`Set` on text. Half-normalizing breaks the rack endpoint's id-vs-name lookup, so it was all three or none. `Program` has since been dropped (`0011`); the rule carried forward to every prescription row in the `Training*` hierarchy.

### Extended in Phase 5+ (Group/TrainingSession Hierarchy & Athlete Max Layer)

New models, built in Phase 5, plus extensions to three of the original seven.
Full field-level detail lives in the Phase 5 prompt below — this is the
summary view:

```
TrainingGroup — name, created_at
                (P11: the single `coach` FK is GONE — see TrainingGroupCoach.
                Several staff run one group; one field could not say that.)
TrainingGroupCoach — training_group (FK→TrainingGroup), coach (FK→User),
                role ("head" | "assistant"), created_at
                unique(training_group, coach). One head at a time: naming a
                new head demotes the incumbent. ⚠️ A row here is a STATEMENT,
                not a permission — nothing enforces it yet, by decision.
Block         — training_group (FK→TrainingGroup), name, order (Int)
Tag           — name (unique). ⚠️ Movement labels on Exercise ONLY. Block
                catalog labels are BlockCategory — separate on purpose, or
                "Upper" would mean a body region or a grade level depending
                on what it hangs off.
BlockCategory — name (unique), created_at
                TrainingBlock.categories is M2M → several per block, because
                the labels sit on different axes ("Off-season" AND "Football").
                Catalog filtering is ANY-OF.
Exercise      — name (unique), tags (M2M→Tag), is_stub (Bool), created_at
                (standard auto-increment PK — no custom ID assignment logic)
SessionExercise — session (FK→TrainingSession), exercise (FK→Exercise), target_sets,
                target_reps, target_weight_percent (Float — % of the
                athlete's own max, not an absolute weight), velocity_zone_min,
                velocity_zone_max, coach_notes
SessionInsight  — session (FK→TrainingSession), athlete (FK→Athlete, nullable = team-
                level), content (Text), source (choices: local_model/coach_note),
                flagged_for_review (Bool), created_at
AthleteReferenceMax — athlete (FK→Athlete), exercise (FK→Exercise),
                reference_weight_lbs (Float), rep_basis (Int, default 1),
                source (choices: manual/estimated), source_session (FK→TrainingSession,
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
           group only; reassigning it never rewrites historical TrainingSession/Set
           data, which stays attached to whatever Block/TrainingSession it actually
           happened under.
TrainingSession  EXTENDED — ❌ SUPERSEDED, DO NOT BUILD. This proposed
           `block` FK + `schedule_date` on TrainingSession. The merge chose the
           opposite shape (canon D20, built in P14): the schedule lives in its
           OWN table, `ScheduledSession`, so no model is asked to mean two
           things — a TrainingSession stays "a day that is real". The decoupling
           this line wanted is achieved by the slot's nullable `session` FK plus
           TrainingSession.started_at being nullable. Building both would give
           two answers to "when is this day".
Set      EXTENDED — is_makeup (Bool, default False) — excluded from
           team_completion_time calculations.
```

---

> ## 📐 The training model — folded in from the merge canon (2026-07-30)
>
> Everything from here to the end of the Decision Log was the authority for the
> `merge-braydon` merge and is now the authority for the system. It is here
> because it is **durable**: how the training hierarchy fits together, and how a
> prescribed percentage becomes a weight on a bar.
>
> **Section numbers (§4, §6.3, …) are preserved deliberately.** The text below
> cross-references them constantly, and renumbering would break every reference
> for no gain. They are the merge canon's numbers.
>
> What was *not* folded in, and why:
>
> | Left behind | Where it lives now |
> |---|---|
> | Branch mechanics, `git show`/checkout recipes | The merge is done; git history |
> | The P0–P15 phase plan and its gates | [`docs/_PATCH_NOTES.md`](docs/_PATCH_NOTES.md) |
> | Endpoint reconciliation (which of his routes we kept) | [`_MESSAGE_CONTRACT.md`](_MESSAGE_CONTRACT.md) has the real shapes |
> | Migration plan (`0008`→`0017`) | The migration files themselves |

## §4. The `Training*` hierarchy

### §4.1 Conceptual weight (this is NOT ownership, NOT lifespan)

```
TrainingBlock   →   TrainingProgram   →   TrainingGroup   →   TrainingSession
  template            instance             squad               one shared timeslot
```

This arrow only means "bigger idea → smaller idea." **It is not the foreign-key direction.** Read every name
by *this* definition, not by outside strength-and-conditioning convention:

| Name | Means | Note |
|---|---|---|
| `TrainingGroup` | A **named subset of athletes** who train together and share one `TrainingProgram`. ⚠️ **NOT the list of all registered athletes** — that's the `Athlete` table. A gym has many groups at once, each on its own program. | Long-lived; carries no dates and no workouts itself. |
| `TrainingBlock` | The reusable **TEMPLATE** a coach designs once and redeploys. | ⚠️ **Inverted from common usage on purpose** — here the *block is the template*, not a dated phase. |
| `TrainingProgram` | A scheduled **INSTANCE** for a group, placed in time. | Instantiated from a block (snapshot-copied), or standalone with a NULL block link. |
| `TrainingSession` | One **shared** timeslot when lifting happens. | Owned by nobody; **many groups can be on it** via `SessionParticipation`. |

### §4.2 Actual foreign keys (what really points at what)

Arrows below point **from the table holding the FK → to the table it references.** Compare with §4.1 — they
deliberately do not match.

```
   User (coach)
     │ owns                    ┌──────────────── Exercise (catalog) ◄──┐
     ├──────────────► TrainingGroup                                    │ (every *Exercise
     │                   ▲   │ owns                                    │  row references it,
     │                   │   └──────────► TrainingProgram              │  PROTECT)
     │          M2M      │                   │ owns                    │
     │      Athlete ─────┘                   ├──► TrainingProgramWorkout
     │         │                             │        └──► TrainingProgramExercise ──┤
     │         │ owns                        │                    ▲                  │
     │         ├──► AthleteReferenceMax      │ PROTECT, NULLABLE  │ CASCADE          │
     │         ├──► Set ──► Rep              ▼                    │                  │
     │         └──► RackCheckIn        TrainingBlock         AthleteOverride ─────────┤
     │                                       │ owns                                   │
     └──────────────────────────────────────►├──► TrainingBlockWorkout                │
                                             │        └──► TrainingBlockExercise ─────┘
   TrainingSession (root, owned by nobody)
        │ owns
        └──► SessionParticipation ──► TrainingProgram (+ the day's workout)
```

**Three non-obvious calls — intentional, do not "fix" them:**
1. **`Athlete ↔ TrainingGroup` is many-to-many, not ownership** (D12). An athlete can be in several groups at
   once (football *and* speed squad), each with its own program; the session decides which one applies (§6.2
   step 2). Membership is current-state only — adding or removing a group **never** rewrites past sessions or
   sets, because history stays attached to what was actually created at the time.
2. **`TrainingSession` is a root owned by nobody.** The group link lives on `SessionParticipation` — that is
   precisely what lets one shared session host many groups at once.
3. **`TrainingProgram.training_block` is nullable** (D6). NULL means a standalone one-off program that was
   never built from a template. This is a permanent supported path, not a migration shim.

### §4.3 Master vs. copy (why the same columns appear twice)
`TrainingBlock*` rows are the **master** prescription. Creating a `TrainingProgram` from a block
**snapshot-copies** those rows into `TrainingProgramWorkout` / `TrainingProgramExercise` — the **editable
copy**, which is what actually runs.

- Editing the **block** changes *future* instances only.
- Editing the **program** changes *only that instance*.
- History therefore stays pinned to what actually ran.
- For a **standalone one-off** (NULL block) there is nothing to copy — the coach authors the program rows
  directly and the program simply *is* the master.

**Promoting a one-off into a template later** = create a `TrainingBlock` row and point the existing FK at it.
No data migration, no rewrite. That is the entire reason the FK is nullable.

### §4.4 The rack stays group-blind
A session hosts many groups. The rack reads a **flat union roster** (every athlete across every participating
group), resolves each athlete's plan **per athlete**, and renders exactly as today. All multi-group logic lives
**behind** the frozen §2.2 seam — response shapes don't change, only their coverage widens:
- `/sessions/active/` roster = union of every participating group's athletes.
- Check-in validation = "athlete is in *any* participating group of the active session."
- `/sessions/active/status/` and `/progress/` are per-athlete and group-blind already.

### §4.5 Deferred but schema-ready (NOT built in this merge)
The **calendar generator** (drag a block onto a date → auto-create/attach sessions). We keep it *possible*:
the block carries `duration_weeks` + `cadence_days_of_week`, the program carries `start_date`. That's all.
**Do not build the generator.**

---


---

## §5. Schema rules that are easy to get wrong

> Numbering starts at §5.3 on purpose. §5.1 was a merge-time disposition table
> (what happened to each of the old models) and §5.5 was the migration plan
> `0008`→`0017`. Both described work that is finished; the migration files are
> their own record.

### §5.3 What we deliberately do NOT create a table for (§3.4)

| Coach need | Derived from | Endpoint |
|---|---|---|
| Room / wall live state | `RackCheckIn` (who's here) + per-athlete derived progress | `services/` room-state (D8) |
| Per-athlete day progress | `Set` / `Rep` rows for the active session | `services/` day-progress (D3) |
| Which athlete is at rack N | Newest `RackCheckIn` for that session | derived (D2) |
| Athlete reports list/detail | `DailyReport` rows filtered by athlete id | `reports/?athlete={id}` (R6) |
| **Athlete notes** | **The existing `Athlete.notes` TextField** — no new table *and* no new route | **`athletes/{id}/` PATCH** (R1) |

**Justifying the two stored tables we DO add** (they look like exceptions to §3.4, so here's why they aren't):
- **`DailyReport`** — could technically be recomputed from `Set`/`Rep`, but must **not** be: it has to stay
  correct even after a coach edits the program it reported on. Recomputing later would silently rewrite
  history. Immutability *is* the feature. It also replaces `SessionParticipation.snapshot` (D14).
- **`MonitoringEvent`** — an outbox exists precisely so a change survives a dropped connection. Deriving it
  would defeat its purpose.

**And the two copy tables** (`TrainingProgramWorkout` / `…Exercise`) are not avoidable: a **standalone one-off
program has no block to derive from** (D6), so these rows are the only prescription that exists for it.
Making them conditional on having a block would be more complexity, not less.

### §5.4 Seed data (D1)
The migration that establishes the catalog seeds these starter movements so there is always something to build
against (names are the canonical spelling; `is_stub=False`):

`Back Squat`, `Front Squat`, `Bench Press`, `Deadlift`, `Overhead Press`, `Hang Clean`, `Power Clean`,
`Push Press`, `Barbell Row`, `Romanian Deadlift`

**No backfill of existing rows** — all current data is disposable dev/seed data.

> **Two different "seed" mechanisms — do not confuse them** (this trips people up):
>
> | | `0009_seed_exercise_catalog` (RunPython migration) | `seed_active_session` (management command) |
> |---|---|---|
> | Seeds | the **10 canonical `Exercise` rows** above | demo fixtures: athletes, `Program`s, a session, sets/reps, reference maxes |
> | Runs | **automatically** on every `migrate` (incl. the test DB) | **only when invoked by hand** |
> | Is | canonical reference data, part of the migration lineage | dev/demo convenience, predates the migration |
>
> **After `docker compose down -v`:** the exercise catalog returns **by itself**; the demo fixtures do **not** —
> re-run `docker exec edgeathlete-django python manage.py seed_active_session` (and `ensure_demo_coach` for the
> `coach`/`coachpass` login). Until then the rack screen shows an empty movement list, because `athlete_progress`
> still reads the legacy `Program` rows (until the P5 `% × max` swap).
>
> ⚠️ **Keep the names in sync.** `seed_active_session` does `Exercise.objects.get_or_create(name=…)` with
> `"Back Squat"` / `"Bench Press"` — spellings that **must** match §5.4 exactly, or it silently creates a second
> near-duplicate movement (the exact drift D1's canonical catalog exists to prevent). Verified aligned
> 2026-07-24; re-check if either list changes.

> ⚠️ **Seed data is present in the TEST database too.** Django applies every migration — including
> the `0009` seed — when it builds the test DB, so a test must **not** assume `Exercise` (or any seeded
> reference table) starts empty. This bit `test_lists_catalog_by_name` in P1 (it created `Bench Press`,
> already a seeded row → `UniqueViolation`); the fix asserts the *name-sorted* invariant robustly instead
> of hard-coding the catalog contents. **Default rule for any new test: account for seeded rows.**

### §5.6 Two "colors" — do not conflate
- **(a) Per-rep velocity-zone color** (`Rep.velocity_color`) — how fast a rep moved vs. its target band.
  **Already alive in both branches, untouched by this merge.** Nothing to build.
- **(b) Rollup health-status** (red = nobody started, green = whole roster has data, yellow = partial).
  **Not built anywhere. OUT OF SCOPE.** Do not build it, do not re-anchor it onto the new hierarchy.

They only ever shared a color palette. The per-rack `status` (idle/active/complete/false-set) is a **third**,
separate thing (live execution state) and is likewise unaffected.

---


## §6. The derivation rules (the part that must not be guessed) ⭐

Everything in §4–5 is inert until something turns a *percentage* into a *number on a bar*. This section is the
algorithm. **If you find yourself inventing a rule here, stop — it belongs in this doc first.**

### §6.1 Resolving an athlete's target weight

Given an athlete and a `TrainingProgramExercise`, compute `target_weight_lbs`:

1. **Find the athlete's current reference max** for that exercise: the **newest** `AthleteReferenceMax` row for
   `(athlete, exercise)` by `recorded_at`. The table is add-only, newest-wins — never edit an old row.
2. **Normalize it to a 1-rep basis.** If `rep_basis == 1`, use `reference_weight_lbs` unchanged. Otherwise
   convert with the **Epley formula** (D11):
   `one_rep_max = reference_weight_lbs × (1 + rep_basis / 30)`
3. **Apply the prescribed percentage:** `raw = one_rep_max × (target_percent / 100)`
4. **Apply a per-athlete override if one exists** (`AthleteWorkoutExerciseOverride` for this athlete +
   program-exercise): a non-null `target_percent` on the override **replaces** the program's percent at step 3;
   non-null `sets` / `reps` replace the program's. Null fields on the override change nothing. *(The override
   endpoint isn't built until P5, but the resolution logic should account for it from the start.)*
5. **Round to the nearest 5 lb** — gyms load in 5 lb increments (2.5 lb plates in pairs). Return the rounded
   value in `target_weight_lbs` as a float. **Do not add a second "raw" field** — that would change the frozen
   response shape (§2.2).
6. **If the athlete has NO reference max for that exercise**, `target_weight_lbs = null`. Do **not** guess, do
   **not** substitute zero, do **not** error the request. Null is already a legal value in the frozen contract,
   and the rack tablet's existing `WeightPad` lets the athlete enter a load manually. **Fail soft.**

**Worked example:** athlete's newest reference for Back Squat is `225 lb @ rep_basis 3`; prescription is 80%.
→ `one_rep_max = 225 × (1 + 3/30) = 247.5` → `raw = 247.5 × 0.80 = 198.0` → **`target_weight_lbs = 200.0`**.

#### 6.1a The three weights — which lever moves which (memorize this)

There are **three** distinct "weights" in this system, they move by **three different levers**, and confusing
any two of them is the single most expensive mistake on this project (it derailed a prior attempt). A cold dev
hits this exact fork, so it's spelled out here:

| # | Weight | Where it lives | Moved by | Notes |
|---|---|---|---|---|
| a | **Reference / working max** | `AthleteReferenceMax` (stored, add-only, newest-wins) | the **reference-max write** endpoint (§7.2, manual coach entry) **or** the D10 auto-recalc on session end | The anchor. Not a lifetime PR — can go down. |
| b | **Prescribed target** | **nowhere — DERIVED** as `% × (a)` per §6.1 | move (a), or the P5 per-athlete override (`AthleteWorkoutExerciseOverride`) | Never stored. This is what `target_weight_lbs` in the frozen contract returns. |
| c | **Actual / working load** | `Set.weight_lbs` (stored per set) | the athlete's **WeightPad** on the rack, **or** a **coach weight adjustment (D15)** | This is what `last_weight_lbs` in the frozen contract returns — the load the tablet defaults the *next* set to. |

**The rule:** to change the *prescription*, move **(a)** (or override). To change only what an athlete is
*loading right now*, move **(c)** via D15. **(b) is always derived and never written.** A coach who "changes an
athlete's weight" must know which of the two they mean — the canon offers a lever for each and they do not
compete: (a) rewrites future targets up or down; (c) nudges today's working load without touching the plan.

> **D11 — Epley is the canon formula, and it lives in exactly one function.** Any rep-basis conversion goes
> through a single helper in `services/` so swapping it (Brzycki, Lombardi, a coach-tuned curve) is a one-line
> change. Do not inline this math at call sites. This is *separate from* D10's deferred question of how to
> *estimate a new max from session data* — that's a different problem, still deferred.

### §6.2 Resolving "what is this athlete doing today"

Given an athlete and the active session, produce their ordered movement list:

1. **Groups:** `athlete.training_groups.all()` (M2M — an athlete may be in several, D12). If they're in
   **none** → the athlete has no plan; return an **empty movements list** (valid, not an error — the frozen
   contract already handles an empty list).
2. **Programs — INTERSECT their groups with the session** *(true AND logic)*. Take the `SessionParticipation`
   rows on the active session whose `training_program.training_group` is one of the athlete's groups. This is
   the whole point of the M2M: an athlete in both "Varsity Football" and "Speed Squad" gets the football
   program at a football session and the speed program at a speed session, with nothing to configure.
   - **Zero matches** → none of their groups is on this session → empty movements list.
   - **Exactly one match** → that's their program. **This is the normal case.**
   - **More than one** → they train **all of them, merged** (step 4). Do not discard any.
3. **Workout-of-the-day:** for each matched participation, `SessionParticipation.training_program_workout`.
   If **NULL** → that participation contributes nothing (the coach hasn't picked its workout yet — a planning
   gap, not a runtime error). If *every* matched participation is NULL → empty movements list.
4. **Movements — UNION the workouts, deduped by exercise** *(OR logic + collapse)*.

   > ⚠️ **Two different set operations, one chain — don't conflate them.** Step 2 is an **intersection**
   > (which *programs* apply = your groups AND the session's groups). Step 4 is a **union** (the *movement
   > list* = everything those programs prescribe, OR'd, duplicates collapsed). A receiver on the football
   > session trains the team lift **plus** their position work — not just the overlap between them.

   **4a. Order the matched programs (the "primary" comes first).** Sort by the size of their
   `training_group` — **most athletes first**, i.e. the most general group leads. Tie-break deterministically:
   **latest `start_date`** → **latest `created_at`** → **lowest `id`**. Rationale: the big team lift is the
   main work and position/accessory work follows it, which is also the order a coach runs the session in — and
   this matters because `current_exercise_id` points the athlete at the first incomplete movement. Cost is one
   annotated count, so it stays cheap.
   *(Group **join order** was considered and rejected: Django's auto-created M2M table has no timestamp, so
   "which group did they join first" isn't reliably available and would silently change if a membership were
   ever re-added.)*

   **4b. Concatenate** each program's `TrainingProgramExercise` rows for its workout-of-the-day, **ordered by
   `position` within each program**, in the 4a program order.
   ⚠️ Within a single program this replaces the old ordering (`Program.id`) — see §6.3.

   **4c. Dedupe by `exercise_id` — this is mandatory, not cosmetic.** The frozen contract derives
   `completed_sets`, `false_sets`, `last_weight_lbs`, and `next_set_number` from `Set` rows keyed by
   `exercise_id`. If one exercise appeared twice in `movements`, both entries would read the **same** tallies —
   3 finished squat sets would show as `3/5 in_progress` on one row and `3/3 complete` on the other, and both
   would hand back the same `next_set_number`. That corrupts the set counter the rack depends on.
   **Exactly one entry per `exercise_id`, always.** Keep the position of its **first** occurrence in 4b order.

   **4d. Resolve a collision — LOWER `target_percent` wins.** When two programs prescribe the same exercise,
   keep the row with the lower percent. Coaches overwhelmingly adjust a specific group's plan *downward* to
   take load off, so the lower number is the deliberate one and the safer default. **Take the winning row
   whole** — its `sets`, `reps`, and velocity zones travel with its percent. **Never mix fields across rows**:
   one plan's percent with another's rep scheme is a prescription nobody actually wrote.
   If the percents are **equal**, the row from the earlier program in 4a order wins.
   *Escape hatch: if this default is ever wrong for a given athlete, the coach can adjust the load directly —
   the rack's existing weight-entry path already lets the actual lifted load differ from the target, and P5's
   per-athlete override (§5.2) covers the durable case. We are not adding schema for this.*
5. **Hardware filter (D9):** resolve the athlete's current rack from their newest `RackCheckIn` for this
   session, then drop any movement whose exercise is **not** in that `Node`'s `allowed_exercises`. **Empty
   `allowed_exercises` = unrestricted** (the normal case — costs nothing). **Fail open:** if the rack can't be
   resolved yet (the check-in write hasn't landed before the progress fetch), treat it as unrestricted. Never
   fail closed and block a legitimate lift over a timing gap.
6. **Per-movement targets:** run §6.1 for each.

**Worked example (the multi-group case, end to end).** Athlete is in **Varsity Football** (60 athletes) and
**Receivers** (8 athletes). Both groups are on tonight's session.

| | Football program | Receivers program |
|---|---|---|
| Workout-of-the-day | Back Squat 5×3 @ **80%**, Bench 3×5 @ 75%, Power Clean 4×2 @ 70% | Back Squat 3×5 @ **70%**, Sled Push 3×1 @ 0%, Nordic Curl 3×6 @ 0% |

- **Step 2:** both participations match → two programs, neither discarded.
- **Step 4a:** Football (60) leads Receivers (8) — most general first.
- **Step 4b/4c:** concatenate, then collapse the duplicate Back Squat.
- **Step 4d:** Back Squat collides → **70% wins (lower)**, and it brings its own `3×5` with it — *not* `5×3`.

**Result — 5 movements, in order:**
`Back Squat 3×5 @70%` · `Bench 3×5 @75%` · `Power Clean 4×2 @70%` · `Sled Push 3×1` · `Nordic Curl 3×6`

The athlete does the team lift **and** their position work; the one shared movement appears once, at the
lighter prescription. Then §6.1 turns each percent into a rounded weight.

### §6.3 ⚠️ The frozen progress contract — `/sessions/active/athlete/{id}/progress/`

This is the highest-risk seam in the merge. Today `athlete_progress` in `views.py` loops over
`Program.objects.filter(athlete_id=...)`. In **P5** that loop is replaced by the §6.2 chain and §6.1 targets.
**The response shape must not change by even one key.** It is, and must remain, exactly:

```jsonc
{
  "session_id": 12,                     // null when no active session
  "athlete": { "id": 3, "name": "..." },
  "current_exercise_id": 7,             // first movement not yet "complete"; null if all done
  "movements": [
    {
      "exercise_id": 7,
      "name": "Back Squat",
      "planned_sets": 5,                // ← was Program.target_sets, now TrainingProgramExercise.sets
      "target_reps": 3,                 // ← now .reps
      "target_weight_lbs": 200.0,       // ← now DERIVED per §6.1; null if no reference max
      "last_weight_lbs": 195.0,         // unchanged: newest non-false completed set THIS session, else null
      "velocity_zone_min": 0.5,
      "velocity_zone_max": 0.8,
      "completed_sets": 2,              // unchanged: non-false completed sets this session
      "false_sets": 0,                  // unchanged: counted separately, never advance set number
      "next_set_number": 3,             // unchanged: completed (non-false) + 1 — the SERVER owns this
      "status": "in_progress"           // "not_started" | "in_progress" | "complete"
    }
  ]
}
```

**Behaviors that must survive the swap unchanged:**
- A set counts as completed once it has `ended_at`. False sets **never** advance `next_set_number`.
- `status` = `complete` when `completed_sets >= planned_sets`; `in_progress` when `completed_sets > 0`; else
  `not_started`.
- `current_exercise_id` = the first movement whose status isn't `complete`.
- `last_weight_lbs` is **session-scoped only** — never read a prior session's loads.
- Empty-envelope convention: **no active session ⇒ HTTP 200** with nulls/empties, not an error.
- Athlete not found ⇒ 404. Athlete not in the active session ⇒ 404.

**How to prove you didn't break it:** capture the JSON before and after your change and diff the *keys*:
```bash
curl -s localhost/api/sessions/active/athlete/1/progress/ | python3 -m json.tool > /tmp/before.json
# ...make the change, restart...
curl -s localhost/api/sessions/active/athlete/1/progress/ | python3 -m json.tool > /tmp/after.json
diff <(python3 -c "import json,sys;print(sorted(json.load(open('/tmp/before.json'))['movements'][0]))") \
     <(python3 -c "import json,sys;print(sorted(json.load(open('/tmp/after.json'))['movements'][0]))")
```
That diff must be **empty**.

### §6.4 The room-state contract (D8 rebuild)
We are **rebuilding** his room-state, not renaming it. His version read `RackWorkoutState` (a rack holding a
coach-*pre-selected* athlete + *pre-assigned* workout) plus `AthleteDayProgress`. Our rack is
**athlete-centric and group-blind**: an athlete carries their plan via group membership, self-selects any rack
via `RackCheckIn`, and their current movement is derived live. Different shapes — so the forward
rack-assignment concept **dies entirely** (D8).

**Rebuild it from:** the set of rack numbers seen on `Node` ∪ `RackScreen` ∪ `RackCheckIn` *(not his dropped
`Set.rack_number` — D11)*, then for each rack the newest `RackCheckIn` athlete, then §6.2/§6.1 for what they're
doing, then their newest `Set`/`Rep` for live `status` and `status_color`.

**The response shape is defined by his consumer, not by us** — we're bending to his front end (§3.3). Before
writing the endpoint, read what his dashboard actually destructures:
```bash
git show braydons-dev-branch:react/src/dashboardView.js
git show braydons-dev-branch:react/src/useLiveRoomState.js
git show braydons-dev-branch:react/src/roomMonitor.js
```
Reproduce those keys exactly, minus anything that depended on forward assignment. His
`dashboardView.test.js` / `roomMonitor.test.js` come across too and are the acceptance check.

### §6.5 Coach weight adjustment (D15)

**What it is.** A coach can adjust an athlete's carried-forward **working weight** for a session — before their
first set, or between sets, for one athlete or several — by writing through the **same `sets/` +
`sets/{id}/complete/` path the rack's WeightPad uses** (the one path his rack-scoped `racks/{n}/sets/` folded
into under D14), with the new field **`Set.is_coach_adjustment=True`**.

**What it moves — and what it must NOT.** It moves **`last_weight_lbs`** (weight *(c)* in §6.1a — the working
load the tablet defaults the next set to, which carries forward). It does **not** move `target_weight_lbs`
(weight *(b)*, the `% × max` prescription). A coach who wants to change the *prescription* uses the
reference-max write (weight *(a)*, §7.2) or the P5 override — **not** this. Keeping these separate is
non-negotiable: conflating "nudge today's load" with "rewrite the plan" is exactly what derailed the earlier
attempt.

**Not a §2.2 violation — do not block on this.** `sets/` is frozen by *response shape*. `is_coach_adjustment`
is an **optional request field defaulting to False**; the rack omits it and behaves byte-identically, and no
response key changes. It touches no frozen *file* (§2.1) either — only view internals and the model.

**Why the flag is mandatory (not just convenient).** In `athlete_progress` two outputs are computed on the
*same* loop branch:

```python
for s in Set.objects.filter(session=session, athlete_id=athlete_id,
                            ended_at__isnull=False).order_by("started_at", "id"):
    if s.is_false_set:
        false_by_exercise[s.exercise_id] += 1
    else:
        completed_by_exercise[s.exercise_id] += 1              # the set counter
        if s.weight_lbs is not None:
            last_weight_by_exercise[s.exercise_id] = s.weight_lbs   # the displayed weight
```

- The filter is `ended_at__isnull=False`, so an **uncompleted** "empty" set is invisible here and moves
  nothing — a naive adjustment silently no-ops. So the adjustment **must be a completed set** (`ended_at` +
  `weight_lbs`).
- But `last_weight` is set in the **same `else` branch** that increments `completed`. So any set that moves the
  weight also bumps `completed_sets` → `next_set_number = completed + 1` (the server-owned number sent at
  `set_create`) → and can flip `status` to `complete` early and skip the movement via `current_exercise_id`.
- `is_false_set=True` doesn't help: false sets never reach the `last_weight` line.

**⇒ No `Set` shape moves the weight without also moving the set counter.** Hence the flag — it lets one read
*include* these rows and every other read *exclude* them.

**Mandatory include/exclude list (enumerated so it cannot drift). Verified against current code 2026-07-23:**

| Read | Adjustment rows | Effect if you get it wrong |
|---|---|---|
| `athlete_progress` — `last_weight_lbs` | **INCLUDE** | (correct target) newest-wins ordering unchanged, so a real lift afterward still supersedes it |
| `athlete_progress` — `completed_by_exercise` / `false_by_exercise` | **EXCLUDE** | keeps `completed_sets`, `false_sets`, `next_set_number`, `status`, `current_exercise_id` all unaffected |
| `session_status` (line ~489) | **EXCLUDE** | else the adjusted athlete shows **"resting" with a ticking rest timer** having lifted nothing — visible on the rack *and* the coach dashboard |
| `analytics_session` / `analytics_athlete` (lines ~650/676) | **EXCLUDE** | phantom sets skew every analytic (they filter `is_false_set=False` only, so an adjustment slips through today) |
| `sessions_active` — `has_data` (line ~311) | **EXCLUDE** | ⚠️ **found in this audit, beyond the original list:** `has_data` drives `is_makeup`, so an adjustment before an athlete's first real set would silently mark that real set as a makeup |
| `DailyReport` snapshot generation (P4, not built yet) | **EXCLUDE** | phantom sets in the immutable end-of-day record |

**General rule — write it down so it survives new code:** *any* future read over `Set` rows must consciously
decide include/exclude on `is_coach_adjustment`. The default assumption for a new read is **EXCLUDE** (it's an
adjustment, not a lift); `last_weight_lbs` is the lone documented include.

**Session scoping.** `last_weight_lbs` is session-scoped, so an adjustment only means anything against an
existing session (the active/target one). "Before the session" means **before the athlete's first set in that
session**, not before the session row exists.

---


---

## REST API

### Original endpoints (Phase 4 — built)

```
POST  /api/auth/login/                 coach login → {access, refresh}  (already wired via simplejwt)
POST  /api/auth/refresh/               → {access}

GET   /api/nodes/                      list nodes                         (open)
PUT   /api/racks/node-assignment/      select node for this rack screen   (active staff only)
      body: { device_id, node_id }

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

GET   /api/prescriptions/?athlete={id}      list for athlete                   (open read)
POST  /api/prescriptions/                   create                             (coach only)

POST  /api/sessions/                   create session                     (coach only)
PATCH /api/sessions/{id}/              end session                        (coach only)

POST  /api/sets/                       create a set (on set_start)        (open)
POST  /api/sets/{id}/complete/         *** THE BATCH WRITE ***            (open)
      body: { reps_completed, avg_velocity, peak_velocity, is_false_set,
              reps: [ {rep_number, mean_velocity, peak_velocity, duration_ms,
                       timestamp, velocity_color}, ... ] }
      effect: one bulk_create of all Rep rows + one Set update, single transaction

GET   /api/analytics/session/{id}/     summary stats                      (coach only)
GET   /api/analytics/athlete/{id}/     athlete + summary + per-exercise
                                      aggregates + per-set reps          (coach only)
                                      Exact shape: _MESSAGE_CONTRACT.md (P13).
                                      Summary spans ALL history; `sets` is the
                                      50 most recent. 404 if no such athlete.
```

**Open (no auth):** node/rack/dashboard reads, rack-screen self-registration + assignment polling, and the set-complete write.
**Coach-only (JWT):** athlete/program writes, session create/end, and analytics.
**Active-staff-only:** rack-screen assignment and rack-local node selection.

### Extended in Phase 5+ endpoints

```
POST  /api/sessions/upload/            CSV import — creates/reuses the full   (coach only)
                                        Group → Block → TrainingSession →
                                        SessionExercise chain in one
                                        transaction; stubs unrecognized
                                        exercises rather than rejecting

GET   /api/exercises/                  list the movement catalog — what the   (open)
                                        rack/coach pickers choose from
                                        (BUILT early; see the exercise-identity
                                        note in Data Models)

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
trust tier as the other rack-facing endpoints above it. **The exact AS-BUILT
minimal response shape is pinned in _MESSAGE_CONTRACT.md §3** — it returns resolved
absolute target weights (from `Program`) keyed by catalog `exercise_id`, not the
`target_weight_percent` × max form the Phase 10/11 prompts describe; see the seam
note there.

---

## Folder Structure (target state after all phases)

```
Edge-Athlete/
├── docker-compose.yml
├── .env                          # gitignored — runtime values
├── .env.example                  # committed — template with stubbed keys
├── _RUNBOOK.md                    # started Phase 1, completed by Sprint 4 handoff
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
│       ├── permissions.py        # IsActiveStaff (JWT) vs open
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
---

# The build, in the order it actually happened

Two numbering systems exist and both are real. **Phases 1–18** were the original
build order, written up front. **The merge (P0–P15)** was a fifteen-phase piece of
work that began the moment Phase 11 froze the rack screen.

It has **its own section immediately below this table** — so this document holds
one timeline instead of sending you elsewhere to find out what happened. It is
written up there, ahead of the numbered phases, rather than slotted in between 11
and 12, because it is not a step between two others: it rebuilt Phases 5–6,
reworked 12, and delivered 14. Those rows say so.

| | Phase | State | Notes |
|---|---|---|---|
| **Sprint 1** | 1 · Repo bootstrap, broker, RUNBOOK | ✅ done | |
| | 2 · Data models & migrations | ✅ done | Superseded in shape by THE MERGE — see §4 |
| | 3 · MQTT pulse pipeline & simulator | ✅ done | |
| **Sprint 2** | 4 · REST API + batch set-complete | ✅ done | Set-complete contract is **frozen**, §2.2 |
| | 5 · Group/Block/Session hierarchy, catalog, maxes | ✅ done | **Rebuilt** by THE MERGE · P1/P5 |
| | 6 · CSV import pipeline | ✅ done | **Rebuilt** by THE MERGE · P5 |
| | 7 · Session status, roster, makeup flow | ✅ done | |
| | 8 · Wire insights generation | ⛔ **stub** | `generate_insights` still returns `[]` |
| **Sprint 3** | 9 · Django broadcast publisher | ✅ done | Folded into one backbone by THE MERGE · P2 |
| | 10 · Rack screen PWA shell | ✅ done | **FROZEN**, §2.1 |
| **Sprint 4** | 11 · Rack screen end-to-end | ✅ done | **FROZEN**, §2.1 — the merge starts the moment this is finished |
| | **↓ THE MERGE (P0–P15) starts here** | ✅ **done** | Coach frontend onto the real API, plus planning, reports, scheduling, analytics. Reaches into 5, 6, 12 and 14 — **written up in its own section below, not as a numbered phase** |
| | 12 · Team dashboard kiosk | ✅ done | `/dashboard` — **reworked** by THE MERGE · P3 |
| | 13 · Real ESP32 firmware v1 | ⛔ **not in this repo** | No `firmware/` directory exists |
| **Sprints 5–6** | 14 · Coach tablet | ⚠️ **built, but not as written** | Delivered by THE MERGE — read the correction in that section |
| | 15 · Fatigue scaffold | ⛔ not built | Still coherent as written |
| | 16 · Security hardening | ⚠️ **rewritten** | Its original premise was overturned by the merge — see that section |
| | 17 · Firmware hardening & mounts | ⛔ not built | Still coherent as written |
| | 18 · Full integration test & demo prep | ⛔ not done | Still coherent as written |

**What is genuinely left:** Phase 8 (insights), 13 (firmware), 15 (fatigue),
16 (security), 17 (firmware hardening), 18 (integration + demo). Everything else
is built.

⚠️ **The numbered phases are kept for provenance.** They are the original
prompts, and where the merge rebuilt something the phase text can be out of date.
Where that is true it is said so in the phase itself. **§2–§10 above, and THE
MERGE below, are current and authoritative; a phase prompt is not.**


# THE MERGE (P0–P15) · Owner: Devin · ✅ COMPLETE

**This is not one of the numbered phases, and it is written up here on purpose.**
Everything below `# SPRINT 1` is history — the prompts the system was built from.
This is the opposite: it is the most recent description of what is actually
running, and it is what you should read before you touch the backend.

**When it happened:** Phase 11 finished the rack screen end to end and froze it.
The merge began the moment that was done. That is its slot in the timeline above.

**Why it is not "Phase 11.5":** because it did not stay in that slot. Over
fifteen sub-phases it reached in both directions through the numbering:

- **rebuilt** Phases 5 and 6 (hierarchy, catalog, maxes, CSV import) — P1, P5
- **reworked** the Phase 12 dashboard into the shared room-state read — P3
- **delivered** Phase 14 (coach tablet), diverging from that prompt — P7, P10–P15
- **added** work no original phase describes: reports and PDF, scheduling,
  athlete analytics, multi-coach, program promotion

A fractional number implied a small step between two others. It was a rewrite of
the middle of the system, and the phases it superseded each say so.

### Goal
Merge Braydon's coach frontend onto the base station API without touching the rack
experience, and leave the backend reading as one documented system.

The two things that could not be lost, and did not:

1. **The rack screen** — athlete-facing, frozen, ships today and works.
2. **The percentage-of-max idea** — a prescription is a percent of each athlete's
   own tested max, never a number of pounds. See §6.1.

| | |
|---|---|
| Files changed | 82 · +10,655 / −659 |
| Tests | 280 backend · 131 frontend |
| Migrations | `0008` → `0017` |
| Tags | `p1-complete` … `p15-complete` |
| Frozen-file check | clean at all fifteen gates |

> **Detail lives in [`docs/_PATCH_NOTES.md`](docs/_PATCH_NOTES.md)** — each sub-phase
> with the files it touched and a click path to see it working. It is not repeated
> here; two copies would drift.

### Sub-phases

| | Sub-phase | What it did | Left behind |
|---|---|---|---|
| **P0** | Cold-build smoke test | Proved the tree built and the rack loop ran *before* anything changed | The baseline every "visually unchanged" claim is measured against |
| **P1** | Models + migrations | The `Training*` hierarchy (`0008`), movement catalog seeded by hand (`0009`) | §4, §5.4 |
| **P2** | Realtime backbone | One publisher; every rack topic byte-identical; dropped the ntfy/motion cruft | nginx caches upstream IPs — restart it after a rebuild |
| **P3** | Derived reads | `room-state/` with **no state table**; wall and coach behind one `?details=` flag | §6.4 · the detail level *is* the privilege boundary |
| **P4** | Reports + finalization | `DailyReport` immutable snapshot (`0010`), reports family, PDF, reference-max recalc | D10 · the one exception to derive-don't-store |
| **P5** | Planning + `% × max` | Target resolution behind the frozen seam, planning CRUD, three CSV importers, the repair loop | §6.1 · D16/D17 |
| **P6** | Retirement + the delete fix | Dropped the legacy `Program` table; `Set.session` → `PROTECT` (`0011`) | A `Set` is the only permanent record an athlete trained |
| **P7** | Coach frontend on the real API | Rewired his screens; folded 6 of his routes, dropped 3; `ErrorBoundary`; router race fixed | **Seven bugs found by clicking, none by a green suite** |
| **P8** | Verify on a fresh database | Cold build, rack loop end to end, replaced invented test fixtures with live payloads | |
| **P9** | Naming alignment | Routes and models renamed to match what they serve (`0012`) | [`_NAMING_CHANGES.md`](docs/_NAMING_CHANGES.md) · a blunt sed shadows model imports |
| **P10** | Catalog editing + reordering | Rename/reorder/delete days and rows; `updated_at` (`0013`) | Reorder sends the **whole list** — non-deferrable unique constraint |
| **P11** | Multi-coach | `?coach=me` lens, block categories M2M (`0014`), `TrainingGroupCoach` join (`0015`) | **Filter, not fence** — see the Phase 16 rewrite below |
| **P12** | One open training day | 409 on a second open day; end-time correction after a power cut | D18 |
| **P13** | Athlete analytics read | Summary, per-movement aggregates, per-set reps | D19 |
| **P14** | Scheduling | `ScheduledSession` calendar; `started_at` nullable (`0016`, `0017`) | D20 · **"active" means STARTED**, and NULLs sort first descending |
| **P15** | Promote a program into a block | Copies days and rows **up** into a new block | D21 · pointing the FK alone leaves an empty block |

### What the merge deliberately did not do

- **No team permission boundary at merge time.** This historical decision was
  superseded by the active-staff fence; tenant-aware team scope remains pending.
- **No group-staff UI.** The API takes several coaches per group; adding an
  assistant needs Django admin.
- **No overnight auto-close policy.** A day left open has no defined behaviour;
  auto-closing would write an immutable report with nobody watching.

**STOP. The merge is closed.** Its remaining debts are in "Known Open Items".

---

> **Everything from here down is the original build history.**

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

## 4. Start _RUNBOOK.md
Create _RUNBOOK.md at repo root. Sections (fill what's known now, leave TODO
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
- [x] `_RUNBOOK.md` exists and covers all services + start/stop
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
  nfc_tag_id  CharField(max_length=255, null=True, blank=True), unique with organization
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

TrainingSession:
  label       CharField(max_length=255)
  started_at  DateTimeField(auto_now_add=True)
  ended_at    DateTimeField(null=True, blank=True)
  athletes    ManyToManyField(Athlete, related_name="sessions")
  notes       TextField(blank=True, default="")

Set:
  session         ForeignKey(TrainingSession, on_delete=CASCADE, related_name="sets")
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
s = TrainingSession.objects.create(label="AM Lift"); s.athletes.add(a)
n = Node.objects.create(node_id="rack_1", rack_number=1, mount_type="bar")
st = Set.objects.create(session=s, athlete=a, node=n, exercise="Squat", set_number=1)
r = Rep.objects.create(set=st, rep_number=1, timestamp="2026-01-01T00:00:00Z",
    mean_velocity=0.72, peak_velocity=0.95, duration_ms=850, velocity_color="green")
# FK chain resolves: r.set.session.athletes.first() == a
```

### ✅ Phase 2 Exit Checklist
- [ ] All seven models migrated cleanly
- [ ] Django shell creates one of each and the FK chain `Athlete → Program`, `TrainingSession → Set → Rep`, `Set → Node` resolves
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
DRF ModelSerializers for Node, RackScreen, Athlete, Program, TrainingSession, Set, Rep.
Add a RepInputSerializer (rep_number, mean_velocity, peak_velocity, duration_ms,
timestamp, velocity_color) and a SetCompleteSerializer with:
  reps_completed, avg_velocity, peak_velocity, is_false_set,
  reps = RepInputSerializer(many=True)

## permissions.py
IsActiveStaff requires an authenticated, active staff user and gates every
unscoped coach endpoint plus rack screen/sensor assignment.

## views.py + urls.py — endpoints
Open (AllowAny):
  GET   /api/nodes/
  POST  /api/racks/register/          upsert a RackScreen by device_id, rack_number stays null if new
  GET   /api/racks/racknumber/?device_id=   return {rack_number} for polling while unassigned
  GET   /api/athletes/
  GET   /api/prescriptions/?athlete={id}
  POST  /api/sets/                    create a Set (session, athlete, node, exercise, set_number, weight_lbs, started_at=now)
  POST  /api/sets/{id}/complete/      *** batch write, see below ***
Coach-only (IsActiveStaff):
  GET   /api/racks/unassigned/        list RackScreen rows where rack_number is null
  POST  /api/athletes/  PATCH /api/athletes/{id}/
  POST  /api/prescriptions/
  POST  /api/sessions/  PATCH /api/sessions/{id}/   (end = set ended_at=now)
  GET   /api/analytics/session/{id}/  aggregate: total sets, reps, avg velocity per athlete
  GET   /api/analytics/athlete/{id}/  the coach athlete+history context (widened
                                     in merge P13 from a flat velocity trend)
Active-staff-only (IsActiveStaff):
  PATCH /api/racks/{device_id}/       assign rack_number
  PUT   /api/racks/node-assignment/   select this screen's registered node;
                                      exact body {device_id, node_id}

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

# SPRINT 2 (EXTENDED) — Group/TrainingSession Data Layer

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

## Phase 5 — Group/Block/TrainingSession Hierarchy, Exercise Catalog, Athlete Max & Insights Scaffold · Owner: TBD

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
  session                ForeignKey(TrainingSession, on_delete=CASCADE, related_name="session_exercises")
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
  session             ForeignKey(TrainingSession, on_delete=CASCADE, related_name="insights")
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
  # attached to whatever Block/TrainingSession they were actually created under —
  # reassigning group here must never rewrite past records. See Phase 7 for
  # how session rosters snapshot membership at creation time instead of
  # querying this field live.

TrainingSession: ADD
  block          ForeignKey(Block, on_delete=CASCADE, null=True, blank=True,
                             related_name="sessions")
  schedule_date  DateTimeField(null=True, blank=True)
  # schedule_date is PLANNING ONLY — when this session is meant to happen.
  # started_at/ended_at (already on TrainingSession) remain execution-only and stay
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
- `TrainingGroup → Block → TrainingSession` FK chain resolves in the Django shell.
- `Athlete.group` can be reassigned without altering any existing `TrainingSession`/`Set`/`Rep` rows tied to that athlete's history.
- Creating an `Exercise` with `is_stub=True` and no tags works; deleting it removes it cleanly with no ID-reuse logic anywhere.
- `generate_insights(session_id)` is callable and returns `[]`.

### ✅ Phase 5 Exit Checklist
- [ ] All new models migrated; no existing model's prior fields removed or renamed
- [ ] `Athlete.group` reassignment does not touch historical TrainingSession/Set data
- [ ] `Exercise` uses standard auto-increment; no custom ID-walking logic anywhere in the codebase
- [ ] `generate_insights` has a real signature, stub return, no call site yet (that's Phase 8)
- [ ] Every new model/file has a WHY comment

**STOP. Review the above before moving to Phase 6.**

---

## Phase 6 — CSV Import Pipeline · Owner: TBD

### Goal
Let a coach upload the CSV export (one row per planned exercise) and have it
create/reuse the full Group → Block → TrainingSession → SessionExercise chain in one
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
     c. create TrainingSession (block=block, label=session_label,
        schedule_date=schedule_date). Snapshot the roster onto TrainingSession's
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
- TrainingSession roster (`TrainingSession.athletes`) matches the group's membership at upload time, unaffected by later `Athlete.group` reassignment.

### ✅ Phase 6 Exit Checklist
- [ ] Full CSV upload creates/reuses Group → Block → TrainingSession → SessionExercise correctly in one transaction
- [ ] Repeat upload for the same group/block reuses existing rows, no duplication
- [ ] Unrecognized exercises stub cleanly; confirm/reject both work with no orphaned rows
- [ ] TrainingSession roster snapshot taken at creation time, not computed live
- [ ] Every file has a WHY comment

**STOP. Review the above before moving to Phase 7.**

---

## Phase 7 — TrainingSession Status, Roster, Makeup Flow & Athlete Max Entry · Owner: TBD

### Goal
Compute red/yellow/green completion status at the TrainingSession/Block/Group level
(derived, not stored), support the retroactive makeup-session flow, implement
the team_completion_time rule, and open the athlete-max write/read endpoints.

### Prompt to paste into Claude
```
Working directory: django/event_handler/. Builds on Phases 5/6.

## GET /api/sessions/{id}/roster-status/   (coach-only, JWT)
Returns each athlete on the session's roster (TrainingSession.athletes, the snapshot
from Phase 6) alongside whether a completed Set exists for them:
  { athletes: [ {athlete_id, name, has_data: bool}, ... ] }

## Status computation (derived — do NOT add a stored status field anywhere)
  - TrainingSession status: red = zero non-makeup completed Sets exist; green = every
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
- A `Block` with a mix of red/green child `TrainingSession`s reports yellow; a `TrainingGroup` reflects the same rollup one level up.
- Roster-status endpoint correctly flags athletes with no completed Set.
- A makeup Set (`is_makeup=True`) completes normally but does not affect `team_completion_time`; a session where every Set is a makeup returns `team_completion_time: null`.
- `POST /api/athlete-maxes/` creates a new row without touching any prior row for the same athlete/exercise pair; `GET /api/athlete-maxes/?athlete=&exercise=` returns the full ordered history.

### ✅ Phase 7 Exit Checklist
- [ ] Status is computed at request time at all three levels (TrainingSession/Block/Group), never stored
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
2. Athlete check-in (however a Set/TrainingSession ties an athlete to a rack — publish on
   set create): publish_rack_state(rack_number, {type:"athlete_checkin", athlete, rack_number})

Import the publisher into views.py and replace the Phase 4 marker comment with
the real calls. Every file opens with a WHY comment.
```

### Verify
- `mosquitto_sub -t 'edgeathlete/rack/#' -v` and `-t 'edgeathlete/dashboard/state' -v` in two terminals.
- PUT a rack node assignment → a durable `node_assignment_changed` room invalidation is queued.
- POST a set-complete → both a `rack/{n}/state` (`set_complete`) and a `dashboard/state` (`leaderboard_update`) message appear.

### ✅ Phase 9 Exit Checklist
- [ ] `publisher.py` exposes the three publish helpers, single reused client
- [ ] Assigning a node queues a durable room invalidation
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
null — pick the most recent qualifying TrainingSession; document whatever tie-break
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

### Built — implementation notes (2026-07-18, branch `rack-screen-and-active-session`)
What actually shipped for the Phase 10 shell, and the decisions that extend/adjust the prompt above:

- **URL routing (added).** A tiny dependency-free router (`react/src/router.js`, History API — NOT React Router) makes the address bar the source of truth:
  `/` (picker/dispatcher) · `/rack/setup` · `/rack/:n` · `/coach` · `/dashboard` · `/connection-test`.
  Nginx already serves `index.html` for any path (its SPA fallback), so hard-loads/refresh of `/rack/1` work with no nginx change. localStorage still remembers identity (role, device id, rack number) so a cold boot at `/` redirects to the right screen — but the URL decides the view. This supersedes the prompt's "localStorage determines routing, not the URL," and aligns with the folder-structure sketch (`/rack/:n`, `/coach`, `/dashboard`).
- **`/rack/setup` (was "registration/wait").** Rack-scoped registration + assignment-wait, and reachable any time to (re)home a tablet. **Non-destructive:** it only leaves when the server's rack number *changes* from what it was on arrival (a coach override), so an assigned rack that lands here just shows its id. **Role guard:** if the device is already an established coach/wall device, it does NOT silently convert — it asks first ("Set it up as a Rack instead?"), which prevents hijack and doubles as the deliberate switch. The **"Change device role" escape** lives here (and on the coach/wall stubs), NOT on the live rack screen, so athletes can't knock a rack out of mode mid-set. Changing a device's role leaves its old `RackScreen` row orphaned — see the "Stale RackScreen rows" known open item.
- **Remote command channel (new MQTT topic).** Every tablet subscribes to `edgeathlete/rack/command` from boot; `{type:"enter_setup", target}` sends matching tablets to `/rack/setup` (target = `all` | device_id | rack_number). Sender is a coach button → Django publish in Phase 14; the receiver is built + testable now via `mosquitto_pub`. A future `identify` command is reserved. Full shape in _MESSAGE_CONTRACT.md.
- **Orientation: portrait.** The rack manifest is `"orientation": "portrait"` (matches the `edge_athlete_rack_ui.html` mockup, which is a 540×720 portrait device). The wall stays landscape; the coach tablet portrait.
- **Aesthetic: the `.monitor` design system.** The rack screen matches the team's coach/wall look (near-black `#070b0e`, lime `#a9f04d`, mint/amber/coral status, Inter bundled locally so it renders on the offline Pi network). Palette centralized in `react/src/theme.js`.
- **Rep buffer uses Dexie.** The IndexedDB durability buffer is written with Dexie (`react/src/db/repBuffer.js`) for readability. Service worker caches the app shell (network-first, skips `/api/`).
- **Install / PWA.** A per-role manifest (rack/dashboard/coach), swapped by `App.jsx`; manifest colors are the `.monitor` near-black. On the real Pi, fullscreen comes from Chromium `--kiosk` at boot (Phase 12), since the browser install prompt needs a secure context and the Pi serves plain HTTP. **TODO if phone "Add to Home Screen" is wanted:** iOS Apple meta tags (`apple-mobile-web-app-*`) + an `apple-touch-icon`, and PNG 192/512 + maskable icons (current icons are SVG placeholders).
- **Coach/wall dashboards need NO new data model.** Everything the Phase 12/14 wall + coach surfaces display (room snapshot, per-rack latest set/reps, leaderboard, athlete history, notes) derives from the existing seven tables — confirmed by Braydon's `room-state`/`wall-state` work, whose own spec says "Migrations: none."

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
call GET /api/athletes/ or GET /api/prescriptions/?athlete={id} for this picker —
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
- The working weight is editable on the fly (pencil → numpad): the entered value shows immediately and saves as the set's `weight_lbs` (actual load), never the `Program` target. It carries forward to the next set via `last_weight_lbs`, session-scoped. (SUPERSEDES the old missing-max inline entry — see Built Step 2 redesign item 9.)
- The server's rep count for that set matches what streamed in.
- The False-Set button returns to idle and writes zero reps (`Rep.objects.filter(set=...).count() == 0`, `Set.is_false_set == True`).
- Rest timer counts down and returns to idle, keeping the same athlete/exercise selected for the next set.
- No repeated calls to `/api/sessions/active/` occur during a full cycle.

### ✅ Phase 11 Exit Checklist
- [ ] Athlete/exercise picker sources only from the active session's roster/exercises, never the open list endpoints; set start is disabled until both are chosen
- [ ] Full flow idle → countdown → active → summary → rest works against the simulator
- [ ] Exactly one `complete/` POST per set, with correct rep count, summary stats, athlete, and exercise
- [ ] Selecting a `has_data: true` athlete automatically sets `is_makeup: true`, no manual toggle
- [x] Target weight displays from `targets`; the working weight is editable on the fly (pencil → numpad) into the set's actual `weight_lbs`, carried forward per session via `last_weight_lbs`, prescription untouched (supersedes missing-max inline entry)
- [ ] IndexedDB buffer cleared only after a successful POST
- [ ] False-set undo returns to idle and writes no reps
- [ ] Rest timer works; set_number increments; athlete/exercise selection persists across sets in the same rotation
- [ ] Every file has a WHY comment

> ## ⚠️ The four "Built —" blocks below say **authoritative**. They were, in July 2026. They are not now.
>
> They describe the **minimal** build that existed before THE MERGE, and they are
> kept because they record how the rack screen actually got made — decision by
> decision, including the ones later overturned. Read them as history.
>
> **What they say that is no longer true:**
>
> | They say | Now |
> |---|---|
> | Targets come from `Program` | `Program` was **dropped** (migration `0011`). Plans belong to a group and store a **percent** |
> | "`maxes` is informational only" | The reference max is now **load-bearing** — it is the number every percent multiplies against |
> | "`Set` has NO `is_makeup` column" | Added in migration `0006`, exactly as the block instructs |
> | "`NodeSerializer` doesn't expose the pk" | It does — `"id"` was added, the recommended option |
> | "no `SessionExercise` table (deferred)" | The idea landed as `SessionParticipation`, with a different shape |
> | "no maxes endpoint under any name" | `GET/POST /api/reference-maxes/` exists |
>
> **What survived, and matters more than any of the above:** the *seam*. These
> blocks decided that the tablet **reads** a resolved weight and never computes
> `percent × max`, so that a future percent-of-max system could compute the same
> number server-side and leave the tablet untouched. That is exactly what
> happened — the rack contract never changed. The rule is now **§6.3**, and it is
> the reason `react/src/rack/` is frozen. This is where it was decided and why.
>
> For what is true today: **§6** (the derivation rules) and
> [`_MESSAGE_CONTRACT.md`](_MESSAGE_CONTRACT.md).

### Built — Phase 11 minimal-path corrections (authoritative *as of July 2026* — see the banner above)
The Phase 11 prompt above was written against the FULL Phase 5 contract (SessionExercise + percent×max + an athlete-maxes endpoint). The vertical slice was built on the MINIMAL models instead (see the design memory + the exercise-identity note in Data Models), so several steps above are stale. Build to THIS:

- **Target weight — READ, don't compute.** The tablet reads `roster[athlete].targets[exercise_id]` — an already-resolved absolute weight (from the athlete's `Program`) — and never computes `percent × max`. `session_exercises[]` has NO `target_weight_percent`. (Supersedes §1412–1414. Resolution is server-side; a future percent×max swap leaves the tablet unchanged — the settled "seam".)
- **`maxes` is informational only** in the minimal build. `targets` and `maxes` are INDEPENDENT: a target comes from `Program`, not from a max, so a missing max does NOT mean a missing target, and entering a max would NOT by itself produce a target.
- **Missing TARGET fallback (not missing max).** The real gap is an athlete with no `Program` for the picked exercise → no key in `targets`. Then show an inline "Set starting weight" numeric field; the entered value becomes the displayed target AND the set's `weight_lbs` — a LOCAL, per-set weight only. It writes NO reference max and hits NO maxes endpoint. (Supersedes §1415–1423. `POST /api/athlete-maxes/` does NOT exist and is not built in Phase 11; the column is `reference_weight_lbs`, not `max_weight_lbs`.)
- **Set-create body:** `POST /api/sets/` = `{ session, athlete, node?, exercise, set_number, weight_lbs, is_makeup }`. `exercise` is the catalog INTEGER id; `weight_lbs` MUST be sent at create (from `targets[exercise_id]` or the entered starting weight) so `is_weight_pr` works at complete. (Corrects §1427, which omitted `weight_lbs`.)
- **`is_makeup` requires a one-field migration.** `Set` currently has NO `is_makeup` column (deferred from the full Phase 5). The recorded decision is `is_makeup` driven by `has_data` — so Phase 11 must ADD `Set.is_makeup` (BooleanField default False) + the serializer field + set_create pass-through, then send `is_makeup: has_data` on create. (Without the field, sending `is_makeup` is silently ignored.)
- **`node` on set-create is the Node's INTEGER pk, not `node_id`.** `NodeSerializer` doesn't expose the pk, so either add `"id"` to it, or OMIT `node` (nullable — the set still saves; only the `set_complete`/`athlete_checkin` broadcasts, which need `node.rack_number` and feed the Phase 12 dashboard, won't fire). Omitting is fine for the minimal rack flow.
- **`session_exercises` is DERIVED from `Program` per request** — there is no `SessionExercise` table (deferred). Don't query one.
- **Blueprint extras are OUT of minimal scope:** the "suggested next set" insight card (insights are Phase 8/15), the "3 of 5" sets-progress dots, the rep-by-rep velocity breakdown, and the elapsed/duration timer. Keep only: idle picker → countdown (3-2-1) → active (rep count + velocity color) → summary (`reps_completed`, avg/peak) → rest (countdown).
- **`GET /api/sessions/active/` exact shape** is pinned in _MESSAGE_CONTRACT.md §3.

### Built — Phase 11 Step 2 redesign: athlete-centric day view (authoritative *as of July 2026* — see the banner above)

**Why this changed.** The idle/picker was originally a bare athlete+exercise dropdown read off the one-shot session snapshot. Real training is fluid — athletes rotate between stations, superset across racks, and don't finish one movement before touching another — and the rack is a **vertical tablet read at a glance**, so density is the enemy. Step 2 is therefore rebuilt around the athlete's *live, server-derived progress*, shown the same way at every rack. This deliberately borrows the good ideas from Braydon's athlete-driven screen (`braydons-dev-branch`) **without his extra tables** — everything below derives from the existing `Program` + `Set` rows.

1. **Athlete-centric, progress-derived — NO new tables.** An athlete's "workout for the day" = their `Program` rows (one planned movement each: `target_sets`/`target_reps`/`target_weight_lbs`/velocity zone). Their *progress* = their completed `Set` rows this session, counted per exercise. Nothing new is stored; it is all derived per request from `Program` + `Set`.

2. **Fetch-on-check-in, plus a light roster poll.** The initial `GET /api/sessions/active/` loads the roster + session exercises. When an athlete **checks in**, the tablet fetches that athlete's derived progress (endpoint below); because it's server truth, they see the same up-to-date view wherever they check in. While the **check-in screen** is showing, the tablet also **polls the roster + hot list (~every 5s)** purely for freshness — to pick up a coach adding/removing a session athlete, and to drop an athlete who has since checked in at another rack. Progress itself is never polled: the **single-rack rule** (item 6) guarantees an athlete's progress can't change anywhere else while they're the one selected here, so fetch-on-check-in is sufficient. (This RETIRES the old "2b" live cross-rack push — see Known Open Items.)

3. **New derived endpoint (no new tables):** `GET /api/sessions/active/athlete/{athlete_id}/progress/` (open, like active-session). Shape:
   ```jsonc
   {
     "session_id": 1,
     "athlete": { "id": 4, "name": "Jordan Lee" },
     "current_exercise_id": 1,        // SUGGESTED current = first movement not yet complete (in order)
     "movements": [
       { "exercise_id": 1, "name": "Back Squat",
         "planned_sets": 5, "target_reps": 3,
         "target_weight_lbs": 225.0,   // the PRESCRIPTION from Program (never changed by the tablet)
         "last_weight_lbs": 230.0,     // actual load of the newest non-false set THIS session (null if none) — next-set default
         "velocity_zone_min": 0.5, "velocity_zone_max": 0.8,
         "completed_sets": 2, "false_sets": 0,
         "next_set_number": 3,         // completed (non-false) sets + 1 — the authoritative set_number
         "status": "in_progress" }     // not_started | in_progress | complete
     ]
   }
   ```
   Derived from `Program` (planned) + `Set` (this session, this athlete, grouped by exercise). **Movement order = `Program.id`** — the order the athlete's programs were created, which is the intended workout order in practice (a coach entering the day's movements in order gets that order for free). The server order NEVER changes; a deliberate-reorder `Program.order` field is an open nicety, not built.

4. **`set_number` now comes from the server (`next_set_number`), NOT a client counter.** This SUPERSEDES the earlier "increment set_number client-side across sets" note — a client counter can't stay correct across racks or superset switches. On set-create, send the `next_set_number` from the freshly-fetched progress.

5. **Superset switching is free.** "Current" is a *suggestion* (`current_exercise_id`), not a lock. The athlete may pick any of the day's movements; progress is per-exercise counts, so bouncing between movements keeps every count correct.
   - **Active-set float-to-top (client-side, transient):** when a set goes ACTIVE at this rack (countdown/active), that movement's card floats to the TOP of the stack so the in-progress movement is front-and-center. This reorder is presentational and **per-rack only — NOT persisted and NOT in the endpoint**; on any other rack, or once the set ends, the list returns to `Program.id` order. (Server order is immutable; only the client floats the active card. This is the one and only thing that ever reorders the stack.)

6. **Fluid check-in — no COACH-assigned athlete↔rack binding.** The coach assigns racks↔screens/nodes only (Carl's admin); a coach never pins an athlete to a rack. An athlete binds themselves, transiently, by **checking in**.
   - **Check-in records + hot list (fast re-pick).** Checking an athlete in **writes a `RackCheckIn`** row (append-only: `{session, athlete, rack_number, checked_in_at}`). An athlete's **current rack this session = their newest check-in row** (newest-wins, same pattern as `AthleteReferenceMax`). A rack's **hot list** = the athletes whose newest check-in is THIS rack, surfaced first so a lifter doing 5 sets doesn't re-scroll the roster; the full roster stays reachable. It's server-side, so it survives a tablet reload and follows the athlete across tablets. **TrainingSession-scoped only — filtered by session; nothing persists past it.**
   - **Single-rack ownership (assumption + rule).** We assume one athlete can't lift at two racks at once. Checking in at a new rack writes a newer `RackCheckIn` that **supersedes** the old one — that rack now owns the athlete, and they drop off the previous rack's hot list. Newest-wins enforces single ownership for free, and is exactly why progress needs no live cross-rack push (the retired 2b).
   - **Endpoints:** `POST /api/racks/{n}/checkin/` (records a check-in) and `GET /api/racks/{n}/checkins/` (the hot list). Shapes in MESSAGE_CONTRACT §3.
   - **"Not here?" guard:** an auto-suggested next-up athlete/movement is only a suggestion; a "Not here?" control clears it so a set is never armed for someone who walked away.

7. **Vertical, glanceable layout (hard constraint).** Single column, current movement prominent; previous/next movements as compact cards or a slim rail; only pertinent numbers (movement, set X of N, load, target velocity). **No dense grid** — it does not read on a portrait tablet at a glance.
   - **Per-movement progress:** each movement card carries a small progress bar + a `completed/planned` fraction (e.g. "2/3"), from `completed_sets`/`planned_sets` (false sets don't count toward completed).
   - **Overall session progress bar:** one bar for the athlete's whole day = total completed sets ÷ total planned sets across their movements.
   - **Completion-confirmation animation:** on set completion (summary → next state), animate the session bar advancing to its new fill as a satisfying "done" beat — a completeness confirmation at the state boundary.

8. **Carries forward the minimal-path corrections above**, with one supersession (see item 9): target is READ (`target_weight_lbs`); `weight_lbs` sent at set-create; `is_makeup = has_data`; `node` = Node pk or omitted; catalog integer `exercise` id.

9. **On-the-fly working weight + session carry-forward (authoritative; SUPERSEDES the "missing target → inline starting weight" fallback).** `Program.target_weight_lbs` is `NOT NULL` and the day view only lists a lifter's `Program` movements, so the old "missing target" case is unreachable — that inline-entry fallback is retired. In its place, a general edit: a **pencil beside LOAD** opens a full-screen themed numpad (`rack/WeightPad.jsx`) where the athlete sets what they're ACTUALLY loading. **Storage — no schema change:** the entered value becomes the set's `weight_lbs` at create (the "actual load lifted" column), a DIFFERENT slot from `Program.target_weight_lbs` (the prescription, never touched). It feeds weight-PR + future-target math downstream; the plan stays clean.
   - **Next-set default = `last_weight_lbs ?? target_weight_lbs`.** The progress endpoint returns `last_weight_lbs` — the actual load of the athlete's newest **non-false** set of that movement **this session** (null before their first). So a weight change carries forward across sets, tablet reloads, and rack moves — but is **session-scoped**: a prior session's loads are never read (the endpoint only queries the active session), so every session opens at the prescription. A local numpad edit (client `weightOverrides`, per exercise, reset on athlete change) takes precedence until the set is created. The LOAD reads lime whenever it differs from the prescribed target.

### Built — Phase 11 Steps 3–5 + room state (authoritative *as of July 2026* — see the banner above)

The full set lifecycle + rotation, on branch `phase-11-set-lifecycle`. State machine: `idle → countdown → active → summary → rest`.

**Set lifecycle (Steps 3–4):**
- **Start** (idle picker → countdown → active): `POST /api/sets/` with the selected movement's `next_set_number`, `weight_lbs` (resolved target or entered starting weight), `is_makeup = has_data`, and the Node **pk** (or omit). Keep the returned `set_id`.
- **Active**: subscribe to the linked node's reps over MQTT **only while active**; buffer each rep to the Dexie buffer FIRST, then update the live count + per-rep velocity color (against the movement's zone). `clearBuffer()` at the countdown→active edge so no stray idle/rest reps leak.
- **End** ("End Set"): read the buffer, **renumber reps 1..N** (ignore the node's advisory `rep_number`), compute `reps_completed`/`avg`/`peak`, send EXACTLY ONE `POST /api/sets/{id}/complete/` (a ref guard makes a double-tap impossible), clear the buffer only on success → `summary` (reps + avg/peak). Refetch progress so the day-view bars advance.
- **False set** ("False Set", active only): one complete POST with `is_false_set:true` + empty `reps` → `idle`; writes zero Rep rows, doesn't advance progress. (No summary "undo" — a set completes exactly once.)

**Rest + rotation (Step 5):**
- `summary` → `rest`: a countdown (default 120s) showing "Up next · {movement} · Set N".
- **`set_number` always comes from the server** (`next_set_number`) — survives rack moves + supersets.
- **Selection persists** across the whole loop (athlete + movement); only changed explicitly.
- **Auto-advance**: when a movement's planned sets are all done, the selection advances to the next movement on its own.
- **Rest-screen check-in** (athletes rotate ONE set at a time): the rest screen shows "Next Set" (current lifter continues) AND the shared check-in list — the next lifter taps in (or scans, later) to take the rack, which checks them in and opens their day view. NFC is the same code path.

**Room state / athlete status — `GET /api/sessions/active/status/` (open, coach-reusable):**
- Each session athlete's live `status` (`lifting` / `resting` / `ready` / `not_started`) + a `since` timestamp, DERIVED from `Set` (start/end) + `RackCheckIn` — **no new tables**. The tablet ticks a local per-second timer from `since` (lifting-since-start, resting-since-end, ready-since-check-in). `resting` is bounded to ~20 min (actively *between* sets, not "finished hours ago"). A coach tablet can read the same endpoint for a room view. Shape in MESSAGE_CONTRACT §3.

**Check-in / hot list (recap):** `RackCheckIn` (append-only, newest-wins, migration `0007`) via `POST /api/racks/{n}/checkin/`; the rack's hot list ("At this rack") via `GET /api/racks/{n}/checkins/`. One athlete = one rack (newest check-in wins). The check-in list is a shared component (`react/src/rack/CheckInList.jsx`) used by both the idle and rest screens, sorted by **surname** (last word of the single `name` field — stopgap until structured names), the group titled by the **session label** (real `TrainingGroup`/`Block` are deferred — see Data Models §Extended in Phase 5+).

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

- [ ] `_RUNBOOK.md` complete: start/stop, firmware flashing, MQTT test commands, full integration-test steps, common failure modes
- [ ] Architecture diagram present (Mermaid, in `_RUNBOOK.md`) showing nodes → broker → Django/Postgres and broker → browser clients over WS
- [ ] A dry run of the full session flow with **Devin observing only, not helping**
- [ ] Every teammate has flashed firmware once and run the integration test once

**STOP. Devin exits. Sprints 5–6 run without him.**

---

# SPRINTS 5–6 — Team Alone

## Phase 14 — Coach Tablet · Owner: Braydon · ⚠️ BUILT, BUT NOT AS WRITTEN

> **Delivered by THE MERGE (P0–P15), which diverged from this prompt.** The
> deliverable exists and works; the prompt below is the original design and is
> kept for provenance. Where the two disagree, **the built product wins** — read
> [`docs/_PATCH_NOTES.md`](docs/_PATCH_NOTES.md) P7/P10/P11/P13/P14.
>
> | This prompt says | What was built |
> |---|---|
> | "no multi-page tabs for this section" | **Eight tabs**: room · workouts · schedule · reports · athlete · history · programs · notes |
> | Subscribe to `edgeathlete/coach/state` | The coach view subscribes to `edgeathlete/dashboard/state`. ⚠️ The `coach/state` channel is **unused at both ends** — see Known Open Items |
> | Group/block/session browsing | Became the `Training*` hierarchy (§4) plus the schedule tab (P14) |
> | CSV upload with stub confirmation | Built, and extended with the in-preview repair loop (D17) |
> | `GET /api/racks/unassigned/`, Room Layout drag-and-drop | ✅ accurate — both exist, at `/coach/setup` |
> | Athlete max entry, max progression chart | Max entry exists; the progression chart was **not** built |

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

## Room Layout
Coach setup assigns waiting screens to rack slots with
`PATCH /api/racks/{device_id}/`. Sensor selection is intentionally absent here:
an active staff coach selects the registered sensor beside the physical rack,
before athlete check-in, through `PUT /api/racks/node-assignment/`.

## Group/Block/TrainingSession browsing
1. Groups list — GET /api/groups/, each row shows a rolled-up status dot.
2. Group detail — GET /api/blocks/?group={id}, same status-dot pattern.
3. Block detail — GET /api/sessions/?block={id}, same status-dot pattern,
   plus a roster-completion summary per session (e.g. "3/8 athletes") from
   GET /api/sessions/{id}/roster-status/.
4. TrainingSession detail — full roster from roster-status/; clicking a "no data"
   athlete is the entry point for a makeup hand-off — reuse the SAME
   drag-and-drop/assignment pattern built above (assign this athlete+session
   to a rack), not a new interaction pattern.

## CSV upload flow
"Upload TrainingSession CSV" action (from Group or Block view) posts to
/api/sessions/upload/ (Phase 6). On response, if any exercises were stubbed,
show a confirmation modal per stubbed exercise (tags, target numbers,
Confirm/Reject), calling PATCH /api/exercises/{id}/confirm/ (Phase 6).

## Status dots
One reusable StatusDot.jsx ("red"|"yellow"|"green"), used identically at
Group/Block/TrainingSession levels — same one-component principle as the shared
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
- Navigating Group → Block → TrainingSession shows correctly rolled-up status dots at every level, matching the backend's computed status.
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

## Phase 16 — Security Hardening · Owner: whole team · ⚠️ PARTIAL

> ⚠️ **Rewritten 2026-07-30.** The original prompt said "verify JWT covers all
> coach-only endpoints (should already be true)". That is still true and is no
> longer the interesting part — the merge made a deliberate decision that changes
> what "hardening" means here, and verifying the old sentence would have someone
> confirm something the team decided *not* to do.

### What the merge decided, and why it matters here

**Historical merge behavior:** authentication was enforced without staff or team
authorization. Any authenticated coach could read and edit any block, group, or
program. This was the **filter-not-fence** decision
(§9, P11): `?coach=me` is a lens so nobody scrolls a department-sized catalog, not
a wall. It was chosen because a real boundary costs object-level checks on every
write endpoint plus a who-can-do-what test matrix, and because the scenario it
would guard is not reachable — there is no block DELETE and no way for one coach
to destroy another's work.

The active-staff fence now blocks non-staff users from remaining unscoped routes.
Athlete, TrainingGroup, and TrainingBlock routes enforce organization scope;
program catalog/deployment/promotion also require active staff plus organization
scope. CSV imports use the same staff-plus-organization boundary. Remaining
program, session, report, and analytics scoping is pending.

### The actual work

1. **Decide whether authorization is now wanted.** If the answer is yes, it is
   additive on top of the filter — the filter does not have to be undone first.
   If no, say so here and close it.
2. **Move Mosquitto off `allow_anonymous true`** to ACLs/auth on both listeners
   (1883 for hardware and Django, 9001 for the browsers). This is the largest real
   hole: anything on the gym's network can currently publish to any topic,
   including fake rep data.
3. **Rate-limit login.**
4. **Confirm no coach-only path is reachable unauthenticated** — still worth doing,
   and it was never the same question as authorization.
5. **Group-staff UI.** `TrainingGroupCoach` records who runs a group and nothing
   reads it for permission. If step 1 says yes, this is where it starts being real.

**STOP. Review before moving to Phase 17.**

---

## Phase 17 — Firmware Hardening & Additional Mounts · Owner: Derrilon
Waist and wrist mount thresholds, WiFi reconnect logic, enclosure v1. Resolve (or keep hooked) the noise-reduction location decision.

**STOP. Review before moving to Phase 18.**

---

## Phase 18 — Full Integration Test & Demo Prep · Owner: whole team
Seed script, one-command `start.sh`, `DEMO_SCRIPT.md`, screen-recording backup. The full session script must run clean at least twice in a row before demo day.

Add to the seed script and `DEMO_SCRIPT.md`: seed at least one TrainingGroup
with a Block and a CSV-uploaded TrainingSession (including at least one intentionally
unrecognized exercise name, to demo the stub-confirmation flow), and include
one deliberately "missing" athlete to demo the makeup flow and its effect
(or non-effect) on team_completion_time. The full session script (already
required to run clean twice before demo day) should now also cover: CSV
upload → stub confirm → run session → one athlete makeup → status dots
updating correctly at all three hierarchy levels.

---

---

## §9. Decision log

- **D1 — Exercise catalog is canonical.** Keep `Exercise`(+`Tag`); his CharFields → `FK→Exercise`. No backfill;
  seed starter movements in the migration (§5.4).
- **D2 — Rack presence → keep `RackCheckIn`, drop `AthleteRackParticipation`.** Everything his table held
  (current rack, first/last seen) is derivable from our append-only log.
- **D3 — Day progress → derived; drop `AthleteDayProgress`.** Coach-shaped derived endpoint; all derivation
  lives in `services/`.
- **D4 — `is_simulated` → adopt (union)** on Node/Athlete/Session/Set/MonitoringEvent; simulators stamp it so
  `clear_simulation_data` wipes demo data cleanly.
- **D5 — MQTT → keep his `realtime/` + monitoring outbox; fold in our rack `broadcast/publisher`** without
  changing any rack topic/route. Drop our inherited `notification_flow/` cruft. Webhooks untouched.
- **D6 — `TrainingProgram.training_block` is NULLABLE** → one-off programs are a permanent first-class path.
  ⚠️ **CORRECTED 2026-07-29:** this decision used to end "promotion to a template is just pointing the FK at a
  new block row." That is wrong — the FK records provenance and copies nothing, so it would produce a block
  with no days. Promotion has to copy the rows up first; see D21 / P15.
- **D7 — CSV import survives at BOTH block and program level.** Block-level = reusable template;
  program-level = immediate one-off. Only the old single fixed target shape retired. ⚠️ **The single-contract
  framing here is SUPERSEDED by D16** (sheet-type detection); the both-levels requirement stands unchanged.
- **D8 — Drop `RackWorkoutState`; rebuild room-state** from `RackCheckIn` + derived progress (§6.4). The
  forward rack-assignment concept dies entirely.
- **D9 — `Node.allowed_exercises`** — a static hardware fact, empty = unrestricted. **Filtered into the
  movement list (§6.2 step 5), NEVER a `set_create` rejection**: `RackScreen.jsx` flips to the active lifting
  screen *before* `set_create` resolves and swallows its error, so a rejection would strand an athlete on a
  dead screen — and fixing that needs new UI inside a frozen file (§2.1). Fail open.
- **D10 — Reference max recalculates on session completion, feeds forward only. No new schema.** Writes a new
  `AthleteReferenceMax` row (`source=estimated`); never recomputes targets an athlete already trained against.
  Lives in the same service as `DailyReport` generation. **The estimation method is deferred** — decide it when
  that service is built.
- **D11 — Epley for rep-basis conversion; rounding to 5 lb; `Set.rack_number` dropped.** See §6.1. The formula
  lives in exactly one `services/` helper. Rack identity comes from `RackCheckIn` everywhere (D2), so his
  `Set.rack_number` column is not needed and is dropped with the workout-link cleanup.
- **D12 — `Athlete ↔ TrainingGroup` is MANY-TO-MANY.** An athlete can train with several groups at once
  (e.g. "Varsity Football" *and* "Speed Squad"), each carrying its own `TrainingProgram`. Which program applies
  on a given day is **not** stored or configured — it's the intersection of the athlete's groups with the
  groups participating in that session (§6.2 step 2). A deterministic tie-break covers the rare case where two
  of an athlete's groups are on the same session. Membership is current-state only and never rewrites history.
  *(Decided 2026-07-23, replacing an earlier single-FK `training_group` that would have forced a
  multi-program athlete into one squad.)*
- **D13 — A multi-group athlete trains the MERGED plan: intersect programs, union movements, dedupe by
  exercise, lower percent wins.** Two set operations at two levels (§6.2): *which programs apply* is an
  **intersection** (athlete's groups AND the session's participating groups); *the movement list* is a
  **union** of those programs' workouts with duplicates collapsed. A receiver on a football session trains the
  team lift **plus** position work, not just the overlap. Dedupe by `exercise_id` is **mandatory** — the frozen
  contract tallies progress per exercise, so a duplicated movement would corrupt `next_set_number` (§6.2 step
  4c). Collisions resolve to the **lower `target_percent`**, taking that row whole (coaches adjust downward to
  shed load, so the lower number is the deliberate one). Program order = **largest group first**, so the team
  lift precedes accessory work. *(Decided 2026-07-23.)*
- **D14 — Redundancy audit: 6 of his routes fold into existing ones, 3 are dropped outright** (§7.3/§7.4), and
  `SessionParticipation.snapshot` is removed. Rule applied: *two routes must never do one job; when they tie,
  keep OURS and change his FE.* Folds: `athletes/{id}/notes/`→`athletes/{id}/` PATCH (the serializer already
  exposes `notes`); `sessions/{id}/end/`→`sessions/{id}/` PATCH (ours already ends sessions); `wall-state/`→
  `room-state/?details=` (same function, one boolean apart); the athlete-scoped `reports/*` family→
  `reports/?athlete=` (deletes 3 routes); `racks/{n}/sets/*`→`sets/*`. Dropped: `racks/{n}/athlete/`,
  `racks/{n}/state/`, `racks/{n}/assignment/` — their only callers were his dropped rack screen and the
  D8-deleted assign panel. Net: **~9 fewer endpoints to build and maintain.** *(Audited 2026-07-23.)*
- **D15 — Coach weight adjustment rides the shared `sets/` path, flagged `Set.is_coach_adjustment`** (full
  spec §6.5). It moves the **working load** (weight *(c)*, `last_weight_lbs`), never the prescription (weight
  *(b)*) — that lever is the reference-max write or the P5 override. **Reuse, not a new route:** it writes
  through the same set-creation path the WeightPad uses (the one `racks/{n}/sets/` folded into under D14).
  **The flag is mandatory** because in `athlete_progress` the same `else` branch that sets `last_weight` also
  increments the set counter — so no `Set` shape can move the displayed weight without also moving
  `next_set_number`/`status` unless a flag lets reads separate them. **Include/exclude list** (verified against
  code 2026-07-23): INCLUDE only in `athlete_progress`→`last_weight_lbs`; EXCLUDE from that view's set counts,
  `session_status` (else the athlete shows "resting"), analytics, `sessions_active`'s `has_data` (else the
  first real set is mis-flagged `is_makeup` — **caught in this audit, not in the original request**), and P4
  `DailyReport` generation. Default for any new `Set` read = EXCLUDE. **Not a §2.2 break:** optional request
  field, default False, response shape unchanged, no frozen file touched. *(Decided 2026-07-23.)*
- **D16 — CSV import is SHEET-TYPE DETECTED, not one fixed contract.** A coach's spreadsheets are not all the
  same thing, so the importer identifies which of three shapes a file is by **the column headers present**,
  then routes it. This **supersedes D7's single-contract framing** while keeping its requirement (plan import
  works at block *and* program level).

  | sheet type | detected by | writes to | unknown names |
  |---|---|---|---|
  | **roster** | `athlete_name` + no `exercise` | `Athlete` | **creating is the point** |
  | **reference max** | `athlete_name` + `exercise` + a weight column | `AthleteReferenceMax` | resolve, never auto-create |
  | **plan** | `workout_name` + `exercise` + `target_percent` | `TrainingBlock*` **or** `TrainingProgram*` (D7) | resolve, or explicit `is_stub` |

  Three rules bind all three shapes:

  1. **`target_percent` REPLACES his `default_weight_lbs` column.** A pounds column is a second, contradictory
     way to prescribe that bypasses the reference-max machinery entirely, and §6.1/`TrainingBlockExercise`
     already say the plan stores percent and *"never an absolute weight."* Accept **1–150** (over-100 is real:
     overload eccentrics); reject 0 and negative. **This is a deliberate break in his CSV contract** — the only
     one — and it is why his sample files need one header renamed.
  2. **A weight is only converted when its meaning is EXACT.** `AthleteReferenceMax.rep_basis` +
     `lifting_math.normalize_to_single()` already handle "225x5" honestly, so three of four cases need no
     guess at all: a bare max (`rep_basis=1`), rep-qualified work (`rep_basis=5`), and a stated percent
     (exact back-solve).
  3. **The fourth case — a bare weight with no reps and no percent — IS SKIPPED, never inferred.** Assuming a
     percentage does not stay local to its row: `AthleteReferenceMax` is newest-wins, so a fabricated row
     **outranks the athlete's real tested max** and skews every *other* movement's target for them, silently,
     as a side effect of an upload. A *missing* max is by contrast an already-tested state (P5 exit criteria:
     no reference max → `null` target, rack still works). Skipping trades a novel failure for a known-safe one.
     Both preview and import report who was skipped and for what movement. *(Decided 2026-07-27.)*

- **D17 — Import errors are REPAIRED IN PREVIEW, not rejected.** Hard-failing a 200-row file over one typo is
  the wrong behavior, and the mechanism to avoid it is already built: preview exists, and every error already
  carries `{row, field, code, detail}` which his `flattenApiErrors` walks. Four additions make it a repair loop.

  **(a) Name resolution ladder** — cheapest and most certain first. `athlete_name` and `exercise` both use it:

  | # | rule | outcome |
  |---|---|---|
  | 1 | `nfc_tag_id` column present and matches | exact, zero ambiguity |
  | 2 | matches exactly one athlete **in the target squad** | resolved |
  | 3 | matches exactly one gym-wide | resolved |
  | 4 | matches several | `ambiguous_athlete` → candidates offered |
  | 5 | matches none | `unknown_athlete` → suggestions + "create new" |

  **Squad-scoping (step 2) is what collapses the ambiguity.** Two "Jordan Lee"s in a building is plausible; two
  in one 30-person squad is not. Same trick as scoping workout-name uniqueness to the parent. Normalize before
  matching — casefold, strip, collapse internal whitespace, flip a single `Lee, Jordan` → `Jordan Lee` — which
  covers essentially all real spreadsheet drift. **No new column on `Athlete`**: a few hundred rows resolve in
  memory (derived-over-stored, §3).

  **(b) Errors carry `suggestions`.** `difflib.get_close_matches` against the catalog/roster. Stdlib, no
  dependency. Any error with a `suggestions` array gets identical UI treatment — which is what makes this one
  handler rather than three features.

  **(c) Preview returns parsed rows EVEN WHEN THEY HAVE ERRORS.** His `preview_workout` returns only valid
  workouts today, so a repair grid would have nothing to render. **This one change is what unblocks P7's UI**;
  without it the frontend work is impossible.

  **(d) The repair submits a name→id MAP, not corrected strings.** Resolve "Jordn Lee" once and all 14 of their
  rows resolve. The map is what carries typo fixes, ambiguity picks, and create-new decisions uniformly.

  **Auto-creation is never silent.** A typo'd ghost athlete sits in the roster forever shadowing the real one,
  and a typo'd movement is one no rack's `allowed_exercises` covers (D9). So creation happens only on a roster
  sheet, where it is the point, or by explicit coach action — for exercises that means `Exercise.is_stub`,
  which **already exists for exactly this** ("a row auto-created from an unrecognized import that a coach
  hasn't confirmed yet"). It is reached deliberately from preview, not automatically.

  **Split across phases on purpose: every backend piece P7 needs ships in P5**, so the frontend work is pure
  UI with no backend contract left to design. *(Decided 2026-07-27.)*

- **NEW — reference-max write endpoint** (§7.2) — neither branch had one, yet §6.1 needs it; add a bulk
  (list-of-athlete-ids) POST creating `AthleteReferenceMax` rows. No new schema. The prescription lever;
  separate from D15.
- **NEW — Athlete notes → the existing `Athlete.notes` field, no new table AND no new route** (R1).

---

### D18–D21 — the four found late, all now built

These four were raised after the decision log above was written, while the merge
was already running. All four are **built**; they are recorded here because the
reasoning still governs the code.

**D18 — the stacked-session trap.** Nothing stopped several sessions being open at
once, and "the active session" was simply the most recent one with no `ended_at`.
A stray second session therefore **silently captured check-ins**: athletes' sets
attached to a day with no participants, the day's report came out wrong, and every
tablet looked completely normal. It also made "End training day" look broken —
ending the top of the stack instantly promoted the next one and the panel redrew
identically. **Built in merge P12:** creating a second open day is a 409 naming the
one already running, and ending a day says which day ended.

**D19 — the analytics shape gap.** The coach front end's `athlete` and `history`
tabs were written against an analytics payload nobody had ever pinned down;
`analytics/athlete/{id}/` returned only a flat velocity trend, so selecting an
athlete threw and took the whole coach view down with it. **Built in merge P13:**
the endpoint returns the athlete, a summary, per-exercise aggregates and per-set
reps, with the exact field list in `_MESSAGE_CONTRACT.md`. ⚠️ The same trap is still
unsprung on `GET /api/analytics/session/{id}/`, which remains prose-only.

**D20 — scheduling.** See §"The training calendar" below and `docs/_PATCH_NOTES.md`
P14. The load-bearing consequence: **"active" means STARTED and not ended**, never
merely un-ended, because `started_at` is now nullable so a session can exist before
it runs. Postgres sorts NULLs *first* in a descending order, so without that filter
a session created for next Thursday sorts ahead of the day being trained and the
racks follow it. The rule lives in exactly one place,
`services/active_session.py`.

**D21 — promotion.** Turning a program back into a reusable block **copies its days
and prescription rows up**. It is not a matter of pointing `training_block` at a
new row: that records provenance and copies nothing, so the block comes out with
zero days and deploying it hands a group an empty plan. ⚠️ This document and two
docstrings asserted the false version for weeks before anyone checked. **Built in
merge P15** as `promote_program_to_block()`.


---

## §10. Explicitly deferred / out of scope

Do not build these. If you think one is needed, escalate (§11) rather than expanding scope.

- **Calendar generator** (drag block → date → auto-create sessions). Schema-ready only (§4.5).
- **`AthleteWorkoutExerciseOverride` mechanics debate.** The model is settled and the endpoint is scoped to P5
  as a thin exception path. **Do not re-open its design** — that was the previous attempt's rabbit hole.
- **Rollup health-status color (b)** (§5.6) — not built anywhere, not this merge.
- **Ref-max estimation method** (D10) — *when* it fires is decided; *how* it estimates is not.
- **Dashboard layout redesign** (§7.6) — theme kept, layout redo is separate.

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
- **Phases 5–8 (new):** Group/Block/TrainingSession hierarchy, Exercise catalog + Tag
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
