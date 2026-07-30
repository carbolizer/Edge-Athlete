# Patch notes — `merge-braydon`

What changed on this branch, phase by phase, and how to see each thing working.

**Scope:** merging Braydon's coach frontend onto the base station API, plus the
planning, reporting, scheduling and analytics the merged product needed. Fifteen
phases, each tagged (`p1-complete` … `p15-complete`).

| | |
|---|---|
| Files changed | 82 |
| Lines | +10,655 / −659 |
| Tests | 280 backend · 131 frontend |
| Migrations | `0008` → `0017` |
| Frozen | `react/src/rack/*`, `repBuffer.js`, `device.js` — untouched, checked every phase |

## How to read the click paths

Every path starts at `http://localhost/` on a browser with no device role yet.
`>` means "then click". Login is `coach` / `coachpass`.

The role picker offers exactly three: **Rack Tablet**, **Base Station Display**,
**Coach Admin**.

> **Two things that will trip you up.** A device remembers its role, so
> `localhost/` stops showing the picker — press **Change device** (top right of the
> coach screen) to get it back. And on a *return* visit a coach device lands on
> **Room Layout** (`/coach/setup`), not the workspace; the workspace is
> `localhost/coach`.

Seed a realistic gym first — most paths assume it:

```bash
docker compose exec django python manage.py seed_active_session
```

---

## P1 · The training hierarchy

A plan can belong to a **group** instead of being retyped per athlete.
`TrainingBlock` (reusable template) → `TrainingProgram` (that template placed in
time for one group) → `TrainingGroup` → `TrainingSession`.

| File | Change |
|---|---|
| `migrations/0008_training_hierarchy_and_columns.py` | The new tables and columns |
| `migrations/0009_seed_exercise_catalog.py` | Seeds the movement catalog by hand |
| `models.py` | The `Training*` models |
| `tests.py` | Schema coverage |

**See it:** `localhost` > **Coach Admin** > log in > **workouts** tab — the whole screen
is built on these tables.

> The seeded catalog is why "Back Squat" and "back squat" can never become two
> different movements: movements are picked from a list, never typed.

---

## P2 · One messaging backbone

Racks, the wall and the coach tablet all learn about a change the same way.
Adopted the `realtime/` layer, folded the rack publisher into it, and deleted the
unused notification/motion code.

| File | Change |
|---|---|
| `realtime/broadcast/publisher.py` | The one publisher |
| `realtime/event_processor/process_pulse.py` | Node pulse handling |
| `notification_flow/**` | **Deleted** — ntfy and motion cruft |
| `basestation_config/settings.py` | Broker settings |

**See it:** `localhost` > **Base Station Display** on one browser tab,
`localhost/coach` on another > complete a set on the rack screen — both update without a
refresh.

> Every rack topic and payload stayed **byte-identical**, including the
> "all racks → pairing mode" signal.

---

## P3 · The live room, derived not stored

There is **no table holding "the state of the room"**. Every screen works it out
per request from check-ins and saved sets, so nothing can drift out of sync.

| File | Change |
|---|---|
| `services/room_state.py` | The whole derivation |
| `views.py`, `urls.py` | `room-state/`, day-progress, `auth/refresh/` |
| `tests.py` | Coverage |

**See it:** `localhost` > **Coach Admin** > log in > **room** tab > pick a rack from the
left-hand list.

> One endpoint serves both audiences: `room-state/` for the wall,
> `room-state/?details=true` for the coach. **The detail level is the privilege
> boundary** — ids and the roster need a login, because the wall is a shared
> screen nobody signs into.

---

## P4 · Freeze the day, roll maxes forward

Ending a training day writes an **immutable** `DailyReport` snapshot and
recalculates every athlete's reference max from what they actually lifted.

| File | Change |
|---|---|
| `migrations/0010_daily_report.py` | The snapshot table |
| `services/session_completion.py` | Ending a day, atomically |
| `services/reports.py`, `report_pdf.py` | The reports family and PDF |
| `views.py`, `urls.py` | `reports/`, `reference-maxes/` |

