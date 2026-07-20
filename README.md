# Edge Athlete — Base Station

Velocity-based training for the whole gym, running on one offline Raspberry Pi.
Sensors on the racks measure bar speed, tablets show live feedback, a wall display
scoreboards the room, and everything is saved for history — with no internet.

This repo is the **base station**: the Docker stack (Django API, PostgreSQL,
Mosquitto broker, Nginx, React) that runs on the Pi.

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
- **Screens:** coach and wall browsers talk to the broker **directly** over
  MQTT-over-WebSockets (9001) — no server in the middle, no Django Channels.
- **The key rule:** Django's subscriber only listens for **heartbeats**
  (`edgeathlete/node/+/pulse`). Reps are saved in **one batch** when a set
  finishes (`POST /api/racks/{rack}/sets/{id}/complete/`) — never streamed one
  at a time. The generic completion route remains simulator compatibility only.

**Nineteen database tables:** `Node`, `RackScreen`, `Athlete`, `Program`,
`Workout`, `WorkoutExercise`, `WorkoutProgram`, `WorkoutProgramItem`,
`AthleteWorkoutAssignment`, `AthleteWorkoutProgramAssignment`,
`AthleteWorkoutExerciseOverride`, `Session`, `AthleteDayProgress`, `DailyReport`,
`AthleteRackParticipation`, `RackWorkoutState`, `Set`, `Rep`, and
`MonitoringEvent`.
(`RackScreen` = the tablet at a rack;
`Node` = the sensor. They share a `rack_number` but are assigned independently.)

---

## Quick start

Create local configuration before starting Docker:

```bash
cp .env.example .env
```

The template runs as copied but binds the website to loopback only. `setup.sh`
generates restricted deployment secrets and changes the bind address to the Pi
access-point IP. For another shared deployment, replace `SECRET_KEY` and
`POSTGRES_PASSWORD`, set `DEBUG=False`, and set `EDGEATHLETE_BIND_ADDRESS`
deliberately. Keep
`EDGEATHLETE_HTTP_PORT=8081` unless that port is already occupied.

```bash
docker compose up --build -d --remove-orphans
```

The website defaults to host port `8081`, so another project on port 80 cannot
be mistaken for this app.

When replacing a stack created under a different Compose project name, stop
that project explicitly first. `--remove-orphans` cannot remove containers or
volumes owned by another Compose project; retain or delete its data according
to that project's retention requirements.

Then open:

| URL | What it is |
|---|---|
| `http://localhost:8081/dashboard` | Live Edge Athlete wall display |
| `http://localhost:8081/coach` | Authenticated coach workspace |
| `http://localhost:8081/rack` | Athlete sign-in, current program progress, rack-bound sets, and live-rep feedback |
| `http://localhost:8081/connection-test` | **API & architecture demo page** — click endpoints, see live data |
| `http://localhost:8081/admin/` | Django admin — browse registered operational tables (needs a superuser) |
| `http://localhost:8081/api/...` | The REST API (below) |

Create a superuser for the admin: `docker exec -it edgeathlete-django python manage.py createsuperuser`

Start generated sensor data without hardware:

```bash
docker compose --profile simulation up -d simulator
```

If ports 1883 or 9001 are already occupied, stop the older MQTT project before
starting Edge Athlete. Do not use `http://localhost/` for this stack; its explicit
entry point is `http://localhost:8081/` unless `EDGEATHLETE_HTTP_PORT` is changed.

To identify older containers before startup:

```bash
docker ps --format "table {{.Names}}\t{{.Ports}}"
```

Stop the older Compose stack from its own repository with
`docker compose down --remove-orphans`. This does not delete its database volume.

---

## REST API

Base path: `/api/`. **Open** = no login. **Coach** = needs a JWT from `/api/auth/login/`.
Request/response shapes for the real-time messages are in [MESSAGE_CONTRACT.md](MESSAGE_CONTRACT.md).

### Auth
| Method | Path | Access | What it does |
|---|---|---|---|
| POST | `/api/auth/login/` | open | Log in as a coach → returns `{access, refresh}` tokens. |
| POST | `/api/auth/refresh/` | open | Exchange a refresh token for a fresh `access` token. |

### Tablet — racks & sets
| Method | Path | Access | What it does |
|---|---|---|---|
| POST | `/api/racks/register/` | open | A tablet introduces itself (`{device_id}`) so a coach can assign it a rack. |
| POST | `/api/racks/racknumber/` | open | A waiting tablet submits `{device_id}` and receives `{rack_number}` without putting its stable ID in logs. |
| GET | `/api/racks/{rack_number}/state/` | open | Read the selected athlete, full prescription, active movement, and bounded node readiness for one rack. |
| PATCH | `/api/racks/{rack_number}/state/` | coach | Legacy coach movement selection; retained for compatibility. |
| PUT | `/api/racks/{rack_number}/assignment/` | coach | Legacy rack catalog assignment; athlete-driven training does not use it. |
| PUT · DELETE | `/api/racks/{rack_number}/athlete/` | open | Select or clear an active athlete using the canonical ID of the tablet assigned to the rack. |
| POST | `/api/racks/{rack}/sets/` | open/private AP | Start the signed-in athlete's server-derived current set with `{device_id}`. |
| POST | `/api/racks/{rack}/sets/{id}/complete/` | open/private AP | Finish an athlete-driven set using canonical `X-Rack-Device-Id`; saves reps and progress atomically. |
| POST | `/api/sets/` | open | Legacy simulator-owned set start; real active sessions return `rack_bound_set_required`. |
| POST | `/api/sets/{id}/complete/` | open | Legacy/simulator completion; athlete-driven sets return `rack_bound_set_required`. |

