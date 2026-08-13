# Feature Spec: Durable Room Mutation Invalidations

- Ticket: N/A
- Owner: Edge Athlete team
- Date: 2026-08-05
- Status: Done

## User story

As a coach or wall-display viewer, I want persisted rack activity to appear
without refreshing, so that the room view reflects athlete check-ins and set
state changes while training is underway.

## Scope

- Successful rack check-in writes `athlete_checked_in`.
- Successful set creation writes `set_started`.
- Successful normal or false set completion writes `set_completed`.
- Each `MonitoringEvent` commits in the same transaction as its domain mutation.
- Repeated completion returns stable `409 set_already_completed` without adding
  reps or another invalidation.
- Simulated mutations preserve `is_simulated=True`.

## Non-goals

- In-progress rep streaming before set completion.
- BLE acquisition, node enrollment, or rack-local setup UI.
- Changing the existing privacy-safe MQTT invalidation payload.

## Acceptance criteria

- [x] Successful check-in creates one unpublished `athlete_checked_in` event.
- [x] Rejected check-in creates no event.
- [x] Successful set start creates one unpublished `set_started` event.
- [x] Rejected set start creates no set and no event.
- [x] Normal and false completion each create one `set_completed` event.
- [x] Invalid completion creates no reps, completion update, or event.
- [x] Event-write failure rolls back check-in, set start, reps, and completion fields.
- [x] Repeated completion returns `409` without duplicate reps or events.
- [x] Simulated check-in, set start, and completion events retain simulation provenance.
- [x] Existing coach/wall clients accept every reason and reconcile newer revisions.

## Validation

- Focused invalidation tests: 17 passed during the original slice.
- Current combined full Django suite: 397 passed with the shipped test
  `SECRET_KEY` fixture on 2026-08-05.
- Django system check: passed.
- Migration drift check: no changes detected.
- Current frontend Vitest suite: 151 passed on 2026-08-05.
- Frontend production build: passed with the existing bundle-size warning.
- Previously observed runtime MQTT: check-in published retained `athlete_checked_in` revision 1,
  set start published retained `set_started` revision 2, and completion published
  retained `set_completed` revision 3. Each payload used the existing
  privacy-safe `room_state_changed` envelope.
- Runtime MQTT was not repeated during the rack-assignment validation pass.

## Remaining release boundary

These open rack mutations are designed for the current private-AP deployment.
Hosted deployment requires rack/gateway authentication, scoped throttling,
authenticated MQTT with ACLs, and a published-event retention policy.
