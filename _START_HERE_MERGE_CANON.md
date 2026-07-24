# 🧭 START HERE — Merge Canon (v2)

> **The single source of truth for merging `braydons-dev-branch` into `SprintBranch`.**
> Read this top-to-bottom before touching either branch. If something you're about to do contradicts this
> doc, stop and reconcile here first. Supersedes `_DEPRECATED_MERGE_CANON.md` (history only — do not use it
> for decisions).
>
> **Written for someone with zero context.** If you hit something this doc doesn't answer, that's a bug in
> this doc — escalate (§11) instead of guessing. Guessing is how the last attempt went sideways.

**One-line goal:** our **rack experience is untouched**, Braydon's **coach experience runs on our data**, and
the backend still reads like **one clean, documented system**.

---

## 0. Orientation — read this if you're new

### 0.1 What this product is
A **base station** (a Raspberry Pi) runs the whole gym locally — no cloud, no internet. It broadcasts its own
WiFi and serves everything itself. Athletes lift at **racks**; sensors measure how fast the bar moves; tablets
at each rack show them what to do and how they're doing.

### 0.2 Glossary (terms used everywhere below)

| Term | What it is |
|---|---|
| **Node** | The ESP32 + sensor unit on the bar. Measures velocity. Identified by `node_id`. |
| **RackScreen** | The tablet PWA standing at a rack. Identified by a browser-generated `device_id`. |
| **Rack** | The physical station. A Node and a RackScreen are **separate identities linked only by `rack_number`** — there is no FK between them, and a coach assigns each independently. |
| **Set / Rep** | A `Set` is one bout of lifting (created when it starts, summarized when it ends). `Rep` rows are written **only in bulk** by the set-complete endpoint — never one at a time, never from a live MQTT message. |
| **False set** | A set that didn't really count (bumped bar, misfire). Counted separately and **never advances the set number**. |
| **Makeup set** | A set logged retroactively for an athlete who missed the original run (`Set.is_makeup`). |
| **Velocity zone** | A min/max bar-speed band. A rep inside it reads "on target" — this drives `Rep.velocity_color` (green/yellow/red). |
| **Reference max** | An athlete's *current working* max for a movement (`AthleteReferenceMax`). **Not a lifetime PR** — it can go DOWN. Everything prescribed is a percentage of this. |
| **Athlete** | One lifter. The `Athlete` table is the **full registry of every person in the system** — the "everyone" list. |
| **TrainingGroup** | A **named subset** of athletes who train together on one program (e.g. "Varsity Football"). **Not** the full athlete list. Many groups exist at once, on different programs, and several can share one session. |
| **The rack screen** | Our athlete-facing lifting UI (`react/src/rack/*`). **Frozen** — see §2. |
| **The coach tablet** | Braydon's coach-facing UI (dashboard, reports, catalog, planning). The thing we're merging in. |

### 0.3 The two branches

| | `SprintBranch` (ours) | `braydons-dev-branch` (his) |
|---|---|---|
| Owns | Backend, DB, exercise catalog, **the rack screen**, offline/PWA layer | **The coach tablet** + all its sections |
| We keep | All of it (backend is canonical) | His **front end** and the thinking in it |

We work on **`merge-braydon`**, a scratch integration branch off `SprintBranch`. `SprintBranch` and
`braydons-dev-branch` are **not touched** until §7 P8 fast-forwards `SprintBranch`.

### 0.4 ⚠️ How we combine the branches — READ BEFORE RUNNING ANY GIT COMMAND

**Do NOT run `git merge braydons-dev-branch`. Ever.** Both branches share migrations `0001`–`0002` then fork
with **colliding numbers and different content** (ours `0003`–`0007`, his `0003`–`0013`). A real merge leaves
two migration leaves that both mutate `Set`, and Django can no longer migrate the database at all. There is
no clean recovery except starting over.

**Instead, we take his work file-by-file**, on purpose:

```bash
# Look at one of his files without changing anything
git show braydons-dev-branch:react/src/Dashboard.jsx

# Bring a specific file (or folder) onto merge-braydon when its phase says to
git checkout braydons-dev-branch -- react/src/Dashboard.jsx
```

His `django/event_handler/migrations/*` are **never** brought over. `makemigrations --merge` is **banned**.

### 0.5 Commands you'll actually type

```bash
# FIRST TIME on a fresh clone: create the .env the stack reads (it is gitignored,
# so it never arrives with the clone). .env.example ships runnable dev-safe values.
cp .env.example .env

# Start the whole stack (from the repo root, where docker-compose.yml lives)
docker compose up --build   # then open http://localhost/ (nginx publishes port 80)

# Fresh database (destructive — wipes the volume; do this to prove migrations apply clean)
docker compose down -v && docker compose up --build

# Make a migration (must run INSIDE the container, then copy it back to the host)
# NOTE: no `-it` — an automated/non-interactive shell has no TTY and `-it` errors
# with "the input device is not a TTY". Add `-it` back ONLY when you (a human) run
# these by hand in a real terminal.
docker exec edgeathlete-django python manage.py makemigrations event_handler
# NOTE: the container WORKDIR is /backend_container (NOT /app — verified 2026-07-24).
docker cp edgeathlete-django:/backend_container/event_handler/migrations/. ./django/event_handler/migrations/

# Prove there are no un-generated model changes (must be clean before any commit)
docker exec edgeathlete-django python manage.py makemigrations --check --dry-run

# Run the tests
docker exec edgeathlete-django python manage.py test event_handler
```

