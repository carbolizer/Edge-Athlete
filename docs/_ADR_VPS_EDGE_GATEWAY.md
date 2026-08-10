# ADR: VPS Edge Gateway Health Foundation

- Date: 2026-08-07
- Status: Accepted for one-gateway health ingestion; hosted reps, NFC, control,
  browser delivery, and real workouts remain blocked
- Related spec: `docs/_VPS_EDGE_GATEWAY_SPEC.md`
- Related ADR: `docs/_ADR_RACK_BLE_LIVE_WORKFLOW.md`

## Context

The current deployment is an all-in-one local base station. Django reaches the
WT901 Agent through `/run/edgeathlete/ble-agent.sock`, PostgreSQL and Mosquitto
stay local, and browsers use the private base-station network. That profile must
continue to start without VPS configuration or internet access.

The hosted spec proposes a larger first slice based on accepted-rep fixtures.
The first implementation step will be narrower: one provisioned gateway polls the
existing WT901 Agent health route over its local Unix socket, durably queues a
strict health event, and sends it to the VPS over authenticated outbound HTTPS.
This proves deployment separation, authentication, replay handling, queue recovery,
boot/sequence fencing, and staff diagnostics without crossing the unqualified rep
detector or unfinished rack collector boundary.

This step does not satisfy the spec's complete accepted-rep first slice. It is a
foundation for that slice. No hosted profile may start or complete a real workout
until the later rep, browser deduplication, and set-context slices are accepted.

## Existing patterns

- `scripts/hardware/wt901_rack_agent.py` exposes bounded, exact-schema HTTP over a
  mode `0600` Unix socket. `GET /v1/racks/{rack}/health` returns derived health and
  keeps BLE addresses and raw frames private.
- `django/event_handler/services/ble_agent.py` uses fixed Agent paths, bounded
  reads, timeouts, strict JSON, and safe error translation.
- `django/event_handler/views.py` and `RackCommandReceipt` use random opaque
  capabilities, digest-only storage, constant-time comparison, UUID idempotency,
  stable conflict codes, and `transaction.atomic()` with `select_for_update()`.
- `process_pulse_event()` locks `Node`, rejects future timestamps, updates health,
  and creates `MonitoringEvent` in the same transaction as a material change.
- `IsActiveStaff` is the accepted permission for security-sensitive setup.
- `docker-compose.yml` is the local profile and publishes anonymous MQTT only for
  the private network. The production deployment cannot extend that file in a way
  that makes local startup depend on hosted variables.
- The Django image currently runs `ensure_demo_coach` on every normal startup.
  A VPS service must override that command; `coach` / `coachpass` is forbidden in
  production.

No existing pattern conflicts with an additive health-only gateway. The existing
schema is single-gym, however. `Node.rack_number` has no tenant key. This ADR allows
one hosted gym and one non-revoked gateway only; it blocks multi-gym data, reps,
NFC, and control until tenant scope is added to every affected domain query and
constraint.

## Decision

1. Keep `docker-compose.yml` and `docker-compose.basestation.yml` as the local/Pi
   profile. They do not read VPS credentials, contact the VPS, or share a database,
   broker, queue, or volume with the hosted profile.
2. Add a standalone `docker-compose.vps.yml`, a VPS-only Nginx configuration, and
   a VPS environment template. The VPS runs PostgreSQL, Django/Gunicorn, React,
   and Nginx. The first slice runs no Mosquitto service and exposes no MQTT port.
3. Run a new gateway as a systemd service on the gym host, outside Docker and as
   the same restricted OS account that owns the mode-`0600` WT901 Agent socket.
   It opens no TCP listener and makes outbound connections only to one configured
   `https://` origin on port 443.
4. Poll only `GET /v1/racks/{rack_number}/health`. Whitelist the Agent's
   `schema_version`, `node_id`, `state`, and `sample_age_ms`. Do not copy `label`,
   `movement_g`, `activity_score`, `accepted_reps`, or `detector` into the queue,
   request, database, or logs.
