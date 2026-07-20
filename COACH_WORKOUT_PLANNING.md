# Coach Workout Planning and Daily Reports

## Status

Delivered in six vertical slices on 2026-07-16. Workout templates, rack
execution, and immutable reports retain separate data-lifecycle requirements.

### Local rollback incident and recovery

During final rollback-evidence work on 2026-07-16, the first command supplied
`POSTGRES_DB` as a host variable. Docker Compose retained the Django service's
`env_file` value, so `migrate event_handler 0005` targeted the live local Compose
database instead of the newly created disposable database. This reversed
`0011` through `0006` and dropped the workout catalog, assignment, override, and
daily-report tables. Applying `python manage.py migrate` immediately restored the
schema but could not restore rows from the dropped tables.

The immediately preceding QA state identified two immutable `[QA]` reports, one
`[QA] Report Workout`, and one athlete-workout assignment; all four rows were
absent after schema reapplication. Legacy rows remained: one athlete, two
Sessions, one Set, two Reps, and one rack screen, with no active Session. No
database backup was available to this session for comparison or restoration, so
the deleted report snapshots could not be recovered or compared byte-for-byte.
The preceding QA inventory did not provide a backup or full row export, so it
cannot prove whether any additional Slice-table rows existed. No production or
remote database was involved; this affected the local Compose database only.

The user selected fresh fixture recreation. Application services created a new
workout and assignment, started and ended two new `[QA]` training days, and
generated two replacement immutable reports. A `[QA] Report Program` was then
created through the coach API for Slice 2 evidence. Current fixtures are
replacements, not restored originals. The rollback test was rerun afterward with
the explicit service override and verified disposable database documented below.

## Problem

The current `Program` model is one exercise prescription owned by one athlete.
It cannot represent a reusable workout, a group of workouts, a CSV-defined
template, or the prescription snapshot required for an accurate historical
report.

The coach needs to create reusable workouts manually or from CSV, group them
into programs, assign them to racks or athletes, adjust athlete targets, run a
training day, and review durable day and athlete reports.

## User stories

- As a coach, I can create and reuse an ordered multi-exercise workout.
- As a coach, I can preview and atomically import workouts from CSV.
- As a coach, I can group ordered workouts into a program.
- As a coach, I can assign a workout or program to a rack.
- As an athlete, I can identify myself at a rack and see my effective targets.
- As a coach, I can override sets, reps, and weight for one athlete.
- As a coach, I can start and end the room's training day.
- As a coach, I can browse immutable reports by day and by athlete.

## Vocabulary

- **Workout:** reusable template containing ordered exercise prescriptions.
- **Workout exercise:** movement, position, sets, reps, default weight, and an
  optional velocity range.
- **Workout program:** ordered collection of workouts. The UI may call this a
  Program, but the internal name must not collide with the legacy `Program`.
- **Legacy prescription:** the current athlete-owned `Program` row.
- **Training day:** the single room-wide active training window.
- **Effective targets:** template defaults after athlete overrides are applied.
- **Daily report:** immutable snapshot generated when a training day ends.

## Assumptions

- CSV rows define workout exercises, not athlete assignments.
- The initial CSV columns are `workout_name`, `exercise`, `position`, `sets`,
  `reps`, `default_weight_lbs`, `velocity_min`, and `velocity_max`.
- Sets and reps are positive integers. Weight is a finite number at least zero.
- Velocity bounds are both blank or both present, finite, ordered, and between
  0 and 10 m/s.
- Workout and workout-program names are unique after trimming and
  case-insensitive comparison.
- Athlete overrides can change sets, reps, and weight, but not movement order
  or velocity bounds.
- Assigning a program exposes its ordered workouts; progression is selected,
  not inferred automatically.
- Rack athlete identification initially uses name selection and confirmation.
  It is identity selection on the private AP, not authentication. NFC remains
  deferred.
- Only persisted sets and reps appear in reports. Memory-only live reps do not.
- Existing `Program`, `/api/programs/`, and rack behavior remain compatible
  until a later migration is explicitly approved.

## Non-goals

- NFC, PINs, biometrics, or cryptographic athlete authentication.
- Cloud sync, calendar scheduling, or automatic program progression.
- Editing or deleting finalized reports.
- CSV updates or merges into existing workouts; initial imports are create-only.
- Saving the current memory-only rack rep stream in the catalog slice.

## Slice 1: Workout catalog and CSV

