> # ⛔ DEPRECATED — DO NOT USE FOR DECISIONS
> This document has been **superseded by `_START_HERE_MERGE_CANON.md`** (the clean v2 canon, 2026-07-22).
> It is kept only for historical context / to show how each decision was reached. Every resolved
> decision (D1–D10), the hard constraints, the schema, and the endpoint plan were carried forward into
> the new canon — read that one instead. Nothing here is authoritative anymore.

---

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
- **`TrainingProgram`** — a scheduled **INSTANCE** for a group, placed in time. Usually instantiated
  from a `TrainingBlock` (template), but the block link is **nullable** — a program can also stand alone
  as a custom one-off with its own prescription and no template behind it (see D6).
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
- **`TrainingProgram` (instance)** — **nullable** `FK→TrainingBlock` (D6), `FK→TrainingGroup`, `start_date`,
  derived `end_date` (from the block's duration, or program-set for a one-off). The object a coach places on
  a calendar; it generates sessions. **Two first-class creation paths, both permanent:** (a) *instantiated
  from a block* — the FK points at the template and the prescription is snapshot-copied down; (b) *standalone
  one-off* — the FK is `NULL` and the program carries its own prescription directly, with no template ever
  created. Same table, same downstream shape either way. **Promotion is trivial** (D6): to turn a one-off into
  a reusable template, add a `TrainingBlock` row and set this existing FK to point at it — no data migration,
  no rewrite. This is why the FK must be nullable rather than required.
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
weight. When a program is instantiated from a block it is **snapshot-copied `TrainingBlock` →
`TrainingProgram`**: the block owns the *master* prescription; the program owns an *editable copy*. Editing
the block changes future instances; editing a program changes only that instance (and history stays stable).
For a **standalone one-off program** (nullable block FK, D6) there is nothing to copy — the coach authors the
program's prescription rows directly and the program simply *is* the master. Either way the program row is the
runtime prescription. **Absolute target is always derived:** `athlete target = target_percent × their current
AthleteReferenceMax`. The old per-athlete `Program` table **retires** — its job moves to Block/Program % + this
derivation.

**CSV import → both levels (RESOLVED, D7).** Coaches still on spreadsheets get two import entry points, both
first-class: **import at the `TrainingBlock` level** builds a reusable template (+ its ordered
workouts/exercises) for later instantiation; **import at the `TrainingProgram` level** builds immediate one-off
program content (nullable block FK) with no template behind it. The old SPEC.md Phase 5 CSV pipeline (which
created a group-owned dated block in one chain) is **not** retired as a capability — only its single fixed
target shape is; the import logic re-points at whichever `Training*` level the coach chose.

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
- `TrainingProgram` →(`PROTECT`, **`null=True`**) `TrainingBlock` *(the template it instantiated; NULL for a
  standalone one-off — D6. `PROTECT` still guards against deleting a block that live programs reference)*
- every `*Exercise` →(`PROTECT`) `Exercise`; `Exercise` ↔ `Tag` (M2M)
- `Athlete` →(**`SET_NULL`**) `TrainingGroup` *(current group only — preserves history)*
- `SessionParticipation` →(assoc.) `TrainingProgram` + `TrainingProgramWorkout` *(the day's workout)* + block/program snapshot
- `Set` →(`PROTECT`) `TrainingSession`, →(`PROTECT`) `Exercise`, →(`SET_NULL`) `Node`
- `RackCheckIn` →(`CASCADE`) `TrainingSession`

Two non-obvious calls: `Athlete → TrainingGroup` is **`SET_NULL`, not ownership** (athlete outlives group
membership; history survives reassignment), and `TrainingSession` is a **root** — the group link lives on
`SessionParticipation`, which is what makes shared multi-group sessions work.

**⚠️ MUST-FIX carried by the Session→TrainingSession rename phase (not optional, do not lose this):**
today's `Set.session` FK is still `on_delete=CASCADE` (the original, pre-merge behavior) — it has NOT yet been
changed to the `PROTECT` this table specifies. That's correct for right now (Phase 1 deliberately deferred the
`Session`→`TrainingSession` rename and left `Set` untouched), but it is **not optional to eventually fix**: a
`TrainingSession` delete must never be able to silently wipe historical `Set`/`Rep` rows. Whoever executes the
rename phase MUST change `Set.session` to `on_delete=models.PROTECT` as part of that same migration — verified
by a second reviewer (2026-07-22) specifically because this is the kind of cross-phase detail that's easy to
lose. Do not consider the rename phase done until this is checked.

### 6.3 Model inventory (side by side)

*Dispositions are resolved in §6.4; the workout family reorganizes into the `Training*` hierarchy above (§6.2).*

| Model | Ours (`SprintBranch`) | Braydon | Disposition (RESOLVED — see §6.4 / §6.2) |
|---|---|---|---|
| `Node` | ✅ | ✅ (+`is_simulated`) | **Keep + add `is_simulated`** (D4); + `allowed_exercises` M2M→`Exercise` (D9). |
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
| `AthleteDayProgress` | — | ✅ | **Drop** — derived (D3), `services/` endpoint. Also supplies the `current_workout_exercise` (velocity-zone lookup) that room-state read from it — that now comes from the same derived progress service (D8). |
| `DailyReport` | — | ✅ | Adopt (additive). |
| `AthleteRackParticipation` | — | ✅ | **Drop** — derive from `RackCheckIn` (D2). |
| `RackWorkoutState` | — | ✅ | **DROP — rebuild room-state against `RackCheckIn` + derived progress (D8).** It stored a coach's forward rack-assignment (rack → pre-selected athlete + pre-assigned workout); that concept dies with the group-blind athlete-centric rack (D2, §6.2). `wall_state`/`room_state` rebuild on who's checked in + per-request derivation; the `racks/{n}/state` PATCH + `racks/{n}/assignment` "assign a workout to a rack" panel are dropped. |
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
  `AthleteRackParticipation`, and `RackWorkoutState` — the last now fully resolved as a drop-and-rebuild, D8).

