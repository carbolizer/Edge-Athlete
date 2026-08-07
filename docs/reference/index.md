# Reference

Precise shapes, for looking things up — not where reasoning lives. Each page links to
the journal page that explains *why*.

**{doc}`message-contract`**
: The authority on wire formats: what sensors publish, what the server broadcasts, and
  the request and response bodies the screens are built against.

**{doc}`database`**
: A plain-English tour of every table and how they connect.

**{doc}`spec`**
: The original specification, kept verbatim while it is rewritten. Governing rules and
  constraints up top; the historical Phase 1–18 build prompts below them.

```{toctree}
:maxdepth: 1
:hidden:

message-contract
database
spec
```

---

## The REST API

Every route with the method and permission it needs, generated from the routing table
and permission decorators in the code — so it matches what is actually wired up.

**Shapes are not here.** See {doc}`message-contract`. For *why* the permissions split
this way, the route-order trap, and the two endpoints worth knowing about
specifically, see {doc}`../journal/apis`.

**15 open · 36 coach-only · 51 total**

### Open — no login required


**Athletes**

| Method | Route |
|---|---|
| `GET,POST` | `/api/athletes/` |

**Catalog**

| Method | Route |
|---|---|
| `GET` | `/api/exercises/` |

**Racks & screens**

| Method | Route |
|---|---|
| `POST` | `/api/racks/register/` |
| `GET` | `/api/racks/racknumber/` |
| `POST` | `/api/racks/<int:rack_number>/checkin/` |
| `GET` | `/api/racks/<int:rack_number>/checkins/` |

**Sensors**

| Method | Route |
|---|---|
| `GET` | `/api/nodes/` |

**Sessions & the live day**

| Method | Route |
|---|---|
| `GET` | `/api/room-state/` |
| `GET` | `/api/sessions/active/` |
| `GET` | `/api/sessions/active/athlete/<int:athlete_id>/progress/` |
| `GET` | `/api/sessions/active/status/` |

**Sets & reps**

| Method | Route |
|---|---|
| `GET,POST` | `/api/prescriptions/` |
| `POST` | `/api/sets/` |
| `POST` | `/api/sets/<int:set_id>/complete/` |

**System**

| Method | Route |
|---|---|
| `GET` | `/api/health/` |

### Coach only — requires a login


**Analytics**

| Method | Route |
|---|---|
| `GET` | `/api/analytics/session/<int:session_id>/` |
| `GET` | `/api/analytics/athlete/<int:athlete_id>/` |

**Athletes**

| Method | Route |
|---|---|
| `GET,PATCH` | `/api/athletes/<int:athlete_id>/` |
| `GET,PUT,DELETE` | `/api/athletes/<int:athlete_id>/program/` |
| `GET,PUT,DELETE` | `/api/athletes/<int:athlete_id>/program-exercises/<int:exercise_id>/override/` |

**Blocks (templates)**

| Method | Route |
|---|---|
| `GET,POST` | `/api/training-blocks/` |
| `GET,PATCH` | `/api/training-blocks/<int:block_id>/` |
| `GET,POST` | `/api/training-blocks/<int:block_id>/workouts/` |
| `PUT` | `/api/training-blocks/<int:block_id>/workout-order/` |
| `PATCH,DELETE` | `/api/training-blocks/<int:block_id>/workouts/<int:workout_id>/` |
| `PUT` | `/api/training-blocks/<int:block_id>/workouts/<int:workout_id>/exercise-order/` |
| `PATCH,DELETE` | `/api/training-blocks/<int:block_id>/workouts/<int:workout_id>/exercises/<int:exercise_id>/` |

**Catalog**

| Method | Route |
|---|---|
| `GET,POST` | `/api/block-categories/` |

**Groups**

| Method | Route |
|---|---|
| `GET,POST` | `/api/training-groups/` |
| `GET,POST,DELETE` | `/api/training-groups/<int:group_id>/athletes/` |
| `GET,POST,PATCH,DELETE` | `/api/training-groups/<int:group_id>/coaches/` |

**Other**

| Method | Route |
|---|---|
| `POST` | `/api/reference-maxes/` |

**Programs (scheduled)**

| Method | Route |
|---|---|
| `GET,POST` | `/api/training-programs/` |
| `POST` | `/api/training-programs/<int:program_id>/promote/` |
| `GET` | `/api/scheduled-sessions/` |
| `GET,PATCH` | `/api/scheduled-sessions/<int:slot_id>/` |
| `POST` | `/api/scheduled-sessions/<int:slot_id>/session/` |

**Racks & screens**

| Method | Route |
|---|---|
| `GET` | `/api/racks/unassigned/` |
| `PATCH` | `/api/racks/<str:device_id>/` |

**Reports**

| Method | Route |
|---|---|
| `GET` | `/api/reports/` |
| `GET` | `/api/reports/<int:report_id>/` |
| `GET` | `/api/reports/<int:report_id>/pdf/` |

**Sensors**

| Method | Route |
|---|---|
| `PATCH` | `/api/nodes/<str:node_id>/` |

**Sessions & the live day**

| Method | Route |
|---|---|
| `POST` | `/api/sessions/` |
| `PATCH` | `/api/sessions/<int:session_id>/` |
| `GET,POST,DELETE` | `/api/sessions/<int:session_id>/participation/` |
| `POST` | `/api/sessions/<int:session_id>/start/` |

**Spreadsheet import**

| Method | Route |
|---|---|
| `POST` | `/api/imports/preview/` |
| `POST` | `/api/imports/` |

**System**

| Method | Route |
|---|---|
| `GET` | `/api/system/status/` |
| `POST` | `/api/system/wifi-password/` |
