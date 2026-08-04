# Fluid Coach Planning, Scheduling, and Reports

## Status

Code is implemented locally through migrations `0014`-`0017`. Automated validation
and the isolated full Start Day browser demo pass. This extends
`ATHLETE_DRIVEN_TRAINING.md`; see Validation evidence.

## Problem

Workout and program setup requires too much context switching. Athlete plans have
no weekday or date schedule and cannot differ from a shared program except for
exercise targets. Start Day requires rebuilding a roster manually. Rack identity
requires a second Start Set action. Report hierarchy is hard to scan and browser
PDF downloads are unreliable.

## User stories

- As a coach, I create workouts while building a program without losing my draft.
- As a coach, I schedule an athlete for recurring weekdays or an exact date.
- As a coach, I add, remove, reorder, and retarget workouts for one athlete without
  changing shared templates or other athletes.
- As a coach, I start the room once; today's schedules produce the roster and turn
  rack logging on.
- As an athlete, identity restores today's work and automatically starts my set.
- As a coach, I scan reports quickly and download daily or athlete PDFs reliably.
- As a demo operator without PN532 hardware, I seed reversible demo athletes and
  simulate a wristband tap through the normal rack identity flow without changing
  existing training Sets.

## Confirmed behavior and assumptions

- Dates and weekdays use the configured server timezone.
- Exact-date entries override recurring weekday entries for that date.
- A recurring weekday entry repeats every week until changed or removed.
- An exact date may be an explicit rest day, which excludes the athlete.
- Athlete schedule items are materialized from a shared program, then independently
  addable, removable, reorderable, and targetable. Shared templates remain unchanged.
- Shared workouts and programs are currently immutable after creation, so existing
  athlete schedules stay pinned until the coach explicitly replaces them.
- Start Day materializes one immutable execution plan per eligible athlete. Later
  schedule edits apply only to future days.
- Existing unscheduled whole-program assignments remain an all-days fallback until
  that athlete receives an explicit schedule.
- A different identity cannot replace an unfinished set. The rack requires Save Set
  or Mark False first.
- With no unfinished set, identity switches athletes. Frozen day plans automatically
  start the expected set; legacy sessions retain explicit Start Expected Set. Each
  confirmed identity action carries the active Session ID and one canonical UUID event ID;
  retries reuse it and return its durable result without starting a later set.
- Manual selection invokes the same transition as a future bracelet tap. PN532
  transport and firmware remain deferred.

## Non-goals

- Biweekly/monthly recurrence, date ranges, athlete-local timezones, or calendars.
- Silent merging of later shared-template edits into athlete schedules.
- Mid-day plan replacement or destructive abandonment of an unfinished set.
- PN532 wiring, payload parsing, retries, or bracelet provisioning.
- Public schedule or report access.

## Acceptance criteria

### Fluid planning

- **EXT-AC1:** A coach can create a required workout inline while building a
  program; the new workout is added to the existing program draft.
- **EXT-AC2:** Inline creation, workout selection, validation errors, and returning
  from a nested editor preserve all valid draft content.
- **EXT-AC3:** One workspace supports workout creation, program ordering, removal,
  and save without top-level navigation.
- **EXT-AC4:** Validation appears beside the affected workout, exercise, or program
  item and does not clear the draft.
- **EXT-AC5:** Leaving a dirty planning context requires discard confirmation.

### Scheduling and athlete customization

- **EXT-AC6:** A coach can assign one materialized athlete plan to one or more
  recurring weekdays.
- **EXT-AC7:** A coach can assign a plan or explicit rest state to an exact date.
- **EXT-AC8:** Exact-date plan/rest wins over the matching weekday entry; deleting
  it restores weekday resolution.
- **EXT-AC9:** Duplicate weekday/date entries for one athlete are rejected atomically.
- **EXT-AC10:** Schedule reads show local date/source and the complete effective
  workout/exercise order and targets.
- **EXT-AC11:** For one athlete schedule, the coach can add catalog workouts, remove
  included workouts, reorder them, and override exercise sets/reps/weight.
- **EXT-AC12:** Athlete-local changes never alter shared workouts/programs, another
  athlete schedule, an active day, or finalized reports.
- **EXT-AC13:** Schedule replacement is atomic and uses a version precondition to
  reject stale concurrent edits.

### Start Day

- **EXT-AC14:** Preview computes today's eligible roster from exact-date entries,
  weekday entries, and legacy all-days fallback in that priority order.
