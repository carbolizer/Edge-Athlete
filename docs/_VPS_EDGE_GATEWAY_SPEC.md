# Feature Spec: Secure VPS and Gym Edge Gateway Deployment

- Ticket: N/A
- Owner: Edge Athlete team
- Date: 2026-08-07
- Status: Ready for architecture review

## User story

As a coach at a connected gym, I want the application and training history hosted
on a secure VPS while a gym-owned Pi or Linux laptop handles nearby BLE sensors
and NFC readers, so that I can use one centrally managed application without
publishing raw hardware data or opening the gym host to inbound internet traffic.

## Problem

The current deployment assumes one offline Raspberry Pi owns Django, PostgreSQL,
React, Mosquitto, the private Wi-Fi access point, and local hardware Agents. That
profile is useful and must remain available, but it cannot provide a centrally
hosted application for connected gyms.

Moving only Django, PostgreSQL, and React to a VPS breaks the existing local
hardware boundary. Django currently reaches BLE and NFC Agents through Unix
sockets on the same host, rack browsers consume anonymous local MQTT, and the
browser is the first durable receiver of accepted reps. A hosted deployment needs
an authenticated outbound bridge from the gym, replay protection, a durable
derived-event queue, and explicit behavior when the internet or VPS is unavailable.
It must not expose BLE addresses, raw IMU frames, raw NFC tag IDs, anonymous MQTT,
or host Agent sockets to the internet.

## Current constraints

- The existing local/Pi Compose profile and private-AP behavior remain supported.
  Its current anonymous MQTT listeners are a known private-network constraint, not
  a pattern permitted on the VPS or public internet.
- The WT901 and NFC Agents run on Linux outside Docker and expose fixed local APIs
  through `/run/edgeathlete/ble-agent.sock` and
  `/run/edgeathlete/nfc-agent.sock`. Those sockets remain local-only.
- Raw 50 Hz WT901 frames and BLE addresses remain inside the BLE Agent. Raw NFC
  tag IDs remain inside the NFC Agent/gateway trust boundary.
- The rack browser currently writes each accepted rep to IndexedDB before updating
  its UI and clears that buffer only after successful set completion. Hosted work
  must preserve this ordering and add event deduplication before replay is enabled.
- Completed `Set` and `Rep` rows in PostgreSQL remain authoritative for reports,
  rankings, records, and insights. In-progress activity is not a completed result.
- The accepted-event fencing described by AC24 in
  `docs/_RACK_BLE_LIVE_WORKFLOW_SPEC.md` is not implemented. Provisional WT901
  publishing remains disabled by default outside controlled qualification.
- The detector, hidden-tab collector, and rack frontend have uncommitted work.
  The first hosted slice must not rewrite, copy, or normalize those files. It must
  consume an agreed normalized event boundary after that work is accepted.
- The current offline profile has no VPS dependency. The production profile may
  require internet, but it must define outage behavior rather than silently lose
  or misattribute events.

## Assumptions

- Each hosted gym has one logical tenant and at least one dedicated Linux Pi or
  laptop that stays within BLE/USB range of its racks.
- The VPS has a DNS name, a valid publicly trusted TLS certificate, routine
  PostgreSQL backups, and an operator who can rotate gateway credentials.
- Gym egress permits HTTPS/WSS on port 443. The production design does not require
  inbound port forwarding, a public IP, or a VPN on the gym network.
- One gateway owns a rack's BLE/NFC hardware at a time. Multi-gateway failover is
  deferred because two active gateways could duplicate physical events.
- VPS server time is authoritative for receipt and lease decisions. Gateway event
  time is retained as device evidence but cannot override server ordering.
- A hosted rack browser can reach the VPS. Continued full rack operation during a
  total internet outage is not promised by the hosted profile.
- An active set may continue through a short outage only when the gateway already
  holds server-issued context for that set and its durable queue remains healthy.
  A new set does not start while hosted context or gateway readiness is unavailable.
