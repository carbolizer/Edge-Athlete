# Edge Athlete — Base Station

Velocity-based training for the whole gym, running on one offline base station.
Sensors on the racks measure bar speed, tablets show live feedback, a wall display
scoreboards the room, and everything is saved for history — with no internet.

This repo is the **base station**: the Docker stack (Django API, PostgreSQL,
Mosquitto broker, Nginx, React) that runs the gym.

---

## Quick start

```bash
docker compose up -d --build
```

Then open `http://localhost/`. The first screen is a **role picker** — this device
has no role yet. Pick one:

| Role | What it is |
|---|---|
| **Rack Tablet** | The athlete-facing screen at a rack — check in, run a set, rest, repeat |
| **Base Station Display** | The read-only wall scoreboard for the room |
| **Coach Admin** | The coach's console — planning, roster, reports, schedule, analytics |

> **A device remembers its role.** After you pick one, `localhost/` goes straight
> there forever. Change it with **Change device** in the top right.

The demo login is `coach` / `coachpass`. For a gym full of realistic data:

```bash
docker compose exec django python manage.py seed_active_session --reset
```

---

## How it fits together

```
  Rack node (ESP32 + sensor)                 Browsers (tablets, wall display)
        │ MQTT 1883                                   │ MQTT-over-WebSockets 9001
        ▼                                             ▼
  ┌─────────────── Mosquitto broker ───────────────┐
  │  reps + heartbeats                             │
  └───────┬────────────────────────────────────────┘
          │ heartbeats only
          ▼
   Django  ──►  PostgreSQL           Nginx ──► React (this UI) + /api → Django
```

- **Web path:** browser → Nginx → Django (the API) → PostgreSQL.
- **Sensors:** each node publishes reps + heartbeats to Mosquitto over MQTT (1883).
- **Screens:** tablets and the wall display talk to the broker **directly** over
  MQTT-over-WebSockets (9001) — no server in the middle, no Django Channels.
- **The key rule:** Django's subscriber only listens for **heartbeats**
  (`edgeathlete/node/+/pulse`). Reps are saved in **one batch** when a set
  finishes (`POST /api/sets/{id}/complete/`) — never streamed one at a time.

### The two ideas worth knowing before you read any code

1. **A plan stores a percent, not pounds.** A coach prescribes "Back Squat 5×3 at
   80%" once for a whole group; each athlete's bar weight is resolved at read time
   against their own current reference max. There is no target-weight column.
   ⚠️ That reference max is what the athlete can do *now*, so it can go **down** —
   and prescribed weights are meant to follow it down. That is the design, not a
   bug. [`docs/HANDOFF.md`](docs/HANDOFF.md) §1 explains why, and what the tempting
   wrong fix breaks.
2. **The rack experience is frozen.** `react/src/rack/`, `react/src/db/repBuffer.js`
   and `react/src/device.js` are a fixed contract — they ship and they work. Don't
   edit them; build alongside.

### Changing the training math

Every number a coach or sports scientist might argue with lives in **one file**:
[`django/event_handler/services/tuning.py`](django/event_handler/services/tuning.py).
The functions that use those numbers sit beside it in `lifting_math.py`.

| To change | Edit |
|---|---|
| How generous the 1RM estimate is | `tuning.EPLEY_DIVISOR` |
| Which rep counts are trusted for an estimate | `tuning.MIN/MAX_REPS_FOR_ESTIMATE` |
| Bar rounding (5 lb → 2.5 lb plates) | `tuning.LOADING_INCREMENT_LBS` |
| How long "resting" lasts / when a sensor reads stale | `tuning.RESTING_WINDOW`, `tuning.NODE_STALE_AFTER` |
| The 1RM formula itself (Epley → Brzycki) | `lifting_math.one_rep_max()` — one line |
| **Rep colour (green/yellow/red)** | `react/src/rack/velocity.js` — **frozen**, see below |

Two deliberate exclusions, both explained in `tuning.py`:

