# Feature Spec: Rack BLE Rep Capture and Live Room Updates

- Ticket: N/A
- Owner: Edge Athlete team
- Date: 2026-08-05
- Status: Logical assignment, controller/observer foundation, and diagnostic
  WT901 acquisition and central BLE discovery/enrollment accepted.
  Unattended Agent startup, detector qualification (AC6-AC9), live accepted-event
  ingestion/reconciliation (AC10-AC13 and AC18), the complete logging audit (AC15),
  staff takeover (AC23), and event fencing (AC24) remain deferred.

## User story

As a rack operator, I want to authorize and select the rack's local BLE sensor
before athlete sign-in, so that physical reps are counted accurately and current
activity reaches the rack, coach, and wall displays without manual refreshes.

## Problem

Main has a complete rack workout flow but no WT901BLE acquisition or validated
rep detector. Node assignment is currently performed from `/coach/setup`, away
from the physical sensor and rack computer. Coach and wall clients already know
how to reconcile versioned room-state invalidations, but check-in, set-start,
and set-completion mutations do not create those durable invalidations.

## Goals

- Configure the rack's sensor only from that rack before athlete sign-in.
- Require an active staff coach login for sensor selection or replacement.
- Produce exactly one contract-compatible rep event for each accepted physical rep.
- Achieve at least 95% count accuracy over 100 controlled qualification reps.
- Allow no more than one false rep during a 10-minute noise protocol.
- Show accepted in-progress reps on rack, coach, and wall views within one second.
- Reconcile completed-set rankings on coach and wall views within two seconds.
- Allow exactly one browser instance to control a rack while every other browser
  at that rack mirrors the authoritative live state read-only.

## Non-goals

- Automatic exercise recognition or mount modes other than a bar-mounted sensor.
- Laboratory-grade velocity validation against force plates or motion capture.
- Persisting or publishing raw 50 Hz IMU samples.
- Ranking incomplete sets or using rejected/false reps in leaderboards.
- Treating a BLE address or advertised name as cryptographic device identity.
- Applying the old BLE stash wholesale to the newer rack implementation.

## Assumptions

- One central Linux laptop or Pi runs the dashboard and owns every BLE connection.
  Rack screens are browser clients; TVs mirror the read-only dashboard.
- The WT901BLE is configured for 50 Hz and physically mounted consistently.
- In-progress rep count is live activity; ranked leaderboards remain based on
  completed, persisted, non-false sets.
- Existing IndexedDB buffering and batch set completion remain the rack durability boundary.
- Physical enrollment plus coach authorization is acceptable for the demo, while
  production still requires authenticated gateway credentials and broker ACLs.

## Acceptance criteria

- [x] AC1: Given no sensor is selected, when the rack opens, then staff-authorized
  sensor setup appears before the athlete roster and athlete sign-in is blocked.
- [x] AC2: Given a non-staff, inactive, or unauthenticated user, when they attempt
  sensor assignment, then the server returns `403` or `401` and mapping is unchanged.
- [x] AC3: Given an authenticated active staff coach at the rack, when they select
  a discovered WT901BLE and its live sample check passes, then the logical node is
  transactionally assigned to that screen's rack and sign-in becomes available.
- [x] AC4: Given a saved selection, when the gateway or rack browser restarts, then
  it reconnects without rescanning; failure keeps sign-in blocked with retry and
  replace-sensor actions.
- [x] AC5: Given a node is selected elsewhere, when another rack selects it, then
  the server rejects the assignment or performs an explicit confirmed transfer;
  one node never silently drives two racks.
- [ ] AC6: Given no athlete is signed in or no set is active, when the sensor moves,
  then no rep is buffered, persisted, ranked, or broadcast as athlete activity.
- [ ] AC7: Given stationary vibration, plate loading, rack impact, bar handling, or
  nearby movement, when the detector processes the trace, then hysteresis,
  duration, stillness, and refractory rules prevent duplicate or false reps.
- [ ] AC8: Given one valid physical rep during an active set, when movement returns
  to verified stillness, then exactly one existing-contract rep payload is emitted
  with bounded finite mean/peak velocity and duration.
- [ ] AC9: Given 100 controlled qualification reps, then accepted count is at least
  95 and no more than one false rep occurs during the separate 10-minute noise test.