More detail lives in `RUNBOOK.md`. Our migration lineage currently ends at **`0007_rackcheckin.py`** — every
new migration stacks on top of that.

### 0.6 Where we are right now (2026-07-23)
The additive Phase-1 model changes are **committed on `merge-braydon`** in `django/event_handler/models.py`
(the new `Training*` tables, `is_simulated`, `is_coach_adjustment`, `Athlete.training_groups` M2M,
`Node.allowed_exercises`, `AthleteWorkoutExerciseOverride`, `MonitoringEvent`) and were independently reviewed
as clean. **No migration has been generated yet** — that's the first real task. The `Session`→`TrainingSession`
rename and `Program` retirement are deliberately still pending (§7 P6). Nothing else from Braydon's branch has
been brought over. **Your first action is §7 P0 (cold-build smoke test), then P1.**

---

## 1. The two things we cannot lose

1. **Our rack screen** — the athlete-facing lifting runtime. Frozen. It ships today and works.
2. **Braydon's coach tablet + its sections** — room dashboard, reports, workout catalog, athlete planning,
   training-day panels. We treat his front end as the target and **bend our backend to serve it**.

Everything below serves those two surviving together.

---

## 2. Hard constraints (never violated)

### 2.1 Frozen files — do not edit, reformat, or "clean up"

```
react/src/rack/RackScreen.jsx      react/src/rack/Idle.jsx
react/src/rack/CheckInList.jsx     react/src/rack/RackSetup.jsx
react/src/rack/WeightPad.jsx       react/src/rack/velocity.js
react/src/db/repBuffer.js          react/src/device.js
react/src/ (service worker + manifest.* + icons)
```

**Verify you haven't touched them** before every commit:
```bash
git diff --name-only SprintBranch -- react/src/rack react/src/db/repBuffer.js react/src/device.js
```
That command must print **nothing**. If it prints a file, your change is wrong — find another way.

### 2.2 Frozen API contracts
These endpoints keep their **exact response shape** (key names, nesting, types). Their *internals* may be
rewritten and their *coverage* may widen, but a rack tablet must not be able to tell the difference:
`/sessions/active/`, `/sessions/active/status/`, `/sessions/active/athlete/{id}/progress/`, `/sets/`,
`/sets/{id}/complete/`, `/racks/{n}/checkin/`. The exact frozen shape of the progress endpoint is written out
in §6.3 — that one is the highest-risk seam in the merge.

### 2.3 Other hard constraints
- **The role splash / device-role picker stays.** The boot screen every role lands on is ours and remains the
  entry point (it must survive the `App.jsx` reconciliation in P7).
- **Braydon's root-level `react/src/RackScreen.jsx` is dropped from the run path.** It is his own separate
  file; it does **not** replace ours, and ours does not move.
- **Carl's dashboard page stays near-untouched**, preserved as `/coach/setup`. Integration may *reach* it
  (§6.4); its internals are not rewritten.

If a resolution would change any of the above, **the resolution is wrong.**

---

## 3. Governing principles (apply in order when a case isn't spelled out)

1. **Protected set (§2) always wins.** No exceptions.
2. **Rack / athlete-facing runtime → ours.** Adopt none of his rack-side reimplementation.
3. **Coach / dashboard / reports / planning front end → his.** Bend our backend to serve it rather than
   reshaping his UI.
4. **Derived over stored.** If a coach screen needs data we can *compute* from tables we already own, build a
   **derived endpoint in `services/`** — do **not** add a table to store it. New tables are only for data that
   is genuinely *authored* and not derivable.
5. **Backend style & docs → ours.** Refactor his features to our conventions and document every new route in
   `SPEC.md` + `MESSAGE_CONTRACT.md`.
6. **Database → additive union.** Tack columns onto existing tables; where two tables collide, keep whichever
   is least work and drop the other. One table at a time.
7. **Still tied → keep the canon** (clean / documented / reusable). Prefer deleting *duplicated* effort over
   deleting *distinct* capability.

---

## 4. The `Training*` hierarchy

### 4.1 Conceptual weight (this is NOT ownership, NOT lifespan)

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

### 4.2 Actual foreign keys (what really points at what)

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

### 4.3 Master vs. copy (why the same columns appear twice)
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

### 4.4 The rack stays group-blind
A session hosts many groups. The rack reads a **flat union roster** (every athlete across every participating
group), resolves each athlete's plan **per athlete**, and renders exactly as today. All multi-group logic lives
**behind** the frozen §2.2 seam — response shapes don't change, only their coverage widens:
- `/sessions/active/` roster = union of every participating group's athletes.
- Check-in validation = "athlete is in *any* participating group of the active session."
- `/sessions/active/status/` and `/progress/` are per-athlete and group-blind already.

### 4.5 Deferred but schema-ready (NOT built in this merge)
The **calendar generator** (drag a block onto a date → auto-create/attach sessions). We keep it *possible*:
the block carries `duration_weeks` + `cadence_days_of_week`, the program carries `start_date`. That's all.
**Do not build the generator.**

