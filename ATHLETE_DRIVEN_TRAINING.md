# Athlete-Driven Training

## Status

Approved behavior on 2026-07-16. This specification supersedes rack-owned
catalog assignment and manual workout-item selection in
`COACH_WORKOUT_PLANNING.md`.

## Problem

Normal operation requires too much coach interaction. A coach should configure
programs and athlete assignments before training, start one room-wide day, then
observe. Athlete identity and progress must follow the athlete between racks.
The wall must choose a comparable VBT movement automatically, and finalized
reports must be downloadable.

## User stories

- As a coach, I assign one ordered program to an athlete and do not assign work
  to individual racks.
- As an athlete, I identify at any rack and resume my current workout, exercise,
  set, targets, and results.
- As a spectator, I see the VBT movement with the most current participants and
  one room-wide leaderboard for that movement.
- As a coach, I download immutable whole-day and athlete-day reports as PDFs.

## Assumptions

- One athlete has at most one assigned ordered workout program.
- Start Day retains an explicit athlete roster and activates every uniquely
  registered rack for sign-in.
- A persisted, completed, non-false set counts toward progression even when its
  rep count differs from the target. The variance remains visible in reports.
- Progress is scoped to athlete, active day, assigned program, workout, and
  exercise. It is never owned by a rack.
- Completing the prescribed sets advances immediately to the next exercise and
  then the next workout during the same day.
- Completing the final workout produces a stable completed state. A later day
  starts the assigned program from its first workout.
- Only one rack may hold an athlete's sign-in. Moving is blocked by an unfinished
  set and otherwise clears the old rack atomically.
- The wall uses signed-in athlete progress to choose a movement and persisted
  completed sets to rank athletes. Memory-only MQTT reps remain non-authoritative.
- PN532 wiring, wristband payloads, and firmware behavior are unverified. Manual
  name selection and confirmation remain the supported identity fallback. A
  future wristband endpoint must invoke the same server-side identity transition.

## Non-goals

- Inventing PN532 wiring, firmware payloads, pairing, or retry behavior.
- Assigning workouts or programs to racks during normal training.
- Mid-day program editing, reordering, reassignment, reset, or automatic wrap.
- Persisting each live MQTT rep before set completion.
- Comparing athletes across unlike movements.
- Public report or PDF access.
- Replacing the legacy `Program` API in this slice.

## Acceptance criteria

### Setup and activation

- **AC34:** A staff coach can assign one complete ordered `WorkoutProgram` to an
  athlete without selecting a program item or rack.
- **AC35:** Assignment reads return the complete ordered program and effective
  athlete targets.
- **AC36:** Start Day creates one active day and makes every uniquely registered
  rack available for athlete sign-in without a rack workout assignment.
- **AC37:** Start Day publishes a room revision so already-open wall, coach, and
  rack clients enter active-day state without a separate action.
- **AC38:** Invalid or duplicate rack registrations remain unavailable. A public
  rack may receive generic `rack_screen_conflict` without screen IDs or counts;
  detailed registration diagnosis is available only in the authenticated coach
  view.

### Identity and mobility

- **AC39:** A roster athlete with an assigned program can identify at any active
  rack through bounded manual selection and explicit confirmation.
- **AC40:** Rack identity responses omit NFC IDs, notes, tokens, device UUIDs,
  and coach-only fields.
- **AC41:** Sign-in resolves server-owned athlete progress; the rack never creates
  or resets progress.
- **AC42:** Signing into another rack atomically clears the previous sign-in and
  restores the same workout, exercise, set, targets, and persisted results.
- **AC43:** Move or sign-out is rejected while the athlete has an unfinished set.
- **AC44:** Concurrent sign-ins cannot leave one athlete active on two racks.
- **AC45:** Refresh, reconnect, restart, sign-out, and rack changes preserve
  persisted progress.

### Rack execution and progression

- **AC46:** A signed-in rack shows athlete and program, current workout and
  position, current exercise and position, expected set and prescribed set
  count, reps, weight, optional velocity range, and persisted completion data.
- **AC47:** Unsaved live reps are visually distinct from persisted completed sets.
- **AC48:** Set creation accepts only the active day, signed-in athlete, current
  stable workout exercise, expected set number, and matching registered rack.
  Client exercise text cannot choose or advance progress.
- **AC48a:** Athlete-driven set creation uses
  `POST /api/racks/{rack}/sets/` with only the canonical rack screen UUID as
  `device_id`; Django derives the athlete, Session, exercise, set number, node,
  and load.
- **AC49:** Set completion and athlete progress update in one transaction.
- **AC49a:** Athlete-driven completion uses
  `POST /api/racks/{rack}/sets/{set_id}/complete/` with the canonical rack screen
  UUID in `X-Rack-Device-Id`. The transaction locks the rack and rejects a
  missing, moved, mismatched, or duplicate screen without saving reps or
  advancing progress.
- **AC49b:** Generic `POST /api/sets/` cannot create sets in a real active day.
  Simulator-owned active sessions retain the legacy endpoint.