**See it:** `localhost` > **Coach Admin** > log in > **End training day** > **Confirm
end** — the finished report appears in place. Then **reports** tab > pick a day >
**Download PDF**.

> Ending is a `PATCH` on the session, not a separate `end/` route: "end the day"
> **is** "set its end time", and a second route would be two ways to do one thing.
> It is idempotent — a double tap cannot produce two reports.

---

## P5 · Percent-of-max, and the coach's own spreadsheet

The most important idea in the product: a prescription is a **percentage of each
athlete's own max**, never a number of pounds. One line — "Back squat 5×3 @ 80%" —
serves a whole group, and each athlete's bar weight is worked out from their own
tested max. Plus CSV import for the three sheets a coach already keeps.

| File | Change |
|---|---|
| `services/plan_resolution.py` | percent × reference max, per athlete |
| `services/lifting_math.py` | Epley rep-basis conversion, rounded to 5 lb |
| `services/planning.py` | Deploying a block for a group |
| `services/csv_import.py`, `csv_parsing.py` | Sheet-type detection + three importers |
| `views.py`, `urls.py`, `serializers.py` | Planning and import routes |

**See it (planning):** `localhost` > **Coach Admin** > log in > **workouts** tab >
**Step 3 · Deploy** > pick a block and group > **Deploy to group**. Then
**athlete** tab > pick two athletes — same plan, different weights.

**See it (import):** same tab > the **Import** panel > choose a max sheet > **Preview before import** > **Import**.
Misspell a name first and watch the preview offer the right athlete instead of
rejecting the file.

> Without reference maxes, **every target resolves to null** — which is why the
> max-sheet importer was built first.

---

## P6 · Retire the old table, protect the lifting

Dropped the legacy per-athlete `Program` table and changed `Set.session` to
`PROTECT`.

| File | Change |
|---|---|
| `migrations/0011_alter_set_session_delete_program.py` | Drop `Program`, add `PROTECT` |
| `models.py`, `admin.py`, `serializers.py` | Remove the legacy model |
| `services/plan_resolution.py`, `room_state.py` | Read the group plan instead |
| `management/commands/seed_active_session.py` | Rebuilt on the real hierarchy |

**See it:** try to delete a session that has sets, from Django admin at
`localhost/admin/` — it refuses.

> ⚠️ **A `Set` is the only permanent record that an athlete actually did
> something.** Deleting a session used to take the lifting with it, silently.

---

## P7 · The coach frontend on the real API

Braydon's coach screens rewired onto the base station's actual endpoints. Six of
his routes folded onto ours, three dropped.

| File | Change |
|---|---|
| `react/src/App.jsx` | The routing seam + an `ErrorBoundary` |
| `react/src/Dashboard.jsx` | Coach and wall views on real shapes |
| `react/src/WorkoutCatalog.jsx` | Rebuilt on the training hierarchy |
| `react/src/AthleteWorkoutPlanning.jsx`, `athletePlanning.js` | Assignment payloads |
| `react/src/ReportsWorkspace.jsx` | The reports screen |
| `react/src/router.js` | `usePathname` → `useSyncExternalStore` |

**See it:** `localhost` > **Coach Admin** > log in — the entire screen is this phase.

> ⚠️ **Seven bugs were found by clicking and none by a green test suite** — the
> tests asserted against invented fixtures rather than real payloads. An
> `ErrorBoundary` now stops a render error blanking the whole app, and
> `usePathname` uses `useSyncExternalStore` because the old version raced on any
> redirecting URL and produced a black screen.

---

## P8 · Verify on a fresh database

Cold-build check, the rack loop end to end, and the last shape crashes.

| File | Change |
|---|---|
| `react/src/dashboardView.js` + tests | Replaced invented fixtures with live payloads |
| `views.py`, `serializers.py` | `athletes/{id}/` GET, report lens fixes |
| `management/commands/seed_active_session.py` | Reset path that survives an ended day |

**See it:**