5. Accept only `sensor_health` events at `POST /api/gateway/v1/events/`. The first
   slice has no rep, NFC, set-context, command, lease-renewal, or browser endpoint.
6. Use a random bearer credential with digest-only server storage. Derive gym and
   gateway scope from the authenticated credential, never from a tenant field in
   the request.
7. Store queued events in one local SQLite database with WAL, foreign keys,
   `synchronous=FULL`, and explicit transactions. Enqueue commits before the
   gateway reports local durability. Acknowledgement and deletion commit together.
8. Serialize each gateway's VPS ingestion with a locked gateway row. Store a
   terminal receipt for every accepted, duplicate, or permanently rejected event.
   Advance only the current boot's contiguous terminal sequence.
9. Expose gateway and sensor diagnostics through a REST snapshot guarded by
   `IsActiveStaff`. Realtime browser delivery is deferred; a transactional
   `MonitoringEvent(reason="gateway_health_changed")` may invalidate a future
   staff view without containing gateway or sensor details.

## Credential choice

The first slice uses a 32-byte cryptographically random bearer secret, encoded as
base64url and sent only in `Authorization: Bearer`. The credential has this form:

```text
egw1.<gateway_public_id>.<credential_version>.<43-character-secret>
```

The database stores `SHA-256("edgeathlete-gateway-v1\0" || secret)` as 64 lowercase
hex characters. The server parses the public gateway ID and version, loads that
credential row, hashes the presented secret, and compares with
`hmac.compare_digest`. A random 256-bit secret does not need a slow password hash;
an offline database attacker cannot feasibly guess it. The prefix and domain
separator prevent accidental reuse with rack controller tokens. Django never
stores or returns the clear credential.

### Alternatives considered

| Option | Decision | Reason |
|---|---|---|
| Random bearer, digest at rest | Accepted | Smallest fit with the existing opaque-capability pattern; supports one-time display, revocation, overlap, and constant-time verification without storing a server-side signing key |
| Per-request bearer HMAC signature | Rejected for this slice | Requires the VPS to retain a usable symmetric signing secret, canonicalize every request exactly, and manage nonce/time-skew rules; TLS already provides request integrity and the event receipt/sequence contract provides replay safety |
| Mutual TLS | Deferred | Strong device-bound channel authentication, but adds a private CA, client certificate issuance, Nginx certificate forwarding, expiry recovery, revocation distribution, and certificate rotation before one gateway can send health |

A stolen bearer can impersonate the gateway until expiry or revocation. TLS,
least-privilege endpoints, a root-managed credential file, rate limits, rotation,
and event fencing bound that risk. mTLS should be reconsidered before unattended
fleet enrollment or multi-gym rollout.

## Data model and migration

Migration `0022_vps_gateway_health_foundation` is additive and contains no data
backfill:

### `HostedGym`

- `id`: server-generated UUID primary key
- `slug`: unique, immutable operator identifier
- `display_name`: bounded staff-facing label
- `created_at`: server time

The first slice enforces one `HostedGym` row in the provisioning service and tests.
The database cannot express a useful global one-row constraint without a sentinel;
application startup fails if the VPS contains zero or more than one active hosted
gym. Local profile startup does not perform this check.

### `EdgeGateway`

- `id`: server-generated UUID primary key and public gateway ID
- `gym`: `PROTECT` foreign key to `HostedGym`
- `label`: bounded staff-facing label
- `revoked_at`: nullable server time
- `current_boot`: nullable `SET_NULL` foreign key to `GatewayBoot`
- `last_contact_at`: nullable server time
- `last_event_at`: nullable gateway occurrence time retained as evidence
- `queue_state`: `unknown|healthy|unhealthy|full|corrupt|read_only`
- `queue_depth`: nullable bounded positive integer
- `oldest_queued_at`: nullable gateway time
- `created_at`, `updated_at`: server times