- **AC1:** An active staff coach can atomically create a uniquely named workout
  with one or more valid, contiguously ordered exercises.
- **AC2:** Invalid exercises, duplicate or missing positions, and duplicate
  names reject the complete manual request without partial writes.
- **AC3:** The coach can list workouts and see their exercises in position order.
- **AC4:** CSV preview performs no writes and returns normalized workouts plus
  row- and field-specific errors.
- **AC5:** CSV import revalidates the file and creates all workouts and exercises
  in one transaction.
- **AC6:** Any invalid row or existing workout name rolls back the complete
  create-only import.
- **AC7:** Empty, malformed, oversized, over-row-limit, missing-header,
  duplicate-header, and unknown-header files are rejected without writes.
- **AC8:** Quoted commas, UTF-8, UTF-8 BOM, CRLF, and blank velocity pairs parse
  consistently.
- **AC9:** Manual creation, preview, import, and catalog reads require coach JWT
  access and return private no-store responses.

### CSV contract

```csv
workout_name,exercise,position,sets,reps,default_weight_lbs,velocity_min,velocity_max
Lower Strength,Back squat,1,4,5,225,0.55,0.75
Lower Strength,Romanian deadlift,2,3,8,185,,
```

Headers are exact and may appear in any order. Rows are grouped by normalized
workout name, and rows for one workout need not be adjacent. Positions start at
1 and must be unique and contiguous within each workout. Repeated movement
names at different positions are allowed. Initial limits are 1 MiB and 1,000
exercise rows. Import never updates, merges, or partially appends.

### Slice 1 validation evidence

- `docker compose run --rm --no-deps django python manage.py test event_handler
  --noinput` passed 147 tests, including atomic manual
  creation, normalized-name conflicts, ordered pagination, CSV preview with zero
  writes, atomic import rollback, BOM/CRLF/quoted-comma parsing, exact 1 MiB and
  1,000-row boundaries, database constraints, authorization, and no-store
  responses.
- `npm test -- --run` passed 43 tests and `npm run build` passed with the existing
  bundle-size warning; these include catalog normalization and error-display
  coverage.
- Live coach API returned one `[QA] Report Workout` with its exercise in position
  1. Earlier live checks created workouts manually, previewed invalid CSV without
  writes, imported corrected CSV, and displayed normalized row/field errors.
- Browser checks showed the workout catalog and creation/import controls without
  horizontal overflow in landscape and portrait. Evidence:
  `/tmp/opencode/edge-workout-catalog-landscape.png` and
  `/tmp/opencode/edge-workout-catalog-portrait.png`.
- Security review passed active-staff authorization, private no-store responses,
  bounded uploads and rows, strict UTF-8/CSV parsing, transactional writes, and
  non-logging of file bodies and prescriptions.

## Slice 2: Workout programs

- **AC10:** A coach can create a uniquely named workout program containing one
  or more existing workouts in contiguous order.
- **AC11:** Duplicate positions, duplicate workout membership, or unknown
  workouts reject the complete request.
- **AC12:** The legacy `Program` model and `/api/programs/` retain their current
  meaning until an explicit migration and rollback plan exists.

Migration `0007` is additive and reversible while no later migration references
its tables. Rolling it back drops only `WorkoutProgram` and `WorkoutProgramItem`;
it does not alter workouts, legacy `Program` rows, rack state, or session data.

### Slice 2 validation evidence

- `docker compose run --rm --no-deps django python manage.py test event_handler
  --noinput` passed 147 tests. The suite covered ordered normalized creation, duplicate
  name/position/workout rejection, unknown workouts, contiguity, 1,000-item
  limits, database constraints, pagination, authorization, atomic writes, and
  unchanged legacy `/api/programs/` behavior.
- From `react/`, `npm test -- --run` passed 43 tests and `npm run build` passed
  with the existing 669.17 kB bundle warning. These cover ordered program draft
  normalization and selection behavior.
- `docker compose run --rm --no-deps django python manage.py check` reported no
  issues; `docker compose run --rm --no-deps django python manage.py
  makemigrations --check --dry-run` reported no changes; `git diff --check`
  passed.
- Live coach API created and listed `[QA] Report Program` with `[QA] Report
  Workout` at position 1. Responses returned the ordered allowlisted item shape.