---

## 5. Schema

### 5.1 Disposition summary (what happens to every model)

| Model | Ours | His | Decision |
|---|:--:|:--:|---|
| `Node` | ✅ | ✅ | **Keep** + `is_simulated` + `allowed_exercises` M2M (D9). |
| `RackScreen` | ✅ | ✅ | Keep, no change. |
| `Athlete` | ✅ | ✅ | **Keep** + `is_simulated` + `training_groups` **M2M**→TrainingGroup (D12). `notes` TextField already exists. |
| `Exercise` / `Tag` | ✅ | — | **Keep — canonical catalog** (D1). His `exercise` CharFields become `FK→Exercise`. |
| `AthleteReferenceMax` | ✅ | — | **Keep** — the basis for `% × max`. Recalc writes new rows (D10). |
| `RackCheckIn` | ✅ | — | **Keep — single source of rack presence** (D2). |
| `Session` | ✅ | ✅ | **Keep → rename to `TrainingSession` in P6**; + `is_simulated`; group link moves to `SessionParticipation`. |
| `Set` | ✅ | ✅ | **Keep ours** (FK→Exercise, `is_makeup`); + `is_simulated` + `is_coach_adjustment` (D15). His workout-link FKs **and `rack_number`** dropped (D11). |
| `Rep` | ✅ | ✅ | Keep, no change (identical on both branches). |
| `Program` (per-athlete) | ✅ | ✅ | **RETIRES in P6** — prescription moves to Block/Program `% × max`. |
| `Workout` / `WorkoutExercise` | — | ✅ | **Adopt →** become `TrainingBlockWorkout` / `TrainingBlockExercise`. |
| `WorkoutProgram` / `WorkoutProgramItem` | — | ✅ | **Adopt →** fold into `TrainingBlock`. |
| `AthleteWorkoutAssignment` / `…ProgramAssignment` | — | ✅ | **Drop** — replaced by group-level `TrainingProgram`. |
| `AthleteWorkoutExerciseOverride` | — | ✅ | **Model kept** as thin exception layer; **endpoint deferred to P5**. |
| `AthleteDayProgress` | — | ✅ | **Drop → derive** in `services/` (D3). |
| `AthleteRackParticipation` | — | ✅ | **Drop → derive** from `RackCheckIn` (D2). |
| `RackWorkoutState` | — | ✅ | **Drop → rebuild** room-state from `RackCheckIn` + derived progress (D8). |
| `DailyReport` | — | ✅ | **Adopt as-is** (additive, immutable JSON snapshot). |
| `MonitoringEvent` | — | ✅ | **Adopt** — durable outbox for the room-state channel (D5). |
| — new — | — | — | `TrainingGroup`, `TrainingBlock`(+Workout/Exercise), `TrainingProgram`(+Workout/Exercise), `SessionParticipation`. |

### 5.2 New / changed tables — attributes & descriptions

Unchanged tables (`RackScreen`, `Rep`, `Tag`, `AthleteReferenceMax`, `RackCheckIn`) keep their current shape —
read them in `models.py`.

**`TrainingGroup`** — a named subset of athletes who train together on one program.

> ⚠️ **This is not the athlete registry.** Every person in the system lives in the `Athlete` table; a
> `TrainingGroup` is a *slice* of them (e.g. "Varsity Football", "Freshman Speed") that a coach hangs a
> `TrainingProgram` on. Many groups exist simultaneously, each running a different program, and several can
> share one `TrainingSession` (§4.4). Membership is via the `Athlete.training_groups` M2M (D12) — an athlete
> can be in several groups at once — so there is no membership column on this table. `group.athletes` reads
> the reverse side.
>
> ⚠️ Don't confuse this with `TrainingProgram.training_group`, which **is** a plain FK: a *program* belongs to
> exactly one group, even though an *athlete* can be in many.

| Column | Type | Description |
|---|---|---|
| `coach` | FK→User (PROTECT) | Who owns the group. PROTECT so deleting a user never nukes training history. |
| `name` | CharField(255) | The group's name, e.g. "Varsity Football". |
| `created_at` | DateTime (auto) | — |

**`TrainingBlock`** — the reusable, timeless TEMPLATE.

| Column | Type | Description |
|---|---|---|
| `coach` | FK→User (PROTECT) | Author of the template. |
| `name` | CharField(255) | Template name. |
| `duration_weeks` | Int (null) | For the future calendar generator (§4.5). **Unused today.** |
| `cadence_days_of_week` | CharField(100) | e.g. `"Mon,Wed,Fri"`. For the future generator. **Unused today.** |
| `created_at` | DateTime (auto) | — |

**`TrainingBlockWorkout`** — one ordered workout inside a block (e.g. "Day 1: Squat").

| Column | Type | Description |
|---|---|---|
| `training_block` | FK→TrainingBlock (CASCADE) | Owner. |
| `name` | CharField(255) | Workout label. |
| `position` | PositiveInt | Order within the block. **Unique per `(block, position)`.** |

**`TrainingBlockExercise`** — one MASTER prescription row (the copy source at instantiation).