Provisioning permits only one gateway with `revoked_at IS NULL`. Historical revoked
rows remain for receipt and audit integrity.

### `GatewayCredential`

- `gateway`: `CASCADE` foreign key
- `version`: positive integer, unique with `gateway`
- `secret_digest`: fixed 64-character value, unique
- `created_at`, `not_before`, `expires_at`, `revoked_at`, `last_used_at`: server times
- `created_by`: nullable `SET_NULL` user foreign key for the active staff sponsor

At most two unexpired, non-revoked credentials may overlap during rotation. The
service enforces the limit under a gateway row lock.

### `GatewayNodeGrant`

- `gateway`: `PROTECT` foreign key
- `node`: `PROTECT` one-to-one foreign key to the existing `Node`
- `assignment_revision`: positive bigint
- `created_at`, `revoked_at`: server times

`Node.rack_number` remains the canonical logical mapping. Add
`Node.assignment_revision`, default `1`, and increment it in the existing
transactional node-assignment and BLE-selection paths whenever the canonical rack
mapping changes. A grant is valid only when it belongs to the authenticated gateway,
is not revoked, its revision equals `Node.assignment_revision`, and the request's
rack and logical node equal the current `Node` row. This table grants gateway
ownership; it does not create a second rack mapping.

### `GatewayBoot`

- `gateway`: `CASCADE` foreign key
- `boot_id`: gateway-generated UUID, unique with `gateway`
- `server_epoch`: positive bigint, unique with `gateway`
- `acknowledged_through`: positive bigint, default `0`
- `first_received_at`, `last_received_at`: server times
- `superseded_at`: nullable server time

The server allocates `server_epoch` while holding the gateway lock. A new boot is
established only by sequence `1` after all earlier queue rows have reached a
terminal result. Establishing it supersedes the previous current boot. Receipts
for older boots remain readable for duplicate responses, but an unseen event from
an older boot is terminally rejected as `stale_gateway_boot`.

### `GatewayEventReceipt`

- `gateway`, `boot`: `CASCADE` foreign keys
- `event_id`: UUID
- `sequence`: positive bigint
- `event_type`: fixed `sensor_health` choice in this slice
- `result`: `accepted|rejected`
- `result_code`: bounded stable code
- `occurred_at`, `received_at`: timestamps

Unique constraints cover `(gateway, event_id)` and `(boot, sequence)`. The table
stores no request body, health payload, credential, Agent path, or physical
identifier. Receipts remain for 30 days after receipt. Cleanup must not remove a
receipt younger than 30 days; the local queue's supported outage is seven days.

### `GatewayNodeHealth`

- `grant`: one-to-one `CASCADE` foreign key
- `sensor_state`: `starting|live|stale|reconnecting`
- `sample_age_ms`: nullable integer from `0` through `600000`
- `agent_schema_version`: positive small integer
- `gateway_occurred_at`, `server_received_at`: timestamps
- `boot`, `sequence`: last event fence

It contains only the latest accepted derived health. It does not alter `Set`, `Rep`,
`RackRuntime`, rankings, reports, records, or insights.

Before applying the migration, take and verify a PostgreSQL backup. Reversing to
`0021` drops only these hosted tables and `Node.assignment_revision`; it does not
change existing node-to-rack values or local training rows. Export receipt ranges
and preserve the gym queue before reversal. Do not reverse while a VPS gateway is
running or has unacknowledged rows.

## Provisioning, rotation, and revocation

Provisioning is a VPS-console management command, not an anonymous enrollment API:

```text
python manage.py provision_edge_gateway --gym <slug> --label <label> --staff <username>
```

The command verifies that the sponsor exists and is active staff, locks the hosted
gym, refuses a second non-revoked gateway, creates a version-1 credential, and
prints the complete bearer exactly once. The secret is generated by the server and
is never accepted as a command argument. The operator installs it through systemd
`LoadCredential=` from a root-owned mode `0400` source file; it does not enter the
repo, Compose environment, shell history, browser storage, or `.env.example`.

