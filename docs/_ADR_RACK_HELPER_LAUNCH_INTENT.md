# ADR: Rack Helper Launch Intent

- Date: 2026-08-10
- Status: Accepted; thin control-plane implementation authorized, signed release
  work blocked
- Related spec: [`_RACK_HELPER_SPEC.md`](_RACK_HELPER_SPEC.md)
- Related identity direction:
  [`_RACK_DASHBOARD_TEAM_REGISTRATION.md`](_RACK_DASHBOARD_TEAM_REGISTRATION.md)
- Related tenancy ADR: [`_ADR_COACH_WORKSPACE_TENANCY.md`](_ADR_COACH_WORKSPACE_TENANCY.md)
- Accepted identity ADR:
  [`_ADR_BROWSER_ENDPOINT_AND_HELPER_IDENTITY.md`](_ADR_BROWSER_ENDPOINT_AND_HELPER_IDENTITY.md)
- Accepted development runtime ADR:
  [`_ADR_RACK_HELPER_RUNTIME_LINUX_WINDOWS.md`](_ADR_RACK_HELPER_RUNTIME_LINUX_WINDOWS.md)

## Context

The Rack page needs one user action that starts or foregrounds an installed native
helper. A browser cannot reliably detect a custom-protocol handler, silently install
an application, or prove that a protocol invocation caused a process to start. Any
website can attempt to invoke a registered custom scheme.

The helper holds a credential and may reconnect BLE, drain queued events, or resume
an acquisition lease. Treating `edgeathlete-rack:launch` alone as authorization
would make the helper a confused deputy for an unrelated website.

The current `RackScreen`, controller capability, and `/api/racks/...` routes belong
to the private-AP compatibility profile. They are absent from VPS ingress and have
no organization ownership. This ADR does not expose or extend them. Hosted launch
uses the accepted organization-owned `BrowserEndpoint(kind=rack)` identity in the
endpoint/helper identity ADR.

## Existing Patterns

- `RackCommandReceipt` and Rack controller services use opaque IDs, idempotency,
  stable conflict codes, `transaction.atomic()`, and `select_for_update()`.
- Endpoint and helper credentials derive scope from authenticated server
  relationships, never request organization or endpoint IDs.
- Organization-scoped lookups return `404` for foreign objects and create no write.
- Cookie-authenticated endpoint mutations require CSRF and exact Origin validation.
- Helper ingress uses outbound HTTPS only; the helper opens no localhost or LAN
  listener.

## Decision

The Rack click creates a short-lived server launch intent before invoking one fixed
custom-protocol URI. The URI carries no capability or identity. A paired helper must
authenticate and atomically consume the current intent before BLE, upload, queue
drain, heartbeat mutation, or lease recovery. An unpaired helper may open only its
inert pairing UI; confirmed pairing can bind the current provisional intent to the
new installation.

The fixed URI is exactly:

```text
edgeathlete-rack:launch
```

The native protocol parser accepts exactly one OS-delivered argument with those
ASCII bytes. It rejects extra arguments, percent encoding, controls, NULs, malformed
Unicode, authorities, paths, queries, fragments, credentials, and trailing bytes
before dispatch. It never invokes a shell.

## Data Model

This ADR uses the accepted `BrowserEndpoint` and `RackHelperInstallation` models in
[`_ADR_BROWSER_ENDPOINT_AND_HELPER_IDENTITY.md`](_ADR_BROWSER_ENDPOINT_AND_HELPER_IDENTITY.md).
It adds these fields or records when those roots are implemented.

### `RackHelperLaunchIntent`

- `id`: server-generated UUID primary key and browser-visible attempt ID.
- `endpoint`: `PROTECT` foreign key to `BrowserEndpoint(kind=rack)`.
- `target_installation`: nullable `PROTECT` foreign key to
  `RackHelperInstallation`; null for a provisional intent created without an active
  installation and remains null if that intent terminates before binding.