| Column | Type | Description |
|---|---|---|
| `training_block_workout` | FK→…Workout (CASCADE) | Owner. |
| `exercise` | FK→Exercise (PROTECT) | The catalog movement. |
| `position` | PositiveInt | Order. **Unique per `(workout, position)`.** |
| `sets` / `reps` | PositiveInt | Prescribed volume. |
| `target_percent` | Float | Percent of the athlete's reference max (`80.0` = 80%). **Never an absolute weight.** |
| `velocity_zone_min` / `_max` | Float (null) | The "on-target" velocity band. |

**`TrainingProgram`** — the scheduled INSTANCE for a group.

| Column | Type | Description |
|---|---|---|
| `training_group` | FK→TrainingGroup (CASCADE) | Whose calendar it's on. |
| `training_block` | FK→TrainingBlock (**PROTECT, null=True**) | Template it came from. **NULL = standalone one-off** (D6). PROTECT guards a block that live programs reference. |
| `name` | CharField(255) | — |
| `start_date` | Date | When the program begins. **Used by the §6.2 resolution chain.** |
| `end_date` | Date (null) | From the block's duration, or set directly for a one-off. **Used by the §6.2 resolution chain.** |
| `created_at` | DateTime (auto) | Tie-breaker when two programs overlap (§6.2 step 2). |

**`TrainingProgramWorkout`** — editable copy of `TrainingBlockWorkout`.

| Column | Type | Description |
|---|---|---|
| `training_program` | FK→TrainingProgram (CASCADE) | Owner. |
| `name` | CharField(255) | Workout label. |
| `position` | PositiveInt | Order. **Unique per `(program, position)`.** |

**`TrainingProgramExercise`** — editable copy of `TrainingBlockExercise`. **This is the runtime prescription
row** the rack ultimately reads through. Same columns as `TrainingBlockExercise`, but owned by
`training_program_workout`. The absolute weight is **never stored here** — it is derived per §6.1.

**`SessionParticipation`** — the join that lets many groups share one session.

| Column | Type | Description |
|---|---|---|
| `session` | FK→Session (CASCADE) | The shared timeslot. |
| `training_program` | FK→TrainingProgram (PROTECT) | Which group's program is running here. |
| `training_program_workout` | FK→…Workout (PROTECT, null) | **The workout-of-the-day for this group.** Null handling in §6.2 step 3. |
| `created_at` | DateTime (auto) | — |
| — | UniqueConstraint | `(session, training_program)` unique. |

> **`snapshot` JSONField REMOVED (D14, leanness audit).** An earlier draft carried a `snapshot` blob here "so
> past sessions stay pinned to history." It was **redundant on both sides**: what was actually *performed* is
> already durable in `Set`/`Rep`, and what was *prescribed* is frozen at session end by `DailyReport.snapshot`
> — which is immutable and covers the whole session, not one group. Keeping both meant two write paths for one
> guarantee. Mid-session there is nothing to pin, because the live program **is** the truth.

**`AthleteWorkoutExerciseOverride`** — thin per-athlete EXCEPTION (model kept; endpoint deferred to P5).

| Column | Type | Description |
|---|---|---|
| `athlete` | FK→Athlete (CASCADE) | Who the exception is for. |
| `training_program_exercise` | FK→…Exercise (CASCADE) | The prescription row being overridden. |
| `target_percent` / `sets` / `reps` | Float / PositiveInt, all nullable | Override the **percent** (never a static weight) and/or volume. Non-null wins; see §6.1 step 4. |
| — | Constraints | Unique per `(athlete, program_exercise)`; check that **at least one** of the three fields is non-null. |
| `updated_at` | DateTime (auto) | — |

**`DailyReport`** (adopt as-is) — immutable end-of-day snapshot for one completed session.

| Column | Type | Description |
|---|---|---|
| `session` | OneToOne→Session (PROTECT) | The completed session this reports on. |
| `schema_version` | PositiveInt (default 1) | Snapshot format version (check ≥ 1). |
| `generated_at` | DateTime (auto) | — |
| `snapshot` | JSONField | The full report payload. Indexed by a **GinIndex on `$.athletes[*].athlete.id`** — ⚠️ **requires PostgreSQL** (we run Postgres, so this is fine; it will break on SQLite). |

**`MonitoringEvent`** (adopt) — durable outbox: "something changed."

| Column | Type | Description |
|---|---|---|
| `event_id` | UUID (unique) | Stable id. |
| `reason` | CharField(32) | Short code for what changed. |
| `occurred_at` | DateTime (auto) | When it happened. |
| `published_at` | DateTime (null) | Set once the publisher loop delivers it. Null = still pending. |
| `publish_attempts` / `last_error` | PositiveInt / CharField(255) | Retry bookkeeping — a dropped connection leaves the row unpublished for the next attempt instead of losing the update. |
| `is_simulated` | Bool | For clean demo-data wipe. |

**Additive columns on existing tables:** `is_simulated` Bool → `Node`, `Athlete`, `Session`, `Set`,
`MonitoringEvent`; `Set.is_coach_adjustment` Bool (D15, default False); `Node.allowed_exercises` M2M→`Exercise`
(D9); `Athlete.training_groups` M2M→`TrainingGroup` (D12, `related_name='athletes'` — so `group.athletes` reads
naturally).

### 5.3 What we deliberately do NOT create a table for (§3.4)

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