- **EXT-AC15:** The preview distinguishes date, weekday, fallback, rest, and missing
  schedule states without exposing private data publicly.
- **EXT-AC16:** A coach starts the computed roster with one action and no athlete
  checkbox selection.
- **EXT-AC17:** The Start Day transaction stores the local training date, freezes
  each athlete's ordered execution plan/targets, creates progress, activates every
  valid rack, enables logging, and publishes one room revision.
- **EXT-AC18:** Concurrent starts or schedule edits cannot create duplicate or mixed
  day plans.
- **EXT-AC18a:** Preview and Start Day reject an aggregate effective prescription
  above 500 sets with `scheduled_day_too_large` and count-only dimensions. Start
  Day recomputes under its lock, rejects a frozen schema 3 report baseline above
  2 MiB, and writes nothing on rejection.

### Identity and automatic start

- **EXT-AC19:** Identity resolves only the active day's frozen athlete plan.
- **EXT-AC20:** A ready athlete with no open set is signed in and has the expected
  set created automatically in the same transaction.
- **EXT-AC21:** Repeating the same identity with an open set is idempotent and returns
  that set without duplication.
- **EXT-AC22:** A completed athlete signs in to the completion view without a set.
- **EXT-AC23:** A different identity with an open set returns `unfinished_set` and
  leaves the current athlete/set unchanged; UI requires Save Set or Mark False.
- **EXT-AC24:** After Save or False, a different identity atomically switches and
  starts the new athlete's set.
- **EXT-AC25:** Node/screen/progress failure rolls back both identity and automatic
  set creation.
- **EXT-AC26:** Manual confirmation and future bracelet input call the same service.
- **EXT-AC26a:** `PUT /api/racks/{rack}/athlete/` requires a positive `session_id`
  matching the locked active Session and a canonical UUID `event_id`. Replaying the
  same screen/event returns immutable event metadata and its historical resulting
  Set, while the top-level `set` remains the current unfinished Set. Reusing the UUID
  with a different rack, athlete, or session returns `identity_event_conflict`.
- **EXT-AC26b:** A screen may retain at most 256 identity events per active session.
  End Day retains the ledger; ended-session rows do not consume a later session's cap.
- **EXT-AC26d:** A Session records at most 500 distinct athlete/rack participations so
  rack history cannot consume the report's reserved runtime budget.
- **EXT-AC26c:** Identity never creates a legacy Set. An existing unfinished legacy
  Set remains authoritative, and explicit Start Expected Set creates the next one.
- **EXT-AC26e:** In debug environments, `seed_demo_athletes --session-id <id>`
  idempotently adds four `[DEMO]` athletes and one complete fallback program to an
  active legacy Session. A protected `DemoAthleteSeed` row records the exact Session,
  catalog, and four athlete slots; reruns validate that graph without changing IDs or
  training rows. Confirmed cleanup removes only rows reachable through that ownership
  record and rejects unsafe references. End Day returns `demo_seed_cleanup_required`
  until cleanup succeeds.
- **EXT-AC26f:** When an unoccupied rack has eligible `[DEMO]` athletes, Simulate
  wristband tap chooses one random athlete whose rack-state row has
  `demo_wristband_eligible: true` and submits the normal session-bound identity request.
  Names and prefixes do not grant eligibility or create a second identity path.

### Reports

- **EXT-AC27:** Browser PDF downloads produce a nonempty `%PDF` file using the
  server filename in supported coach browsers.
- **EXT-AC28:** Download UI shows preparing, success, retryable error, and throttle
  timing; object URLs remain valid until the browser consumes them.
- **EXT-AC29:** Reports prioritize day summary, athlete, schedule source, program,
  workout, exercise, qualifying/false set, then optional rep detail.
- **EXT-AC30:** Prescribed versus completed values, missing values, measured zero,
  incomplete work, and false sets are visually distinct.
- **EXT-AC31:** New reports snapshot training date, schedule source, and the frozen
  athlete-local execution plan while schema 1/2 reports remain readable.
- **EXT-AC32:** Existing coach authorization, private no-store handling, safe
  filenames, PDF bounds/throttle, and immutable rendering remain enforced.

## Failure behavior