- Browser checks showed program creation, ordered selection, and catalog display
  without horizontal overflow in landscape and portrait. Evidence:
  `/tmp/opencode/edge-workout-program-builder-landscape.png`,
  `/tmp/opencode/edge-workout-program-landscape.png`, and
  `/tmp/opencode/edge-workout-program-portrait.png`.
- Security review passed active-staff authorization, no-store responses, bounded
  item counts, locked workout membership validation, atomic writes, protected
  referenced workouts, and unchanged legacy prescription access.

#### Slice 1-3 rollback evidence

The successful rerun used `docker compose run -e`, rather than a host variable,
to override the service's `env_file` value:

```bash
docker exec edgeathlete-postgres sh -c \
  'dropdb --if-exists -U "$POSTGRES_USER" edgeathlete_rollback_evidence_20260716 && createdb -U "$POSTGRES_USER" edgeathlete_rollback_evidence_20260716'
docker compose run --rm --no-deps \
  -e POSTGRES_DB=edgeathlete_rollback_evidence_20260716 \
  django python manage.py shell -c \
  "from django.conf import settings; print(settings.DATABASES['default']['NAME'])"
docker compose run --rm --no-deps \
  -e POSTGRES_DB=edgeathlete_rollback_evidence_20260716 \
  django python manage.py migrate event_handler 0005
```

The database-name check printed
`edgeathlete_rollback_evidence_20260716`. At `0005`, SQL inserts seeded IDs
`910001` in `event_handler_athlete`, `event_handler_node`,
`event_handler_rackscreen`, `event_handler_program`, `event_handler_session`,
`event_handler_session_athletes`, `event_handler_set`, `event_handler_rep`, and
`event_handler_rackworkoutstate`. The count query returned one athlete, legacy
program, Session, Set, Rep, and rack state; the node and screen inserts also
returned `INSERT 0 1`.

The seed used these values at the `0005` schema:

```sql
INSERT INTO event_handler_athlete
  (id, name, nfc_tag_id, created_at, notes, is_simulated)
  VALUES (910001, 'Rollback Athlete', NULL, NOW(), 'legacy row', FALSE);
INSERT INTO event_handler_node
  (id, node_id, rack_number, mount_type, firmware_version, battery_level,
   signal_strength, last_seen, is_active, is_simulated)
  VALUES (910001, 'rollback-node', 91, 'bar', NULL, 90, -40, NOW(), TRUE, FALSE);
INSERT INTO event_handler_rackscreen
  (id, device_id, rack_number, last_seen)
  VALUES (910001, 'rollback-screen', 91, NOW());
INSERT INTO event_handler_program
  (id, exercise, target_sets, target_reps, target_weight_lbs,
   velocity_zone_min, velocity_zone_max, athlete_id, is_simulated)
  VALUES (910001, 'Rollback squat', 3, 5, 225, 0.5, 0.8, 910001, FALSE);
INSERT INTO event_handler_session
  (id, label, started_at, ended_at, notes, is_simulated)
  VALUES (910001, 'Rollback Session', NOW(), NULL, 'legacy session', FALSE);
INSERT INTO event_handler_session_athletes (session_id, athlete_id)
  VALUES (910001, 910001);
INSERT INTO event_handler_set
  (id, exercise, set_number, started_at, ended_at, reps_completed,
   avg_velocity, peak_velocity, is_false_set, athlete_id, node_id, session_id,
   weight_lbs, rack_number, is_simulated)
  VALUES (910001, 'Rollback squat', 1, NOW(), NOW(), 1, 0.7, 0.8, FALSE,
          910001, 910001, 910001, 225, 91, FALSE);
INSERT INTO event_handler_rep
  (id, rep_number, timestamp, mean_velocity, peak_velocity, duration_ms,
   velocity_color, set_id)
  VALUES (910001, 1, NOW(), 0.7, 0.8, 900, 'green', 910001);
INSERT INTO event_handler_rackworkoutstate
  (rack_number, updated_at, active_program_id, active_session_id)
  VALUES (91, NOW(), 910001, 910001);
```

The forward and reverse commands were:

```bash
docker compose run --rm --no-deps \
  -e POSTGRES_DB=edgeathlete_rollback_evidence_20260716 \
  django python manage.py migrate
docker compose run --rm --no-deps \
  -e POSTGRES_DB=edgeathlete_rollback_evidence_20260716 \
  django python manage.py shell -c \
  "from event_handler.models import Athlete,AthleteWorkoutAssignment,RackWorkoutState,Session,WorkoutProgram,WorkoutProgramItem; from event_handler.services.workout_catalog import create_workouts; athlete=Athlete.objects.get(pk=910001); session=Session.objects.get(pk=910001); workout=create_workouts([{'name':'Rollback Catalog Workout','normalized_name':'rollback catalog workout','exercises':[{'exercise':'Catalog squat','position':1,'sets':3,'reps':5,'default_weight_lbs':225.0,'velocity_min':0.5,'velocity_max':0.8}]}])[0]; program=WorkoutProgram.objects.create(name='Rollback Catalog Program',normalized_name='rollback catalog program'); item=WorkoutProgramItem.objects.create(workout_program=program,workout=workout,position=1); AthleteWorkoutAssignment.objects.create(athlete=athlete,assigned_workout=workout); RackWorkoutState.objects.create(rack_number=92,active_session=session,assigned_program_item=item,selected_athlete=athlete)"
docker compose run --rm --no-deps \
  -e POSTGRES_DB=edgeathlete_rollback_evidence_20260716 \
  django python manage.py migrate event_handler 0005
```

Before the reverse, the catalog counts were one workout, one workout program,
one athlete assignment, and two rack states. After reversing `0011 -> 0005`,
this SQL observation checked both legacy counts and removed tables:

```sql
SELECT
  (SELECT COUNT(*) FROM event_handler_athlete) AS athletes,
  (SELECT COUNT(*) FROM event_handler_node) AS nodes,
  (SELECT COUNT(*) FROM event_handler_rackscreen) AS screens,
  (SELECT COUNT(*) FROM event_handler_program) AS legacy_programs,
  (SELECT COUNT(*) FROM event_handler_session) AS sessions,
  (SELECT COUNT(*) FROM event_handler_set) AS sets,
  (SELECT COUNT(*) FROM event_handler_rep) AS reps,
  (SELECT COUNT(*) FROM event_handler_rackworkoutstate) AS rack_states,
  to_regclass('event_handler_workout') AS workout_table,
  to_regclass('event_handler_workoutprogram') AS workout_program_table,
  to_regclass('event_handler_dailyreport') AS report_table;
```

Observed counts were athlete 1, node 1, screen 1, legacy `Program` 1, Session 1,
Set 1, Rep 1, and rack states 2. All three `to_regclass` results were null.
Reapplying `python manage.py migrate` against the same explicit database retained
those counts, recreated the catalog/report tables empty, and returned workout 0,
workout program 0, athlete assignment 0, and daily report 0. Finally:

```bash
docker compose run --rm --no-deps \
  -e POSTGRES_DB=edgeathlete_rollback_evidence_20260716 \
  django python manage.py migrate
docker exec edgeathlete-postgres sh -c \
  'dropdb -U "$POSTGRES_USER" edgeathlete_rollback_evidence_20260716'
```

A later `SELECT COUNT(*) FROM pg_database WHERE
datname='edgeathlete_rollback_evidence_20260716'` returned 0, confirming the
disposable database no longer existed.
Migration `0005` was not reversed because its guard requires a pre-`0005` backup.

## Slice 3: Rack assignment and athlete identity

- **AC13:** During an active training day, a coach can assign exactly one workout
  or workout program to a known rack; assigning one type replaces the other.
- **AC14:** An athlete can select and confirm their identity from a bounded
  rack-safe list and sign out when finished.
- **AC15:** After athlete identity confirmation, the rack resolves its assigned
  workout and displays ordered exercises and effective targets. Athlete-specific
  assignment precedence remains Slice 4 AC19.
- **AC16:** A program assignment requires selection of one included workout
  before exercise targets are shown.
- **AC17:** Athlete switching or assignment changes are rejected while the rack
  has an unfinished set.
- **AC18:** Ending the day or reassigning the rack clears athlete identity.

Migration `0008` is additive and reversible while no later migration references
its fields. Rolling it back removes catalog assignment and selected-athlete
columns from `RackWorkoutState`; legacy `active_program`, workouts, programs,
sessions, and completed training data remain intact.

### Slice 3 validation evidence

- `docker compose run --rm --no-deps django python manage.py test event_handler
  --keepdb`: 98 tests passed, including concurrent set-start/session-end,
  assignment/session-end, screen reassignment, identity, and legacy-transition
  coverage.
- `npm test -- --run`: 27 tests passed. `npm run build` passed with the existing
  bundle-size warning.