- [ ] AC10: Given an accepted rep, then rack, coach, and wall show current rack
  activity within one second without a manual refresh; leaderboard rank does not
  change until set completion.
- [ ] AC11: Given successful set completion, then its reps are persisted once and
  coach/wall totals and rankings reconcile within two seconds without refresh.
- [ ] AC12: Given a false set, rejected movement, failed completion, duplicate, or
  stale packet, then completed totals, rankings, records, and insights do not change.
- [ ] AC13: Given BLE, MQTT, or display interruption, then affected views show stale
  state, reconnect with bounded backoff, and reconcile from authoritative REST state.
- [x] AC14: Given a node or rack has an open set, then reassignment is rejected until
  the set closes, preventing completion from being routed to another rack.
- [ ] AC15: Raw BLE samples, BLE addresses, athlete identifiers, tokens, and MQTT
  bodies are absent from normal application logs.
- [x] AC16: Given two browsers concurrently open one rack, exactly one receives a
  short-lived controller lease and the other renders the same rack state read-only.
- [x] AC17: Given an observer, expired lease, wrong rack, or stale controller epoch,
  check-in, set-start, phase, and completion mutations return a stable `409` and
  write no domain row or invalidation.
- [ ] AC18: Given a controller selects an athlete, changes phase, starts a set, or
  accepts a rep, observers reconcile athlete, exercise, phase, set, rep count,
  latest metrics, and phase timing within one second.
- [x] AC19: Given an athlete is already selected at the current rack revision, a
  repeated semantic check-in creates no second `RackCheckIn`.
- [x] AC20: Given a retried controller command ID, the server returns the prior
  result or an idempotent response without duplicate state, rows, reps, or events.
- [x] AC21: Given lease expiry without an open set, one eligible claimant receives
  the next fencing epoch; all delayed requests from the old epoch are rejected.
- [x] AC22: Given lease expiry with an open set, a different browser remains an
  observer in `recovery_required`; takeover cannot discard browser or Agent queues.
- [ ] AC23: Given an active staff takeover from the current observed epoch, prior
  controller credentials are fenced; open-set takeover remains blocked until the
  Rack Agent can prove its acknowledged queue is transferable.
- [ ] AC24: Given the Rack Agent sends an old epoch, assignment revision, boot ID,
  duplicate event ID, or unexpected sequence, live and completed activity do not change.
- [x] AC25: Given an active staff coach starts a scan, then the central Agent lists
  actual nearby WT901 devices by advertised label and scan-scoped opaque handle.
- [x] AC26: Given a discovered device is selected, then assignment stays disabled
  until the Agent receives fresh valid WT901 frames and shows derived movement for
  physical confirmation.
- [x] AC27: Given a verified device and eligible rack, then confirmation privately
  binds that physical device to a generated logical node and transactionally assigns
  the node to the rack without sending its BLE address to Django or the browser.
- [x] AC28: Duplicate names remain separately selectable; expired handles, devices
  assigned elsewhere, concurrent selection, and open-set replacement fail closed
  without changing the existing assignment.
- [x] AC29: Rack and TV clients cannot invoke Bluetooth directly. Agent outage,
  adapter failure, scan timeout, and verification loss produce explicit retryable states.
- [ ] AC30: Agent restart restores private bindings, but readiness for eight
  simultaneous rack streams remains unaccepted until tested on the target adapter.
- [x] AC31: Given the original controller tab has an active set, when another
  browser tab is foreground, then every Agent-accepted rep continues into that
  tab's IndexedDB-backed rack count without duplicate collectors.
- [ ] AC32: Given the controller lease expires while its active-set tab is hidden,
  when that exact tab becomes visible, then it reclaims the set, synchronizes all
  buffered reps once, and a different or cloned tab cannot mutate or complete it.

## UX / API / device behavior

- UI states: `setup required`, `coach login`, `scanning`, `verifying`, `ready`,
  `reconnecting`, `stale`, and `replace sensor` before athlete check-in.
- Central runtime: one host Agent owns BlueZ and BLE identities. Django calls its
  fixed-schema API over a permission-restricted Unix socket. Rack and TV browsers
  use Django only; they never receive Agent connection details.