- NFC production identity will use a gateway-derived, gym-scoped opaque tag
  reference. The VPS will not receive or store the reader's raw tag ID in the new
  production path.
- This specification defines product behavior and contract requirements. An ADR
  must select the exact gateway process, transport, credential format, server push
  mechanism, storage engine, and production Compose files before implementation.

## Goals

- Preserve the current local/Pi deployment as an independently selectable profile.
- Run Django, PostgreSQL, React/static hosting, and the public reverse proxy on a VPS.
- Keep BLE, NFC, raw sensor processing, and physical identifiers on the gym host.
- Require the gym gateway to initiate every internet connection over authenticated,
  encrypted transport; expose no gym-host listener to the public internet.
- Deliver each accepted derived event to the correct gym and rack at most once at
  the domain-write boundary, including after reconnect and replay.
- Queue accepted events durably at the gym until the VPS acknowledges them.
- Preserve IndexedDB-before-render ordering for rack browsers and reconcile shared
  views from authoritative VPS REST state.
- Make gateway, sensor, NFC, queue, and internet failures visible without
  fabricating reps, consuming the wrong wristband tap, or changing rankings.

## Non-goals

- Replacing or hardening the existing offline/private-AP profile in this feature.
- Exposing the local Mosquitto listeners, BLE Agent API, NFC Agent API, BlueZ,
  USB devices, or Unix sockets through Nginx, a tunnel, or a public port.
- Sending raw IMU samples, BLE addresses, raw NFC tag IDs, coach JWTs, athlete
  names, athlete IDs, notes, or full MQTT bodies through the edge event channel.
- Automatic local-to-VPS or VPS-to-local database replication, conflict merging,
  active-active operation, or transparent failover between profiles.
- Reworking or qualifying the provisional WT901 detector, collector lock, hidden-tab
  recovery, rack controller model, or IndexedDB schema as part of deployment work.
- Supporting Windows, macOS, browser Bluetooth, browser NFC, or direct TV/rack
  access to hardware.
- Multi-gateway high availability, gateway-to-gateway handoff, OTA firmware, remote
  shell access, fleet package management, or eight-sensor capacity certification.
- Migrating an existing gym's historical database in the first implementation slice.

## Deployment profiles

### Local/Pi profile

- Keeps the current all-in-one topology: local Django, PostgreSQL, React, Mosquitto,
  host Agents, and optional private access point.
- Starts through its existing Compose/runbook path unless a later accepted spec
  changes it.
- Does not contact the VPS and does not share live state or credentials with the
  production profile.
- Retains current private-AP anonymous MQTT as a documented risk. It must never be
  enabled by a VPS production configuration or bound to a public interface.

### VPS production profile

- The VPS runs the public HTTPS reverse proxy, React assets, Django API/processes,
  PostgreSQL, background event processing, and the authenticated realtime service
  selected by the ADR.
- The gym host runs the existing BLE/NFC Agents and one supervised edge gateway.
  The gateway is the only component permitted to hold its hosted device credential.
- The gateway calls local Agents over permission-restricted Unix sockets and opens
  an outbound TLS connection to the VPS. The VPS never calls a gym-host address.
- Production browsers use the VPS origin and never connect to the local anonymous
  broker or receive a gateway credential, BLE address, raw tag ID, or Agent path.
- Public PostgreSQL, MQTT 1883, unencrypted WebSockets, Django development server,
  and Agent sockets are not internet-accessible.

## Smallest first implementation slice

The first slice proves one derived BLE event can cross the new trust boundary
without changing current local behavior or the dirty detector/frontend work.

### Included

- Add a separate, explicit VPS production deployment configuration with HTTPS-only
  application access and PostgreSQL isolated from the public network.
- Add enrollment for one gym and one gateway using a revocable, least-privilege
  credential that cannot authenticate as a coach or another gym.
- Run one supervised gateway on one Linux gym host. It reads a normalized accepted
  rep fixture or an already-approved Agent output boundary; it does not alter the
  provisional detector.
