# ADR: Central BLE Enrollment and Authoritative Live Reconciliation

- Date: 2026-08-05
- Status: Accepted for logical assignment and central WT901 discovery/acquisition;
  detector/ingestion and eight-device capacity remain proposed. **Deployed topology
  note (2026-08-12):** the first real deployment uses a per-rack-laptop WT901 agent
  (`wt901_rack_agent.py --address ... --node-id rack_N`) instead of one central agent.
  Each rack screen owns its own sensor and publishes reps + pulses to the base
  station broker as an ordinary `mqtt`-kind node; this deliberately bypasses the
  central Unix-socket health path and its 2-second freshness gate. The NFC reader
  also lives at the rack in this topology: `ccid_rack_agent.py` exposes a loopback
  HTTP tap endpoint (`localhost:8766`) the rack browser polls, forwarding the raw
  `tag_id` to Django for athlete resolution; the Unix socket is kept for a
  base-station-attached reader.
- Related spec: `docs/_RACK_BLE_LIVE_WORKFLOW_SPEC.md`

## Context

One central Pi or laptop is within BLE range of the rack sensors and owns their
connections. Rack screens are browser clients, while TVs mirror the dashboard.
Current node assignment lives in coach setup, while current coach/wall clients
already implement REST reconciliation from privacy-safe MQTT invalidations but
normal rack mutations do not enqueue those invalidations.

A local hardware test recorded 20/40-byte WT901BLE frame handling, bounded
buffering, and BLE/MQTT reconnect behavior; its code remains in `stash@{0}`.
That stash predates the current rack lifecycle and reports movement intensity
only. It is not a rep detector and must not be applied wholesale.

## Decision

1. One central host Agent owns BLE discovery, connections, decoding, filtering,
   and rep segmentation for every rack. Django reaches its fixed-schema API over
   a permission-restricted Unix socket. BLE identities and raw frames remain in
   the Agent.
2. Sensor selection is available only on that rack before athlete sign-in and
   requires an active staff coach login.
3. The server keeps `Node.rack_number` as the canonical mapping. A narrow,
   transactional assignment endpoint replaces coach-setup node mutation and
   enforces one node per rack plus no reassignment during an open set.
4. The rack browser continues to own active set boundaries, IndexedDB rep
   buffering, and batch completion. The Rack Agent publishes each detector-confirmed
   rep to the local rack immediately and asynchronously sends the same uniquely
   identified normalized event to the hosted server. It never publishes raw samples.
5. Accepted in-progress reps are ephemeral live activity. Completed set totals,
   rankings, records, and insights come only from persisted REST snapshots. The
   server stores only the latest recoverable `LiveRackActivity` snapshot for an
   open set, not raw IMU frames.
6. Every room-visible database mutation creates a `MonitoringEvent` in the same
   transaction. The existing publisher sends privacy-safe retained revision
   invalidations; coach and wall clients refetch authoritative snapshots.
7. Implementation proceeds in independently testable slices: durable live
   invalidations, rack-local assignment API/UI, BLE acquisition, trace-based
   detector qualification, then completed-rep publication.
8. A server-owned `RackRuntime` provides a fenced, short-lived controller lease
   and authoritative transient rack snapshot. Exactly one browser may mutate;
   other `/rack/{n}` clients are REST/MQTT mirrors. Domain writes remain in
   `RackCheckIn`, `Set`, and `Rep`.
9. Every controller command carries an opaque capability, controller epoch,
   expected state revision, and command ID. Expiry fences old requests. A different
   browser cannot take over an open set until Agent queue continuity is available.
10. The Rack Agent will ultimately custody hosted credentials and accepted-rep
    queues, but browser control remains separately leased so one person controls UI.
11. Discovery returns random, scan-scoped handles and advertised labels. Staff
    must verify fresh FFE5/FFE4 frames and derived movement before assignment.
    Browser and Django responses never contain BLE addresses or raw frames.
12. A verified selection creates a random MQTT-safe logical node. Django keeps
    `Node.rack_number` authoritative; the Agent privately persists the physical
    binding and reconnects it after restart. FFE9 is never written.
13. The room defines eight rack slots. No release may claim eight simultaneous
    notification streams until the target Bluetooth adapter passes that hardware test.

### Edge publisher flow

```text
WT901BLE -> central Agent -> privacy-safe Django API/MQTT -> rack UI
                              \-> local acknowledged queue
                                  -> authenticated HTTPS/WSS
                                  -> LiveRackActivity + MonitoringEvent
                                  -> coach/wall REST reconciliation
```

Rack browsers read privacy-safe state from Django on the local base-station network.
The server deduplicates `event_id`, rejects stale assignment revisions and prior
gateway boots, updates `LiveRackActivity`, and acknowledges the sequence. A server
outage delays shared views but does not stop local counting. Completed rankings
change only after batch completion commits `Rep` rows.

## Alternatives considered

| Option | Pros | Cons | Reason rejected/accepted |
|---|---|---|---|
| Keep node assignment on coach setup | Existing UI and API | Cannot verify the nearby physical sensor; violates requested workflow | Rejected |
| Allow unauthenticated rack assignment | Minimal taps | Anyone at the rack can reroute reps | Rejected |
| Store a second selected-node FK on `RackScreen` | Direct screen relation | Competes with `Node.rack_number` used by room state, simulator, and set routing | Rejected |
| Send raw IMU data to Django | Central detector | High-rate private data, network dependence, larger failure surface | Rejected |
| Push full coach/wall state over MQTT | Low apparent latency | Duplicates authority and exposes athlete data | Rejected |
| Versioned invalidation plus REST snapshot | Existing durable pattern, privacy-safe, reconnectable | Requires events at every mutation boundary | Accepted |

## Consequences

- Positive: staff select physical advertisements rather than logical test IDs;
  mappings are deterministic; noisy
  movement cannot become rankings without set completion; connected and
  reconnecting displays converge on the same database truth.
- Negative: rack setup needs coach authentication; the central host is one failure
  domain for all BLE racks; adapter connection limits require hardware validation;
  detector tuning requires captured physical traces.
- Follow-up work: define gateway credentials for hosted
  deployment, authenticate MQTT with ACLs, and retire incompatible direct
  `leaderboard_update` traffic after confirming no consumer depends on it.

## Required validation

- Qualification meets the spec's 100-rep and 10-minute noise thresholds.
- One selected sensor cannot drive two racks and cannot be moved during an open set.
- Rack, coach, and wall show accepted activity within one second.
- Completed rankings reconcile within two seconds and survive MQTT/display reconnects.
- No raw sensor or athlete data appears in invalidation messages or logs.