- `state`: `pending|consumed|superseded|expired|cancelled`.
- `created_at`, `expires_at`: server times; expiry is five minutes.
- `consumed_at`: nullable server receipt time.
- `consumer_boot_id`: nullable helper-generated UUID.
- `consume_request_id`: nullable helper-generated UUID, unique with
  `target_installation` when present.
- `ack_cursor`: nullable positive bigint copied from the endpoint status cursor.
- `superseded_at`, `cancelled_at`: nullable server times.

A partial unique constraint permits at most one `state=pending` intent per endpoint.
Application code also locks the endpoint because expiry depends on server time and
cannot be represented in a useful uniqueness predicate.

Database checks enforce:

- `expires_at = created_at + five minutes`.
- `consumed` requires target installation, `consumed_at`, consumer boot,
  consume-request ID, and positive acknowledgement cursor.
- Every non-consumed state keeps consume fields and acknowledgement cursor null.
- `superseded` and `cancelled` require their matching timestamp; other states keep
  those timestamps null.

The endpoint-locked transition service enforces one-way movement from `pending` to
one terminal state. Terminal unbound provisional intents may keep
`target_installation` null.

### `RackHelperLaunchConsumeReceipt`

- `installation`: `PROTECT` foreign key to `RackHelperInstallation`.
- `consume_request_id`: helper-generated UUID, unique with installation.
- `helper_boot_id`: helper-generated UUID.
- `intent_id`: copied UUID, not a foreign key to the short-lived intent row.
- `acknowledged_at`: server receipt time.
- `ack_cursor`: positive bigint.

The receipt reconstructs the immutable successful consume response after the intent
row is deleted. Receipts remain for the active installation's lifetime and until 24
hours after installation revocation. They are then deleted with the retired
installation's authorization history. Because a revoked installation cannot consume
another intent, deleting its receipts cannot bind an old retry to a new launch.
Service-wide capacity monitoring uses the accepted create throttle as its upper
bound; production blocks new intent creation before receipt storage reaches its
reviewed limit.

### Endpoint Status Fields

`BrowserEndpoint` owns:

- `helper_status_cursor`: positive bigint, starting at one.
- `helper_status`: one of the cloud-visible states in the Rack Helper spec.
- `helper_status_at`: nullable server receipt time.
- `last_launch_intent`: nullable `SET_NULL` foreign key.

The endpoint-scoped snapshot returns the current helper status and, when authorized,
the caller's requested launch-intent state. Cursors order changes; they never grant
access.

## Interface Contract

The operation semantics, URLs, and wire shapes below are accepted in
[`../_MESSAGE_CONTRACT.md`](../_MESSAGE_CONTRACT.md). Exact public route inclusion
still requires implementation tests and VPS allowlist review.

### Create Intent

```http
POST /api/rack/v1/helper-launch-intents/
```

Authentication uses the host-only Rack endpoint cookie. The exact request body is
the empty JSON object `{}`.
The server requires CSRF, exact application Origin, `BrowserEndpoint(kind=rack)`,
and an active endpoint assignment. Organization, endpoint, installation, and return
URL fields are rejected rather than ignored.

Success returns `201`:

```json
{
  "intent_id": "UUID",
  "expires_at": "UTC RFC 3339 timestamp",
  "launch_uri": "edgeathlete-rack:launch",
  "create_status_cursor": 41
}
```

The transaction locks the endpoint, then its single current active installation if
one exists. It revalidates that endpoint, installation, assignment, and organization
agree, marks every prior pending intent `superseded`, creates the new intent with
that installation as target or null when no active installation exists, and sets
`last_launch_intent`. It increments the endpoint status cursor once and returns
that committed value as `create_status_cursor`. Commit order is the deterministic
winner for concurrent Rack tabs.

### Inspect Intent

```http
POST /api/rack/v1/helper-launch-intents/inspect/
Content-Type: application/json

{
  "intent_id": "UUID"
}
```

The same endpoint cookie, CSRF check, and exact Origin policy apply. Request bodies
are excluded from proxy, application, and APM logs. The endpoint may inspect only
its own intent; foreign, malformed, and unknown IDs return the same `404`. Every
response sends `Cache-Control: no-store`. The bounded response is:

```json
{
  "intent_id": "UUID",
  "state": "pending|consumed|superseded|expired|cancelled",
  "expires_at": "UTC RFC 3339 timestamp",
  "acknowledged_at": "UTC RFC 3339 timestamp or null",
  "ack_cursor": 42,
  "current_status_cursor": 44,
  "helper_status": "exact status enum or null"
}
```

The exact status enum is:

```text
pairing_required | launching | no_sensor | scanning | verifying | ready
active_online | active_offline | stopping | draining | released | stale
credential_revoked | authentication_blocked | sensor_reconnecting
queue_full | queue_corrupt | keychain_unavailable | update_required
queue_unsafe | queue_read_only | queue_write_failed
endpoint_reassigned | recovery_required
```
`ack_cursor` and `acknowledged_at` are null unless this intent was consumed and never
change afterward. `current_status_cursor` and `helper_status` may reflect later
heartbeats. The browser accepts an acknowledgement only when its immutable
`ack_cursor` exceeds the create response's `create_status_cursor` and its server
acknowledgement time follows intent creation.

Inspection marks an expired pending intent `expired` under the endpoint lock. The
browser's five-second acknowledgement wait does not expire the five-minute intent.

### Consume Intent

```http
POST /api/rack-helper/v1/launch-intents/consume/
Authorization: RackHelper <credential>
Content-Type: application/json

{
  "helper_boot_id": "UUID",
  "consume_request_id": "UUID"
}
```

Helper authentication derives installation and endpoint. The server locks endpoint
then installation and first validates the credential, inactivity/expiry, current
installation authority, endpoint assignment, and organization consistency. It then
resolves an existing `(installation, consume_request_id)` before looking for a
pending intent. An existing request with matching boot data returns its immutable
receipt response. Otherwise it locks the current pending intent and verifies intent
expiry and target installation. It then atomically:

1. Verifies that `target_installation` is this authenticated installation.
2. Changes the intent to `consumed` and stores server `consumed_at`, boot ID, and
   consume-request ID.
3. Increments `helper_status_cursor`.
4. Stores `helper_status=launching`, `helper_status_at`, `last_launch_intent`, and
   the same cursor as `ack_cursor`.
5. Creates the immutable consume receipt.

Success returns `200`:

```json
{
  "intent_id": "UUID",
  "acknowledged_at": "UTC RFC 3339 timestamp",
  "ack_cursor": 42,
  "next": "reconcile"
}
```

A helper creates and durably retains one consume-request UUID for each protocol
dispatch, reusing it only to retry that consume request. A response lost after
commit is idempotent for the same installation and consume-request ID even when a
newer intent now exists; retry returns the original body. A later launch in the same
boot uses a new consume-request ID. Reusing one request ID with changed boot data
returns `409`:

```json
{
  "code": "consume_request_conflict",
  "detail": "The consume request cannot be reused."
}
```

An authorized installation without a consumable intent receives `409`:

```json
{
  "code": "launch_intent_unavailable",
  "detail": "No launch request is available."
}
```

The failure creates no heartbeat, status, lease, queue, pairing, sensor, or set
write. Authentication failure uses the generic helper-authentication contract.

VPS Nginx uses exact or anchored route-and-method allowlist entries for only these
hosted operations. It must not add a broad `/api/rack` prefix because that also
matches legacy `/api/racks/...` compatibility routes. The `/api/` public deny
fallback remains. Allowlist tests cover every legacy Rack route and prefix-confusion
variant as public `404`.

## First-Pairing Binding

Before helper enrollment, an intent is endpoint-scoped and non-consumable. The
pairing-confirmation transaction locks endpoint and pairing, then inserts a
`RackHelperInstallation(state=pending_activation)` with no active credential and
`activation_expires_at` equal to bootstrap expiry. Installation states are
`pending_activation|active|expired|cancelled|revoked`. A partial constraint permits
one pending or active installation per endpoint. Concurrent confirmation serializes
on the endpoint; only one provisional installation can survive. The proposed
credential UUID and digest bind to that provisional row.