- Durably queue normalized accepted-rep envelopes, upload bounded batches over
  authenticated HTTPS, retry with bounded backoff and jitter, and delete only the
  contiguous events explicitly acknowledged by the VPS.
- Validate tenant, gateway, rack, logical node, assignment revision, gateway boot,
  sequence, event ID, timestamp bounds, numeric bounds, and exact schema before an
  event can affect live rack state.
- Deduplicate replays at the VPS. A duplicate returns the original acknowledgement
  and creates no second live-state update, `MonitoringEvent`, `Rep`, or completed-set
  result.
- Expose coach-visible gateway status: online/stale, last accepted sequence, queue
  health reported by the gateway, and last contact time. Do not expose secrets or
  physical identifiers.
- Keep completed-set persistence on the existing fenced REST completion path. The
  first slice may update in-progress rack state only; it cannot create a completed
  `Rep` row directly from gateway ingestion.
- Prove the existing local/Pi profile starts and its focused rack/backend/frontend
  tests still pass unchanged.

### Deferred after the first slice

- Browser delivery of replayed accepted reps and the required IndexedDB `event_id`
  deduplication boundary.
- Production NFC enrollment, local opaque tag-reference derivation, mapping sync,
  tap upload, and hosted check-in.
- Remote BLE scan, verification, binding, replacement, and command results through
  the gateway's outbound command channel.
- Live physical detector input until detector qualification and event fencing pass.
- Multi-rack and eight-sensor capacity, gateway replacement, credential rotation UI,
  automated installation/update, metrics export, and profile data migration.
- Starting or completing a real hosted workout. Those require browser replay,
  controller continuity, and set-context acceptance criteria in later slices.

## Acceptance criteria

- [ ] AC1: Given the repository's current local/Pi configuration, when an operator
  starts the local profile after the hosted profile is added, then Django,
  PostgreSQL, React, Mosquitto, and existing rack flows start without requiring VPS
  DNS, internet, gateway credentials, or production environment variables.
- [ ] AC2: Given a VPS production deployment, when its externally reachable ports
  are scanned, then only approved HTTPS/SSH operations ports are reachable;
  PostgreSQL, MQTT 1883, MQTT WebSockets 9001, Django, and Agent sockets are not
  publicly reachable.
- [ ] AC3: Given a production browser or gateway request over plain HTTP or an
  unencrypted realtime transport, when it reaches the VPS, then it is redirected
  to HTTPS where safe or rejected before credentials or event data are accepted.
- [ ] AC4: Given a valid enrolled gateway, when it connects from a NATed gym network,
  then the connection is initiated outbound on port 443 and no inbound gym firewall
  rule or public gym address is required.
- [ ] AC5: Given a missing, expired, revoked, malformed, or wrong-gym gateway
  credential, when an event batch is submitted, then the VPS returns a stable
  authentication error, writes no event or rack state, and records only a
  privacy-safe security audit entry.
- [ ] AC6: Given a valid accepted-rep event, when the VPS validates it, then it is
  associated only with the credential's gym, configured gateway, logical node,
  current rack assignment, gateway boot, and active set context; a client-supplied
  tenant identifier cannot cross that boundary.
- [ ] AC7: Given a duplicate `event_id`, repeated sequence, retried batch, or delayed
  response, when the gateway resubmits, then the VPS returns the prior contiguous
  acknowledgement and creates no duplicate domain write, live count, or invalidation.
- [ ] AC8: Given a sequence gap, stale boot ID, stale assignment revision, unknown
  rack/node, future timestamp, expired set context, or out-of-range velocity/duration,
  when the event arrives, then the VPS rejects or quarantines it with a stable
  machine-readable reason and does not advance live or completed activity.
- [ ] AC9: Given the gateway loses internet or the VPS returns a retryable error,
  when accepted events occur for an already-authorized active set, then the gateway
  stores them durably before reporting success locally, retries with bounded
  exponential backoff and jitter, and removes none until acknowledged.