- Accepted-rep transport is implemented as an opt-in provisional central-Agent
  publisher on `edgeathlete/node/{node_id}/rep` for demo/qualification only. The
  rack browser keeps the existing IndexedDB buffer and set-complete persistence path.
- Provisional segmentation now requires a sustained 50 Hz translational excursion,
  return near the starting position, and minimum 600 ms duration. A completed return
  emits without requiring a full pause, so consecutive reps remain distinct; endpoint
  stillness rejects an incomplete pickup. Small wiggle, angular-only motion, and
  incomplete return traces are rejected. Altitude is unavailable in the current
  WT901 `0x61` payload.
- The detector learns a bounded idle-noise floor and raises its onset/settle
  thresholds when rack vibration exceeds the static defaults. Raw acceleration
  continues through brief below-threshold samples, but only active movement can
  establish a completed return.
- Active rep count and latest mean/peak velocity are mirrored through `RackRuntime`
  into a separate room-state `live` block. Coach and wall views render that block
  without treating it as a persisted set result or leaderboard input.
- API contract: staff-only scan and verification endpoints return opaque handles,
  labels, and derived movement. Verified rack selection accepts the rack screen ID
  plus a short-lived verification token; callers never submit a BLE address or node ID.
- Device payload: accepted reps continue using
  `edgeathlete/node/{node_id}/rep`; raw IMU samples stay in the gateway process.
- Live activity: ephemeral accepted-rep progress may be broadcast, but completed
  rankings always reconcile from `GET /api/room-state/`.
- Offline Agent-side accepted-rep queuing remains deferred. Diagnostic movement
  is memory-only; accepted reps publish live to Mosquitto and rely on the rack
  browser's existing IndexedDB buffer after receipt.
- Error behavior: sensor failure blocks new athlete sign-in, never fabricates reps,
  and does not discard already buffered accepted reps.

## Data model

- Keep `Node.rack_number` as the canonical node-to-rack mapping.
- Add a partial uniqueness constraint for non-null `Node.rack_number` after a
  migration reconciles any duplicate assignments.
- Do not add a second `RackScreen.selected_node` source of truth.
- Keep completed `Set` and `Rep` rows authoritative for reports and rankings.
- Add server-owned `LiveRackActivity` keyed by rack/open set for recoverable
  in-progress rep count and latest accepted metrics. Completion clears it after
  persisted reps commit.
- Extend accepted rep events with `event_id`, `assignment_revision`, `gateway_boot_id`,
  and monotonic `sequence`; enforce unique event IDs at server and IndexedDB boundaries.
- Raw BLE samples are memory-only or short-lived test fixtures with no athlete data.
- Provisional Agent-published WT901 reps stay disabled by default until MQTT ACLs
  or AC24 event fencing prevent forged, replayed, or stale accepted reps.
- Add one server-owned `RackRuntime` per rack for controller fencing and transient
  presentation state. It stores no raw samples and does not replace Set/Rep history.
- Provision nodes by acquisition path (`mqtt` or `wt901_ble`) through the narrow
  active-staff endpoint. Firmware metadata never changes this trust decision.
  Trusted central Agent health must remain within a two-second window for assignment,
  controller acquisition, set start, check-in, countdown, and live rep updates.
  Completion stays available after health becomes stale so buffered work can close.
- Controller credentials are opaque, short-lived capabilities stored as digests;
  each accepted controller mutation checks rack, token, epoch, and expected state revision.
- Migration `0018` clears every mapping on an ambiguously assigned legacy rack before
  adding partial uniqueness; `0019` clears assigned MQTT-unsafe IDs before adding its
  guard. Reverse migration cannot infer those old mappings and leaves current explicit
  assignments intact.

## Security notes

- Auth required: active staff coach JWT for selection, replacement, or transfer.
- Input validation: canonical MQTT-safe node IDs, registered screen identity,
  screen rack assignment, node existence, and no open set at source/destination.
- Secrets involved: rack gateway credentials and coach JWT; neither belongs in logs
  or browser-local long-term storage on the rack.
- Abuse cases: sensor spoofing, duplicate assignment, wildcard topic injection,
  replayed reps, athlete changing setup, and reassignment during a set.