- **Operational guards stay put** (`MAX_CSV_BYTES`, `MAX_PDF_PAGES`, `SET_LIMIT`).
  They protect one piece of code rather than expressing a view about training, so
  they live next to it. Keep `tuning.py` short or it stops being findable.
- **The velocity-colour threshold can't move.** The tablet computes each rep's
  colour and POSTs it — the server only stores what it was told, so there is no
  second copy. Changing it means touching the frozen rack contract *and* accepting
  that every colour already stored was computed under the old threshold.

---

## Where things are

| | |
|---|---|
| [`_SPEC.md`](_SPEC.md) | **The single authority.** Constraints, the hierarchy, the derivation rules, the decision log, and the full build timeline. Start here. |
| [`_MESSAGE_CONTRACT.md`](_MESSAGE_CONTRACT.md) | Exact request/response shape of every endpoint and MQTT topic. The authority for wire formats. |
| [`_RUNBOOK.md`](_RUNBOOK.md) | Services, start/stop, operational notes. |
| [`docs/HANDOFF.md`](docs/HANDOFF.md) | The non-obvious things, for whoever picks this up. Start here if you are new. |
| [`docs/`](docs/) | Write-ups of finished work — patch notes, the database tour, the migration playbook, the import guide. |

**Two documents are authoritative and everything else defers to them:** `_SPEC.md`
for *why the system is shaped this way*, `_MESSAGE_CONTRACT.md` for *what a request
looks like*. If another file disagrees with those two, those two are right.

---

## The API

Base path `/api/`. **Open** = no login (the rack tablet and wall display never log
in). **Coach** = needs a JWT from `POST /api/auth/login/`.

About fifty routes, grouped:

| Group | Covers |
|---|---|
| **Auth** | login, refresh |
| **Rack tablet** (open) | rack register/assign, check-ins, the one startup fetch, athlete day view, room status, start a set, complete a set |
| **Room** (open) | `room-state/` — the wall display and the coach room view, same read behind a `?details=` flag |
| **Roster** | athletes, exercise catalog, training groups, group athletes, group coaches |
| **Planning** | training blocks + their days and prescription rows, block categories, reordering, training programs, promote a program into a block |
| **Scheduling** | scheduled slots, move a slot, create the session for a slot |
| **Per-athlete** | an athlete's program view, per-exercise overrides, reference maxes |
| **Reports** | list, detail, PDF |
| **Analytics** | per-session summary, per-athlete history |
| **Imports** | preview then commit — roster, maxes, and workout-plan CSVs |

> **Route-by-route detail is in [`_MESSAGE_CONTRACT.md`](_MESSAGE_CONTRACT.md), not
> here.** This README used to list every endpoint and quietly went out of date;
> one copy is the fix.

### A note on access

`IsCoach` currently means **"is authenticated"** — not "is a coach of *this*
group". Coach assignment is recorded and used to *filter* views, and it is not
enforced as a permission. That is a deliberate choice for a single-gym offline
box, written up in `_SPEC.md` §9 and Phase 16. Don't mistake it for an oversight,
and don't assume a group-coach row protects anything.

---

## The database

24 tables. The shape, in one line:

```
TrainingBlock (template) → TrainingProgram (deployed, dated) → TrainingGroup (who) → TrainingSession (the day) → Set → Rep
```

A plain-English tour of every table — what it is, why it exists, and the two or
three things that surprise people — is in
[`docs/DATABASE-OVERVIEW.md`](docs/DATABASE-OVERVIEW.md). The source of truth is
[`django/event_handler/models.py`](django/event_handler/models.py), which carries
the reasoning in comments.

Changing the schema? Read [`docs/MIGRATION_PLAYBOOK.md`](docs/MIGRATION_PLAYBOOK.md)
first — the Django container **bakes its source at build time**, which makes
`makemigrations` behave in a way that has already cost this project a migration.

---

## Admin

```bash
docker exec -it edgeathlete-django python manage.py createsuperuser
```

Then `http://localhost/admin/` to browse the tables directly.
