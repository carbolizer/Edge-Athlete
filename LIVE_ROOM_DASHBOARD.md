# Feature Spec: Live Room Dashboard Snapshot

- Ticket: N/A
- Owner: Braydon
- Date: 2026-07-13
- Status: Done

## User story

As a coach, I want the wall and coach dashboards to load the active room state from the base station so that the screen reflects saved workout data instead of demo athletes.

## Problem

The dashboard currently renders rack, athlete, session, and leaderboard data from `react/src/data/demoDashboardData.js`. Its only backend request counts nodes and does not affect the room display.

## Goals

- Return bounded wall and coach snapshots of the active session and assigned racks from Django.
- Render the same snapshot on the wall and coach dashboard routes.
- Make loading, empty, and failed requests visible.

## Non-goals

- MQTT-driven updates after the initial snapshot.
- Live reps that have not been submitted by the rack screen.
- Coach mutations, inferred fatigue guidance, rest timers, or program compliance.
- Connecting the separate rack, athlete, and admin preview pages.

## Assumptions

- The newest session without an `ended_at` value is the active room session.
- A set belongs to its node's current rack because `Set` does not store a rack snapshot.
- The base station runs on a private gym network, matching the existing open read endpoints.

## Acceptance criteria

- [x] AC1: Given an authenticated coach and an active session with saved sets, when `/api/room-state/` is requested, then it returns session totals, assigned racks, each rack's latest set and reps, and a per-athlete leaderboard.
- [x] AC2: Given no active session, when the endpoint is requested, then it returns HTTP 200 with `session: null`, zero totals, and assigned racks with no set data.
- [x] AC3: Given the wall or coach dashboard loads, when the request succeeds, then only backend room data is displayed and no demo athletes are used as fallback data.
- [x] AC4: Given the request fails, when the dashboard renders, then it shows an error and a retry action.
- [x] AC5: Anonymous callers cannot access `/api/room-state/`; `/api/wall-state/` exposes scoreboard fields but omits database IDs, weights, target zones, node details, NFC tags, notes, device IDs, credentials, and tokens.

## UX / API / device behavior

- UI states: loading, populated, no active session, no assigned racks, request failed.
- API contract: authenticated `GET /api/room-state/` for coaches and open `GET /api/wall-state/` for the shared scoreboard.
- Device payload: unchanged.
- Offline behavior: show the request failure state; do not substitute demo data.
- Error behavior: retain no stale snapshot in this slice and allow manual retry.

## Data model

- Tables: existing `Session`, `Set`, `Rep`, `Athlete`, `Program`, `Node`, and `RackScreen` tables.
- Migrations: none.
- Retention: unchanged.
- Privacy notes: athlete IDs and names are required for the room board; notes and NFC tags are excluded.

## Security notes

- Auth required: JWT coach login for detailed room state; the minimized wall scoreboard remains open.
- Input validation: no request parameters.
- Secrets involved: none.
- Abuse cases: responses are capped at 32 racks, 20 leaderboard entries, and 100 reps per latest set; set submission is capped at 100 reps.
- Logging restrictions: do not log response bodies or athlete data.

## Test plan

- Unit/integration: Django API tests for populated, empty, newest-session, summary, latest-set, and privacy behavior.
- Frontend: production build plus manual loading, populated, empty, and failure checks.
- Firmware/hardware: not applicable.
- Regression: run the existing Django test suite and Vite production build.

## Demo script

1. Start the Edge Athlete stack with an active session and completed sets.
2. Open `/` and `/coach`.
3. Confirm both routes show the backend session, racks, totals, and leaderboard; stop Django and confirm retryable failure behavior.

## Validation evidence

- PostgreSQL-backed Django suite: 6 tests passed.
- Vite production build: passed; bundle-size warning remains.
- Headless wall checks: populated session and no-active-session states rendered.
- Headless coach check: login loaded the detailed session, rack, rep, target, and hardware state.
- Failure/retry check: with Django stopped, the wall showed `Room state unavailable` and `Retry`; after Django restarted and Retry was clicked, the same page rendered the seeded session and athlete data.

## Architecture decision

Use a REST snapshot for initial state only. This gives a browser enough persisted state after a reload without violating the existing rule that ongoing live updates use MQTT. Polling and new MQTT event handling are deferred. The known limitation is that changing a node's rack assignment also changes where historical sets appear because `Set` has no immutable rack number.
