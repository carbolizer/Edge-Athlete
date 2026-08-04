# ADR: Scheduled Athlete Plans and Frozen Day Execution

## Status

Accepted and implemented locally through migrations `0014`-`0017` on 2026-07-23.

## Decision

Separate editable athlete schedules from immutable training-day execution. Shared
Workout and WorkoutProgram rows remain catalog sources. Schedule and day-plan
occurrences own ordering and targets so duplicate workouts and athlete-specific
changes never modify shared templates.

## Editable schedule aggregate

- `AthleteSchedule`: one durable row per athlete, with a positive monotonic version
  and active/tombstoned state used for atomic replacement and stale-editor rejection.
- `AthleteSchedulePlan`: an athlete-owned materialized plan optionally sourced
  from a shared WorkoutProgram.
- `AthleteSchedulePlanWorkout`: ordered workout occurrences. Duplicate source
  workouts are allowed.
- `AthleteSchedulePlanExercise`: ordered source exercises with concrete sets,
  reps, weight, and velocity targets for that occurrence.
- `AthleteScheduleEntry`: one exact date or weekday selector and either a plan or
  explicit rest state. Unique constraints prevent duplicate selectors.

Saving replaces the complete versioned aggregate in one transaction. Exact-date
entries resolve before weekday entries. If an athlete has no explicit entries,
the existing whole-program assignment remains an all-days fallback. Once any
explicit schedule exists, unmatched days are missing rather than fallback.
Deleting clears the aggregate, increments and returns its version, and tombstones
the durable row. Recreating must use that returned version, so an editor from before
the delete cannot pass an ABA check. Tombstoned schedules resolve through the legacy
all-days fallback.

## Frozen day plans

Start Day stores the configured local training date and materializes:

- `AthleteDayPlan`, unique by Session and athlete, with schedule source/version.
- Ordered `AthleteDayPlanWorkout` occurrences.
- Ordered `AthleteDayPlanExercise` target snapshots.

Frozen rows do not depend on editable schedule rows. Schedule edits after Start
Day affect only future days.

`AthleteDayProgress` gains frozen current workout/exercise bindings while legacy
bindings remain readable. Set gains frozen occurrence bindings. A progress or Set
uses exactly one complete binding mode: legacy schema 2, frozen schema 3, or
unbound simulator/legacy Set where already supported.

## Start Day

`GET /api/sessions/preview/` resolves date, weekday, rest, missing, and fallback
states and returns an opaque preview version. Real `POST /api/sessions/` accepts
the label and preview version, recomputes under locks, and rejects stale previews.
One transaction stores the roster/date, frozen plans, ready progress, rack
activation, and `session_started` revision. No athlete checkbox list is required.
Before full preview serialization or Start Day writes, Django sums prescribed sets
for all eligible explicit, fallback, and override occurrences. More than 500 returns
`scheduled_day_too_large` with count-only dimensions; Start Day recomputes this under
the training-day lock so rejection is atomic. After freezing, Start Day
compact-serializes a zero-result schema 3 baseline and rejects more than 2 MiB inside
the same transaction. The remaining report budget is protected by the 500-Set,
5,000-Rep, and 500-row Session rack-participation limits; End Day retains the final
4 MiB serialized-size guard.

## Identity and automatic set start

Manual confirmation and future bracelet input call one locked identity service.
For an eligible ready athlete, sign-in/movement, rack participation, server-derived
Set creation, progress `in_set`, and monitoring revision commit together.

- Same athlete plus open Set returns that Set idempotently.
- Completed athlete returns completion without a Set.
- Different athlete plus open Set returns `unfinished_set`; Save or Mark False is
  required first.
- Screen, node, schedule, progress, or Set failure rolls back the whole transition.