- `schedule_conflict`: duplicate date or weekday entry.
- `schedule_version_conflict`: stale coach update.
- `scheduled_plan_invalid`: empty or invalid materialized plan.
- `unknown_fields`: schedule input contains a field outside the documented shape.
- `athlete_not_scheduled_today`: identity is absent from the frozen day roster.
- `unfinished_set`: Save Set or Mark False is required before switching.
- `automatic_set_start_failed`: identity and start both roll back.
- `invalid_session_id`: identity `session_id` is not a positive integer.
- `identity_session_conflict`: identity `session_id` is not the locked active Session.
- `identity_event_conflict`: the screen/event UUID is bound to another request.
- `identity_event_limit`: the screen reached 256 identity actions for the day.
- `session_rack_participation_limit`: the Session reached 500 athlete/rack visits.
- `scheduled_day_too_large`: eligible plans prescribe more than 500 sets or their
  frozen report baseline exceeds 2 MiB.
- Existing rack screen/node, one-active-day, report, and PDF errors remain stable.

## Backend API

- `GET|PUT|DELETE /api/athletes/{athlete_id}/schedule/` is coach-only. `PUT`
  replaces the aggregate and accepts `expected_version`, `plans`, and `entries`;
  plan entries reference a request-local `client_id`. `DELETE` accepts
  `expected_version`.
  `DELETE` returns the next monotonic version. A later `GET` returns that inactive
  tombstone version, empty schedule rows, and the effective fallback resolution so
  recreation remains possible after a client restart.
- `GET /api/sessions/preview/` is coach-only and returns the configured local
  training date, each athlete's resolution state, and an opaque `preview_version`.
- Scheduled `POST /api/sessions/` accepts `label`, optional `notes`, and
  `preview_version`. The server recomputes the roster; client athlete IDs are not
  accepted for this path. The legacy `athletes` shape remains available without a
  preview version for simulation and existing clients.

Preview and scheduled Start Day aggregate prescribed sets across every eligible
explicit, fallback, and athlete-override occurrence before full response/frozen-plan
materialization. The maximum is 500; overflow responses expose only counts and limits.
Start Day also compact-serializes the frozen zero-result report inside its transaction
and reserves the remaining 2 MiB for the bounded 500 Sets, 5,000 Reps, and 500 rack
participations. End Day retains the authoritative 4 MiB serialized-size check.

Schedule input is bounded before catalog lookup or writes: at most 32 plans, 400
entries, 32 workouts per plan, 64 exercises per workout, and 1,024 exercises total.
Plan names are at most 255 characters and client IDs 64 characters. Exercise targets
allow 1-100 sets, 1-1,000 reps, and 0-10,000 lb. Exact dates must be literal
`YYYY-MM-DD`; unknown fields are rejected at every payload level.

## Implemented report UI

Schema 3 report detail presents day summary, athlete, schedule source/version and
frozen plan, workout, exercise, prescribed versus completed Set results, false-set
exclusions, and optional Rep detail in that order. Missing values and measured zero
remain distinct. The browser download helper checks for a successful nonempty
`%PDF` body, uses the safe server filename, clicks a temporary download link, and
waits one second before revoking the object URL. The UI reports preparation,
success, retryable failure, and server throttle timing.

## Security and privacy

- Schedule, customization, preview, reports, and PDF actions require active staff JWT.
- Public rack responses expose only the selected athlete's frozen execution state.
- NFC IDs, device UUIDs, schedule metadata for other athletes, notes, tokens, and
  report bodies never enter public responses or logs.
- Automatic set creation derives screen, rack, node, athlete, plan step, targets,
  and expected set server-side under existing locks.
- Event UUIDs provide request replay protection, not screen authentication or
  cryptographic pairing. Rack screen identity continues to rely on assignment and
  the documented private-AP trust boundary.

Independent security review passed for private-AP local testing on 2026-07-22.
It covered coach authorization, schedule input/concurrency, session-bound identity
replay, report/PDF privacy, resource limits, migration safety, dependencies, and
forbidden logging. Residual risk: rack UUIDs and anonymous plaintext HTTP/MQTT are
not cryptographic device authentication. Do not expose ports 8081, 1883, or 9001
beyond the generated-password private AP.

## Test plan

- Backend: date precedence, weekday recurrence, rest, fallback, atomic customization,
  stable order/targets, stale versions, frozen Start Day plans, and schema 3 reports.
- Concurrency: Start Day versus schedule update; identity switch/start; immediate
  duplicate, delayed replay after completion, mismatched reuse, and concurrent replay.
