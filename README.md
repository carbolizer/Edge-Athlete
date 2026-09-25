# Edge Athlete — Offline Training Platform

Edge Athlete is a team-built velocity-based training system designed to run an entire gym from a local base station, without depending on an internet connection.

Rack-mounted sensors publish barbell data over MQTT, athletes use rack tablets for live feedback, coaches manage the room from an admin interface, and a wall display shows activity across the gym. The base station ties those pieces together with **Django, React, PostgreSQL, Mosquitto, Nginx, and Docker Compose**.

## Why I keep this project featured

This is the project where I have gotten the most experience working inside a larger software system instead of building one isolated assignment. It has a real service boundary, persistent data, device communication, authentication, multiple frontend roles, and deployment concerns.

### My contributions

My work in the repository includes the initial base-station setup and a coach-admin integration that added:

- a JWT-gated coach interface
- rack-screen and sensor-node assignment to numbered rack slots
- API helpers for authenticated coach requests
- role-specific PWA manifests for coach, rack, and dashboard devices
- service-worker support for the offline application shell
- Django startup support for the demo coach workflow used during development

This is a collaborative project, so the repository also includes substantial work from other team members.

## Stack

| Area | Technology |
|---|---|
| Backend | Django / Django REST API |
| Frontend | React |
| Database | PostgreSQL |
| Device messaging | MQTT / Mosquitto |
| Reverse proxy | Nginx |
| Deployment | Docker Compose |
| Hardware side | ESP32-based rack nodes |


---

## Quick start

```bash
docker compose up -d --build
```

Then, on a fresh database, print the one-time setup code from the base station
itself, and open `http://localhost/` to create the initial coach/admin account:

```bash
docker compose exec django python manage.py setup_code
```

The code proves the person enrolling has access to the machine, so the first
visitor to the website cannot claim the installation. Additional coach logins are
created by an administrator under **Coach → coaches**; there is no public
registration. Other devices can use the **role picker**, or you can use **Change
device** to choose a role:

| Role | What it is |
|---|---|
| **Rack Tablet** | The athlete-facing screen at a rack — check in, run a set, rest, repeat |
| **Base Station Display** | The read-only wall scoreboard for the room |
| **Coach Admin** | The coach's console — planning, roster, reports, schedule, analytics |

> **A device remembers its role.** After you pick one, `localhost/` goes straight
> there forever. Change it with **Change device** in the top right.

Normal startup does not create a default login. Existing installations keep their
accounts. See [Coach accounts and roster management](docs/coach-accounts.md) for
first-run setup, login, password recovery, and history-preserving roster removal.

For demonstration data in a development installation:

```bash
docker compose exec django python manage.py seed_active_session
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
   bug. [`docs/_HANDOFF.md`](docs/_HANDOFF.md) §1 explains why, and what the tempting
   wrong fix breaks.
2. **The rack experience is contract-sensitive.** Preserve its state machine and
   buffering behavior unless an accepted feature spec explicitly changes them.
   The rack BLE workflow documents the current sensor-setup exception.

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
| [`docs/reference/spec.md`](docs/reference/spec.md) | **The single authority.** Constraints, the hierarchy, the derivation rules, the decision log, and the full build timeline. Start here. |
| [`docs/reference/message-contract.md`](docs/reference/message-contract.md) | Exact request/response shape of every endpoint and MQTT topic. The authority for wire formats. |
| [`docs/guides/base-station.md`](docs/guides/base-station.md) | Services, start/stop, operational notes. |
| [`docs/_HANDOFF.md`](docs/_HANDOFF.md) | The non-obvious things, for whoever picks this up. Start here if you are new. |
| [`docs/`](docs/) | Write-ups of finished work — patch notes, the database tour, the migration playbook, the import guide. |

**Two documents are authoritative and everything else defers to them:** `docs/reference/spec.md`
for *why the system is shaped this way*, `docs/reference/message-contract.md` for *what a request
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

> **Route-by-route detail is in [`docs/reference/message-contract.md`](docs/reference/message-contract.md), not
> here.** This README used to list every endpoint and quietly went out of date;
> one copy is the fix.

### A note on access

`IsCoach` requires an active account assigned to this installation's weight room.
The server checks membership on each authenticated data request. Training-group
coach assignments remain descriptive; they do not restrict access within the
assigned room. See [room access](docs/guides/coach-room-access.md) and
[account security](docs/coach-accounts.md#account-security-and-failed-login-limits).

---

## The database

24 tables. The shape, in one line:

```
TrainingBlock (template) → TrainingProgram (deployed, dated) → TrainingGroup (who) → TrainingSession (the day) → Set → Rep
```

A plain-English tour of every table — what it is, why it exists, and the two or
three things that surprise people — is in
[`docs/reference/database.md`](docs/reference/database.md). The source of truth is
[`django/event_handler/models.py`](django/event_handler/models.py), which carries
the reasoning in comments.

Changing the schema? Read [`docs/guides/migrations.md`](docs/guides/migrations.md)
first — the Django container **bakes its source at build time**, which makes
`makemigrations` behave in a way that has already cost this project a migration.

---

## Admin

```bash
docker exec -it edgeathlete-django python manage.py createsuperuser
```

Then `http://localhost/admin/` to browse the tables directly.

### Coach room access

See [coach assignments and deployment](docs/guides/coach-room-access.md) and the
[detailed implementation plan](docs/coach-room-implementation-plan.md).