`PUT /api/racks/{rack}/athlete/` requires a positive active `session_id` and canonical
UUID `event_id`. Django validates the Session under lock before mutation and keeps
a durable `RackIdentityEvent` keyed by canonical RackScreen and event UUID, bound to
the session, athlete, rack, persisted outcome, and optional resulting Set. A replay
returns immutable event metadata and the serialized historical resulting Set even if
it later completed, but the top-level Set is always the current unfinished Set.
Mismatched reuse is a stable conflict. The global screen/event uniqueness remains;
the 256-row cap is per screen/session, and successful End Day retains rows without
charging them to a later session's cap.

The UUID is an idempotency key, not an authentication credential. It adds no
cryptographic pairing: RackScreen identity and open rack access retain the existing
private-AP trust model.

Identity never creates a legacy Set. The rack-bound set-start endpoint delegates to
the internal start operation for active legacy-session compatibility, and an existing
unfinished legacy Set remains authoritative. The rack UI labels this explicit Start
Expected Set path as compatibility behavior; schema 3 identity starts automatically.
PN532 transport remains deferred and may not create a second identity path.

## Reports and downloads

Frozen days produce immutable report schema 3 containing training date, schedule
source, complete frozen plan order/targets, frozen progress bindings, rack visits,
Sets, and Reps. Schema 1 and 2 extractors remain unchanged.

The coach UI presents day summary, athlete, schedule/program, workout, exercise,
qualifying/false Set, then optional Reps. Browser downloads validate a nonempty
PDF response, use the safe server filename, retain the object URL until a later
task, expose retry/throttle state, and retain existing auth/privacy/output bounds.

## Locks

Use training-day advisory lock for Start Day, End Day, and schedule replacement,
then sorted rack locks, screens, Session, Athletes, schedule hierarchy, frozen day
plans, progress, rack states, nodes, Sets, Reps, and monitoring event last.
This serializes schedule replacement with Start Day so one complete version wins.

## Migration and rollback

Migration `0014` is additive: create schedule/frozen tables, add
`Session.training_date`, add frozen progress/Set bindings, and replace binding
constraints. Backfill Session dates from configured local time. Do not infer
frozen plans for historical progress, Sets, or reports.

Reverse preserves Athlete, Session, Set, Rep, and DailyReport rows, nulls frozen
Set bindings, removes schema-3 progress that cannot satisfy legacy constraints,
and drops schedule/day-plan metadata. Export schedule metadata before reversal if
it must be retained. Old application binaries cannot operate an active schema-3
day; end it or restore matching application/database backup first.
Reverse preflight aborts before changing rows if an active schema-3 day, active
frozen progress, or unfinished frozen Set exists. Ended-day reversal emits an
old-reader warning and preserves schema-3 report/core rows.

Migration `0015` adds the active schedule tombstone. Delete clears child rows,
increments the version, and leaves the inactive aggregate so recreation must use
the post-delete version and stale pre-delete editors cannot pass an ABA check.

Migration `0016` additively creates the retained identity-event ledger. Its reverse
preflight blocks while an active schema-3 day, active frozen progress, or unfinished
frozen Set exists. Once safe, reversal drops only replay metadata, so outstanding
clients must start a new confirmed action; Athlete, Session, RackScreen, Set, and Rep
rows remain unchanged.

Migration `0017` additively creates protected ownership for the development-only
wristband seed and a conditional uniqueness constraint for its four reserved athlete
names. The seed never infers ownership from names, NFC values, or notes. Reverse
preflight blocks while the ownership row or any reserved athlete/NFC/catalog row
remains; confirmed demo cleanup is required before reversal.

Old application readers support neither frozen schedule bindings nor schema 3
report semantics. Do not roll the application back independently while schema 3
data is active; end the day or restore a matching application/database backup.

## Deferred

PN532 wiring, payloads, bracelet transport retries, and bracelet provisioning remain
blocked pending a hardware contract. HTTP identity action retries use the request
ledger above. Physical sensor ranges and Pi behavior retain their existing
verification requirements.