- Frontend: inline draft preservation, reorder/customization, roster preview, switch
  conflict, report hierarchy, tested download lifecycle, and deterministic demo-tap
  selection with injected randomness.
- Browser: desktop and tablet PDF download event/file, coach portrait/landscape,
  automatic rack start, Save/False switch flow, and report scanning.
- Hardware: deferred pending PN532 and ESP32 contracts.

### Acceptance evidence

| Criterion | Evidence |
|---|---|
| EXT-AC1 | `WorkoutCatalog.jsx` inline create appends to the current draft; `workoutCatalog.test.js` payload/identity tests. |
| EXT-AC2 | Draft state survives validation/catalog refresh; field-error and selection tests. |
| EXT-AC3 | One catalog workspace renders create, select, reorder, remove, and save; production build. |
| EXT-AC4 | `workoutCatalog.test.js` field-local path/client validation tests. |
| EXT-AC5 | Dirty source confirmation test plus unload/tab guards in `WorkoutCatalog.jsx` and `Dashboard.jsx`. |
| EXT-AC6 | `test_schedule_is_coach_only_materialized_versioned_and_atomic`. |
| EXT-AC7 | `test_exact_rest_overrides_weekday_and_stale_preview_is_rejected`. |
| EXT-AC8 | `test_exact_plan_precedence_and_removal_restore_weekday_effective_plan`. |
| EXT-AC9 | Atomic schedule/version test and frontend duplicate-selector test. |
| EXT-AC10 | `test_schedule_read_materializes_existing_fallback_for_editing` and preview integration. |
| EXT-AC11 | Frontend duplicate-occurrence/reorder/target payload tests. |
| EXT-AC12 | `test_schedule_edit_after_start_does_not_change_frozen_plan`. |
| EXT-AC13 | Atomic version test and `test_start_and_schedule_replacement_serialize_without_mixed_frozen_plan`. |
| EXT-AC14 | Preview integration plus exact-date/rest precedence tests. |
| EXT-AC15 | Coach-only schedule test and preview source/state assertions. |
| EXT-AC16 | Scheduled payload test and `test_preview_start_identity_progression_and_schema_three_report`. |
| EXT-AC17 | Preview/start/schema-3 integration test. |
| EXT-AC18 | Start/replacement and concurrent-session-start tests. |
| EXT-AC18a | Mixed 500/501 tests and `test_start_rejects_oversized_report_baseline_without_writes`. |
| EXT-AC19 | Frozen preview/start/identity integration and legacy explicit regression. |
| EXT-AC20 | Preview/start/identity integration asserts automatic bound Set creation. |
| EXT-AC21 | Immediate/delayed replay test and concurrent same-event test. |
| EXT-AC22 | `test_completed_frozen_identity_returns_no_set`. |
| EXT-AC23 | `test_unfinished_set_blocks_different_identity_then_completion_allows_atomic_switch`. |
| EXT-AC24 | Same switch test plus false-set completion regressions. |
| EXT-AC25 | Identity screen/node/progress rollback tests. |
| EXT-AC26 | Shared `start_expected_set` service and legacy explicit-start test; hardware deferred. |
| EXT-AC26a | Session validation, replay/current Set, mismatch, privacy, and concurrency tests. |
| EXT-AC26b | `test_identity_event_ledger_is_capped_retained_and_scoped_per_session`. |
| EXT-AC26c | `test_legacy_progress_identity_requires_explicit_set_start`. |
| EXT-AC26d | `test_identity_rejects_new_participation_after_session_report_bound`. |
| EXT-AC26e | `DemoAthleteCommandTests` creation, idempotency, collision, roster-limit, cleanup, privacy, and Set-immutability tests. |
| EXT-AC26f | `rackState.test.js` exact-prefix/random selection tests and rack browser evidence. |
| EXT-AC27 | Backend `%PDF` tests and `/tmp/opencode/fluid-downloads/report-4.pdf`. |
| EXT-AC28 | `reportBrowsing.test.js` PDF lifecycle, retry, terminal, and throttle tests. |
| EXT-AC29 | Schema-3 report hierarchy tests and report workspace build. |
| EXT-AC30 | Zero/missing, false-Set, and prescribed/completed report tests. |
| EXT-AC31 | Schema-3 integration and schema-1/2 report regressions. |
| EXT-AC32 | Report auth/no-store, immutable trigger, safe PDF, throttle, and bounds tests. |

