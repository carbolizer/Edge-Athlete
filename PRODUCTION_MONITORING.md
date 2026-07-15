# Feature Spec: Production Wall and Coach Monitoring

- Ticket: N/A
- Owner: Braydon
- Date: 2026-07-13
- Status: In Progress

## User stories

As an athlete, I want a large room scoreboard that updates after completed sets so I can see rack progress and session leaders without interacting with the display.

As a coach, I want an authenticated tablet view with live rack details and measured performance trends so I can identify where attention is needed without unsupported recommendations.

## Problem

The current views load one persisted snapshot but do not update when sets finish. The wall is a dashboard shell rather than a kiosk-grade scoreboard, and the coach view lacks measured trends, broker state, token recovery, and stale-data behavior.

## Goals

- Reconcile both views within two seconds after a set commits.
- Keep PostgreSQL/REST authoritative and use MQTT as a durable invalidation signal.
- Present a legible, read-only wall at kiosk resolution.
- Present authenticated rack details and measured insights on tablet widths.
- Recover from broker and API interruptions without substituting demo data.

## Non-goals

- Session, athlete, program, or hardware mutations.
- Unsaved per-rep streaming on wall or coach views.
- Fatigue, readiness, form, compliance, rest, or load recommendations.
- Administrative preview pages and multi-page coach navigation.
- Trained or scaffolded machine-learning output.

## Assumptions

- The newest session with no `ended_at` remains the active session.
- A saved set snapshots its rack number so later node reassignment does not move history.
- The wall may show athlete display names and measured scoreboard values, but no database or hardware identifiers.
- The public MQTT event contains no athlete, set, session, node, rack, or credential data.
- The private Pi network remains the transport boundary until the security-hardening phase adds TLS and broker credentials.

## Acceptance criteria

- [ ] AC1: Given either view is open, when a set commits, then rack state, room totals, insights, and leaderboard reconcile from REST within two seconds without reload.
- [ ] AC2: Given MQTT is unavailable when a set commits, when the broker returns, then the durable outbox publishes the pending revision and connected clients reconcile.
- [ ] AC3: Given a client reconnects or receives duplicate/out-of-order events, then it ignores old revisions and converges to the latest REST revision.
- [ ] AC4: The wall route `/dashboard` is read-only, requires no login, is legible at 1920x1080 and 1366x768, and exposes only scoreboard-safe fields.
- [ ] AC5: The coach route requires JWT login and shows latest saved reps, target comparison, previous comparable set, velocity loss/range, and node staleness using measured data only.
- [ ] AC6: Loading, no session, no racks, no sets, reconnecting, stale snapshot, API failure, expired login, and truncated-data states have explicit UI behavior.
- [ ] AC7: A pulse on `edgeathlete/node/{node_id}/pulse` updates the matching `Node` health fields; malformed pulses do not terminate the listener.
- [ ] AC8: A saved set retains its original rack after its node is reassigned.
- [ ] AC9: Backend, frontend, privacy, MQTT publisher, reconnect, and responsive tests pass with recorded evidence.

## Interface contract

- REST bootstrap: `GET /api/wall-state/` and authenticated `GET /api/room-state/`.
- MQTT topic: `edgeathlete/dashboard/state`, QoS 1, retained.
- MQTT body: `{schema_version, type:"room_state_changed", reason:"set_completed", revision, event_id, occurred_at}`.
- MQTT contains no domain data. Clients refetch their role-appropriate REST snapshot when `revision` increases.
- REST includes `schema_version`, `revision`, `generated_at`, summaries, racks, leaderboard, factual insights, and truncation flags.

## Failure behavior

- Initial REST failure: offline screen with retry.
- MQTT disconnect with a valid snapshot: retain data and show reconnecting; mark stale after 15 seconds.
- REST refresh failure: retain the last valid snapshot and mark it stale.
- Broker publish failure: keep the outbox event pending and retry; never roll back an already committed set after commit.
- JWT expiry: clear detailed coach state and return to login. Token refresh is deferred because the current login UI does not persist refresh tokens.

## Security and privacy

- Detailed coach REST requires authentication.
- Wall REST and MQTT omit IDs, weights, targets, reps, node details, notes, NFC identifiers, tokens, and credentials.
- Access tokens remain in memory and are never logged or persisted.
- MQTT event handling validates schema/type/revision and debounces reconciliation.
- TLS, broker ACLs, and device credentials remain required before deployment outside the controlled Pi network.

## Test plan

- Backend: snapshot calculations/privacy, immutable rack, outbox transaction, publisher retry/acknowledgment, pulse parsing, duplicate completion.
- Frontend: REST bootstrap, event revision reconciliation, duplicate event, reconnect/stale state, auth loss, empty/error states.
- Responsive: screenshots at 1920x1080, 1366x768, 1024x768, and 768x1024.
- Integration: complete a set, observe retained MQTT revision, and verify both views refetch within two seconds; repeat with broker outage.

## Demo script

1. Open `/dashboard` and `/coach`; authenticate the coach.
2. Complete a set and confirm both screens update without reload.
3. Stop the broker, complete another set, restart the broker, and confirm both screens converge.
4. Reassign the set's node and confirm the completed set remains under its original rack.
5. Publish a pulse and confirm coach hardware health updates after reconciliation.

## Architecture decision

Use a transactional `MonitoringEvent` outbox. Set completion and outbox insertion commit together. A dedicated process publishes pending revisions at least once with QoS 1 and marks each event only after broker acknowledgment. The event is an invalidation signal; clients always refetch REST and ignore revisions at or below their current snapshot.