After durable keychain storage, the confirmed activation transaction locks in this
order:

1. `BrowserEndpoint`.
2. Pairing row.
3. Existing provisional helper installation.
4. Current pending launch intent.

It revalidates endpoint, organization, pairing, and installation relationships,
proves credential possession, activates the installation and credential, and binds
the latest unexpired provisional intent to that installation in one transaction. A
superseded or expired intent is not revived. Failure rolls back activation and
intent binding together; the provisional installation remains non-authoritative for
reviewed retry or expiry. The helper then authenticates normally and calls consume.
Without a current intent, the independent coach-confirmed pairing API may still
activate the credential, but protocol handling itself made no pairing mutation and
BLE/helper status remain inert until another Rack click.

Bootstrap expiry, pairing cancellation, replacement, revocation, and abandoned
process cleanup lock the endpoint then provisional installation. They move
`pending_activation` to `expired`, `cancelled`, or `revoked`, destroy pending
credential and bootstrap material, and ensure no active credential exists. Cleanup
runs before a new pairing inserts its provisional row; a terminal provisional row
cannot block the partial uniqueness constraint and is deleted from the primary
database after 24 hours. Expiry versus activation revalidates under the same
endpoint lock, so exactly one terminal outcome commits.

## Concurrency And Expiry

All creation, consumption, cancellation, pairing binding, and endpoint replacement
lock `BrowserEndpoint` first. This prevents deadlocks and defines race outcomes:

- Two creates: later commit supersedes the earlier pending intent.
- Create versus consume: whichever holds the endpoint lock first completes; consume
  either commits the old intent before the new one exists or consumes the new
  current intent after supersession.
- Two consumes: one commits; the same installation and consume-request ID retries
  idempotently, while a distinct request ID sees no pending intent.
- Lost response, new create, then retry: lookup by consume-request ID returns the
  first acknowledgement without consuming the new intent.
- Endpoint reassignment, helper replacement, revocation, or unpairing cancels the
  current intent in the same endpoint transaction.
- Server time alone controls the five-minute expiry.

At the start of create, inspect, consume, pairing binding, internal cancellation,
and cleanup, the endpoint-locked service marks its pending intent expired when
`expires_at <= server_now` before evaluating the requested transition.

Cancellation is an internal transition only; this ADR exposes no cancellation API.
Endpoint reassignment, replacement, revocation, unpairing, and compatibility
rollback invoke the shared endpoint-locked service. Quitting an inert helper UI does
not cancel an intent; it remains pending until superseded, expired, or cancelled by
one of those server transitions. Internal cancellation is idempotent for an already
cancelled intent. Only the first `pending -> cancelled` transition increments the
endpoint status cursor; a repeat returns the existing result without another write.
Cancellation does not alter a consumed or other terminal intent.

A scheduled cleanup task runs once per minute. One invocation executes at most ten
transactions of at most 1,000 rows each and stops after 45 seconds; invocations do
not overlap. Before enabling production admission, a load test must prove all
10,000 rows complete within 45 seconds. Otherwise the service-wide create throttle
is lowered until measured cleanup capacity is at least ten times admitted volume.
Production monitors that margin. For each endpoint it locks the endpoint before
marking pending rows with
`expires_at <= server_now` as `expired`. It selects terminal rows at age 23 hours 55
minutes and deletes them before age 24 hours while the primary database is writable.
Failures retry on the next minute. A backlog projected to cross 24 hours blocks new
intent creation and alerts operators. Cleanup uses the same endpoint-first lock
order, so create or consume either completes before cleanup or revalidates after it.
The same job deletes consume receipts only when their installation has been revoked
for at least 24 hours; no revoked installation can authenticate a later consume.
Encrypted replicas and backups follow the deployment retention ADR; the 24-hour
deletion claim applies to the writable primary database, not immutable backup media.

## Security And Privacy

- Intent IDs are attempt correlation IDs, not capabilities. Only the authenticated
  endpoint can create or inspect them; only the scoped helper can consume one.