## Validation evidence

### Automated

| Check | Result |
|---|---|
| `docker compose run --rm --no-deps django python manage.py test event_handler --noinput` | Pass: 229 backend tests. |
| `npm test -- --run` from `react/` | Pass: 77 frontend tests. |
| `npm run build` from `react/` | Pass: production build completed. |
| `docker compose build django mqtt-listener monitoring-publisher simulator react` | Pass: all application images built. |
| `python manage.py check` | Pass: no Django system-check issues. |
| `python manage.py makemigrations --check --dry-run` | Pass: no migration drift. |
| `git diff --check` | Pass: no whitespace errors. |
| `git diff --no-index --check /dev/null <untracked-file>` for all new spec, command, migration, and service files | Pass: no whitespace errors. |
| `docker compose config --quiet` | Pass: Compose configuration is valid. |

### Browser

| Check | Result |
|---|---|
| Chrome daily-report download | Pass: Chrome downloaded `report-4.pdf`; the file is a valid one-page PDF 1.4 document. |
| Schedule editor at 1366x768 | Pass: screenshot captured with no horizontal overflow. |
| Schedule editor at 768x1024 | Pass: screenshot captured with no horizontal overflow. |
| Isolated scheduled Start Day | Pass: two weekday-scheduled athletes froze into schema 3 execution plans. |
| Rack identity and switching | Pass: Athlete A auto-started; Athlete B was blocked by `unfinished_set`; Mark False allowed B to auto-start; saved completion allowed A to resume and finish. |
| Schema 3 End Day/report | Pass: report 1 contained two athletes, two qualifying Sets, one false Set, weekday/version context, frozen targets, and retained rack visits. |
| Live report-list refresh | Pass: a second End Day appeared first in Reports without page reload. |
| Filtered report refresh | Pass: Athlete A remained selected after End Day; the new one-athlete result appeared and a C-only historical report remained excluded. |
| Schema 3 rack portrait | Pass: automatic start and blocked switching remained readable at 768x1024 with 768px document width. |
| Schema 3 PDFs | Pass: daily PDF is PDF 1.4/two pages; athlete PDF is PDF 1.4/one page. |
| Demo wristband tap | Pass: live Rack 2 showed the control and selected state at 768x1024 and 1024x768 with no horizontal overflow; taps selected `[DEMO] Avery` then `[DEMO] Morgan` through the normal identity route, created legacy progress without a Set, and returned to the unoccupied tap screen after sign-out. |

Artifacts: `/tmp/opencode/fluid-schedule-editor-1366.png`,
`/tmp/opencode/fluid-schedule-editor-portrait.png`,
`/tmp/opencode/fluid-legacy-rack-portrait.png`,
`/tmp/opencode/fluid-coach-reports-final-1366.png`, and
`/tmp/opencode/fluid-downloads/report-4.pdf`. Isolated schema 3 artifacts:
`/tmp/opencode/fluid-isolated-start-day-1366.png`,
`/tmp/opencode/fluid-isolated-auto-start-1366.png`,
`/tmp/opencode/fluid-isolated-switch-blocked-1366.png`,
`/tmp/opencode/fluid-isolated-false-switch-1366.png`,
`/tmp/opencode/fluid-isolated-schema3-report-1366.png`,
`/tmp/opencode/fluid-isolated-schema3-report-portrait.png`,
`/tmp/opencode/fluid-isolated-report-workspace-1366.png`,
`/tmp/opencode/fluid-isolated-athlete-report-1366.png`,
`/tmp/opencode/fluid-isolated-reports-live-refresh-1366.png`,
`/tmp/opencode/fluid-isolated-filtered-report-refresh-1366.png`,
`/tmp/opencode/fluid-isolated-schema3-rack-auto-portrait.png`,
`/tmp/opencode/fluid-isolated-schema3-rack-blocked-portrait.png`,
`/tmp/opencode/fluid-isolated-downloads/report-1.pdf`, and
`/tmp/opencode/fluid-isolated-downloads/athlete-1-report-1.pdf`. Demo wristband
artifacts: `/tmp/opencode/demo-wristband-button-portrait.png` and
`/tmp/opencode/demo-wristband-selected-portrait.png`, plus
`/tmp/opencode/demo-wristband-button-landscape.png` and
`/tmp/opencode/demo-wristband-selected-landscape.png`.