- **AC50:** The prescribed number of persisted non-false sets advances to the next
  exercise, then immediately to the next ordered workout.
- **AC51:** Duplicate or concurrent completion cannot skip progress.
- **AC52:** Under-target or over-target reps and out-of-zone velocity remain
  visible but do not block set-count progression.
- **AC53:** False or unfinished sets do not advance progress.
- **AC54:** Completing the final exercise marks the athlete complete without
  wrapping or creating another expected set.
- **AC55:** Re-identification during the same day restores the completed state;
  the next day starts at the first workout.

### Automatic wall and coach observation

- **AC56:** The wall selects the current velocity-targeted exercise used by the
  largest number of signed-in athletes across registered racks.
- **AC57:** Participation counts each signed-in athlete once, including time
  between sets.
- **AC58:** A tie uses normalized exercise name ascending, then stable workout
  exercise ID ascending.
- **AC59:** No signed-in VBT exercise produces a waiting state and empty
  leaderboard rather than retaining stale data.
- **AC60:** The leaderboard uses qualifying persisted completed non-false sets for
  the selected stable exercise identity from all racks in the active day.
- **AC61:** Each athlete ranks by best set average velocity descending, then name
  case-insensitively and athlete ID; public output omits athlete IDs.
- **AC62:** Movement changes recompute the leaderboard and exclude other
  movements.
- **AC63:** The coach room view observes sign-in, movement, expected set,
  progression, completion, results, and hardware conflicts without routine rack
  workout controls.

### Reports and PDF

- **AC64:** End Day remains blocked by unfinished sets and atomically creates an
  immutable report.
- **AC65:** The report snapshots assigned program order, effective targets,
  progression/completion, durable rack participation, and persisted sets/reps.
- **AC65a:** Successful sign-in and rack movement durably record each unique
  Session, athlete, and rack transition, so sign-out without a set, false-only
  visits, and multiple rack visits remain in schema 2 reports.
- **AC65b:** Schema 2 retains completed false-set records with stable progress,
  program-item, and exercise bindings and labels them as excluded. Summary,
  leaderboard, progression, and completion counts continue to use only
  qualifying non-false sets. Schema 1 remains readable without reinterpretation.
- **AC66:** A coach can download a whole-day report PDF and one athlete's section
  of one day as a PDF.
- **AC67:** PDFs render only from the immutable report snapshot and preserve null
  versus measured zero.
- **AC68:** PDF endpoints require active staff JWT, return private no-store
  responses and safe filenames, and omit notes, NFC IDs, UUIDs, tokens, and MQTT
  payloads.
- **AC69:** Unsupported schemas, bounded-output overflow, or rendering failure
  returns a stable error without changing the report.

### Migration and rollback

- Migration `0013` additively creates durable rack participation after applied
  migration `0012`; it does not infer visits from current rack state or Sets.
- Reversing `0013` preserves athletes, Sessions, Sets, Reps, athlete progress,
  assignments, and immutable reports, but intentionally loses participation
  timestamps and rack-visit metadata. Reapplying it starts with an empty table.

## Failure behavior

- Domain failures use stable `{code, detail}` bodies.
- Ineligible identity returns `athlete_not_in_active_session` or
  `athlete_program_required` without changing rack state.
- Set mismatch returns `unexpected_workout_step` with the current expected state
  and performs no write.
- Sign-in conflicts return `unfinished_set` or `athlete_sign_in_conflict` without
  partial movement.
- Progress and set completion both commit or both roll back.
- Wall failures show an unavailable state rather than stale movement data.
- PDF failure leaves the immutable JSON report browsable.

## Security and privacy

- Coach setup, reports, and PDFs require active staff JWT access.
- Rack identity is identity selection on the generated-password private AP, not
  authentication. Wristband identity will retain this trust boundary unless a
  separate pairing design is approved.
- Athlete lists and rack responses remain bounded and omit private fields.
- Set writes bind to server-resolved stable identities and must not trust
  client-supplied movement names or progress positions.
- Rack state exposes an unfinished athlete-driven set ID only when
  `X-Rack-Device-Id` identifies the sole screen assigned to that rack.
- Global athlete records, assignments, overrides, notes, analytics, reports, and
  PDFs require active staff JWT access. The public rack receives only the bounded
  active-day identity list needed for manual confirmation.
- Logs must not contain NFC IDs, device UUIDs, report bodies, tokens, or notes.

## Test plan

- Backend: whole-program assignment, start notification, eligible sign-in,
  exclusive rack movement, stable exercise identity, ordered advancement,
  duplicate completion, false and under-target sets, completion, and next-day
  reset.
- Concurrency: simultaneous sign-ins, completions, moves, and End Day.
- Wall: participation counts, VBT filtering, deterministic ties, empty state,
  all-rack aggregation, movement-specific ranking, privacy, and bounds.
- Reports: progress and durable no-set/false-only/multi-rack participation,
  false-set bindings and count exclusions, immutable daily and athlete PDFs,
  authorization, safe filenames, schemas, and size failures.