- `python manage.py check` passed; `makemigrations --check --dry-run` reported no
  changes; migration `0008` is applied; `git diff --check` passed.
- Live API: direct workout assignment returned an active roster of four and no
  effective workout before identity; identity confirmation resolved two ordered
  exercises; signout cleared identity; program assignment selected its included
  workout; unknown and conflicting transitions returned stable errors.
- Browser at 1024x768 and 768x1024 confirmed explicit athlete confirmation,
  effective workout targets, signout, coach catalog assignment controls, and no
  horizontal overflow. Evidence: `/tmp/opencode/edge-rack-athlete-selection.png`,
  `/tmp/opencode/edge-rack-effective-workout.png`,
  `/tmp/opencode/edge-rack-effective-workout-portrait.png`, and
  `/tmp/opencode/edge-coach-rack-catalog-assignment.png`.
- Security review covered coach authorization, open device/rack matching,
  roster privacy, no-store responses, assignment constraints, protected deletes,
  unfinished-set transitions, and lock ordering. Residual risk: athlete name
  selection is identity rather than authentication and relies on the private AP.
- Cleanup restored Rack 1 to the legacy simulated athlete and Back squat,
  removed all QA workouts/programs, and removed the temporary unassigned screen.

## Slice 4: Athlete assignments and overrides

- **AC19:** A coach can assign one workout or workout program directly to an
  athlete, superseding the rack assignment only for that athlete.
- **AC20:** A coach can independently override sets, reps, and weight for an
  athlete and workout exercise; null fields inherit template defaults.
- **AC21:** Removing an override restores inheritance without modifying the
  reusable workout or historical results.
- **AC22:** Override validation matches template validation and cannot change
  movement, order, or velocity bounds.

Migration `0009` adds athlete workout assignments and sparse exercise overrides.
Rolling it back first clears identities that rely only on athlete assignments,
restores the Slice 3 selected-athlete constraint, and then removes only the two
Slice 4 tables. Workouts, rack assignments, legacy `Program`, sessions, and
training history remain intact.

### Slice 4 validation evidence

- `docker compose run --rm --no-deps django python manage.py test event_handler
  --keepdb`: 114 tests passed, including assignment precedence, sparse override
  inheritance, database constraints, privacy, and assignment-versus-set races.
- `npm test -- --run`: 33 tests passed. `npm run build` passed with the existing
  bundle-size warning. Django check, migration drift, and `git diff --check`
  passed; migration `0009` is applied.
- Live API: athlete assignment overrode the rack workout; `5 x 3 @ 245 lb`
  replaced the template `4 x 5 @ 225 lb`; deleting the athlete assignment fell
  back to the rack workout; recreating it restored athlete precedence.
- Athlete-only live check: with no rack assignment, identity remained available
  and resolved the selected athlete's personal workout and effective targets.
- Browser checks at 1366x768, 1024x768, and 768x1024 showed coach assignment and
  sparse override controls plus the rack's source-aware final targets without
  horizontal overflow. Evidence: `/tmp/opencode/edge-coach-athlete-planning.png`,
  `/tmp/opencode/edge-coach-athlete-planning-portrait.png`, and
  `/tmp/opencode/edge-rack-athlete-override.png`.
- Security review passed coach authorization, no-store responses, rack privacy,
  numeric/null validation, assignment precedence, protected deletion, lock
  ordering, and non-sensitive monitoring events. The private-AP identity risk is
  unchanged.
- Cleanup removed all QA athlete assignments, overrides, and workouts; Rack 1
  was restored to the legacy simulated athlete and Back squat; simulation was
  restarted.
- Disposable PostgreSQL rollback validation migrated `0009 -> 0008 -> 0009`.
  The reverse removed both Slice 4 tables, cleared identity that relied only on
  an athlete assignment, preserved rack-backed identity, and retained one test
  Athlete, Session, Workout, legacy Program, and Set. Reapplying `0009` passed;
  rollback fixtures were then deleted.

## Slice 5: Training-day lifecycle and report

- **AC23:** A coach can start one training day; a concurrent second start returns
  a stable conflict.
- **AC24:** Ending is rejected while any set remains unfinished and identifies
  affected rack numbers without private payloads.
- **AC25:** Ending the day and creating its report occur in one transaction; a
  generation failure leaves the day active and retryable.
- **AC26:** The report snapshots timestamps, athletes, workout names and order,
  effective targets, completed persisted sets, and required rep measurements.