- Logging restrictions: no raw frames, BLE addresses, tokens, athlete identifiers,
  MQTT bodies, or coach credentials.

## Test plan

- Unit: frame parsing, orientation/gravity correction, filters, hysteresis,
  stillness, refractory interval, sample-gap reset, and duplicate suppression.
- Integration: coach authorization, enrollment, restart, replacement, transfer
  conflict, unique rack mapping, and reassignment blocked during open sets.
- Integration: mutation-to-`MonitoringEvent` for check-in, set start, accepted rep
  progress, set completion, false set, and assignment change.
- E2E/manual: rack setup before sign-in, five physical reps, coach/wall live activity,
  completed leaderboard update, stale/reconnect behavior, and portrait/landscape.
- Hardware: 100 manually observed reps across slow, normal, explosive, paused, and
  failed attempts plus the 10-minute vibration/handling noise protocol.
- Regression: simulator gating, rack IndexedDB buffering, set completion, reports,
  coach authentication, room-state revision ordering, and reconnect reconciliation.

## Demo script

1. Open a rack with no selected sensor and confirm athlete sign-in is blocked.
2. Sign in as a coach on that rack, select the nearby WT901BLE, and verify live samples.
3. Restart the gateway and confirm automatic reconnection and ready state.
4. Load a plate and bump the rack; confirm zero reps.
5. Sign in an athlete, start a set, and perform five controlled reps.
6. Confirm exactly five rack reps and live coach/wall activity without refresh.
7. Complete the set and confirm persisted reps and leaderboard reconciliation.
8. Interrupt BLE and MQTT independently; confirm stale state and recovery.
9. Attempt reassignment during an open set and confirm rejection.

## Open questions

- Detector thresholds and velocity error tolerances remain provisional until
  captured traces are labeled against manually observed reps.
- Choose explicit transfer semantics. The recommended default is `409 conflict`;
  transfer requires a separate confirmation token and expected assignment revision.
- Define staff-authorized open-set cancellation and transferable queue recovery.
- Pin the Agent service/update process, gateway enrollment challenge, and hosted
  publish request/response schemas. The central Unix-socket interface is accepted
  in the related ADR.
- `_SPEC.md` delegates rack assignment, controller, and WT901 acquisition to
  this document. Rep detection, accepted-event ingestion, and ESP32 retirement remain proposed.

## Controller assumptions

- Initial lease timing is 20 seconds with a 5-second heartbeat; PostgreSQL/server
  time is authoritative.
- Each browser tab has its own `client_instance_id`; shared `device_id` alone does
  not establish controller ownership.
- The current private-AP rollout may use registered rack-screen identity to claim
  a lease. Hosted deployment requires a provisioned rack credential before exposure.
- An expired original controller may recover an open set only with the same tab
  capability and matching server set. A different browser requires staff recovery.
- MQTT carries privacy-safe revision invalidations only; mirrors refetch REST state.

## Evidence: assignment, controller, and acquisition

Automated validation on 2026-08-05:

```bash
docker compose -p edgeathlete-main run --rm --no-deps -e SECRET_KEY=django-insecure-edgeathlete-dev-key-replace-for-prod django python manage.py test event_handler
docker compose -p edgeathlete-main run --rm --no-deps django python manage.py check
docker compose -p edgeathlete-main run --rm --no-deps django python manage.py makemigrations --check --dry-run
(cd react && npm test -- --run && npm run build && npm audit --omit=dev)
.venv-wt901/bin/python -m unittest scripts/hardware/test_wt901_rack_agent.py
```

- Backend focused controller/acquisition suite: 69 passed. Full backend suite:
  399 passed serially. Django check and migration drift passed.
- Frontend: 17 files, 152 tests passed; production build passed with the existing
  bundle warning. Production dependency audit reported zero vulnerabilities.
- WT901 Agent: 44 parser, discovery, verification, binding, persistence,
  multi-connection isolation, provisional rep publisher, MQTT failure, pulse
  freshness, and privacy tests passed.
- Migrations through `0021` are applied locally. `0020` adds fenced runtime state;
  `0021` adds staff-provisioned acquisition kind and receipt indexing.

Observed integration evidence:

- Physical WT901 health reported `live` with sample age under 100 ms and more than
  11,000 decoded frames. The Agent reconnected after a BlueZ disconnect and after
  a graceful process restart without rescanning or manually disconnecting BLE.
- Browser Origin probes returned `200` for `http://basestation` and
  `http://192.168.4.1`, and `403` for an unlisted origin.
- A forged non-Agent pulse for the provisioned WT901 node did not change `last_seen`.
- On temporary Rack 7, a second claim returned `409 rack_controller_busy`. A second
  Chrome profile rendered read-only `countdown` state with Braydon Callender,
  Back Squat, 3 reps, 0.72 mean, 0.91 peak, green, and state version 2. The observer
  contained no mutation controls. Temporary rack/runtime/screen assignments and
  their test invalidations were removed afterward.
- Headless Chrome at 768x1024 showed the selected WT901 mapping with the local BLE
  stream verified before `Open check-in` became available.
- Headless Chrome at a 1024x768 tablet-landscape viewport showed the Rack 1 sensor
  mapping, `Open check-in`, and `Replace sensor` without horizontal or vertical
  overflow. At the same viewport, a second tab rendered the complete idle observer
  snapshot, all six state fields, and no buttons or mutation controls.
- Open Sets 7 and 9 each blocked replacement as designed. The user later approved
  closing both zero-rep sets as false sets. Rack 1 is now assigned to the discovered
  physical WT901 and its central acquisition stream reports live.

Not verified or not complete:

- Unattended service startup. Graceful Agent restart and binding restoration are
  verified, but launch remains manual.
- Timed accepted-rep propagation for AC18. Provisional detection and opt-in MQTT
  publishing exist for demo/qualification, but accepted-event fencing and detector
  qualification are not implemented.
- Interactive staff takeover, transferable queue recovery, detector accuracy/noise
  qualification, hosted credentials/TLS/MQTT ACLs, and AC24 event fencing.
- Eight simultaneous WT901 notification streams on the target Bluetooth adapter.

Hidden-tab validation on 2026-08-07:

- Frontend: 20 files and 162 tests passed; production build passed with the existing
  bundle-size warning. WT901 Agent: 49 tests passed. `git diff --check` passed.
- The deployed rack tab was left hidden with the coach tab foreground. Agent
  `accepted_reps` increased from 53 to 70 while `RackRuntime.rep_count` increased
  from 9 to 26: an exact `+17/+17` with no skipped event. The controller remained
  active during this observed interval.
- The user could not visually confirm the final `26` on the rack screen. Lease-expiry
  recovery, cloned-tab contention, completion-boundary timing, and portrait/landscape
  rendering remain manual evidence gaps under AC32 and the broader AC18.

Central discovery evidence on 2026-08-05:

- The host Agent scanned through BlueZ and returned the physical advertised label
  `WT901BLE68` with a random scan-scoped handle and no BLE address.
- The staff-only Django scan endpoint returned the same label with only its opaque
  handle. The verification endpoint connected to FFE5/FFE4, decoded fresh frames,
  and returned bounded movement plus a short-lived verification token.
- The verified selection replaced Rack 1's prior logical test node transactionally.
  Server health reported `live` with a 4 ms sample age. After a graceful central
  Agent restart, the private binding restored without a scan and returned to `live`
  with a 20 ms sample age.
- Replacement tests preserve the old binding until verification, atomically persist
  the proposed replacement, and restore the old binding on exact-token rollback,
  including after restart. A rollback failure returns `ble_reconciliation_required`.
- Verification now calibrates before requiring at least 0.05 g derived movement;
  stationary, moved, and timeout paths are covered. Physical threshold qualification
  beyond the existing frame capture remains part of detector/hardware work.
- A correctly prefixed forged WT901 MQTT pulse was published after rebuilding every
  Django service. The listener rejected it and the unassigned node's freshness did
  not change. Trusted live health now reaches Django only through the Unix socket.
- Agent unit suite: 44 passed, including pickup/wiggle/rotation rejection,
  rest-to-rest movement acceptance,
  provisional rep publishing, MQTT failure handling, replacement rollback,
  persistence failure, and hostile-label cases. Full Django
  suite: 399 passed. Frontend suite: 152 passed; production build passed with the
  existing bundle warning.
