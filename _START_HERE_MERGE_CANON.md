# 🧭 START HERE — Merge Canon (SprintBranch ⨝ braydons-dev-branch)

> **Read this first, before touching either branch or resolving any conflict.** This is the single
> source of truth for merging `braydons-dev-branch` into `SprintBranch` — the tie-breaker for every
> decision. If anything you're about to do contradicts this doc, stop and reconcile here first.

**Purpose.** This is the tie-breaker. When a merge conflict or a design collision comes up
between `SprintBranch` (our rack-screen + Phase 11 + catalog work) and `braydons-dev-branch`
(Braydon's coach tablet, room dashboard, workout catalog, reports, athlete-driven training),
resolve it by this document. It records **what we're keeping, what we're adopting, the order
we break ties in, and how we settle the database schema piece by piece.**

**How to use it.** Before resolving any conflict: (1) check the *Hard constraints* — those are
non-negotiable; (2) apply the *Tie-break heuristics* in order; (3) for anything touching the DB,
go to *Database reconciliation* and resolve that table's row before writing code. If a case
isn't covered, prefer the choice that keeps the canon intact — **clean, documented, reusable** —
and preserves the two features we can't lose: **our rack screen** and **Braydon's coach tablet**.

**Status:** planning. `merge-braydon` is a scratch integration branch off `SprintBranch`; the
actual `git merge` has NOT run yet. We resolve on `merge-braydon`, get it building + migrating +
green, then fast-forward `SprintBranch` to it. Neither `SprintBranch` nor `braydons-dev-branch`
is touched until then.

---

## 1. The north star (why we're keeping what we're keeping)

**What we prize from our side (`SprintBranch`):**
- A **clean, consistent backend** where everything is written to a spec and the spec is followed.
- **Reusable APIs with clean documentation** (SPEC.md + MESSAGE_CONTRACT.md as the source of truth).

**What we prize from Braydon's side:**
- His **front end** and the **deep, comprehensive thought** in each section.
- The **coach's tablet** and its sections — treat as pristine; we bend our side to make it work.

The merge succeeds when our rack experience is untouched, Braydon's coach experience runs on our
data, and the backend still reads like one clean, documented system.

## 2. Hard constraints (never violated — SprintBranch wins absolutely)

1. **The rack screen is frozen.** Nothing in the rack screen changes. This is
   `react/src/rack/*` (`RackScreen.jsx`, `Idle.jsx`, `CheckInList.jsx`, `WeightPad.jsx`,
   `velocity.js`) and the state machine + endpoints it depends on. Braydon's root-level
   `react/src/RackScreen.jsx` is **his own, separate file** — it does not replace ours and ours
   does not move.
2. **The role splash / device-role picker stays.** The boot screen every role lands on
   (device role picker) is ours and remains the entry point.
3. **Service worker + Dexie stay pristine.** The PWA offline layer and the IndexedDB rep buffer
   (`react/src/db/repBuffer.js`, the service worker, `manifest.*`, icons, `device.js`) are not
   refactored, reordered, or "cleaned up" during the merge. They are the durability boundary.
4. **Carl's dashboard commit stays nearly untouched.** The dashboard page from Carl's branch that
   we later routed to `/coach/setup` is preserved as-is. Integration may *reach* it (see §4 goal),
   but its internals are not rewritten.

If a merge resolution would change any of the above, the resolution is wrong — find another way.

## 3. What we adopt from Braydon (his side wins, adapted to our data)

1. **The coach tablet + all its sections** — his coach-facing front end is the target; we do
   "whatever we need to do to make it work with what we have" (wire it to our APIs/models).
2. **His front-end sections and the thinking in them** — room dashboard, reports workspace,
   workout catalog, athlete workout planning, training-day panels, live-room state.

## 4. Integration goals (nice-to-have, only if in scope)

- **Carl's page → coach setup, reachable from Braydon's main page.** Turn Carl's dashboard/
  `/coach/setup` page into a coach *setup* page opened by a button on Braydon's main coach page.
- **Dashboard layout is a known future redesign.** We like Braydon's dashboard **theme/styling**
  but always intended to **redesign its layout** to surface more important info. Do **not** redo
  that now (out of scope) — but the dashboard is the explicit candidate to sacrifice "if something
  has to die for the project to live." Note, don't act.

## 5. Tie-break heuristics (apply in order)

1. **Protected set (Hard constraints §2) always wins** — no exceptions.
2. **Rack / athlete-facing runtime → ours.** The rack screen, its endpoints, the state machine,
   the offline layer. Adopt none of Braydon's rack-side reimplementation.
3. **Coach / dashboard / reports / workout-planning front end → his.** Bend our backend/data to
   serve it rather than reshaping his UI.
4. **Backend style & docs → ours.** When we bring in a Braydon feature, refactor it to match our
   conventions and **document it in SPEC.md + MESSAGE_CONTRACT.md**. The canon backend stays clean
   and spec-first even when the feature originated on his branch.
5. **Database → additive union, name-collisions resolved by least churn** (see §6). Tack columns
   on; for genuinely redundant tables, keep whichever is less work to preserve and nuke the other.
6. **When still tied → keep the canon** (clean/documented/reusable) and keep both must-have
   features working. Prefer deleting *duplicated* effort over deleting *distinct* capability.

## 6. Database reconciliation (the slow, piece-by-piece part)

**Governing rule (from the goal brief):** where a new idea is *added* to an existing table, **tack
on the extra column(s)** — don't fork the table. Where two tables genuinely collide on a name/role,
**keep whichever is less work to remove-and-replace-without-breaking; nuke the other.** Every table
below gets an explicit decision here before any code is written for it. Decisions are resolved
**one table at a time** — do not batch-resolve.

### 6.1 Naming canon (`Training*`)

Every org/plan entity takes a **`Training*`** prefix. Read each by the definition here, **not** by
outside convention:

- **`TrainingGroup`** — a roster of athletes under a coach.
- **`TrainingBlock`** — the reusable **TEMPLATE / builder.** ⚠️ *Inverted from common S&C usage, on
  purpose:* here the **block is the template**, not the dated phase. Always read by this definition.
- **`TrainingProgram`** — a scheduled **INSTANCE** of a block, for a group, placed in time.
- **`TrainingSession`** — one **shared** timeslot when lifting happens.

### 6.2 The v2 training hierarchy (agreed — supersedes SPEC.md's deferred "Group→Block→Session")

**Conceptual scope — NOT ownership, NOT lifespan, just "bigger concept → smaller":**
```
TrainingBlock  →  TrainingProgram  →  TrainingGroup  →  TrainingSession
  template          instance            roster            one timeslot
```

**Entities & the real relationships (which do not follow the conceptual arrow):**
- **`TrainingGroup`** — `coach FK→User`, `name`. `Athlete.training_group` (FK, *current* group only;
  reassigning never rewrites history). Long-lived — a squad outlives many blocks.
- **`TrainingBlock` (template)** — reusable, timeless. Holds an **ordered set of workouts**
  (→ `Exercise` catalog + targets) **and a duration/cadence** ("4 weeks, Mon/Wed/Fri"). No group, no
  dates. A coach designs it once and redeploys it (tweak last year's block).
- **`TrainingProgram` (instance)** — `FK→TrainingBlock`, `FK→TrainingGroup`, `start_date`, derived
  `end_date` (from the block's duration). The object a coach places on a calendar; it generates sessions.
- **`TrainingSession` (shared timeslot)** — a date/time (+ place). **Owned by nobody; not tied to one
  group.** Many groups can be on it.
- **`SessionParticipation` (join)** — `session FK` × the participating group/program. Carries that
  group's workout-of-the-day (which program-workout is run) and a **snapshot** of the block/program, so
  past sessions stay pinned to what actually ran (non-destructive history — the canon's existing rule).
  *(Named `SessionParticipation`, not "TrainingSessionGroup," so it doesn't read as a kind of group.)*

**Sessions are shared; per-group calendars are VIEWS, not tables.**
- Placing a `TrainingProgram` **creates a `TrainingSession` only if none exists at that time; otherwise
  the group is added to the existing session** (a new `SessionParticipation` row).
- There is **no per-group calendar entity.** An athlete's or coach's "calendar" is a **filtered view /
  tags** over the one shared set of sessions — an athlete sees sessions their group is in; a coach sees
  all, or filters. Filtering is a view concern, never stored structure.

**Calendar generator = FUTURE, schema-ready, NOT built now.** The drag-a-block-onto-a-date →
auto-fill-duration → auto-create/attach-sessions flow is a first-class *later* feature. We only keep it
*possible*: the block carries duration/cadence + ordered workouts; the program carries `start_date`.
We do **not** build the generator in this merge.

**How Braydon's workout tables fold in:**
- `Workout` / `WorkoutExercise` → the ordered workout content **inside a `TrainingBlock`** (on our catalog).
- `WorkoutProgram` / `WorkoutProgramItem` → fold into `TrainingBlock` (the ordered-workout template).
- Per-athlete assignments (`AthleteWorkout*Assignment`) → replaced by **group-level** `TrainingProgram`.
- `AthleteWorkoutExerciseOverride` → **KEPT as a coach-set per-athlete EXCEPTION override** (for outliers
  where a % doesn't fit). Most individualization is automatic (% × each athlete's max), so this is a thin
  exception layer, built with the coach planning screen — not a core path.

**Prescription model (RESOLVED).** The plan prescribes **% of max + velocity zones** — never an absolute
weight. It is **snapshot-copied `TrainingBlock` → `TrainingProgram` at instantiation**: the block owns the
*master* prescription; the program owns an *editable copy*. Editing the block changes future instances;
editing a program changes only that instance (and history stays stable). **Absolute target is always
derived:** `athlete target = target_percent × their current AthleteReferenceMax`. The old per-athlete
`Program` table **retires** — its job moves to Block/Program % + this derivation.

**Rack runtime under shared multi-group sessions (RESOLVED — keeps the rack frozen).** A `TrainingSession`
is a shared timeslot hosting many groups via `SessionParticipation`. The rack stays **group-blind**: it
reads a **flat union roster** (all athletes across all participating groups) so any athlete can sign in at
any shared rack, resolves each athlete's plan per-athlete, and renders timers/targets exactly as today.
All multi-group logic lives **behind** the frozen `/sessions/active/*` seam:
- `/sessions/active/` roster = **union** of every participating group's athletes (was one `Session.athletes`).
- check-in validation = "athlete is in *any* participating group of the active session."
- `/sessions/active/status/` (rest / time-remaining) and `/progress/` are per-athlete and group-blind —
  **shape unchanged**, just wider coverage; `targets[exercise_id]` now resolved as `% × max` (the seam
  already reserved in MESSAGE_CONTRACT §3).
- `session_exercises` in the one-shot becomes a union (for velocity-zone lookup) or defers to per-athlete
  `/progress/`.

### 6.2a Relational / ownership model (EER)

Ownership (**identifying**, `CASCADE` composition) vs. **reference** (non-identifying, `PROTECT`/`SET_NULL`).
This deliberately does NOT follow the conceptual arrow in §6.2. Full picture in the rendered EER diagram.

**Roots (owned by nobody):** `User(Coach)`, `Athlete`, `Exercise`, `Tag`, `TrainingSession`, `Node`, `RackScreen`.

**Owns (identifying / CASCADE):**
- `User` → `TrainingGroup`, `TrainingBlock` *(on_delete `PROTECT` — never nuke history on account delete)*
- `TrainingBlock` → `TrainingBlockWorkout` → `TrainingBlockExercise` *(master prescription: `exercise`, sets, reps, `target_percent`, velocity zones)*
- `TrainingGroup` → `TrainingProgram`
- `TrainingProgram` → `TrainingProgramWorkout` → `TrainingProgramExercise` *(editable copy of the block master)* + `AthleteOverride` *(outlier exceptions)*
- `TrainingSession` → `SessionParticipation`
- `Athlete` → `AthleteReferenceMax`, `Set`, `RackCheckIn`
- `Set` → `Rep`

**References (non-identifying):**
- `TrainingProgram` →(`PROTECT`) `TrainingBlock` *(the template it instantiated)*
- every `*Exercise` →(`PROTECT`) `Exercise`; `Exercise` ↔ `Tag` (M2M)
- `Athlete` →(**`SET_NULL`**) `TrainingGroup` *(current group only — preserves history)*
- `SessionParticipation` →(assoc.) `TrainingProgram` + `TrainingProgramWorkout` *(the day's workout)* + block/program snapshot
- `Set` →(`PROTECT`) `TrainingSession`, →(`PROTECT`) `Exercise`, →(`SET_NULL`) `Node`
- `RackCheckIn` →(`CASCADE`) `TrainingSession`

Two non-obvious calls: `Athlete → TrainingGroup` is **`SET_NULL`, not ownership** (athlete outlives group
membership; history survives reassignment), and `TrainingSession` is a **root** — the group link lives on
`SessionParticipation`, which is what makes shared multi-group sessions work.

### 6.3 Model inventory (side by side)

*Dispositions are resolved in §6.4; the workout family reorganizes into the `Training*` hierarchy above (§6.2).*

| Model | Ours (`SprintBranch`) | Braydon | Disposition (RESOLVED — see §6.4 / §6.2) |
|---|---|---|---|
| `Node` | ✅ | ✅ (+`is_simulated`) | **Keep + add `is_simulated`** (D4). |
| `RackScreen` | ✅ | ✅ (identical) | Keep. No change. |
| `Athlete` | ✅ | ✅ (+`is_simulated`) | **Keep + `is_simulated`** (D4); add `training_group` FK (`SET_NULL`). |
| `Session` | ✅ | ✅ (+`is_simulated`) | **Keep as `TrainingSession`** (frozen `/sessions/` API); + `is_simulated`; group link moves to `SessionParticipation` (§6.2). |
| `Rep` | ✅ | ✅ (identical) | Keep. No change. |
| `Program` (per-athlete) | `exercise`=FK→Exercise | `exercise`=CharField | **RETIRES** — prescription moves to `TrainingBlock/Program` (% × max, §6.2). |
| `Set` | FK→Exercise; +`is_makeup` | +`rack_number`, workout-link FKs | **Keep ours** (FK→Exercise + `is_makeup`); + `is_simulated`; his workout-link FKs dropped (those tables go). |
| `Tag` | ✅ | — | Keep. |
| `Exercise` | ✅ (catalog) | — | **Keep — canonical** (D1). His CharFields become `FK→Exercise`; seed starters in the migration. |
| `AthleteReferenceMax` | ✅ | — | Keep — now the basis for `% × max` target resolution. |
| `RackCheckIn` | ✅ | — | **Keep — single source** for rack presence (D2). |
| `Workout` / `WorkoutExercise` | — | ✅ (`exercise`=CharField) | **Adopt → become `TrainingBlockWorkout/Exercise`** (block-owned, on our catalog); + a copied `TrainingProgram*` set (§6.2). |
| `WorkoutProgram` / `WorkoutProgramItem` | — | ✅ | **Adopt → become `TrainingBlock`** (the template). |
| `AthleteWorkoutAssignment` / `…ProgramAssignment` | — | ✅ | **Drop** — replaced by group-level `TrainingProgram`. |
| `AthleteWorkoutExerciseOverride` | — | ✅ | **Keep** as coach per-athlete *exception* override (§6.2, built w/ coach planning). |
| `AthleteDayProgress` | — | ✅ | **Drop** — derived (D3), `services/` endpoint. |
| `DailyReport` | — | ✅ | Adopt (additive). |
| `AthleteRackParticipation` | — | ✅ | **Drop** — derive from `RackCheckIn` (D2). |
| `RackWorkoutState` | — | ✅ | **Drop (likely)** — derivable; revisit only if a coach action needs stored rack state. |
| `MonitoringEvent` | — | ✅ (+outbox) | **Adopt** — backbone of his room-state channel (D5). |
| — new — | — | — | `TrainingGroup`, `TrainingBlock`(+workout/exercise), `TrainingProgram`(+copy), `SessionParticipation` (§6.2). |

### 6.4 Database decisions — RESOLVED

- **D1 — Exercise identity → KEEP OUR CATALOG.** `Exercise`(+`Tag`) stays; his `exercise` CharFields
  become `FK→Exercise`. **No backfill** (all data is disposable dev/seed) — instead **seed common
  starter movements as data *inside* the migration** (bench press, back squat, hang clean, …) so there's
  always catalog data to build against.
- **D2 — Rack presence → KEEP `RackCheckIn`, DROP `AthleteRackParticipation`.** Everything his table
  held (current rack, first/last seen) is derivable from our append-only log. Re-point his
  `services/training_days.py` at our `RackCheckIn`/API with small API tweaks. His `Set.rack_number` is a
  cheap additive column — keep or drop with the workout-link cleanup, not load-bearing.
- **D3 — Day progress → DERIVED (ours), DROP `AthleteDayProgress`.** Feed his coach screen a
  **purpose-shaped derived endpoint** (its shape differs from the rack's progress endpoint). Put all
  derivation logic in a **`services/` module** — adopt Braydon's clean `services/` convention as the one
  organized home for derived endpoints (keeps it consistent for future backend devs).
- **D4 — `is_simulated` → ADOPT (union).** Tack it onto Node/Athlete/Session/Set/Program/MonitoringEvent;
  update our simulators to stamp it so `clear_simulation_data` wipes demo data cleanly.
- **D5 — MQTT → KEEP HIS `realtime/` + monitoring; FOLD IN OUR rack `broadcast/publisher`.** His
  hardened heartbeat ingest + outbox→retained-invalidation→refetch backbone stays (his two dashboards
  depend on it); **webhooks untouched.** Fold our fire-and-forget rack `broadcast/publisher` into his
  style **without breaking any of our shapes/routes** — the `enter_setup` "all racks → pairing mode"
  signal and every existing rack topic stay exactly as-is. **Drop** our inherited `notification_flow/`
  ntfy/motion cruft (leftover from the fork parent), and his derivable tables (`AthleteDayProgress`,
  `AthleteRackParticipation`; revisit `RackWorkoutState`).

### 6.5 Migration graph (updated for the resolved decisions)

Both branches share `0001`–`0002`, then fork with **colliding numbers but different content** (ours
`0003`–`0007`, his `0003`–`0013`). A plain merge silently keeps both lineages → two leaves depending on
`0002`, both mutating `Set` → Django can't migrate it.

**Plan (updated):** keep **our** lineage as the base and **do NOT bring his `0003`–`0013` over at all** —
most of them build tables we're dropping (stored-derived) or replacing (his workout catalog → the
`Training*` hierarchy). Instead, stack **new** migrations on top of our `0007` that: (a) seed the
`Exercise` starter movements (D1); (b) add `is_simulated` columns (D4); (c) create the `Training*`
tables (§6.2) and the kept content tables adapted to our catalog; (d) add `MonitoringEvent` (D5). This
**sidesteps the two-leaves conflict entirely** — his migration lineage is never merged. A blind
`makemigrations --merge` remains banned. Reminder: migrations are generated inside the django container
and must be `docker cp`'d back to the host.

## 7. Code disposition by domain (default winner; conflicts still reviewed by hand)

| Domain | Files (indicative) | Default winner | Notes |
|---|---|---|---|
| Rack screen + state machine | `react/src/rack/*` | **Ours** (frozen) | §2.1. His root `RackScreen.jsx` is dropped from the run path. |
| Offline layer / PWA | service worker, `db/repBuffer.js`, `manifest.*`, `device.js` | **Ours** (frozen) | §2.3. |
| Role splash | the role picker in `App.jsx` | **Ours** | §2.2 — must survive the `App.jsx` reconciliation. |
| Coach setup (Carl's) | the `/coach/setup` page | **Ours, near-untouched** | §2.4; §4 goal = reach it from Braydon's main page. |
| Coach tablet / dashboard / reports / workout planning | `Dashboard.jsx`, `ReportsWorkspace.jsx`, `WorkoutCatalog.jsx`, `AthleteWorkoutPlanning.jsx`, `TrainingDayPanel.jsx`, `StatisticsView.jsx`, `Timeline.jsx`, `roomMonitor.js`, `useLiveRoomState.js`, `rackState.js`, … | **His** | Wire to our APIs (heuristic §5.3). Dashboard layout redesign is out of scope (§4). |
| `App.jsx` (router shell) | `react/src/App.jsx` | **Hand-merge** | The integration seam: our role-splash + rack route to **our** `rack/RackScreen`, mounting **his** coach/dashboard/reports routes. Highest-touch frontend file. |
| Backend endpoints | `views.py`, `urls.py`, `serializers.py`, `tests.py` | **Hand-merge → our style** | Keep both feature sets; refactor his into our conventions; document in SPEC/MESSAGE_CONTRACT (§5.4). |
| Models / migrations | `models.py`, `migrations/*` | **Per §6** | Table-by-table; migration graph rebuilt. |
| MQTT / ingest pipeline | ours `notification_flow/*` vs his `realtime/*` + `services/*` | **His (per D5)** | Keep his `realtime/` + monitoring + `services/`; fold our rack `broadcast/publisher` into it without changing our rack topics/routes; drop our `notification_flow/` ntfy/motion cruft. |
| Config / deps | `package.json`, `package-lock.json`, `Dockerfile`s, `docker-compose.yml`, `nginx`, `mosquitto`, `setup.sh` | **Hand-merge (union)** | His stack adds services; take the superset that boots both. |

## 8. Process (how we actually execute, once decisions are made)

1. Resolve the **DB decisions D1–D5** in this doc first (each with a side-by-side), one at a time.
2. On `merge-braydon`, run the merge and resolve conflicts **by domain in §7 order** (frozen set →
   backend → DB/migrations → coach frontend → App.jsx seam → config).
3. Rebuild the migration graph deliberately (§6.3); `makemigrations --check` must be clean.
4. Verify: `docker compose up --build`, migrations apply on a fresh DB, backend tests green, the
   **rack screen unchanged** (visual), and Braydon's coach pages load against our APIs.
5. Only then fast-forward `SprintBranch` to `merge-braydon`.

---

*Living document. Every resolved decision (D1–D5, each table) gets its outcome + rationale recorded
here so the canon stays the single source of truth for the merge.*