Rotation creates version `n+1`, makes it valid immediately, and sets the previous
credential to expire after a maximum 24-hour overlap. The operator atomically
replaces the systemd credential source, restarts the gateway, confirms
`last_used_at` on the new version, and revokes the old version. Losing the clear
secret requires rotation; it cannot be recovered from the digest.

Revoking the gateway or credential returns the same authentication failure as an
unknown credential, preserves local queue rows, and never falls back to coach JWT,
HTTP, MQTT, or another gym. Emergency revocation takes effect on the next request;
the first slice has no long-lived connection to terminate.

## Local queue

The queue is `/var/lib/edgeathlete-gateway/queue.sqlite3`; its directory is mode
`0700`, files are mode `0600`, and the systemd service uses the same dedicated,
unprivileged OS account as the WT901 Agent. This preserves the Agent's current
mode-`0600` socket instead of widening access or running either process as root.
SQLite creates the associated `-wal` and `-shm` files under the same directory.

SQLite uses this logical format:

```text
queue_meta(schema_version=1, last_ack_json, created_at)
queued_event(local_order INTEGER PRIMARY KEY AUTOINCREMENT,
             event_id UUID UNIQUE, boot_id UUID, sequence INTEGER,
             occurred_at TEXT, canonical_json BLOB,
             byte_length INTEGER, enqueued_at TEXT)
```

`canonical_json` is UTF-8 JSON with sorted keys, compact separators, no NaN or
Infinity, and exact schema version 1. It contains no athlete identity, BLE address,
raw sample, movement value, detector state, label, tag, token, or Agent path.

The gateway generates one boot UUID at process start and a sequence beginning at
1. It inserts each event and commits with `synchronous=FULL` before reporting the
health sample queued. Upload reads the oldest rows in `local_order`, never skips a
row, and never combines boot IDs in one request. On restart it drains old-boot rows
before uploading rows from the new boot.

After a valid response, one SQLite transaction records the response's boot ID and
`acknowledged_through`, verifies that it never decreases, stores the latest
privacy-safe rejection summary, and deletes only rows for that boot with
`sequence <= acknowledged_through`. A timeout, invalid JSON, unknown status,
mismatched boot, lower cursor, TLS error, or process crash deletes nothing.

The first slice supports at most 50,000 rows or 64 MiB, whichever comes first,
and a documented seven-day outage at the 10-second health interval. At either
limit the gateway sets `queue_state=full`, refuses new durable events, leaves the
database untouched, and remains running so it can upload existing rows and report
queue state. It never discards oldest rows. On `SQLITE_CORRUPT`, failed integrity
check, read-only storage, or failed fsync, it closes the database, marks service
health unhealthy, preserves the database and WAL files for an operator copy, and
may send only non-durable queue status until repair. Repair is an explicit offline
operation, not automatic truncation.

## HTTP contract

The gateway sends at most 100 events and 256 KiB encoded body per request:

```http
POST /api/gateway/v1/events/ HTTP/1.1
Authorization: Bearer egw1.<gateway>.<version>.<secret>
Content-Type: application/json
X-Request-ID: <random UUID>
```

```json
{
  "schema_version": 1,
  "gateway_id": "server-issued UUID",
  "gateway_boot_id": "gateway-generated UUID",
  "gateway_status": {
    "queue_state": "healthy",
    "queue_depth": 3,
    "oldest_queued_at": "2026-08-07T15:03:45.000Z",
    "gateway_version": "1.0.0"
  },
  "events": [
    {
      "schema_version": 1,
      "event_id": "UUID",
      "event_type": "sensor_health",
      "rack_number": 1,
      "logical_node_id": "wt901_0123456789abcdef01234567",
      "assignment_revision": 14,
      "sequence": 205,
      "occurred_at": "2026-08-07T15:04:05.123Z",
      "payload": {
        "agent_schema_version": 1,
        "sensor_state": "live",
        "sample_age_ms": 42
      }
    }
  ]
}
```