- **AC27:** Simulation and false-set data follow existing exclusion rules, and
  unsaved live reps are explicitly absent.
- **AC28:** Retrying an already successful end returns the existing report and
  cannot create a duplicate.
- **AC29:** Later template, assignment, athlete, or result edits cannot alter a
  finalized report, and no application mutation endpoint is provided.
- **AC29a:** Pi-safe ingestion limits allow at most 100 athletes, 500 persisted
  sets, and 5,000 persisted reps per training day. Anonymous set create and
  complete requests share a 120-per-minute client throttle.
- **AC29b:** Report generation rejects count overflow before set or rep
  materialization and rejects a serialized UTF-8 snapshot over 4 MiB. Rejection
  returns stable `report_too_large` dimensions and leaves the session, report,
  and rack identity unchanged.
- **AC29c:** Set creation rejects an athlete outside the locked Session roster
  with `athlete_not_in_session` and no write. Report preflight counts the union
  of roster athletes and athletes referenced by persisted sets.
- **AC29d:** Django admin allows Session browsing but cannot add, change, or
  delete Session rows; lifecycle mutations remain API-only.

Migration `0010` preflights existing sessions, enforces one active training day,
and adds immutable `DailyReport` rows. Rolling it back removes the PostgreSQL
immutability trigger and report table, then removes the partial active-session
index. Session, set, rep, athlete, workout, assignment, and legacy data remain.

### Slice 5 validation evidence

- Backend unit/integration/concurrency evidence: 138 tests passed; Django check,
  migration drift, and diff checks passed. Frontend: 39 tests and production
  build passed with the existing bundle-size warning.
- Disposable migration testing covers duplicate-active preflight with no partial
  schema, valid forward migration, reverse removal of the report table, trigger,
  and active-session index while preserving source rows, and reapply.
- Migration `0010` is applied. The simulator was stopped and 2,232
  simulation-owned sets plus the remaining reserved simulation data were cleared
  before exercising the one-active-day workflow.
- Live API: start returned 201; a concurrent second start returned 409; end with
  an unfinished unassigned set returned 409; completing two persisted reps then
  generated report 1; retry returned the same report. The snapshot retained the
  end-time workout prescription, completed set, both rep measurements, and
  explicit false/simulated/unsaved-live exclusions.
- Browser at 1366x768 started from the no-active-day controls, ended a second QA
  day, and opened the generated report immediately. The report showed the
  `Effective at day end` prescription and persisted-result section. The same
  report at 768x1024 had no horizontal overflow. Evidence:
  `/tmp/opencode/edge-coach-start-day.png`,
  `/tmp/opencode/edge-coach-generated-report.png`, and
  `/tmp/opencode/edge-coach-generated-report-portrait.png`.
- Security review passed authorization, no-store responses, immutable trigger,
  report/session protection, simulation exclusion, lock ordering, bounded
  ingestion, 4 MiB snapshot rollback, and bounded immediate rendering.
- Two clearly labeled replacement `[QA]` immutable demo reports remain
  intentionally saved; deleting them would violate the report immutability
  contract. The local rollback incident and recreation are documented above.

## Slice 6: Report browsing

- **AC30:** A coach can browse bounded daily reports newest first and open one
  report's prescribed-versus-completed detail.
- **AC31:** A coach can browse one athlete's reports grouped by local training
  day, including targets, sets, reps, weight, and available velocity measures.
- **AC32:** Missing optional measurements display as unavailable rather than
  zero; unknown report or athlete identifiers return 404.
- **AC33:** Report responses are coach-only, private, no-store, and omit notes,
  NFC IDs, device UUIDs, tokens, and raw MQTT bodies.

### Slice 6 backend contract

- `GET /api/reports/` and `GET /api/athletes/{athlete_id}/reports/` return newest
  first page-number results, 10 by default and at most 20 per page.
- `GET /api/reports/{report_id}/` returns one allowlisted schema-1 report.
  `GET /api/athletes/{athlete_id}/reports/{report_id}/` returns only that
  athlete's prescription, persisted sets, and rep measurements.
- Responses expose `summary`, `local_date`, and `timezone`. Missing measurements
  remain `null`; measured zeroes remain `0`. Unknown athlete/report combinations
  use the same `report_not_found` response, and unsupported schemas return 409
  `unsupported_report_schema`.