- [ ] AC10: Given the gateway restarts after queued events have reached durable
  storage, when connectivity returns, then it resumes from the last contiguous VPS
  acknowledgement and each event is accepted or rejected exactly once at the
  domain-write boundary.
- [ ] AC11: Given the gateway queue cannot be written, is corrupt, or reaches its
  configured safety limit, when another event would be accepted, then the gateway
  reports `queue_unhealthy`, does not claim the event is durable, blocks new hosted
  set starts, and preserves existing queue files for operator recovery.
- [ ] AC12: Given hosted connectivity or gateway readiness is unavailable before a
  set starts, when a rack operator attempts to start, then the UI blocks the start
  with a specific retryable status rather than opening an unbound set.
- [ ] AC13: Given connectivity fails during an active set with valid cached context,
  when reps continue, then the gateway may queue normalized rep events for that set;
  it cannot apply them to another set after reconnect, assignment change, context
  expiry, or gateway replacement.
- [ ] AC14: Given a valid first-slice accepted-rep fixture, when it is ingested, then
  only recoverable in-progress rack state and a privacy-safe invalidation may change;
  no completed `Rep`, ranking, record, report, reference max, or insight is created.
- [ ] AC15: Given a production browser receives a live accepted rep in a later
  browser-delivery slice, when it updates the rack UI, then it stores the event in
  IndexedDB before rendering it, deduplicates by `event_id`, and clears it only after
  successful fenced set completion acknowledges the same accepted events.
- [ ] AC16: Given BLE raw frames, BLE addresses, NFC raw tag IDs, gateway secrets,
  coach JWTs, athlete identifiers, or MQTT bodies, when normal application,
  gateway, reverse-proxy, and audit logs are inspected, then none of those values
  appear.
- [ ] AC17: Given a production NFC tap in the later NFC slice, when the gateway sends
  it outbound, then the payload contains a gym-scoped opaque tag reference and key
  version, not the raw tag ID; unknown and off-roster tags remain indistinguishable
  to the rack user.
- [ ] AC18: Given two gateways attempt to own the same rack or one gateway sends an
  event after its lease/assignment is superseded, when the VPS validates the event,
  then at most one current gateway is accepted and the stale sender cannot alter
  rack state.
- [ ] AC19: Given a coach views production status, when a gateway is current, stale,
  revoked, queue-unhealthy, or has a sequence gap, then the UI names that state and
  last contact time without exposing its credential, host address, BLE identity,
  tag reference, or raw event body.
- [ ] AC20: Given production secrets are absent or use documented development
  defaults, when the VPS profile starts, then startup fails closed with a specific
  configuration error; it never creates a demo coach or accepts anonymous gateway
  events.
- [ ] AC21: Given a local-profile event and a hosted-profile event use similar
  logical node names, when both profiles operate independently, then neither broker,
  database, credential, queue, or browser state crosses profiles automatically.
- [ ] AC22: Given a production rollback, when operators stop the hosted profile and
  return a gym to local mode between sessions, then the local stack starts from its
  own database without consuming hosted queue entries; the VPS database and
  unacknowledged gateway queue remain preserved for investigation or later replay.

## UX behavior

- Production setup distinguishes `gateway not enrolled`, `connecting`, `online`,
  `stale`, `credential revoked`, `queue unhealthy`, `sensor reconnecting`, `NFC
  unavailable`, and `update required`.
- A stale gateway does not look like an idle rack. Rack setup and set-start controls
  state the missing dependency and provide a retry action.
- An internet outage during an active set shows that local derived events are queued
  only when the gateway confirms queue health and valid cached set context. The UI
  does not claim coach/wall views are current until VPS reconciliation completes.
- Coach and wall views reconcile from VPS REST snapshots after privacy-safe
  invalidations. Realtime messages are hints, not a second source of truth.
- Gateway enrollment, revocation, rack ownership, BLE replacement, and NFC mapping
  are staff-only actions. Athletes cannot invoke them from a rack screen.

## Data and event contracts