The client sends no `gym_id`. `gateway_id` must equal the credential's gateway but
does not grant scope. `gateway_status` is current request metadata rather than a
queued domain event: this lets a full, corrupt, or read-only queue report why it
cannot enqueue another health event. A request may contain zero events only when
`queue_state` is unhealthy; it receives no event acknowledgement and cannot
establish a new boot. Every object rejects unknown keys. Strings, integers, enums,
timestamps, count, and byte size have explicit bounds. Boolean values do not pass
integer validation. Timestamps must be UTC RFC 3339, no more than five minutes in
the future and no more than seven days old. The server uses receipt time for
freshness and ordering.

The response reports every structurally addressable event and one cursor:

```json
{
  "schema_version": 1,
  "gateway_boot_id": "UUID",
  "results": [
    {"event_id": "UUID", "sequence": 205, "result": "accepted", "code": "health_recorded"}
  ],
  "acknowledged_through": 205,
  "server_time": "2026-08-07T15:04:06.010Z"
}
```

### HTTP statuses

| Status | Meaning and gateway action |
|---|---|
| `200` | Authenticated batch has an item result for every event; apply only the returned contiguous acknowledgement |
| `400 invalid_batch` | Envelope, boot, sequence identity, JSON, or content type cannot be addressed safely; retain the entire batch and stop automatic retry until operator/config correction |
| `401 gateway_auth_invalid` | Missing, malformed, unknown, expired, or revoked credential; retain all rows and stop rapid retries |
| `409 gateway_boot_conflict` | Mixed boot IDs, non-1 first sequence for a new boot, or an impossible cursor transition; retain rows and require reconciliation |
| `413 batch_too_large` | Retain rows and retry a smaller bounded batch |
| `429 gateway_rate_limited` | Retain rows and honor bounded `Retry-After` |
| `503 gateway_ingest_unavailable` | No terminal decision; retain rows and retry with backoff |

Within `200`, `accepted`, `duplicate`, and `rejected` are terminal. `retry` is not
terminal and cannot advance `acknowledged_through`. Stable permanent codes include
`invalid_event_schema`, `gateway_identity_mismatch`, `unknown_node`,
`gateway_node_not_granted`, `stale_assignment_revision`, `stale_gateway_boot`,
`event_too_old`, `event_in_future`, and `invalid_health_value`. A gap returns
`retry/sequence_gap` for that item and `retry/blocked_by_sequence_gap` for later
items. A duplicate returns the stored terminal code and effect without another
health write or invalidation.

If an item has a valid event ID, boot ID, and sequence but an invalid payload or
unknown field, the server records a terminal rejection so it cannot block the queue
forever. If those addressing fields are malformed, the whole request is `400` and
nothing changes. This keeps neighboring event outcomes unambiguous.

## Transactions and locking

1. Nginx rejects oversized bodies before proxying. Django parses the bounded outer
   object and validates credential syntax without logging either.
2. Django authenticates the credential, then enters `transaction.atomic()` and
   locks `EdgeGateway` with `select_for_update()`. This serializes concurrent
   batches, credential rotation state, boot transitions, and cursor advancement.
3. The server loads or establishes `GatewayBoot`, then processes events in ascending
   contiguous sequence. Existing `(gateway,event_id)` or `(boot,sequence)` receipts
   return the stored result. If the two uniqueness keys identify different prior
   events, the item is permanently rejected as `event_identity_conflict` and no
   health state changes.
4. For a new event, Django locks `Node`, `GatewayNodeGrant`, and
   `GatewayNodeHealth`; checks credential scope, current rack, grant revision, boot,
   sequence, timestamp, and exact payload; then writes the health snapshot and
   terminal receipt.
5. A material staff-visible state transition creates one unpublished
   `MonitoringEvent` in the same transaction. Queue depth-only changes do not emit
   invalidations on every poll.