- **D6 — `TrainingProgram.training_block` is NULLABLE → one-off programs are a permanent first-class path.**
  A coach can create a standalone `TrainingProgram` (its own prescription rows, no template) with the block FK
  `NULL` — never having created a `TrainingBlock`. This is **not** a migration shim; it is a supported path
  forever (handles coaches who just want a quick custom program). **Promotion is trivial:** to turn a one-off
  into a reusable template, add a `TrainingBlock` row and point this existing FK at it — no data migration, no
  content rewrite, no new table. The FK is therefore `null=True` (with `on_delete=PROTECT`, §6.2a). *This
  corrects an earlier pass that assumed one-off/custom programs died with the old group-owned block shape; only
  old-Block's specific shape retired, not the standalone-program capability.*

- **D7 — CSV import survives at BOTH `TrainingBlock` and `TrainingProgram` level.** Importing at the block level
  creates a reusable template (+ ordered workouts/exercises) for later instantiation; importing at the program
  level creates immediate one-off program content (nullable block FK, D6) with no template behind it. Both are
  real, permanent entry points aimed at coaches running planning in spreadsheets. The old SPEC.md Phase 5 CSV
  *pipeline* (Group→Block chain, single fixed shape) is retired **only in its fixed target**; the parsing/stub
  logic re-points at whichever `Training*` level the coach picks. *This corrects the earlier pass that treated
  CSV import as retired.*