- Frontend: restored rack progress, current target/set display, completion state,
  coach observation, wall movement states, and PDF actions.
- Manual: two-rack movement, immediate multi-workout progression, wall
  landscape/portrait, coach tablet, rack tablet, and PDF inspection.
- Hardware: deferred until the PN532/board/payload contract exists.

## Validation evidence

### Automated

| Acceptance criteria | Command | Result | Evidence |
|---|---|---|---|
| AC34-AC69 | `docker compose run --rm --no-deps django python manage.py test event_handler --noinput` | Pass | 181 tests passed, zero skipped; clean test database created and destroyed. |
| AC34-AC69 | `npm test -- --run` from `react/` | Pass | 55 tests passed across 8 files. |
| Frontend | `npm run build` from `react/` | Pass | Production build completed; existing 668.47 kB chunk warning remains. |
| Django/schema | `python manage.py check`; `makemigrations --check --dry-run` in Docker | Pass | No issues and no migration drift. |
| Deployment | `docker compose up -d --build --remove-orphans`; `nginx -t` | Pass | Images built, migrations through `0013` applied, services running, Nginx configuration valid. |
| Source | `git diff --check`; `docker compose config --quiet` | Pass | No whitespace errors; Compose configuration valid. |
| Nginx DNS | Forced Django recreation without restarting Nginx | Pass | `/api/wall-state/` returned 200 before and after; `/rack` and `/coach` returned 200. |
| Migrations | Explicit disposable PostgreSQL `0011 -> 0013 -> 0011 -> 0013` | Pass | Legacy athlete 1, Sessions 2, Sets 2, Rep 1, report 1, and program 1 survived. Assignment, progress, participation, and Set bindings were removed on reverse and recreated empty. Disposable database was dropped and lookup returned 0. |

### Manual

| Acceptance criteria | Environment and steps | Result | Evidence |
|---|---|---|---|
| AC34-AC37 | Live coach API assigned one two-workout program; active day and two registered racks used | Pass | Assignment returned both ordered workouts; wall and rack clients reconciled through monitoring revisions. |
| AC39-AC55 | Sign in at Rack 1, persist three sets, move to Rack 2, persist final set | Pass | Rack 1 restored workout 1/set 1. Sets saved at 0.61, 0.62, and 0.63 m/s, then immediately advanced to workout 2. Rack 2 restored workout 2/set 1; 0.65 m/s completion produced stable `complete` progress. |
| AC56-AC63 | Observe wall and coach throughout the two-rack flow | Pass | Wall selected `QA Back squat`, switched to `test` after the rack move, then cleared to waiting after completion. Coach showed signed-in rack, program, workout, movement, expected set, and hardware state. |
| AC64-AC69 | End Day, inspect schema-2 JSON, download daily and athlete PDFs | Pass | Report 3 recorded final `complete`, rack participation `[1, 2]`, four Sets/Reps, and 0.6275 m/s average. Both downloads are PDF 1.4, one page, with ID-only filenames, private no-store, and nosniff. |
| Responsive UI | Chrome at 1366x768 and 768x1024 | Pass | No horizontal overflow. Evidence: `/tmp/opencode/athlete-driven-wall-active-1366.png`, `/tmp/opencode/athlete-driven-coach-active-1366.png`, `/tmp/opencode/athlete-driven-rack-active-portrait.png`, `/tmp/opencode/athlete-driven-wall-workout2-1366.png`, `/tmp/opencode/athlete-driven-rack-workout2-portrait.png`, `/tmp/opencode/athlete-driven-rack-complete-portrait.png`. |
| PDF files | Local downloaded artifacts | Pass | `/tmp/opencode/athlete-driven-daily-3.pdf` and `/tmp/opencode/athlete-driven-athlete-5-report-3.pdf`; both parsed as one-page PDF 1.4 documents. |

### Unverified

| Acceptance criteria | Reason | Required follow-up |
|---|---|---|
| Wristband identity | PN532 board, wiring, payload, and firmware contract remain undefined. | Confirm hardware and message contract, then call the existing server-side identity transition. |
| Physical sensor timing/ranges | No physical ESP32/Pi hardware was available. | Compile/flash the confirmed board and validate payload timing, velocity range, duration, and clock skew. |
| Physical Raspberry Pi PDF/build behavior | ARM64 dependencies resolved, but no physical Pi was available. | Build and inspect PDFs on the target Pi under representative report load. |

## Demo

1. Create two ordered workouts and one program, then assign it to two athletes.
2. Start one day and show every registered rack and the wall activate without
   rack workout assignment.
3. Identify an athlete at Rack 1 and show current workout, exercise, expected set,
   targets, and persisted work.
4. Complete prescribed sets and show immediate exercise/workout advancement.
5. Identify the athlete at Rack 2 and show the same progress.
6. Sign athletes into different VBT movements and show deterministic wall
   selection and all-rack aggregation.
7. Complete the final workout, end the day, and download daily and athlete PDFs.