- The protocol URI contains no intent ID, endpoint ID, credential, pairing code,
  organization, team, sensor, context, command, path, or return URL.
- Creating an intent requires a deliberate click, endpoint authentication, CSRF,
  exact Origin validation, and endpoint/source/service throttles.
- Without a pending intent, a malicious website can open only inert helper UI. It
  cannot create the server-side intent because endpoint cookies are host-only and
  SameSite strict.
- A prior legitimate Rack click is standing authorization for five minutes. During
  that window, an unrelated website can invoke the empty URI and cause the helper
  to consume the already-authorized intent sooner than the Rack invocation would.
  The helper still acts only for the endpoint and installation authorized by the
  Rack click. This nuisance-launch window is accepted to avoid a second native
  confirmation; it grants no authority without the prior Rack intent.
- Logs may contain stable result codes and bounded aggregate counts, but not intent
  IDs, consume-request IDs, endpoint IDs, helper boot IDs, credentials, source IPs,
  or arbitrary protocol input.
- Terminal intent rows remain in the primary database no more than 24 hours. Audit
  retention stores actor class, result code, and timestamps without identifiers or
  request bodies under the deployment policy; encrypted backup retention follows
  that deployment policy.

Initial create throttles are ten per endpoint per minute, twenty per trusted source
address per 15 minutes, fifty per organization per hour, and 1,000 service-wide per
minute. Before helper credential parsing, consume applies twenty attempts per
trusted source address per minute, followed by twenty per resolved installation per
minute and 1,000 service-wide per minute. Rejected attempts count. Counters use the
deployment's shared atomic throttle store; per-process memory counters are
forbidden. Every exceeded scope returns the same bounded `429` body. The public
proxy strips inbound forwarding headers and supplies the only trusted source
address; forged forwarding headers cannot change a throttle key. A security ADR may
lower but not remove these scopes.

## Failure Behavior

- Handler absent, denied, or not consumed: intent remains pending until consumption,
  supersession, cancellation, or five-minute expiry; the browser shows unconfirmed
  and applicable download guidance after five seconds.
- Cloud unavailable before create: browser does not invoke the protocol and shows a
  retryable launch error.
- Cloud unavailable after protocol invocation: helper remains inert because it
  cannot consume an intent.
- Pairing outlasts intent expiry: pairing may finish, but helper remains inert until
  a new Rack click.
- Status response lost after consumption: the same consume-request ID retries and
  receives the prior acknowledgement even if a new intent now exists.
- Browser closes after create: intent expires; helper may consume it only before
  expiry and remains scoped to the same endpoint.
- Restart or autostart without a new intent: helper UI is inert and BLE remains
  disconnected.

## Migration And Rollback

The launch-intent migration is additive and must land with the accepted
`BrowserEndpoint` and helper-installation migrations. Before customer use, it may
roll back by deleting launch-intent rows and status fields.

After helper launch is enabled, rollback follows a compatibility deployment:

1. Disable new creates and consumes while preserving inspect and status reads.
2. Cancel or expire pending intents under endpoint locks.
3. Stop new capture, resolve open sets, drain or quarantine queues, and release
   leases for every `launching`, operational, stopping, draining, stale, blocking,
   or recovery state.
4. Deploy browser, server, and helper versions that no longer read or write launch
   fields; verify no older helper consumer remains.
5. Remove exact ingress routes, throttles, cleanup jobs, constraints, status writers,
   and then schema fields in that order.
6. Rehearse rollback with active, offline, queued, and response-loss fixtures.

The `/api/` deny fallback and explicit legacy `/api/racks/...` public `404` tests
remain throughout rollback. Protocol registration may remain inert until the native
package is uninstalled; it never becomes authority by itself.

## Alternatives Considered