- Extraction copies explicitly allowed schema-1 fields and never returns the raw
  snapshot. All four routes are coach-only GET endpoints with
  `Cache-Control: private, no-store`.
- `DJANGO_TIME_ZONE` selects the IANA timezone for local-day grouping and defaults
  to `UTC`.

Migration `0011` adds a descending `(generated_at, id)` btree index and a GIN
index over `jsonb_path_query_array(snapshot, '$.athletes[*].athlete.id')`. The
athlete report query uses the same expression with a bound integer parameter.
Reversing `0011` removes only these indexes and preserves reports, sessions, and
the `0010` immutability trigger.

### Slice 6 backend validation evidence

- Clean isolated backend suite: 147 tests passed; Django system check, migration
  drift, and diff checks passed.
- API tests cover coach authorization, private no-store responses, newest-first
  pagination, generic 404s, schema 409s, allowlisted privacy, numeric ID matching,
  null versus zero, and timezone-local dates.
- Disposable migration testing applies, reverses, and reapplies `0011` while
  preserving source reports. A forced query plan uses
  `daily_report_athlete_ids_gin` for the parameterized athlete predicate.
- Frontend: 43 tests and production build passed with the existing bundle-size
  warning. Live APIs returned two reports newest-first, daily detail, two
  athlete-day entries, and generic 404 for a mismatched athlete/report pair.
- Browser evidence confirmed the two-report daily list, daily detail, athlete
  filtering, athlete-day detail, Back navigation, server-provided date, and no
  horizontal overflow at 1366x768 and 768x1024. Evidence:
  `/tmp/opencode/edge-reports-daily-list.png`,
  `/tmp/opencode/edge-reports-daily-detail.png`, and
  `/tmp/opencode/edge-reports-athlete-detail-portrait.png`.
- Security review passed active-staff authorization, no-store handling, generic
  nested-resource 404s, allowlisted extraction, bound JSON filtering, same-origin
  pagination, bounded rendering, and immutable GET-only behavior.

## Failure and security behavior

- Domain conflicts return stable `{code, detail}` bodies.
- Concurrent name creation is protected by database constraints and transactions.
- CSV cells are untrusted text and are never interpreted as formulas, HTML,
  commands, or paths. File bodies and athlete prescriptions are not logged.
- Rack reads expose only rack-safe identity and the selected athlete's effective
  targets on the private AP.
- Report generation does not depend on MQTT availability.
- Training-day write and report limits fail before persistence or roll back the
  full end-day transaction; overflow responses contain counts, not identities.
- Stored timestamps remain timezone-aware; configured local time determines day
  labels.

## Test plan

- Django tests cover authorization, ordering and numeric constraints, atomic
  manual creation, CSV encodings and malformed cases, preview with zero writes,
  import rollback, duplicate concurrency, assignment precedence, override
  inheritance, one-active-day enforcement, end/report rollback and idempotency,
  report immutability, privacy, pagination, write throttling, exact snapshot
  bytes, and athlete/set/rep boundary rejection.
- Frontend tests cover form normalization, CSV error display, preserved drafts,
  assignment resolution, missing measurements, and report day grouping.
- Each rendered coach and rack slice receives portrait and landscape browser
  evidence plus a production build.
- Assignment, upload, report, auth, privacy, and logging paths receive separate
  QA and security reviews.

## Demo

1. Manually create an ordered multi-exercise workout.
2. Preview an invalid CSV and show row-specific errors with no writes.
3. Import a corrected CSV and show the created workout catalog.
4. Group workouts into a program and assign it to a rack.
5. Select an athlete at the rack and show effective targets.
6. Add an athlete weight or rep override and show it without changing defaults.
7. Start a day, persist completed sets, and block ending on an unfinished set.
8. End the day, open the report, and show that later template edits do not alter it.
9. Browse the same report from the athlete's day-by-day history.

## Delivery order

Implement Slice 1 first. It delivers useful coach catalog management while the
assignment and immutable-report schema receive architecture review. Do not
repurpose or rename the current `Program` model in Slice 1.

## Migration rollback

Migration `0006_workout_and_workout_exercise` is mechanically reversible to
`0005` and does not alter legacy prescriptions, rack state, sessions, sets, or
reps. Reversing it drops all reusable workouts and workout exercises. Export the
catalog or restore a pre-rollback PostgreSQL backup if that data must be kept.
Migration `0005` remains intentionally irreversible for its own nullable legacy
prescription change.
