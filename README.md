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
- **Screens:** tablets and the wall display talk to the broker **directly** over
  MQTT-over-WebSockets (9001) — no server in the middle, no Django Channels.
- **The key rule:** Django's subscriber only listens for **heartbeats**
  (`edgeathlete/node/+/pulse`). Reps are saved in **one batch** when a set
  finishes (`POST /api/sets/{id}/complete/`) — never streamed one at a time.

**Database tables** (11): `Node`, `RackScreen`, `Athlete`, `Tag`, `Exercise`,
`Program`, `Session`, `Set`, `AthleteReferenceMax`, `Rep`, `RackCheckIn`.
(`RackScreen` = the tablet at a rack; `Node` = the sensor — they share a
`rack_number` but are assigned independently.) A plain-English tour of every table
is in [DATABASE-OVERVIEW.md](DATABASE-OVERVIEW.md).

---

## Quick start

```bash
docker compose up --build          # start the whole stack
```

Then open:

| URL | What it is |
|---|---|
| `http://localhost/connection-test` | **API & architecture demo page** — click endpoints, see live data |
| `http://localhost/admin/` | Django admin — browse the seven tables (needs a superuser) |
| `http://localhost/api/...` | the REST API (below) |

Create a superuser for the admin: `docker exec -it edgeathlete-django python manage.py createsuperuser`

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
| GET | `/api/racks/racknumber/?device_id=` | open | A waiting tablet asks which rack it's been given → `{rack_number}`. |
| GET | `/api/sessions/active/` | open | The rack's one startup fetch — roster, each athlete's maxes/targets, planned exercises + velocity zones. |
| GET | `/api/sessions/active/athlete/{id}/progress/` | open | One athlete's day view — their movements + live per-set progress (derived from Program + Set). |
| GET | `/api/sessions/active/status/` | open | Room state — each athlete's live status (lifting/resting/ready) + since-when, for the check-in timers (coach-reusable). |
| POST | `/api/racks/{n}/checkin/` | open | Record an athlete checking in at a rack (newest-wins "hot list" ownership). |
| GET | `/api/racks/{n}/checkins/` | open | The rack's hot list — the athletes it currently owns. |
| POST | `/api/sets/` | open | Start a set — create the record when a lifter begins (`set_number`, `weight_lbs`, `is_makeup`, node pk). |
| POST | `/api/sets/{id}/complete/` | open | Finish a set — save all reps + totals in one transaction. **The only way reps get saved.** Returns the set plus `is_velocity_pr` / `is_weight_pr`. |

### Reads
| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/nodes/` | open | List all sensor nodes and their status. |
| GET | `/api/athletes/` | open | List all lifters. |
| GET | `/api/exercises/` | open | The movement catalog (`Exercise` rows). |
| GET | `/api/programs/?athlete={id}` | open | An athlete's training plans — targets + the speed zone used to color reps. |

### Coach — manage
| Method | Path | Access | What it does |
|---|---|---|---|
| POST · PATCH | `/api/athletes/` · `/api/athletes/{id}/` | coach | Add or edit a lifter. |
| POST | `/api/programs/` | coach | Create a training plan for a lifter. |
| POST · PATCH | `/api/sessions/` · `/api/sessions/{id}/` | coach | Start a session; a PATCH with no `ended_at` ends it now. |
| PATCH | `/api/nodes/{node_id}/` | coach | Reassign a sensor to a different rack. |
| GET | `/api/racks/unassigned/` | coach | List tablets still waiting for a rack. |
| PATCH | `/api/racks/{device_id}/` | coach | Assign a rack number to a tablet. |

### Coach — analytics
| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/analytics/session/{id}/` | coach | Session summary — total sets, total reps, per-athlete average velocity. |
| GET | `/api/analytics/athlete/{id}/` | coach | An athlete's velocity trend across their sets. |

---

## Docs
- [SPEC.md](SPEC.md) — the single source of truth (phases, models, topics).
- [MESSAGE_CONTRACT.md](MESSAGE_CONTRACT.md) — exact shapes of every MQTT / API message.
- [DATABASE-OVERVIEW.md](DATABASE-OVERVIEW.md) — plain-English tour of every table + how they relate.
- [DESIGN_NOTES.md](DESIGN_NOTES.md) — deliberate choices we may revisit.
- [RUNBOOK.md](RUNBOOK.md) — services, start/stop, and operational notes.