- **D8 — `RackWorkoutState` → DROP; rebuild `_room_state_snapshot`/`wall_state`/`room_state` against
  `RackCheckIn` + a derived progress function; drop forward rack-assignment.** *Verified in
  `git show braydons-dev-branch:django/event_handler/views.py`:* `_room_state_snapshot` (the SOLE backing for
  both `wall_state` and `room_state`, i.e. the entire data source for his `Dashboard.jsx` live room view) is
  built directly on `RackWorkoutState.objects.filter(active_session=…, selected_athlete__isnull=False |
  active_program__isnull=False)` (which rack holds which coach-*pre-selected* athlete + *pre-assigned* workout)
  plus `AthleteDayProgress` (for `current_workout_exercise` → velocity zones) and a legacy `Program` fallback.
  `Dashboard.jsx` also calls `GET/PATCH /api/racks/{n}/state/` and `/api/racks/{n}/assignment/` for a coach's
  manual "assign a workout to this rack" panel.
  **This is NOT a safe as-is keep, and NOT a same-shape rename.** His model is **rack-centric** (a rack holds a
  coach-pre-selected athlete + pre-assigned workout). The canon's rack is **athlete-centric and group-blind**
  (§2.1, §6.2, D2): an athlete carries their plan via group membership, self-selects any rack via `RackCheckIn`,
  and their current exercise/zone is derived live per request — the exact pattern already shipping in
  SprintBranch's `athlete_progress` view. These are different shapes.
  **Resolution:** DROP `RackWorkoutState`. Rebuild the room-state snapshot from **`RackCheckIn`** ("who is at
  this rack right now," newest-wins per athlete — our existing table) **+ a per-athlete progress-derivation
  function analogous to `athlete_progress`** ("what are they doing / what's their velocity zone"), housed in the
  `services/` module (D3). The **forward rack-assignment concept is dropped entirely** — `racks/{n}/state` PATCH,
  `racks/{n}/assignment`, and the "assign a workout to a rack" coach panel — because athletes now carry their own
  plan, so a coach never pre-assigns a rack a workout; they only need to see who's checked in and what's derived
  for them. This is the choice consistent with the rest of the canon (group-blind rack, no forward assignment);
  the alternative (repurpose assignment into the group-blind model) buys nothing the derived view doesn't already
  give. **Frontend consequence (note, don't over-build):** `Dashboard.jsx`'s manual assign panel loses its
  backend; per §3/§7 his coach front end bends to our data, so that panel is dropped/simplified when the room view
  is rewired — not a Hard-constraint (§2) risk (the frozen rack screen is untouched; this is coach-side only).
  The per-rack live **`status`** (idle/active/complete/false set) and **`status_color`** (velocity zone) that the
  old snapshot returned are both **still derivable** from the active session's `Set`/`Rep` rows exactly as
  before — see §6.6 for the other red/yellow/health concept this must not be confused with.

- **D9 — Rack hardware-capability guard: `Node.allowed_exercises` (M2M→`Exercise`, blank=True, default
  empty=unrestricted); filtered into `athlete_progress`, NEVER a `set_create` rejection.** A rack's allowed
  exercises are a **static fact about its equipment** ("this station is a power rack, not a high-jump pit"),
  set by a coach once and rarely touched — not a per-session assignment, and explicitly **not** a revival of
  `RackWorkoutState`/D8 (that was scheduling *who runs what plan here today*; this is *what this hardware can
  physically do, full stop*). Default empty = unrestricted, so this adds zero friction to every normal rack —
  only a coach who cares about a specific station ever populates it.
  **Why the guard can't live at `set_create` (verified against the actual frozen code):** `RackScreen.jsx`'s
  `beginActiveSet()` flips to the "active" lifting screen *before* `set_create` resolves, and swallows its
  error silently (`.catch(() => {})`); `finishSet()` then no-ops whenever `setId` never got set. A rejection
  there stack an athlete on a dead lifting screen with no way to end or flag the set — silently broken, not
  just ungraceful. Fixing that requires new error-handling UI inside `RackScreen.jsx`, which §2.1 forbids.
  **Resolution — filter in `athlete_progress`, not reject in `set_create`:** derive the athlete's current rack
  from `RackCheckIn` (as everywhere else, D2) and drop any movement not in that rack's `allowed_exercises` (if
  it has one) out of the day's movement list *before* the athlete ever sees it as an option. Nothing to reject,
  no new frontend, no new endpoint, no frozen-file touch. **Fail-open:** if the athlete's current rack can't be
  resolved yet (e.g. the check-in write hasn't landed before the progress fetch), treat it as unrestricted —
  never fail-closed and block a legitimate lift over a timing gap.
  **Design confirmation (from the human, resolves the one open edge case):** an athlete is only ever physically
  at one rack at a time, and **their program follows them wherever they check in — they never need to view
  their training program except while active at a rack.** There is no other screen anywhere that renders an
  athlete's plan outside this rack-scoped context, so filtering *only* in `athlete_progress` isn't a partial
  fix — it's the complete one; there's no second surface this guard would need to also cover. The superset
  case flagged during vetting (an allowed-only-partway rack silently dropping one exercise of a pair) is
  accepted as a natural consequence of physical equipment layout, not a software gap to design around — a
  coach programming a superset picks racks whose equipment actually supports it.

- **D10 — Reference max recalculates on SESSION COMPLETION, feeds forward only (no new schema).** The
  `% × max` prescription is never against a hand-entered, static number — `AthleteReferenceMax` is meant to
  stay current automatically. When a session ends, recent performance data should produce a fresh
  `AthleteReferenceMax` row (`source=estimated`) rather than requiring manual re-entry, so future sessions'
  targets track the athlete's real current capability (up or down) instead of a stale figure. This is the
  same moment Braydon's end-of-day finalization fires (`DailyReport` generation, adopted additively per
  §6.3) — the natural home for this is alongside that same session-completion service, not a separate
  trigger. **Feeds forward only:** it writes a new row for *future* reads; it never recomputes or touches
  the targets an athlete already trained against during the session that produced it (append-only history,
  same rule as everywhere else in this table). **No new schema required** — `AthleteReferenceMax` already
  is add-only/newest-row-wins by design (see its docstring in `models.py`); this decision is about *when*
  something writes a new row, not the table shape. **NOT decided here (deliberately deferred):** the actual
  estimation method — how many recent data points to use, outlier handling. This is the same open item
  already flagged in `SPEC.md`'s deferred "Coach publish/finalization gate + outlier-robust reference
  recalc" note — to be designed when the session-completion service itself gets built (alongside adopting
  `DailyReport`), not now.

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