6. Django advances `GatewayBoot.acknowledged_through` only across contiguous
   terminal receipts, updates `EdgeGateway.last_contact_at` and its bounded queue
   summary from current request metadata, and commits before returning `200`.

A database error rolls back receipts, cursor, diagnostics, and invalidation together.
If the commit succeeds but the response is lost, retry finds the receipts and
returns duplicates with the same cursor.

## Freshness and diagnostics

The gateway polls the Agent and enqueues health every 10 seconds. Upload retries
start at 1 second, double to 60 seconds, use full jitter, honor bounded
`Retry-After`, and reset after a successful authenticated request.

- `online`: valid authenticated contact within 30 seconds.
- `stale`: no valid authenticated contact for more than 30 seconds.
- `sensor live`: latest accepted current-boot event says `live`, its Agent
  `sample_age_ms <= 1000`, and server receipt is no older than 15 seconds.
- `queue unhealthy`: latest report is `unhealthy`, `full`, `corrupt`, or
  `read_only`, regardless of gateway contact freshness.
- `revoked`: server gateway or current credential is revoked. Revoked overrides
  online/stale presentation.

`occurred_at` remains evidence only. It cannot extend online state, sensor freshness,
credential validity, a grant, or a future lease. A replayed old health event may
receive its terminal receipt but cannot make diagnostics fresh.

`GET /api/gateways/diagnostics/` uses JWT authentication plus `IsActiveStaff` and
returns the single gateway's label, state, last contact, last accepted boot/sequence,
queue state/depth/oldest age, per-rack derived sensor state, and server time. It
does not return credential metadata beyond `rotation_required`, source address,
Agent path, event ID, request body, node ID, BLE identity, label from discovery,
movement data, or host metadata. Non-staff, inactive staff, racks, athletes, and
gateway credentials receive `403` or `401` and no diagnostic body.

## Logging and audit

- Nginx and Gunicorn access logs are disabled globally for this diagnostics-only
  profile. Nginx emits only critical error logs; request credentials and bodies are
  never logged.
- Django security audit rows contain action, internal gateway row ID, credential
  version, server time, result code, and request ID. They contain no secret,
  digest, event ID, boot UUID, sequence payload, node ID, rack, source address,
  timestamp from the gateway, or body.
- The gateway logs state transitions and counts, such as `queue full` or
  `upload retry 503`, without credential, event JSON, UUIDs, node ID, Agent body,
  BLE data, file contents, or exception text from the Agent.
- Gunicorn/Nginx must not include the `Authorization` header in error pages or
  upstream logs. Django returns a generated request ID when the supplied one is
  absent or malformed.

## VPS Compose, TLS, and production startup

`docker-compose.vps.yml` is standalone rather than an overlay. It uses distinct
service, network, project, and volume names so `docker compose up` remains the local
profile. PostgreSQL has no `ports` entry and joins only an internal backend network.
Django and React have no host-published ports. Nginx alone publishes `80` and `443`;
it joins a dedicated routable network for those bindings and separate internal
networks for each upstream. SSH remains a host operation outside Compose. The VPS
profile includes neither Mosquitto, `mqtt-listener`, `monitoring-publisher`,
simulator, seed, host Agent sockets, `/run/edgeathlete`, nor the local PostgreSQL
volume.

Nginx terminates TLS 1.2/1.3 with an operator-provisioned publicly trusted
certificate mounted read-only. Port 80 redirects safe browser `GET`/`HEAD` requests
to HTTPS but rejects gateway POST requests without forwarding credentials or bodies.
The TLS virtual host sets HSTS after certificate validation, forwards the original
host/protocol, applies the 256 KiB gateway body limit, and proxies only to internal
services. Certificate issuance and renewal are host operations with an explicit
renewal alert; the app does not request certificates.

