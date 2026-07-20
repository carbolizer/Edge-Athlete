# ADR: Athlete-Owned Training State

## Status

Accepted and implemented through migrations `0012` and `0013` on 2026-07-16.

## Decision

Use durable athlete/day progress and stable catalog identities for execution.
Racks hold only the athlete currently using them. They do not own workout
assignments or progression.

## Data model

- `AthleteWorkoutProgramAssignment` stores one complete `WorkoutProgram` per
  athlete. Keep `AthleteWorkoutAssignment` temporarily for legacy data;
  normal athlete-driven execution ignores it.
- `AthleteDayProgress` is unique by Session and athlete. It stores the assigned
  program, current program item, current workout exercise, expected set number,
  and `ready`, `in_set`, or `complete` state.
- Bind athlete-driven Set rows to progress, program item, and workout exercise.
  Keep the text exercise snapshot for legacy analytics and readable rollback.
- `AthleteRackParticipation` is unique by Session, athlete, and rack, with
  first/last-seen timestamps. Successful sign-in and movement create the row in
  the identity transaction; sign-out does not remove participation history.
- Permit only one unfinished bound Set per progress row and one rack sign-in per
  athlete. Migration preflights conflicts rather than choosing winners.
- Do not infer stable identities from historical exercise names.

## State machine

- First sign-in in a day creates `ready` progress at the first program item,
  first exercise, set 1.
- Starting a server-derived set changes `ready` to `in_set`.
- Completing a false set returns to `ready` at the same expected set.
- Completing a qualifying set advances the set number, next exercise, next
  workout, or final `complete` state in that order.
- Sign-out, refresh, reconnect, and rack movement do not mutate progress.
- A later day creates new progress at the program start.

## Transactions and locks

Use existing PostgreSQL transactions, advisory rack locks, row locks, and the
monitoring outbox. Lock sorted rack numbers before Session, athlete, assignment,
progress, rack state, Set, and Rep rows. Sign-in locks both old and destination
racks and retries if observed ownership changes. Set completion and progression
commit or roll back together.

## Interfaces

- Athlete assignment `PUT` accepts `workout_program_id`, not a selected item.
- Rack state returns the signed-in athlete's current program, workout, exercise,
  expected set, effective targets, and persisted sets.
- `POST /api/racks/{rack}/sets/` accepts only the canonical screen UUID as
  `device_id` and derives athlete, Session, exercise, set number, node, and weight
  server-side. Client movement text cannot select progress.
- Rack-bound completion carries the canonical screen UUID in
  `X-Rack-Device-Id` and revalidates the sole assigned screen, set, session,
  athlete, progress, and rack state under the existing rack lock.
- Generic set creation is limited to simulator-owned sessions. This keeps
  anonymous legacy writes from consuming limits or blocking a real schema 2 day.
- Start Day writes `MonitoringEvent(reason="session_started")` in its transaction.
- A future wristband endpoint must call the existing identity service; no second
  progression path is allowed.
- Public rack routes may return generic `rack_screen_conflict` without screen IDs
  or registration counts. Detailed rack registration diagnosis is coach-only.
- Global athlete records, assignments, overrides, notes, analytics, reports, and
  PDFs require an active staff JWT. Bounded rack identity remains a private-AP
  selection flow rather than athlete authentication.

## Wall

Choose the stable velocity-targeted workout exercise used by the most signed-in
athletes. Break ties by normalized exercise name and exercise ID. Rank each
athlete's best completed non-false Set for that same exercise in the active day.
No eligible movement returns a waiting state and empty leaderboard.

## Reports and PDF

New days use immutable report schema 2 with full assigned program order, stable
exercise identities, effective targets, final progress, rack participation, and
persisted results. Rack participation comes only from durable participation rows,
not final rack state or qualifying sets. Completed false sets remain as explicitly
flagged schema 2 results with stable bindings, while summaries and completion
metrics exclude them. Schema 1 remains readable through versioned extractors.

Generate bounded PDFs from immutable snapshots with pinned ReportLab and built-in
fonts. Daily and athlete-day endpoints require coach JWT access, return private
no-store responses, use ID-only filenames, and never mutate reports.

## Migration and rollback

Migrations `0012` and `0013` are additive. Reversing `0013` removes durable rack
participation metadata but preserves athletes, Sessions, Sets, Reps, progress,
assignments, and immutable reports. Reversing `0012` then removes athlete-driven
assignment/progress metadata and Set bindings while preserving legacy training
rows. Production rollback requires exporting the removed metadata or restoring a
backup. Validation must use an explicitly verified disposable PostgreSQL database
with `docker compose run -e POSTGRES_DB`.

## Compatibility

`AthleteWorkoutAssignment`, legacy `Program`, rack catalog assignment, coach rack
movement selection, and generic simulator set routes remain available for old
data or simulation. Normal athlete-driven training uses complete
`WorkoutProgram` assignment, server-owned progress, and rack-bound set routes.

## Deferred

PN532 wiring, ESP32 firmware, wristband payloads, retries, and offline reader
behavior remain blocked until the exact hardware contract is available. Manual
selection and confirmation remain the supported identity mechanism.