These are requirements-level contracts. The architecture ADR may choose endpoint
names and transport framing but must preserve the fields, trust rules, and failure
semantics below.

### Gateway identity

- A gateway belongs to exactly one gym and has a random server-generated ID,
  display label, credential status, credential version, enrollment time, last
  contact time, and revocation time.
- A gateway credential authorizes gateway ingestion and its scoped command channel
  only. It cannot call coach APIs, read athlete lists, or select another tenant.
- The VPS derives `gym_id` from the authenticated gateway record. Payload `gym_id`
  is advisory at most and never grants scope.

### Derived event envelope

Every queued event contains:

```jsonc
{
  "schema_version": 1,
  "event_id": "UUID",
  "event_type": "accepted_rep|sensor_health|nfc_tap",
  "gateway_id": "opaque gateway id",
  "gateway_boot_id": "UUID regenerated on process boot",
  "rack_number": 1,
  "logical_node_id": "server-issued logical id",
  "assignment_revision": 14,
  "sequence": 205,
  "occurred_at": "2026-08-07T15:04:05.123Z",
  "context": {
    "set_id": 42,
    "set_context_token": "short-lived opaque server capability"
  },
  "payload": {}
}
```

- `event_id` is globally unique and immutable across retries.
- `sequence` increases monotonically within a gateway boot. The server acknowledges
  the highest contiguous terminal sequence, not merely the highest sequence seen.
- `gateway_boot_id` and `assignment_revision` fence delayed events from a prior
  process or physical mapping.
- `set_context_token` binds accepted reps to one gym, gateway, rack, node,
  assignment revision, set, and bounded validity period. It is not a coach JWT and
  must not appear in logs or browser storage.
- Batch requests are bounded by count and encoded bytes. One malformed item cannot
  make neighboring valid events ambiguous: the response reports a terminal result
  for each sequence and a contiguous acknowledgement.

### Accepted rep payload

```jsonc
{
  "mean_velocity": 0.72,
  "peak_velocity": 0.91,
  "duration_ms": 640
}
```

- Values are finite, positive, and bounded by the approved detector contract.
- The payload contains no athlete identity, exercise, raw acceleration, orientation,
  BLE address, advertised device name, or client-computed ranking.
- The VPS resolves athlete/exercise context from the fenced active set. A gateway
  cannot choose an athlete by adding fields.

### Sensor health payload

- May contain a bounded state enum, sample age, battery percentage when provided by
  the approved hardware, queue state, and software contract version.
- Must not contain raw samples, signal captures, BLE addresses, USB paths, host IPs,
  full exception text, or arbitrary device metadata.
- Health cannot create a completed rep or override a revoked/stale assignment.

### NFC tap payload

```jsonc
{
  "tag_ref": "base64url keyed digest",
  "tag_ref_version": 1
}
```

- The gateway derives `tag_ref` locally using a gym-scoped keyed construction and
  domain separation. A plain hash of a tag ID is not acceptable.
- The VPS stores the opaque reference needed for matching, not the raw tag ID.
- Tap events have a short expiry and one-consumer semantics. Replaying an accepted
  tap cannot create a second check-in.
- Production NFC enrollment and key rotation require a separate data migration and
  rollback note before this contract is implemented.

### Acknowledgement

The server response must distinguish:

- `accepted`: event committed to its allowed in-progress effect.
- `duplicate`: prior terminal result returned; no new effect.
- `rejected`: permanent contract/auth-context failure with a stable code.
- `retry`: no terminal decision; gateway retains the event.
- `acknowledged_through`: highest contiguous sequence whose result is terminal.

The gateway deletes only events at or below `acknowledged_through` after the
acknowledgement itself is durably recorded. Unknown responses and timeouts are
retryable and do not delete queued events.

## Data model and retention requirements

- The VPS needs a gym-scoped gateway identity, credential lifecycle metadata,
  current rack/gateway assignment revision, event deduplication record, contiguous
  acknowledgement cursor, and privacy-safe gateway health summary.