### 6.6 Two different "colors" — do not conflate (velocity zone vs. rollup health)

There are **two independent red/yellow/green concepts** that get talked about in this project. A future reader
must not merge them:

- **(a) Per-rep velocity-zone color** — `Rep.velocity_color` (`green`/`yellow`/`red`, or `neutral`), a live
  measure of whether a rep's velocity landed in the athlete's target zone for that lift. It surfaces per rack/
  per set (e.g. `_room_state_snapshot`'s per-rack `status_color`, the rack screen's live coloring). **Already
  alive in BOTH branches, untouched by this whole merge** — nothing to build, nothing to resolve, stays exactly
  as-is. This is the "colors displayed dynamically based on how you did relative to a target range" feature —
  it was never at risk and was never called retired.
- **(b) Rollup health-status** — the SPEC.md Phase 5/7 red/yellow/green **completion/progress** status
  (red = nobody's started, green = whole roster has data, yellow = partial), rolled up Session→Block→Group. It
  has **nothing to do with velocity** — it measures how far through the planned work a session/program/group is.
  **It is NOT built in either branch today** (a `SprintBranch` SPEC.md Phase 7 idea, never implemented — not
  something Braydon built either). **OUT OF SCOPE for this merge** — do not build it, do not re-anchor it onto
  the new `Training*` hierarchy as part of this work. If it's wanted later, that's a fresh SPEC.md phase, decided
  and scoped on its own, not smuggled in as a merge side-effect.

Rule of thumb: **(a) is about *how fast a rep moved*, is real, and ships today; (b) is about *how much of the
plan is done*, isn't built anywhere, and isn't part of this merge.** They only ever shared a palette. The
per-rack `status` field (idle/active/complete/false set) is a third, separate thing — live execution state of
the newest set on a rack — and is likewise unaffected.

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

1. Resolve the **DB decisions D1–D10** in this doc first (each with a side-by-side), one at a time.
2. On `merge-braydon`, run the merge and resolve conflicts **by domain in §7 order** (frozen set →
   backend → DB/migrations → coach frontend → App.jsx seam → config).
3. Rebuild the migration graph deliberately (§6.3); `makemigrations --check` must be clean.
4. Verify: `docker compose up --build`, migrations apply on a fresh DB, backend tests green, the
   **rack screen unchanged** (visual), and Braydon's coach pages load against our APIs.
5. Only then fast-forward `SprintBranch` to `merge-braydon`.

## 9. Model handoff (which model runs which part)

The expensive thinking is already done and frozen in this doc — so execution is mostly **well-specified
work that follows the canon**, not open-ended design. That means the merge should run on **Sonnet by
default**, with **Opus reserved for the few high-judgment or high-blast-radius spots.** The goal is to
finish without burning the budget, while keeping quality high because the canon is the guardrail.

**Do NOT use Fable for this merge.** It is not a validated fit for careful backend/migration work, and a
one-directional merge with real conflict risk is the wrong place to spend scarce budget experimenting.

**Default driver → Sonnet.** Use it for the bulk of the work:
- Running the merge and resolving the **straightforward** conflicts by the §7 disposition table.
- Building the `Training*` models, serializers, and the derived `services/` endpoints (§6.2, D3).
- Wiring Braydon's coach front end to our APIs (§3, §7).
- The **rebuild → migrate → test → browser-verify loops** (§8.4). These are token-heavy and mechanical —
  paying Opus rates for them is waste.
- Config union (`package.json`, Dockerfiles, `docker-compose.yml`, nginx, mosquitto — §7).

**Escalate to Opus** — for these, switch models (or have Opus review Sonnet's diff before it lands):
- **The migration graph rebuild (§6.5).** The two-leaves collision and the deliberately-stacked new
  migrations on our `0007` are the single most dangerous step. Opus plans/verifies it.
- **The `% × max` target resolution behind the frozen `/sessions/active/*` seam (§6.2).** Correctness here
  is load-bearing for the rack — verify with Opus that the seam shape is unchanged.
- **The `App.jsx` integration seam (§7).** Highest-touch frontend file; our splash + rack route must
  survive alongside his coach/dashboard routes.
- **Any conflict the canon does NOT cover, or where two rules collide.** If the spec is silent or two
  heuristics disagree, that's a judgment call — escalate rather than guess.
- **Any Hard-constraint (§2) risk.** If a resolution looks like it might touch the frozen rack, PWA/Dexie,
  or role splash, stop and bring in Opus.

**Rule of thumb:** if the answer is *in this doc*, Sonnet executes it. If the answer requires *deciding
something this doc didn't*, escalate to Opus. When stuck, in doubt, or about to touch a frozen file —
escalate. Always gate a chunk on **backend tests green + rack screen visually unchanged** before
committing, whichever model did the work.

---

*Living document. Every resolved decision (D1–D10, each table) gets its outcome + rationale recorded
here so the canon stays the single source of truth for the merge.*

---

## Appendix — Phase 1 retrospective & handoff to a fresh session (2026-07-22)

**Read this before doing anything else if you're picking this up new.** The human felt this session's Phase-1
implementation drifted from a concrete plan into something more convoluted, and asked for an honest recap plus
an explicit instruction to CHECK whether all of it was actually necessary — not to assume the below is all
correct just because it got written down. Treat this section skeptically.

### What actually got built (in the working tree, nothing committed)

Purely additive changes to `django/event_handler/models.py` on `merge-braydon`:
- New tables: `TrainingGroup`, `TrainingBlock`(+`Workout`+`Exercise`), `TrainingProgram`(+`Workout`+`Exercise`),
  `SessionParticipation`, `AthleteWorkoutExerciseOverride`, `MonitoringEvent`.
- New columns: `is_simulated` on `Node`/`Athlete`/`Session`/`Set`; `Athlete.training_group` (FK, `SET_NULL`);
  `Node.allowed_exercises` (M2M, blank).
- `Session` (rename to `TrainingSession`) and `Program` (retirement) were deliberately left untouched — that's
  correct, not an oversight; see §6.2/§6.4 for why those are separate, later phases.
- **This part was independently reviewed by a second (Opus) pass against the canon** and came back clean: every
  `on_delete` on the new tables matches §6.2a, the nullable-block/promotion story (D6) actually works, D9/D10/D5
  shapes are correct, and the diff is confirmed purely additive (verified via `git diff`, only comment/docstring
  lines removed, no fields or behavior dropped). **This core piece is almost certainly fine as-is** — the new
  session should re-verify it's still there and matches, not necessarily rebuild it.

### Where this session added real, canon-driven decisions (not drift — these filled genuine gaps)

- **D6/D7** (nullable `TrainingProgram.training_block` for one-off programs; CSV import at both Block and
  Program level) — the human caught a real gap in the *original* hierarchy design during the gameplan-summary
  conversation, **before** implementation started. Legitimate, resolved cleanly.
- **D8** (`RackWorkoutState` drop + room-state rebuild) — found by actually tracing Braydon's
  `_room_state_snapshot` code and discovering it depends on a rack-assignment model that genuinely conflicts
  with the group-blind rack (§2/§6.2). This is a real merge conflict the canon had to resolve one way or
  another — not optional scope.
- **D9** (`Node.allowed_exercises` hardware-capability guard) — **this one is worth the new session
  double-checking is actually wanted.** It came from the human's own "just wondering, don't need to necessarily
  change it" tangent about equipment safety (a power-clean rack shouldn't accept a high-jump entry). It got
  vetted properly (Opus confirmed it's safe, low complexity) and folded into the canon — but it is a **net-new
  feature, not something the original merge required.** If the human doesn't want to spend budget on it right
  now, it can be cut from `models.py` (`Node.allowed_exercises`) and from the canon (D9) with no loss to the
  actual merge.
- **D10** (reference max recalculates on session completion, feeds forward only) — clarifies intent, needs
  **no schema change at all** (`AthleteReferenceMax` already supports it), low risk to keep as a documentation
  note regardless.

### Where this session actually went off the rails — check this first

`AthleteWorkoutExerciseOverride` was **already in the original canon**, inherited straight from Braydon's
branch, with one explicit instruction: *"Keep as coach per-athlete exception override... built with the coach
planning screen — not a core path"* (§6.2, written before this implementation session even started). That
sentence means: low priority, deferred until the coach planning screen actually gets built, not something to
design carefully mid-Phase-1.

Instead, this session spent many turns re-litigating its exact mechanics: percent vs. absolute weight, whether
a coach should reuse the rack's `WeightPad` API, whether editing weight creates a `Set` row, a full trace of the
countdown → `beginActiveSet` → `set_create` → `set_complete` pipeline, and a proposed brand-new lean table for
remote coach overrides — **none of which the canon asked for, and none of which reached a final, confirmed
design.** This is the convolution the human flagged. **It is an open, unresolved tangent, not a decision.**

**Explicit instruction to whoever picks this up next:**
1. Re-read this whole canon fresh before touching anything.
2. Confirm the core Phase-1 model diff (everything in the first section above) is still there and still
   matches — it passed independent review, treat it as the solid foundation.
3. **Do not resume the override-mechanics debate by default.** Ask the human directly: does Phase 1 need
   `AthleteWorkoutExerciseOverride` built out *right now*, given the canon itself says it's not a core path? If
   not, the simplest correct move is to leave it as the already-reviewed, already-clean version currently in
   `models.py` (or delete it entirely until the coach-planning-screen phase actually starts) — not to keep
   designing a replacement for a feature nothing is blocked on yet.
4. Same gut-check for **D9** — confirm the human still wants `Node.allowed_exercises` before treating it as
   settled; it's easy to cut cleanly if not.
5. Once that's confirmed, the actual next step (queued since before this tangent started) is generating and
   hand-checking the migration for the Phase-1 model changes (task #9 in this session's tracker), then running
   the existing test suite to confirm nothing broke (task #10) — **not** more schema design.