The VPS environment sets `DEBUG=False`, an explicit DNS host, secure proxy/cookie
settings, a generated Django secret, and generated PostgreSQL credentials. Startup
fails closed when a required value is absent, equals a documented development
default, TLS proxy settings are absent, or an active staff account still matches
`coachpass`. The VPS Django command runs `migrate`, a database preflight, and
Gunicorn but does not run `ensure_demo_coach`. Nginx allowlists only health, gateway
ingestion, staff authentication, and staff gateway diagnostics; private-AP APIs and
Django admin return `404`. Demo data commands and profiles are absent. Local Compose
keeps its existing optional seed flow unchanged.

## Data flow

```text
WT901BLE
  -> existing WT901 Agent (raw frames and BLE identity stay here)
  -> GET /v1/racks/{rack}/health over local mode-0600 UDS
  -> gateway whitelist + SQLite FULL-sync enqueue
  -> outbound TLS 443 POST with gateway bearer
  -> Nginx body/TLS boundary
  -> Django credential, grant, boot, sequence, and schema checks
  -> GatewayEventReceipt + GatewayNodeHealth + optional MonitoringEvent commit
  -> contiguous acknowledgement
  -> SQLite acknowledgement record + acknowledged-row deletion commit
  -> active-staff diagnostics refetch REST state
```

The VPS never calls the gym host. The gateway never receives coach JWTs, athlete
data, set context, NFC data, commands, or browser traffic in this slice.

## Failure modes

| Failure | Required behavior |
|---|---|
| Agent socket absent, denied, timed out, or malformed | Enqueue bounded `reconnecting` health only when the queue is writable; do not log the Agent response or switch to TCP/MQTT |
| DNS, route, TLS, certificate, or hostname failure | Retain rows, preserve certificate verification, retry with bounded jitter |
| VPS `429` or `503` | Retain rows; honor bounded retry delay |
| Response lost after commit | Retry; VPS returns stored duplicate results and the same contiguous cursor |
| Duplicate event ID or sequence | Return the original terminal result; no second health write or invalidation |
| Sequence gap | Do not infer loss or advance the cursor; retain gap and later rows |
| Gateway restart | Generate a new boot, drain old-boot rows first, then establish new boot with sequence 1 |
| Old boot after a newer boot | Return stored duplicate if known; otherwise terminally reject as stale without changing health |
| Stale assignment or revoked grant | Terminally reject, advance only when contiguous, and do not update diagnostics |
| Credential expired or revoked | Return generic `401`; preserve queue; no coach/MQTT fallback |
| Gateway clock skew | Reject beyond bounds; server time controls freshness and validity |
| SQLite full, corrupt, read-only, or fsync failure | Mark service unhealthy, accept no new durable event, preserve database/WAL, report current queue state without claiming durability, require operator recovery |
| PostgreSQL unavailable or transaction failure | Return `503`; write no receipt, cursor, health, or invalidation |
| Two concurrent uploads | Gateway row lock serializes them; uniqueness constraints prevent duplicate effects |
| Oversized or malformed request | Reject before unbounded parsing; do not log body |
| VPS deploy/restart | Gateway retries; receipt transaction preserves idempotency |

Health upload failure cannot fabricate a rep, alter a set, or change rankings because
the endpoint imports no rep/set service and the schema has no such fields.

## Security review

Security result: design pass for a synthetic/derived health staging slice, subject
to implementation review and the release blocks below.

- Authentication is least privilege and separate from SimpleJWT coach auth.
- Authorization derives gym and gateway from a digest-verified random credential.
- TLS and hostname verification are mandatory; no gym listener or anonymous public
  broker exists.
- Queue and server schemas exclude raw sensor, physical, athlete, NFC, and set data.
- UUID receipts, boot epochs, sequence cursors, assignment revisions, row locks,
  and uniqueness constraints handle replay and concurrent delivery.
- Rate limits apply per credential and at Nginx per source as defense in depth;
  source addresses are not retained in application diagnostics or audit logs.

