# Sponsor Rack Workflow: First Slice

- Date: 2026-07-15
- Status: Implemented; physical sensor verification pending

## User story

As an athlete, I want a minimal rack display showing my complete prescribed
workout, current movement, live rep count, and velocity target result so I can
lift without relying on a whiteboard. As a coach, I want to select the athlete
and movement for a rack and see the same selection beside its latest saved set.

## Assumptions

- The coach selects both athlete and movement from existing `Program` rows.
- The newest unended session is active; the selected athlete must belong to it.
- Selection belongs to a rack number and survives screen or sensor replacement.
- Both null velocity bounds identify a non-velocity exercise. Partial ranges are invalid.
- Live rack MQTT reps are unsaved feedback in this slice and reset manually.
- Set start/completion, Excel import, corrections, NFC, and automatic movement detection are later slices.

## Acceptance criteria

- [x] AC1: A coach can select one active-session athlete and one of that athlete's programs for a known rack; anonymous and non-coach mutations are rejected.
- [x] AC2: Selection changes are atomic, create a `rack_selection_changed` monitoring event, and return HTTP 409 while the rack has an unfinished set.
- [x] AC3: The open rack-state response exposes only rack number, active session, selected athlete, that athlete's prescriptions, active program, and a bounded node readiness state.
- [x] AC4: Programs accept either two valid ordered velocity bounds or two null bounds; partial, negative, non-finite, inverted, and over-10 m/s ranges are rejected.
- [x] AC5: `/rack` registers a stable browser device ID, shows an assignment waiting state, then loads the assigned rack state without exposing coach credentials.
- [x] AC6: The rack shows every selected-athlete prescription, including non-velocity work, and prominently identifies the coach-selected movement.
- [x] AC7: For a ready velocity movement, the rack subscribes only to its assigned node topic and displays unsaved rep count, latest mean velocity, target range, and below/on/above-target text.
- [x] AC8: Rack selection or manual reset clears unsaved live reps; malformed or wrong-node MQTT payloads are ignored.
- [x] AC9: The authenticated coach room view shows and changes rack selection, preserves athlete context across tabs, and reconciles after the monitoring revision.
- [x] AC10: The athlete-facing wall omits the operational session summary strip while preserving rack results and per-set measurements.

## Failure behavior

- No active session, unknown rack, athlete outside the session, mismatched program, or unfinished set returns a stable `{code, detail}` error.
- No node, an inactive node, or multiple nodes keeps the workout visible but disables live velocity feedback.
- REST or MQTT failure preserves the last valid rack selection and displays a retry/reconnecting state.
- Non-velocity movements never fabricate velocity targets or measurements.

## Security and privacy

- Coach mutation requires `IsCoach` JWT authorization.
- Rack reads are open on the private AP but omit notes, NFC IDs, coach tokens, unrelated athletes, node health detail, and conflicting node IDs.
- Browser tokens remain in memory. MQTT reps remain unsaved and are not presented as coach-visible persisted data.

## Test plan

- Django: model constraints, rack-state privacy, coach authorization, selection validation, unfinished-set conflict, outbox event, and room-state selection.
- React: rack payload shaping, rep validation/topic matching, target labels, reset behavior, and route/build checks.
- Manual: rack assignment wait, coach selection, four-rack simulator live feedback, non-velocity prescription, tablet portrait/landscape, and coach reconciliation.

## Validation evidence

- `python manage.py test event_handler`: 46 tests passed.
- `python manage.py check`: passed.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- `npm test -- --run`: 15 tests passed.
- `npm run build`: passed with the existing bundle-size warning.
- Django, listener, publisher, simulator, and React Docker images built.
- Persistent PostgreSQL migration `0005` applied successfully.
- HTTP `/rack` and `/coach`: 200.
- Browser registration created a canonical UUID; authenticated rack assignment and selection returned 200.
- Open rack state returned one selected athlete, two prescriptions including null velocity bounds, and one ready node without private fields.
- Rack-mode simulation published five reps and preserved rack-owned persistence as a non-goal for this slice.
- Headless Chrome at 1024x768 observed waiting assignment, selected workout, five accepted reps at 0.53 m/s, below-target feedback, and reset to zero.
- Headless Chrome at 768x1024 observed the selected workout, live panel, and full prescription without horizontal overflow.
- Authenticated coach Chrome observed Rack 1 athlete/movement controls, saved `Mobility circuit`, and the rack view reconciled to `No velocity target`.
- Wall Chrome at 1366x768 confirmed the operational session summary strip is absent while rack cards retain per-set results.
- Physical ESP32 delivery, touch hardware, and screen-reader behavior remain unverified.

## Migration rollback

Migration `0005` is intentionally irreversible after null-bound non-velocity
programs exist. Back up PostgreSQL before deployment. Rollback requires restoring
the pre-`0005` backup rather than coercing non-velocity prescriptions into fake
velocity targets.

## Demo script

1. Open `/rack`, assign its displayed device to a rack, and select an athlete and movement from `/coach`.
2. Confirm the rack shows the athlete's complete program and highlights the selected movement.
3. Run rack-mode simulation and confirm live rep count and target text update without creating saved reps.
4. Reset live feedback and confirm the count clears.
5. Select a non-velocity movement and confirm the workout remains visible without velocity claims.
6. Confirm the wall opens directly into rack results without the operational session summary strip.