- Store the minimum event fields needed for deduplication, audit, and replay
  decisions. Do not store raw BLE/NFC input in event or audit tables.
- Deduplication records must live at least as long as the maximum gateway queue and
  retry window. The ADR must set both periods together so a delayed duplicate cannot
  become new after server cleanup.
- Rejected-event records retain stable code, gateway, sequence, event ID digest or
  ID, and receipt time. They do not retain secret context tokens or arbitrary bodies.
- Gateway queue files use restrictive ownership and permissions. If disk encryption
  is unavailable, queue payloads must remain free of athlete identity and raw tags.
- PostgreSQL backups are encrypted at rest, access-controlled, tested for restore,
  and retained according to an operator-approved policy before production launch.
- Any schema migration includes a forward backup step and documented reverse path.
  A migration that transforms NFC identifiers must state irreversible loss before run.

## Edge cases and failure behavior

- **Duplicate/out-of-order upload:** buffer later sequences until the gap resolves or
  reject them without advancing the contiguous acknowledgement. Never infer absence.
- **Gateway clock skew:** retain `occurred_at`, add server receipt time, flag values
  outside tolerance, and never use gateway time to extend a lease or context token.
- **Gateway restart:** generate a new boot ID, reopen the durable queue, and continue
  retrying old-boot events under their original IDs. The server evaluates their
  original context rather than rewriting them to the new boot.
- **Credential revocation:** reject new connections and uploads. Preserve the local
  queue; do not fall back to anonymous MQTT or a coach credential.
- **TLS/DNS failure:** treat as offline, retry with bounded backoff, and keep queued
  events. Do not disable certificate or hostname validation.
- **Queue full/corrupt/read-only:** mark the gateway unhealthy, stop claiming durable
  acceptance, block new sets, preserve evidence, and require operator action.
- **VPS deploy/restart:** gateway reconnects and retries. Idempotency prevents a
  response lost during deploy from duplicating an event.
- **BLE disconnect/stale samples:** mark sensor stale, stop accepting new detector
  output until recalibration, and keep already queued events.
- **NFC reader failure:** return `unavailable`; BLE acquisition and completion of an
  already-open set remain independent.
- **Held/repeated NFC tag:** one physical presentation produces at most one tap event;
  removal and a new presentation are required for another event.
- **Unknown/off-roster NFC reference:** return the same user-facing result and do not
  reveal whether the reference exists in another session or gym.
- **Rack reassignment/open set:** reject reassignment while a set is open. Events with
  an older assignment revision cannot flow into the replacement rack or node.
- **Two active gateways:** server-side ownership/lease fencing selects one; the other
  is stale and cannot mutate state even with otherwise valid old credentials.
- **Browser reload/hidden tab:** preserve the accepted controller/collector rules in
  the BLE workflow spec. Hosted delivery cannot introduce a second collector.
- **Malformed/oversized input:** reject before parsing unbounded content; no partial
  domain write and no raw body in logs.
- **Profile rollback:** never replay a hosted queue into the local database or merge
  databases automatically. Operators choose one profile before a session.

## Security and privacy

- TLS is mandatory for every production browser and gateway connection. Certificate
  and hostname validation cannot be disabled in a production option.
- Gateway credentials are random, revocable, scoped to one gym/gateway, stored only
  in a root/operator-readable secret location, and never committed to `.env.example`
  as a working value. The design supports overlap during planned rotation.
- Coach access retains JWT authentication and must enforce active staff status on
  hosted mutations. Gateway credentials and rack identities are not coach auth.
- Tenant isolation applies in queries, uniqueness constraints, event validation,
  realtime groups/topics, caches, tasks, admin views, and backups/restores.
- The VPS production broker, if retained, disables anonymous access and applies
  per-client publish/subscribe ACLs. Prefer server-mediated realtime delivery over
  exposing broad MQTT topics to browsers. No wildcard gateway publish authority.