| Option | Decision | Reason |
|---|---|---|
| Server launch intent plus fixed empty URI | Accepted | Preserves user-click evidence without putting scope or secrets in OS/browser URL handling |
| Custom URI containing a bearer token or endpoint ID | Rejected | Leaks capability or identity through browser history, process arguments, and OS handler records |
| Trust any custom-protocol invocation | Rejected | Any website could trigger credential-backed BLE or queue behavior |
| Localhost callback or helper status server | Rejected | Violates the no-listener boundary and adds browser-to-native attack surface |
| Inert UI requiring a second native confirmation every time | Deferred fallback | Secure but adds a redundant daily action; use only if platform protocol handling cannot satisfy this contract |

## Acceptance Evidence

- Model tests for one pending intent, terminal retention, and endpoint ownership.
- Transaction tests for create/create, create/consume, consume/consume, pairing bind,
  replacement, revocation, response loss followed by new create and retry, and
  create-versus-cleanup races.
- API tests for CSRF, Origin, cookie scope, foreign IDs, exact-`{}` validation,
  throttles, stable errors, and zero-write failures.
- Browser tests for one create and one protocol invocation per click, five-second UI
  fallback, superseded attempts, and server-cursor acknowledgement binding.
- Helper parser vectors for exact URI bytes, extra OS arguments, encoding, controls,
  NULs, malformed Unicode, authority/path/query/fragment input, and no shell use.
- Security tests in which a malicious origin invokes the scheme with no intent and
  produces zero writes, then with a legitimate outstanding intent and can trigger
  only that intent's already-authorized endpoint/installation behavior.
- Listener scans in protocol, launch, unconfirmed, pairing, and recovery states.
- Constraint tests for every state/nullability check and terminal transition.
- Cleanup tests for abandoned pending expiry, 24-hour primary deletion, bounded
  batches, provisional-installation expiry versus activation/new pairing,
  installation-lifetime consume receipts, late retry after intent cleanup, repeated
  internal cancellation, and cleanup/create/consume races.
- Rollback rehearsal with ready, active, offline, queued, blocking, response-loss,
  and older-helper fixtures.

| Acceptance criterion | Required evidence |
|---|---|
| AC26 | Exact status-enum serialization and Rack action matrix for every status |
| AC27 | Endpoint-authenticated create, CSRF/Origin, single protocol invocation, and concurrent-create tests |
| AC28 | Immutable acknowledgement cursor, consume-request retry, later-heartbeat cursor, and concurrent-tab tests |
| AC29 | Five-second browser wait versus five-minute server expiry, inspect, supersession, and retry tests |
| AC30 | Exact parser vectors, inert no-intent launch, independent pairing boundary, and outstanding-intent nuisance test |
| AC31a-c | Remain blocked on the separate release-catalog/package-trust ADR and its artifact evidence |

Planned repository validation after implementation:

```bash
docker compose run --rm --no-deps django python manage.py test event_handler
docker compose run --rm --no-deps django python manage.py check
docker compose run --rm --no-deps django python manage.py makemigrations --check --dry-run
npm --prefix react test -- --run
npm --prefix react run build
```

The native parser command and per-OS protocol/manual evidence must be added by the
runtime ADR; this ADR does not invent a command before the runtime exists.

## Implementation Gates

The identity ADR accepts the organization-owned `BrowserEndpoint(kind=rack)`,
endpoint cookie/CSRF/Origin behavior, helper installation/pairing/credential,
inactivity expiry, status snapshot, cursor, PostgreSQL throttling, and cleanup. The
runtime ADR selects the unsigned development runtime and exact Linux/Windows
protocol parser. `_MESSAGE_CONTRACT.md` accepts launch create, inspect, consume,
status enum, stable errors, and cache/header wire formats.

Those decisions authorize the thin launch control-plane implementation. Exact VPS
route allowlisting, migration tests, transaction/race tests, browser tests, runtime
parser evidence, QA, and security review remain implementation exit criteria rather
than architecture blockers.

The release catalog/package-trust ADR remains required before download UI, signed
installer claims, customer distribution, or updates ship. Physical BLE and rep
ingestion remain blocked by the identity/runtime ADR exclusions. The current
private-AP `RackScreen` routes remain unchanged and absent from VPS ingress.