### 5.4 Seed data (D1)
The migration that establishes the catalog seeds these starter movements so there is always something to build
against (names are the canonical spelling; `is_stub=False`):

`Back Squat`, `Front Squat`, `Bench Press`, `Deadlift`, `Overhead Press`, `Hang Clean`, `Power Clean`,
`Push Press`, `Barbell Row`, `Romanian Deadlift`

**No backfill of existing rows** — all current data is disposable dev/seed data.

### 5.5 Migration plan

Our lineage ends at **`0007_rackcheckin.py`**. His `0003`–`0013` are **never brought over** (they build tables
we drop or replace). We stack **new** migrations `0008+` on top of our `0007`.

**Lineage context (why this is safe):** `main` is a byte-identical prefix of our lineage (`main` = `0001–0005`,
`SprintBranch` = `0001–0007`), so when this branch eventually lands in `main` it is a **forward-only**
fast-forward — no rollback, no DB wipe, no collision. The only divergent lineage is
`braydons-dev-branch` (`0003–0013`), which we never migrate — his *frontend* is cherry-picked, his migrations
abandoned. See the model-handoff note; do not try to reconcile his migration graph.

**Target migration list (the explicit goal — generate against this, don't improvise).** Django auto-numbers and
auto-names; the numbers below are the expected sequence *assuming nothing between generates a migration*, which
holds because **P2, P3, and P5 add no models** (they're services/endpoints against existing tables). After
generating, rename the file to the readable name shown and confirm the number is still contiguous — don't
hand-edit numbers, let Django assign them and adjust the name only.

| File (target) | Phase | Type | Contents |
|---|---|---|---|
| `0008_training_hierarchy_and_columns` | **P1** | schema (auto) | **One `makemigrations` run captures everything currently in `models.py`:** create `TrainingGroup`, `TrainingBlock`(+`Workout`+`Exercise`), `TrainingProgram`(+`Workout`+`Exercise`), `SessionParticipation`, `AthleteWorkoutExerciseOverride`, `MonitoringEvent`; add columns `is_simulated` (Node/Athlete/Session/Set), `Set.is_coach_adjustment` (D15); add M2M `Node.allowed_exercises` and `Athlete.training_groups` (each makes a join table). |
| `0009_seed_exercise_catalog` | **P1** | **data (manual `RunPython`)** | Insert the §5.4 starter movements (D1). Not auto-generated — hand-write it. Make it **reversible** (reverse deletes exactly those rows). Only needs the `Exercise` table (exists since `0004`), so it's independent of `0008`. |
| `0010_daily_report` | **P4** | schema (auto) | Adopt `DailyReport` (OneToOne→`Session`, `schema_version`, `snapshot` JSONField, `generated_at`). ⚠️ Its **GinIndex on `$.athletes[*].athlete.id` is Postgres-only** — the migration will emit `jsonb_path_query_array`; do not try to apply it on SQLite. The reference-max **write** endpoint (§7.2) needs **no migration** — `AthleteReferenceMax` already exists. |
| `0011_trainingsession_rename_and_program_retire` ⚠️ | **P6** | schema (auto + hand-check) | The dangerous one. `RenameModel Session → TrainingSession` (Django rewrites every FK); `DeleteModel Program`; **`AlterField Set.session` → `on_delete=PROTECT`** — the MUST-FIX so a session delete can never wipe historical `Set`/`Rep`. Django may split this into 2–3 migrations; that's fine, keep them stacked in order. Verify the `Set.session` PROTECT change is actually present before calling P6 done — it is the single easiest thing to lose. |

**Phases that generate NO migration:** P0 (build only), P2 (realtime backbone — code), P3 (derived reads —
code), P5 (planning/CRUD/CSV/override/`% × max` re-point — all against existing tables), P7 (frontend), P8
(verify). If any of these *does* produce a migration, something drifted from this plan — stop and reconcile
here before committing it.

**`0008`–`0010` are purely additive** (no existing column changes type, no table dropped) — safe to land before
the risky P6. Only `0011` mutates/drops existing structure, which is why it's quarantined to the last phase.

*(Checked 2026-07-23: the `notification_flow/` cruft dropped in D5 defines **no DB models** — `grep -r
"models.Model" django/event_handler/notification_flow/` is empty — so P2 truly adds no migration. Noted here so
nobody re-worries about it.)*

`makemigrations --merge` is **banned**. Generate inside the container and `docker cp` back (§0.5).

### 5.6 Two "colors" — do not conflate
- **(a) Per-rep velocity-zone color** (`Rep.velocity_color`) — how fast a rep moved vs. its target band.
  **Already alive in both branches, untouched by this merge.** Nothing to build.
- **(b) Rollup health-status** (red = nobody started, green = whole roster has data, yellow = partial).
  **Not built anywhere. OUT OF SCOPE.** Do not build it, do not re-anchor it onto the new hierarchy.

They only ever shared a color palette. The per-rack `status` (idle/active/complete/false-set) is a **third**,
separate thing (live execution state) and is likewise unaffected.

---

## 6. The derivation rules (the part that must not be guessed) ⭐

Everything in §4–5 is inert until something turns a *percentage* into a *number on a bar*. This section is the
algorithm. **If you find yourself inventing a rule here, stop — it belongs in this doc first.**

### 6.1 Resolving an athlete's target weight

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

### 6.2 Resolving "what is this athlete doing today"

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

### 6.3 ⚠️ The frozen progress contract — `/sessions/active/athlete/{id}/progress/`

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

### 6.4 The room-state contract (D8 rebuild)
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

### 6.5 Coach weight adjustment (D15)

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

## 7. Endpoint reconciliation

Left = what his coach front end calls. Right = what we do.

### 7.1 Already served — his FE works as-is
`auth/login/` · `athletes/` · `nodes/` · `nodes/{id}/` · `programs/` (+`?athlete`) · `racks/register/` ·
`racks/racknumber/` · `racks/unassigned/` · `racks/{device_id}/` · `sessions/` · `sets/` ·
`analytics/session/{id}/` · `analytics/athlete/{id}/`

> ⚠️ `programs/` currently serves the **retiring** per-athlete `Program`. In P5 it is re-pointed to resolve
> `% × max` from `TrainingProgram` — **same route, same response shape, new backing.** His FE keeps calling it
> and must not notice.

### 7.2 BUILD — endpoints that don't exist yet

Every row here is called by a **surviving** coach screen, so every row is required.

| Route | Called by (his file) | Backed by | Phase |
|---|---|---|---|
| `auth/refresh/` | `coach/api.js` | SimpleJWT refresh view | P3 |
| **reference-max write** (e.g. `athletes/reference-maxes/` POST, **accepts a list of athlete ids for bulk entry**) | — *(gap: no FE calls it yet, but §6.1 needs the data)* | `AthleteReferenceMax` (add-only, newest-wins, applies forward — no new schema) | P4 |
| `room-state/` **(absorbs `wall-state/` — R3)** | `useLiveRoomState.js`, `ConnectionTest.jsx` | **derived** room-state (§6.4) | P3 |
| `reports/` · `reports/{id}/` · `reports/{id}/pdf/` **(absorbs the athlete-scoped family — R6)** | `ReportsWorkspace.jsx`, `reportBrowsing.js` | `DailyReport`, `?athlete={id}` filter | P4 |
| `workouts/` | `WorkoutCatalog.jsx`, `AthleteWorkoutPlanning.jsx`, `Dashboard.jsx` | `TrainingBlockWorkout` (+ its exercises) | P5 |
| `workout-programs/` | `WorkoutCatalog.jsx`, `AthleteWorkoutPlanning.jsx`, `Dashboard.jsx` | `TrainingBlock` (the template) | P5 |
| `workouts/imports/preview/` · `workouts/imports/` | `WorkoutCatalog.jsx` | CSV import at block **or** program level (D7) | P5 |
| `athletes/{id}/workout-assignment/` | `AthleteWorkoutPlanning.jsx` | group-level `TrainingProgram` | P5 |
| `athletes/{id}/workout-exercises/{id}/override/` | `AthleteWorkoutPlanning.jsx` | `AthleteWorkoutExerciseOverride` | P5 |

> **The reference-max write is a genuine gap in BOTH branches** (verified 2026-07-23: neither `urls.py` has any
> route that *creates* an `AthleteReferenceMax` row, yet §6.1 derives every single target from that table). It
> is the only "build" row here that no front end calls today — it exists because without it there is no way to
> enter weight *(a)* in §6.1a, and every prescribed target would resolve to `null`. It is the **prescription
> lever** and is separate from D15 (which moves the working load); the two do not compete. This is an addition
> of *ours*, so it does not affect the §7.5 coverage claim (that claim is about *his* routes).

### 7.3 FOLD — his route is a duplicate of one of ours; keep OURS, change his FE

Per §3 and the "no two routes doing the same job" rule. Each fold deletes a route we would otherwise have
built. **The FE change is small and belongs to P7.**

| His route | Folds into (ours, already exists) | Why it's redundant |
|---|---|---|
| `athletes/{id}/notes/` | **`athletes/{id}/` PATCH** | `notes` is a plain field on `Athlete`, and `AthleteSerializer` **already exposes it** (`fields = [id, name, nfc_tag_id, created_at, notes]`) on an endpoint that is **already PATCH**. A dedicated notes route would be a second way to write one column. FE: `PATCH /api/athletes/{id}/ {"notes": …}`. |
| `sessions/{id}/end/` | **`sessions/{id}/` PATCH** | Our `session_detail` already ends sessions — its docstring: *"A PATCH with no `ended_at` means 'end it now'."* ⚠️ **The P4 completion service (DailyReport + ref-max recalc, D10) hooks into THIS existing view**, not a new route. FE: `PATCH /api/sessions/{id}/`. |
| `wall-state/` | **`room-state/?details=…`** | Both are backed by the *same* `_room_state_snapshot(include_details)` function — one boolean apart. Two routes for one function is the definition of redundant. FE: `useLiveRoomState.js` passes the flag. |
| `athletes/{id}/reports/` · `…/reports/{id}/` · `…/reports/{id}/pdf/` | **`reports/?athlete={id}` · `reports/{id}/` · `reports/{id}/pdf/`** | Two parallel families returning the same `DailyReport` rows; the athlete-scoped one is just a filter. Keep the general family, filter by query param. Deletes **3 routes**. |
| `racks/{n}/sets/` · `racks/{n}/sets/{id}/complete/` | **`sets/` · `sets/{id}/complete/`** | Same write, rack-scoped path. Only his (dropped) rack screen called it. |

### 7.4 DROP — no surviving consumer

**Verify before deleting:** each of these was confirmed to be called *only* from a file that leaves the run
path. If you find another caller, escalate (§11) instead of dropping.

| Route | Sole caller | Why it dies |
|---|---|---|
| `racks/{n}/athlete/` | `RackScreen.jsx` **(his — dropped, §2.3)** | Our rack resolves its athlete through `RackCheckIn` behind the frozen seam. **Nothing on the coach side calls this.** |
| `racks/{n}/state/` (GET **and** PATCH) | `Dashboard.jsx` assign panel + his `RackScreen.jsx` | The GET existed to feed the forward-assignment panel, which **D8 deletes**. The dashboard's live room view comes from `room-state/`. |
| `racks/{n}/assignment/` | `Dashboard.jsx` assign panel | D8 — forward rack-assignment is gone. |

> **⚠️ Correction (2026-07-23 audit).** An earlier draft of this doc told P3 to *build* `racks/{n}/state/` GET
> and `racks/{n}/athlete/`, and never listed `room-state/` or `wall-state/` at all. That was backwards: it
> would have built two endpoints nobody calls while leaving the live room dashboard with **no backend**.
> `room-state/` is the real one.

### 7.5 Coverage check (audited 2026-07-23)

**Every route in `git show braydons-dev-branch:django/event_handler/urls.py` is accounted for** in §7.1
(already served), §7.2 (build), §7.3 (fold), or §7.4 (drop). If you add a screen or find a call this doc
doesn't list, that's a gap in this doc — fix it here first.

Re-run the audit any time with:
```bash
# his full backend surface
git show braydons-dev-branch:django/event_handler/urls.py | grep "path("
# every /api/ path his front end actually calls
git grep -hoE "/api/[a-zA-Z0-9/_{}$.-]+" braydons-dev-branch -- react/src | sort -u
```

**For every endpoint you build:** implement in our style, put derivation in `services/`, and document the route
in `SPEC.md` + `MESSAGE_CONTRACT.md`. A route that isn't documented isn't done.

### 7.6 Integration goals (only if in scope)
- **Carl's page → coach setup**, reached from a button on Braydon's main coach page.
- **Dashboard layout redesign is OUT OF SCOPE.** We like his theme/styling; the layout redo is a later,
  separate effort. It is the explicit "sacrifice candidate if something must die." **Note, don't act.**

---

## 8. Phased execution plan

**Stop at every gate and verify before starting the next phase. Do not run phases ahead.**
Every gate implicitly includes: **backend tests green + §2.1 frozen-file check prints nothing.**

| Phase | Scope | Exit gate |
|---|---|---|
| **P0 — Cold-build smoke test** *(first)* | Prove the checked-out tree builds and runs from a clean clone **before changing anything**: `git fetch --all` (so `braydons-dev-branch`/`main` are present for later `git show`/`checkout`); `cp .env.example .env`; `docker compose up --build`. | All containers reach healthy; `http://localhost/` loads; the **rack screen runs its full loop** (§8 definition); existing tests pass (`docker exec edgeathlete-django python manage.py test event_handler`). ⚠️ `makemigrations --check` will report the `Training*` models as **pending** — that's expected (P1 generates them), not a P0 failure. If the build itself fails, **stop and escalate** — do not start P1 on a tree that doesn't boot. |
| **P1 — Models + migration** *(after P0 green)* | Confirm the model diff already in `models.py` matches §5.2. Generate the two P1 migrations from the §5.5 target list: `0008` (auto — all the additive schema already in `models.py`) and `0009` (hand-written `RunPython` seeding the §5.4 movements). | `makemigrations --check --dry-run` clean (no pending model changes left); `docker compose down -v && up --build` applies `0001`→`0009` on a fresh DB; tests green; seed movements present in the DB. **Commit `0008`+`0009`.** |
| **P2 — Realtime backbone (D5)** | Bring his `realtime/` + `services/` + the `MonitoringEvent` publisher. Fold our rack `broadcast/publisher` into it **without changing any rack topic or payload**. Drop our `notification_flow/` ntfy/motion cruft. Webhooks untouched. | Every existing rack topic still fires identically (incl. the `enter_setup` "all racks → pairing mode" signal); `MonitoringEvent` rows get `published_at` set; tests green. |
| **P3 — Derived reads** | `services/` **`room-state/`** (§6.4, absorbing `wall-state/` via `?details=`), day-progress (D3), `auth/refresh/`. **Build no per-rack state route** — §7.4. | Endpoints return the shapes his consumers expect (§6.4); his `dashboardView.test.js` / `roomMonitor.test.js` pass; documented in SPEC + MESSAGE_CONTRACT. |
| **P4 — Reports + finalization** | Adopt `DailyReport` + `reports/` family + PDF (**one family, `?athlete=` filter** — R6). Add the completion service to **our existing `sessions/{id}/` PATCH** (R2), firing report generation + ref-max recalc (D10; estimation method still deferred). Generates migration **`0010_daily_report`** (§5.5). **No `notes` route** (R1) and **no `sessions/{id}/end/` route** (R2). | Ending a session via `PATCH /api/sessions/{id}/` generates exactly one `DailyReport`; a new `AthleteReferenceMax` row appears with `source=estimated`; `PATCH /api/athletes/{id}/ {"notes":…}` round-trips. |
| **P5 — Planning + the `% × max` swap** ⚠️ | `TrainingBlock`/`TrainingProgram` CRUD; CSV import at both levels (D7); the override endpoint; **the coach weight adjustment (D15) + its exclusion list across all reads in §6.5**; **re-point `athlete_progress` and `programs/` to §6.1/§6.2.** | **§6.3 key-diff is empty**; the §6.1 worked example reproduces exactly (225×3 @80% → 200 lb); **the §6.2 multi-group worked example reproduces exactly (5 movements, Back Squat once at 3×5 @70%, team lift first)**; an athlete with no reference max gets `null` and the rack still works; an athlete in two groups never sees a duplicated `exercise_id`; **a coach weight adjustment (D15) changes `last_weight_lbs` for an athlete's subsequent sets WITHOUT changing `next_set_number`, `completed_sets`, `false_sets`, or `status`, and the adjusted athlete does not appear as "resting" in `session_status`**; rack screen visually unchanged. |
| **P6 — Rename + retirement** ⚠️ *(highest blast radius — do last)* | `Session`→`TrainingSession` across views/serializers/tests; group link fully on `SessionParticipation`; retire `Program`; **`Set.session` → `on_delete=PROTECT`.** Generates migration **`0011_*`** (§5.5; Django may split into 2–3). | `/sessions/*` shapes unchanged; **deleting a session cannot delete `Set`/`Rep` rows (test this explicitly — verify `Set.session` is actually PROTECT in the applied migration)**; full suite green. |
| **P7 — Coach frontend + `App.jsx` seam** | `git checkout braydons-dev-branch -- <his coach files>` (§0.4); wire each to our APIs (§7); drop the panels whose backends died; hand-merge `App.jsx` so **our** role splash + rack route survive alongside **his** coach/dashboard/reports routes. | His coach pages load and function against our APIs; role splash + rack route intact; §2.1 check clean. |
| **P8 — Verify + ship** | Fresh-DB boot, full test pass, visual rack check, browser-verify every coach page. | All green → **fast-forward `SprintBranch` to `merge-braydon`.** |

**Config union (hand-merge, alongside whichever phase needs it):** `package.json` + lockfile, Dockerfiles,
`docker-compose.yml`, `nginx`, `mosquitto`, `setup.sh` — take the **superset that boots both** stacks.

**"Rack screen visually unchanged" means:** boot the stack, open a rack tablet, run the full loop —
role splash → rack setup → check-in → pick a movement → countdown → active set → finish set → rest timer →
next movement. Nothing in that flow looks or behaves differently than on `SprintBranch`.

---

## 9. Decision log

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
- **D6 — `TrainingProgram.training_block` is NULLABLE** → one-off programs are a permanent first-class path;
  promotion to a template is just pointing the FK at a new block row.
- **D7 — CSV import survives at BOTH block and program level.** Block-level = reusable template;
  program-level = immediate one-off. Only the old single fixed target shape retired.
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
- **NEW — reference-max write endpoint** (§7.2) — neither branch had one, yet §6.1 needs it; add a bulk
  (list-of-athlete-ids) POST creating `AthleteReferenceMax` rows. No new schema. The prescription lever;
  separate from D15.
- **NEW — Athlete notes → the existing `Athlete.notes` field, no new table AND no new route** (R1).

---

## 10. Explicitly deferred / out of scope

Do not build these. If you think one is needed, escalate (§11) rather than expanding scope.

- **Calendar generator** (drag block → date → auto-create sessions). Schema-ready only (§4.5).
- **`AthleteWorkoutExerciseOverride` mechanics debate.** The model is settled and the endpoint is scoped to P5
  as a thin exception path. **Do not re-open its design** — that was the previous attempt's rabbit hole.
- **Rollup health-status color (b)** (§5.6) — not built anywhere, not this merge.
- **Ref-max estimation method** (D10) — *when* it fires is decided; *how* it estimates is not.
- **Dashboard layout redesign** (§7.6) — theme kept, layout redo is separate.

---

## 11. Escalation & model handoff

**Escalate (ask a human, or switch to Opus) when:**
- This doc doesn't cover your case, or two rules seem to conflict.
- A change would touch anything in §2 (frozen files, frozen contracts, role splash).
- You're about to invent a formula, a default, or a response shape.
- `makemigrations` wants to alter or drop an existing column you didn't intend to touch.

**Sonnet runs the bulk** — conflicts by the §5/§7 tables, building models/serializers/derived endpoints, wiring
his front end, and the rebuild→migrate→test→verify loops (token-heavy and mechanical).

**Opus for the high-judgment spots** — the migration graph and **P6** (§5.5), the **`% × max` swap behind the
frozen seam** (P5 / §6.3), the **`App.jsx` seam** (P7), and anything in the escalate list above.

**Do not use Fable for this merge.**

*Rule of thumb: if the answer is in this doc, execute it. If executing requires deciding something this doc
didn't, escalate.*

---

*Living document. Record every newly resolved decision here so the canon stays the single source of truth.*