- The gateway accepts no inbound internet commands. Remote scan/bind work uses an
  authenticated outbound command channel with command IDs, expiry, rack scope,
  expected revisions, and idempotent results.
- UDS permissions remain restrictive; Django containers on the VPS never mount
  `/run/edgeathlete` from a gym. Only the local gateway/approved local services can
  call Agent sockets.
- Never log passwords, JWTs, gateway credentials, set context tokens, raw event
  bodies, raw tag IDs, tag references, BLE addresses, device UUIDs, athlete IDs,
  athlete names, session IDs, notes, or raw sensor values.
- Security audits record action type, gateway record, server time, result code, and
  request correlation ID. They exclude secrets and private payload fields.
- Rate limits apply per gateway and source as defense in depth. Retrying a known
  event ID is checked idempotently without allowing a flood to create domain rows.
- Production launch requires an independent security review covering tenant escape,
  credential theft/replay, event injection, sequence exhaustion, queue tampering,
  SSRF through command results, websocket authorization, dependency risk, secret
  rotation, backup access, and log redaction.

## Test plan

### Unit

- Strict event schema, finite numeric bounds, timestamp tolerance, batch limits,
  tenant derivation, assignment revision, set-context binding, boot/sequence rules,
  and stable rejection codes.
- Gateway durable enqueue, atomic cursor update, contiguous acknowledgement, restart,
  retry/backoff jitter, queue limit, corruption detection, and no-delete-on-timeout.
- Deduplication for repeated event IDs, repeated sequences, reordered batches, lost
  responses, and gateway restart.
- NFC keyed-reference derivation and redaction when the deferred NFC slice begins.

### Integration

- Enroll, authenticate, rotate, revoke, and wrong-gym gateway credentials.
- Submit a valid bounded batch and verify allowed live state plus one privacy-safe
  invalidation; verify no completed `Rep` or ranking change in the first slice.
- Drop the response after commit, resend, and verify the original acknowledgement
  with no duplicate state/event.
- Interrupt VPS, DNS, TLS, and network access; restart the gateway; restore service;
  verify ordered replay and queue cleanup only through contiguous acknowledgement.
- Attempt stale assignment, stale boot, expired context, sequence gap, oversized
  body, unknown fields, non-finite values, and cross-gym IDs; verify no domain write.
- Inspect production container/network exposure and verify PostgreSQL/MQTT/Django
  internals cannot be reached externally.

### E2E and manual

- One-rack first-slice fixture: enqueue five normalized accepted reps, interrupt the
  network after two, restore it, and observe five unique in-progress events at the
  VPS with no completed ranking change.
- Revoke the gateway while connected and confirm status becomes revoked, uploads
  stop, and no anonymous or coach-token fallback occurs.
- Verify coach status at desktop and tablet portrait/landscape sizes for online,
  stale, queue-unhealthy, and revoked states.
- In later slices, verify rack IndexedDB-before-render behavior, duplicate delivery,
  set completion, coach/wall reconciliation, NFC known/unknown behavior, and remote
  sensor replacement.

### Hardware

- The first slice may use a normalized fixture and does not claim detector accuracy.
- Before live BLE production use, pass AC6-AC9 and AC24 from the BLE workflow spec,
  including the 100-rep and 10-minute noise protocol.
- Before multi-rack release, test the target adapter at the released simultaneous
  sensor count and record disconnect/recovery evidence.
- Before NFC release, test held tag, remove/retap, reader unplug/replug, unknown tag,
  off-roster tag, gateway restart, and internet interruption without exposing raw IDs.

### Regression

- Local/Pi Compose startup and health.
- Focused Django rack/controller/assignment/completion tests, Django system check,
  and migration drift check.
- Frontend Vitest and production build, including IndexedDB buffer and collector lock.
- WT901 and NFC Agent unit suites without changing their UDS exposure.
- Verify the existing anonymous local broker is absent from the VPS profile and no
  production browser bundle contains a gateway secret or anonymous broker URL.

## Rollout