### Reads
| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/nodes/` | open | List all sensor nodes and their status. |
| GET | `/api/wall-state/` | open | Read the automatic VBT movement and movement-specific leaderboard without IDs. |
| GET | `/api/room-state/` | coach | Read detailed rack registration, athlete progress, results, and hardware state. |
| GET | `/api/athletes/` | coach | List all lifters. |
| GET | `/api/programs/?athlete={id}` | open | An athlete's training plans — targets + the speed zone used to color reps. |

### Coach — manage
| Method | Path | Access | What it does |
|---|---|---|---|
| POST · PATCH | `/api/athletes/` · `/api/athletes/{id}/` | coach | Add or edit a lifter. |
| POST | `/api/programs/` | coach | Create a training plan for a lifter. |
| GET · POST | `/api/workouts/` | coach | Browse or manually create reusable ordered workouts. |
| POST | `/api/workouts/imports/preview/` | coach | Validate and normalize a workout CSV without saving it. |
| POST | `/api/workouts/imports/` | coach | Revalidate and atomically import a create-only workout CSV. |
| GET · POST | `/api/workout-programs/` | coach | Browse or create ordered programs from reusable workouts. |
| GET · PUT · DELETE | `/api/athletes/{id}/workout-assignment/` | coach | Read, replace, or remove the athlete's complete ordered `WorkoutProgram` assignment. |
| GET · PATCH · DELETE | `/api/athletes/{id}/workout-exercises/{exercise_id}/override/` | coach | Read, sparsely update, or remove athlete exercise target overrides. |
| POST · PATCH | `/api/sessions/` · `/api/sessions/{id}/` | coach | Start a session; a PATCH with no `ended_at` ends it now. |
| POST | `/api/sessions/{id}/end/` | coach | Atomically end a real training day and return its immutable daily report. |
| GET | `/api/reports/` · `/api/reports/{id}/` | coach | Browse paginated report summaries or one allowlisted immutable report. |
| GET | `/api/athletes/{athlete_id}/reports/` · `/api/athletes/{athlete_id}/reports/{report_id}/` | coach | Browse an athlete's report days or one athlete-scoped report. |
| GET | `/api/reports/{id}/pdf/` · `/api/athletes/{athlete_id}/reports/{report_id}/pdf/` | coach | Download a private immutable snapshot PDF, bounded to 250 pages, 8 MiB, and 10 requests per coach per minute. |
| PATCH | `/api/nodes/{node_id}/` | coach | Reassign a sensor to a different rack. |
| GET | `/api/racks/unassigned/` | coach | List tablets still waiting for a rack. |
| PATCH | `/api/racks/{device_id}/` | coach | Assign a rack number to a tablet. |

### Coach — analytics
| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/analytics/session/{id}/` | coach | Session summary — total sets, total reps, per-athlete average velocity. |
| GET | `/api/analytics/athlete/{id}/` | coach | An athlete's velocity trend across their sets. |

Global athlete records, assignments, overrides, notes, analytics, reports, and
PDFs require an active staff JWT. Rack identity is a bounded private-AP workflow,
not athlete authentication. A public rack can receive generic
`rack_screen_conflict` without screen IDs; the coach-only room state supplies the
registration count needed to diagnose it. The open athlete-filtered `Program`
read is a legacy compatibility route, not the canonical whole-program assignment.

---

## Docs
- [SPEC.md](SPEC.md) — the single source of truth (phases, models, topics).
- [MESSAGE_CONTRACT.md](MESSAGE_CONTRACT.md) — exact shapes of every MQTT / API message.
- [RUNBOOK.md](RUNBOOK.md) — services, start/stop, and operational notes.
- [ATHLETE_DRIVEN_TRAINING.md](ATHLETE_DRIVEN_TRAINING.md) — athlete-owned execution, progression, wall selection, reports, and acceptance criteria.
- [ATHLETE_DRIVEN_TRAINING_ADR.md](ATHLETE_DRIVEN_TRAINING_ADR.md) — state, locking, compatibility, and migration decisions.
- [COACH_WORKOUT_PLANNING.md](COACH_WORKOUT_PLANNING.md) — reusable workouts, assignments, training days, and report delivery slices.