```bash
docker compose down -v && docker compose up -d --build
docker compose exec django python manage.py seed_active_session
```

Then `localhost` > **Rack Tablet** > run splash → setup → check-in → set → rest.

---

## P9 · Names that match what things are

Routes and models renamed to say what they actually serve. **No behaviour
changed.** Full old → new table in [`../NAMING_CHANGES.md`](../NAMING_CHANGES.md).

| File | Change |
|---|---|
| `migrations/0012_rename_session_to_trainingsession.py` | `Session` → `TrainingSession` |
| `urls.py`, `views.py`, `serializers.py` | Route and function names |
| `react/src/**` | Every call site, same commit |

**See it:** open the browser network tab on the coach screen — requests read
`/api/training-blocks/`, not `/api/workout-programs/`.

> ⚠️ A blunt find-and-replace shadowed model imports with local variables in nine
> places. Renaming is not a sed job.

---

## P10 · Edit a block after writing it

Rename, reorder and delete days and prescription rows.

| File | Change |
|---|---|
| `migrations/0013_trainingblock_updated_at.py` | "Last edited", backfilled from `created_at` |
| `services/planning.py` | `apply_order()` and `touch_block()` |
| `views.py`, `urls.py` | Four editing routes |
| `react/src/WorkoutCatalog.jsx`, `workoutCatalog.js` | The "Days by block" panel |

**See it:** `localhost` > **Coach Admin** > log in > **workouts** tab > **Days by block**
> use the move buttons to reorder a day, or **Rename** / **Remove**.

> Reordering sends the **whole list**, because the position column carries a
> non-deferrable unique constraint — a one-at-a-time swap collides with whatever
> already sits on that number. And editing a block never touches a program already
> deployed from it.

---

## P11 · Several coaches, one catalog

Blocks stay global; a coach filter is a **lens, not a fence**. Blocks carry
categories. A group has real staff.

| File | Change |
|---|---|
| `migrations/0014_blockcategory_...py` | `BlockCategory` + many-to-many |
| `migrations/0015_traininggroupcoach.py` | Join table, existing coaches backfilled as `head` |
| `views.py`, `urls.py`, `serializers.py` | `?coach=me`, `?category=`, staff routes |
| `react/src/WorkoutCatalog.jsx` | Scope toggle and category chips |

**See it:** `localhost` > **Coach Admin** > log in > **workouts** tab > **Block catalog**
> toggle **My blocks / All coaches**, or click a category chip to filter.

> ⚠️ **Breaking:** `TrainingGroup.coach` is gone — read `coaches` (a list) or
> `head_coach` (nullable). The auto-generated migration dropped the column
> **before** the backfill; the hand-written one creates, copies, then drops.
> ⚠️ **There is still no UI for group staff** — adding an assistant needs Django
> admin.

---

## P12 · One training day at a time

A second open session is refused. Ending a day says which day ended. A day the
base station lost can be closed at the time the room actually emptied.

| File | Change |
|---|---|
| `views.py` | 409 guard, `ended` block, `started_at` validation |
| `services/active_session.py` | The one definition of "active" |
| `react/src/TrainingDayPanel.jsx`, `trainingDay.js` | End-time picker, conflict prompt |

**See it:** `localhost` > **Coach Admin** > log in > **End training day** >
**Confirm end**. The status names the day that ended rather than leaving you to
guess from a screen that may look identical.

**See the recovery path:** on that same confirmation, the **Ended at** dropdown
offers "Now", each hour back to the start, and "When it started" — for the day the
base station lost to a power cut.

**See the conflict prompt** (fiddly, because it needs a stale screen — which is
exactly when it fires in real life):

1. With **no** day running, open the coach screen and fill in the start form —
   label and athletes — but do **not** submit.
2. Start a day from somewhere else, e.g.
   `curl -X POST localhost/api/sessions/ -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"label":"Other tablet","athletes":[5]}'`
3. Now submit the form. It names the day in the way, keeps your label and roster,
   and offers to end that one and start yours in a single press.