1. Complete the architecture/security ADR and threat model; pin the public ports,
   event transport, gateway storage, credential lifecycle, and retention periods.
2. Deploy an isolated non-production VPS and one synthetic gym/gateway. Use only
   normalized fixtures; do not enable provisional physical rep publishing.
3. Pass first-slice security, replay, outage, restore, and local-profile regression
   tests. Record external port-scan and log-redaction evidence.
4. Pilot one gym and one rack with no historical-data migration. Keep the local
   profile stopped but recoverable, and prohibit switching profiles mid-session.
5. Add browser delivery/deduplication and set-context continuity as a separately
   accepted slice before a real hosted workout.
6. Add NFC and remote enrollment as separate slices with migration, privacy, and
   hardware evidence. Expand rack count only after adapter capacity evidence.

## Rollback

- Stop accepting new hosted set starts and finish or explicitly cancel the active
  hosted session before rollback. Do not switch profiles mid-set.
- Revoke or disable the gateway credential, stop the gateway service, and preserve
  its queue and logs. Do not delete unacknowledged events during rollback.
- Restore the prior VPS application/database release from the pre-deploy backup if
  the fault is hosted-only. Verify schema compatibility before application rollback.
- To return the gym to local mode, start the existing local profile against its own
  local database and local credentials. Hosted activity does not appear locally
  unless a separately specified, audited export/import is performed.
- Keep the VPS database and queue snapshot until operators reconcile accepted,
  rejected, and unacknowledged sequence ranges. Rollback is not evidence that queued
  events were safely imported elsewhere.

## Demo script

1. Start the unchanged local/Pi profile with VPS variables absent. Confirm the rack
   application and local health endpoint load without internet.
2. Stop the local profile. Start the VPS production profile in staging and show that
   HTTPS is available while PostgreSQL, MQTT 1883/9001, Django 8000, and Agent
   sockets are not externally reachable.
3. Enroll one synthetic gym gateway and start it behind a NATed network with outbound
   port 443 only. Confirm coach status changes from `connecting` to `online`.
4. Submit two normalized accepted-rep fixtures for an authorized open-set context.
   Confirm in-progress state reaches count two and no completed ranking changes.
5. Disconnect the gym network and enqueue three more fixtures. Confirm the gateway
   reports three durable queued events and the VPS status becomes stale.
6. Restart the gateway while still offline, restore the network, and confirm the VPS
   acknowledges one contiguous five-event sequence. Confirm five unique events, no
   duplicate invalidation/domain effect, and an empty acknowledged queue.
7. Resubmit the same batch and confirm duplicate acknowledgements with no state change.
8. Submit stale-assignment and wrong-gym events and confirm stable rejection codes,
   no live/completed change, and no private payload in logs.
9. Revoke the credential and confirm reconnect/upload fails closed while queued data
   remains local. Confirm no fallback to anonymous MQTT.

## Open questions for architecture review

- Choose HTTPS polling/batching plus server push, an outbound authenticated WSS
  session, or a combination. The choice must satisfy replay, commands, browser
  delivery, and proxy timeout behavior without public anonymous MQTT.
- Choose the gateway queue engine and exact capacity/retention limits based on disk
  budget and maximum supported outage. The acceptance behavior above is fixed.
- Define how the VPS issues and refreshes active-set context to the gateway before
  browser delivery and real hosted workouts are enabled.
- Define initial gateway enrollment ceremony and recovery when the credential is
  lost. It must require an operator/staff action and cannot rely on a shipped default.
- Decide whether the existing `Node`, `RackRuntime`, and `MonitoringEvent` tables can
  carry tenant scope safely or need an additive tenant model before hosted rollout.
- Define historical data migration/export separately. No automatic merge is assumed.

## BSA readiness note

This specification is ready for architecture and security review. Implementation is
blocked until an ADR resolves the open interface, tenant-schema, credential, queue,
and active-set context decisions. The first implementation slice remains valid
without resolving deferred NFC, remote enrollment, multi-rack capacity, or database
migration behavior.