Residual risk: malware or root compromise on the gym host can steal the bearer and
forge health until revocation. This slice does not claim hardware attestation.
Multi-gym tenant isolation, mTLS, package integrity, and automated gateway updates
require separate review before fleet rollout.

## Validation required before release

- Migration from `0021`, reverse to `0021`, forward again, and migration-drift check
  against seeded local data; verify node mappings and training rows do not change.
- Local `docker compose up` with all VPS variables absent; focused Django, frontend,
  WT901 Agent, `manage.py check`, and local profile smoke tests remain unchanged.
- Credential provision, valid auth, malformed/unknown/expired/revoked auth, 24-hour
  overlap rotation, wrong gateway ID, and no secret in database/log inspection.
- Strict schema, unknown fields, bounded bytes/counts, timestamps, enum and integer
  bounds, assignment revision, boot transition, stale boot, sequence gap, duplicate
  event ID, duplicate sequence, and identity-conflict tests.
- SQLite commit-before-success, restart, lost response, contiguous acknowledgement,
  no-delete on unknown response, 50,000-row/64-MiB limit, corruption, read-only disk,
  and failed-fsync tests.
- Kill network access after two events, queue three, restart the gateway, restore
  access, and observe one contiguous five-event outcome with an empty acknowledged
  queue and no duplicate health effect.
- External scan shows only approved HTTPS/SSH ports. Plain HTTP gateway POST is
  rejected. PostgreSQL, Django, MQTT 1883/9001, and Agent sockets are unreachable.
- Active staff can read diagnostics; authenticated non-staff, inactive staff,
  anonymous users, and gateway credentials cannot. Inspect responses and logs for
  every forbidden field listed above.
- Confirm `Set`, `Rep`, `RackRuntime`, rankings, records, reports, and insights are
  byte-for-byte/row-for-row unchanged after health replay.

No application or deployment implementation is approved for production until an
independent QA pass maps these checks to evidence and an independent security pass
reviews credential replay, tenant assumptions, TLS, queue tampering, and redaction.

## Rollback

1. Stop the gateway systemd service. Copy the SQLite database, WAL, service status,
   and last acknowledged ranges; do not delete or replay them into local mode.
2. Revoke the gateway credential and disable the VPS ingestion route.
3. Stop `docker-compose.vps.yml`. Preserve the VPS database and take a backup before
   reversing migration `0022`.
4. If schema reversal is required, export gateway receipts/diagnostics, verify no
   gateway is running, and migrate to `0021`. Existing local rows and rack mappings
   remain; hosted diagnostic history is removed.
5. Start the unchanged local profile against its local PostgreSQL volume and local
   credentials. Do not share VPS environment, gateway queue, or hosted database.

Rollback occurs between sessions even though this slice cannot operate a workout.
It does not establish that queued health was imported elsewhere.

## Deferred slices and release blocks

- Accepted-rep ingestion, detector qualification, active-set capability issuance,
  `LiveRackActivity`, and completion-boundary event fencing.
- Browser delivery, IndexedDB `event_id` deduplication, hidden-tab/controller
  recovery, and IndexedDB-before-render evidence.
- Multi-gym tenant foreign keys and tenant-scoped uniqueness across `Node`, racks,
  runtime, sessions, events, caches, realtime groups, admin, and backups.
- NFC opaque-reference derivation, enrollment, mapping, upload, one-consumer taps,
  and key rotation.
- Outbound command polling/WSS, BLE scan/bind/replace, command expiry, and idempotent
  command results.
- Multiple gateways, rack leases, replacement/handoff, eight-sensor qualification,
  mTLS reconsideration, automated installation/update, metrics, and historical data
  migration.
- Authenticated realtime browser delivery. The first slice uses staff REST polling
  and does not deploy public MQTT or WebSockets.

Until those slices are accepted, the hosted deployment is diagnostics-only. It
must reject every `event_type` except `sensor_health`, expose no workout start path
that depends on the gateway, and carry no claim that hosted workouts work offline
or online.