### Migration rollback

Disposable database `edgeathlete_fluid_rollback_final_20260722` completed
`0013 -> 0016 -> 0013 -> 0016`. The legacy active Session, Set, Rep, assignment,
and schema 2 report survived; reversing with active schema 3 state failed before any
migration changed. The disposable database was dropped and confirmed absent.

The drill used `createdb`, `manage.py migrate event_handler 0016`, a
`manage.py shell -c` seed named `FLUID_ROLLBACK_SENTINEL`, `manage.py migrate
event_handler 0013`, direct count assertions through `psql`, reapplication to `0016`,
and current-model assertions. It then seeded active frozen plan/progress, confirmed
that reversing to `0013` raised the `0016` preflight `RuntimeError`, verified both the
`django_migrations` row and identity-event table remained, ran `dropdb`, and confirmed
the database name was absent from `pg_database`.

### Isolated live validation

A standalone stack at `127.0.0.1:18081` used a separate PostgreSQL container and
database. The browser completed the seven-step demo below twice. The second pass
verified that stale Save/False messages clear across athlete switches and that the
mounted Reports workspace refreshes immediately after End Day. Database assertions
confirmed ended schema 3 Session 1, two athletes, three Set rows including one false
Set, and three retained identity events. The normal stack remained running, and its
active legacy Session 8 was not ended or modified.

A final isolated pass kept Reports mounted with Athlete A selected while a C-only
historical report existed. End Day preserved the Athlete A filter, displayed the new
athlete-scoped result, and excluded the C-only report. Schema 3 rack automatic-start
and `unfinished_set` states were also captured at 768x1024 without horizontal overflow.

### Live demo wristband validation

Before applying migration `0017`, `pg_dump` created
`/tmp/opencode/edgeathlete-pre-demo-session8-20260723.dump`. Session 8 was active,
real, legacy, and had one athlete plus no reserved collisions. The database's 11 Set
rows hashed to `f7d6f7a195805062da9866f8dbb4852b` before migration, after seeding,
and after one simulated tap/sign-out; Session 8 owns 2 of them. The seed added four
durable ownership-bound athletes without creating progress or Sets. Pressing the
Rack 2 button selected `[DEMO] Avery`, created
one legacy progress row and one identity event, and required Start Expected Set. The
browser then signed Avery out, leaving Rack 2 ready for another random tap.

Reproducible backup and Set-integrity commands:

```bash
docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > /tmp/opencode/edgeathlete-pre-demo-session8-20260723.dump

sha256sum /tmp/opencode/edgeathlete-pre-demo-session8-20260723.dump
pg_restore --list /tmp/opencode/edgeathlete-pre-demo-session8-20260723.dump >/dev/null

docker compose exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  "SELECT count(*), md5(COALESCE(jsonb_agg(to_jsonb(s) ORDER BY s.id)::text, '\''[]'\''))
   FROM event_handler_set s;"'
```

The dump is 176398 bytes with SHA-256
`967efbbbc1543985295750f3827ada84c15c6fddefdbe91080704ff32a0f3254`;
`pg_restore --list` parsed it successfully. The Set query returned
`11|f7d6f7a195805062da9866f8dbb4852b`.

Later live training added one unrelated non-demo Set, bringing the current database
total to 12. The original 11 rows through Set ID 2243 still produce the baseline hash
above; demo athletes own zero Sets. The backup predates the later non-demo Set.

Disposable database `edgeathlete_demo_seed_validation_20260723` verified operational
idempotency and cleanup. Two seed commands retained ownership IDs
`wristband-v1|1|1|2|3|4|5`; the unrelated Set remained
`1|e87e140ce91b58383eec366b270d91ae`. Confirmed cleanup ran with `DEBUG=False`
through a temporary database-scoped login, preserved the unrelated Session, athlete,
and Set, removed the ownership graph, and returned the same Set hash. The disposable
database and temporary login were dropped.

## Demo

1. Create a workout inline while building a program and save the draft.
2. Schedule it for a weekday and add an exact-date replacement.
3. Add/reorder a workout and change targets for only that athlete/date.
4. Start today's computed roster with one action.
5. Identify Athlete A and show automatic set start.
6. Attempt Athlete B, receive Save/False requirement, close the set, then switch and
   auto-start Athlete B.
7. End Day, inspect the schedule-aware report, and download daily/athlete PDFs.