> ⚠️ A stray second session used to **silently capture check-ins** — sets landed on
> a day with no participants while every tablet looked normal. And `ended_at` was
> unvalidated: a day could end six years before it started, frozen into a report
> nothing could fix.

---

## P13 · An athlete's history and numbers

The athlete and history tabs were built against a payload nobody had written.

| File | Change |
|---|---|
| `services/athlete_analytics.py` | Summary, per-movement aggregates, per-set reps |
| `views.py` | `analytics/athlete/{id}/` widened |
| `react/src/Dashboard.jsx` | The two tabs, plus a real empty state |

**See it:** `localhost` > **Coach Admin** > log in > pick an athlete from the top
dropdown > **athlete** tab, then **history** tab > **Compare reps** on any set.

> The summary spans **all** history while the set list is capped at 50 — the screen
> says so, so totals taken from the truncated list would make it lie.

---

## P14 · The training calendar

Deploying a block lays its days onto real dates. A coach can set Thursday up on
Tuesday, and it does **not** start until someone starts it.

| File | Change |
|---|---|
| `migrations/0016_scheduled_sessions.py` | `ScheduledSession`; `started_at` nullable |
| `migrations/0017_slot_day_cascade.py` | Slot dies with the day it runs |
| `services/cadence.py` | Which weekdays, and the dates that fall out |
| `services/planning.py` | `generate_schedule()` |
| `views.py`, `urls.py` | Calendar routes, `sessions/{id}/start/` |
| `react/src/ScheduleWorkspace.jsx`, `schedule.js` | The schedule tab |

**See it:** `localhost` > **Coach Admin** > log in > **schedule** tab > **Set up day** on
a planned date > then **Start day**.

> ⚠️ **"Active" now means STARTED and not ended.** Postgres sorts NULLs *first*
> descending, so without that filter a session created for next Thursday would
> sort ahead of the day being trained and the racks would follow it.
> Starting is its own `POST` because `PATCH` with an empty body already means
> *end the day now* — and start and end are opposites.

---

## P15 · Promote a program back into a block

A plan a coach tuned until it beat the template it came from can be lifted back
out as a block anyone can deploy.

| File | Change |
|---|---|
| `services/planning.py` | `promote_program_to_block()` |
| `views.py`, `urls.py` | `training-programs/{id}/promote/` |
| `models.py` | Corrected a docstring that described this wrongly |
| `react/src/WorkoutCatalog.jsx` | "Deployed programs" panel |

**See it:** `localhost` > **Coach Admin** > log in > **workouts** tab > **Deployed
programs** > **Make a block from this**. The new block appears in the Block
catalog below, ready to deploy to another group.

> ⚠️ Promotion **copies the days and rows up**. Pointing `training_block` at a new
> row records provenance and copies nothing — the block would come out with zero
> days, and the failure would only show up later when someone deployed it and got
> an empty plan.

---

## Known gaps

Recorded rather than hidden. All four are in `_START_HERE_MERGE_CANON.md`.

1. **Braydon needs telling** the CSV contract changed: `default_weight_lbs` →
   `target_percent`. The merge's one deliberate break.
2. **No UI for group staff.** The API takes several coaches per group and a
   group's creator becomes its head; adding an assistant needs Django admin.
3. **`GET /api/analytics/session/{id}/` has no pinned field list** — only prose.
   That exact kind of gap broke the coach frontend on arrival once already.
4. **A day left open overnight** has no defined behaviour, deliberately.
   Auto-closing would write an immutable report with nobody watching.

## The pattern worth carrying forward

**Eight bugs on this branch were found by clicking. None were found by a green
test suite.** Every one was the same shape: a test asserting against a fixture
someone constructed, rather than against what the real request path produces.

The two habits that came out of it, both cheap:

- **Click the thing.** A green suite is necessary and not sufficient.
- **Break it on purpose.** After writing a test for something important, make the
  code wrong and confirm the test fails. Several tests on this branch were proved
  real that way — the migration backfill, the null-sort ordering, and promotion
  copying rows rather than just pointing a foreign key.
