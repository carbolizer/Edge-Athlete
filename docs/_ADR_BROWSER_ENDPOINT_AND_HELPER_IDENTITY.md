# ADR: Browser Endpoint And Rack Helper Identity

- Date: 2026-08-10
- Status: Accepted for the thin hosted Rack control plane
- Related direction: [`_RACK_DASHBOARD_TEAM_REGISTRATION.md`](_RACK_DASHBOARD_TEAM_REGISTRATION.md)
- Related tenancy ADR: [`_ADR_COACH_WORKSPACE_TENANCY.md`](_ADR_COACH_WORKSPACE_TENANCY.md)
- Related launch ADR: [`_ADR_RACK_HELPER_LAUNCH_INTENT.md`](_ADR_RACK_HELPER_LAUNCH_INTENT.md)
- Wire contract: [`../_MESSAGE_CONTRACT.md`](../_MESSAGE_CONTRACT.md)

## Context

The hosted Rack needs an organization-owned browser identity before it can create a
launch intent or display helper state. The helper needs a separate installation and
credential because a browser cookie cannot authorize a native process. The current
`RackScreen.device_id`, Rack number, coach JWT, pairing code, and custom-protocol URI
do not grant hosted Rack or helper authority.

This ADR authorizes only endpoint enrollment, helper enrollment, activation,
authenticated status, and the already accepted launch-intent operations. It does
not authorize BLE acquisition, derived-event upload, permanent `Rep` creation,
set completion, sensor transfer, package download, or public coach registration.

## Decision

Add one `BrowserEndpoint(kind=rack)` identity and one independently revocable helper
installation per hosted Rack. Both derive organization and TrainingGroup scope from
server relationships. Request bodies never select an organization or endpoint after
authentication.

The thin control plane uses outbound HTTPS and PostgreSQL only. The helper opens no
listener. The VPS exposes exact method-and-path allowlist entries and retains its
public `/api/` deny fallback. Existing `/api/racks/...` private-AP routes remain
unmodified and publicly return `404`.

## Models

### `BrowserEndpoint`

- `id`: server-generated UUID primary key.
- `organization`: `PROTECT` foreign key.
- `training_group`: nullable `PROTECT` foreign key in the same organization.
- `kind`: `rack` for every route accepted by this ADR.
- `display_name`: 1-80 trimmed Unicode characters.
- `endpoint_revision`: positive bigint starting at one.
- `state`: `active|unpaired|revoked`.
- `helper_status_cursor`: positive bigint starting at one.
- `helper_status`: nullable accepted helper status.
- `helper_status_at`: nullable server receipt time.
- `helper_status_boot_id`: nullable helper-generated UUID.
- `created_at`, `updated_at`, `last_seen_at`, `revoked_at`: server times.

Transactional application services require the TrainingGroup and endpoint to share
an organization and resolve both through that organization; the migration audits
all existing relationships before making ownership non-null. Database constraints
enforce field state, kind, uniqueness, and nullability. Assignment or
organization-safe reassignment locks the endpoint, increments `endpoint_revision`,
cancels pending launch and helper pairing rows, revokes incompatible helper
authority, and clears helper status. This ADR does not expose reassignment or
unpair operations.

### `EndpointCredential`

- `id`: UUID carried in the credential token.
- `endpoint`: `PROTECT` foreign key.
- `secret_digest`: unique, domain-separated SHA-256 digest of the decoded secret.
- `version`: positive integer, starting at one.
- `state`: `active|revoked`.
- `issued_at`, `last_used_at`, `revoked_at`: server times.

At most one endpoint credential is active. The cookie value has this exact ASCII
form:

```text
eae1.<canonical-lowercase-UUID>.<43-character-canonical-unpadded-base64url>
```

The final component decodes to exactly 32 bytes. Whitespace, padding, alternate UUID
forms, non-ASCII input, extra separators, and decoded lengths other than 32 bytes
are malformed. Parsing is bounded before lookup and uses constant-time digest
comparison.

The response cookie is exactly:

```text
ea_rack_endpoint=<eae1 token>; Max-Age=31536000; Path=/api/rack/v1/; Secure; HttpOnly; SameSite=Strict
```

It is host-only: no `Domain` attribute is sent. A successful endpoint-authenticated
status response refreshes the same rolling one-year `Max-Age`; it does not rotate
the credential. Revocation remains authoritative, and an endpoint unused beyond the
cookie lifetime must pair again.

### `EndpointPairing`

- `id`: server-generated UUID.
- `code_digest`, `bootstrap_digest`: separate keyed, domain-separated digests.
- `credential_id`: UUID reserved for the eventual endpoint credential.
- `state`: `pending|claimed|delivered|expired|cancelled`.
- `endpoint`: nullable `PROTECT` foreign key until claim.
- `attempt_count`: non-negative integer.
- `created_at`, `expires_at`, `claimed_at`, `delivered_at`: server times.

The pairing code is exactly eight uppercase Crockford Base32 characters excluding
`I`, `L`, `O`, and `U`. It has 40 bits of CSPRNG entropy, is one-time, and expires
after five minutes. The independent bootstrap capability is 32 random bytes in an
HttpOnly host-only `ea_rack_endpoint_pairing` cookie with `Secure`,
`SameSite=Strict`, and `Path=/api/rack/v1/endpoint-pairings/`. Pairing responses and
request bodies use `Cache-Control: no-store` and are excluded from access,
application, APM, and error-body logging.

After an authorized coach claims the code for one organization-owned TrainingGroup,
the endpoint status operation derives the `eae1` secret from the bootstrap
capability, pairing UUID, credential UUID, and a deployment credential-derivation
key. It stores only the credential digest, sets `ea_rack_endpoint`, marks the
pairing delivered, and deletes the bootstrap cookie. A lost delivery response may
repeat this derivation until delivery or expiry and returns the same credential.
The deployment key is a secret with documented rotation and backup handling; it is
never stored in PostgreSQL or application logs.

### `RackHelperInstallation` And Credential

`RackHelperInstallation` has a server-generated UUID, endpoint `PROTECT` foreign
key, `pending_activation|active|expired|cancelled|revoked` state, platform
(`linux_x64|windows_x64`), contract version, created/activated/last-contact times,
24-hour inactivity expiry, and revocation time. A partial uniqueness constraint
allows one pending or active installation per endpoint.

`RackHelperCredential` has the UUID carried in its token, installation `PROTECT`
foreign key, domain-separated SHA-256 secret digest, positive version, state
`pending|active|revoked`, and issued/activated/last-used/revoked times. There is one
pending or active credential per installation. The exact token form is:

```text
earh1.<canonical-lowercase-UUID>.<43-character-canonical-unpadded-base64url>
```

The parser applies the same 32-byte, canonical, bounded rules as `eae1`. It is sent
only as `Authorization: RackHelper <earh1 token>`. It never enters a URL, cookie,
browser storage, log, crash report, or pairing-code display.

The helper generates its token and a separate 32-byte bootstrap capability, stores
both in the OS keyring before claim, and submits them over HTTPS. The server stores
only their domain-separated digests. Coach confirmation creates the provisional
installation and pending credential. Activation proves possession by presenting
the same `earh1` token. This thin protocol replaces the Rack Helper spec's proposed
HPKE credential-delivery ceremony; no credential is delivered by the server.

### `RackHelperPairing`

The pairing row stores endpoint, code digest, bootstrap digest, proposed credential
UUID and digest, platform, contract version, confirmation-phrase digest, state
`pending|claimed|confirmed|activated|expired|cancelled`, attempt count, and server
times. Code syntax and five-minute expiry match endpoint pairing. The six-word
confirmation phrase comes from 66 bits of domain-separated SHA-256 over pairing ID,
endpoint ID, proposed credential ID and digest, bootstrap digest, and server nonce,
mapped to the repository's fixed 2,048-word list. The browser and helper compare
the same phrase; the coach confirmation body repeats no phrase and confirms the
same short-lived eight-character code already shown by the endpoint-authenticated
Rack and entered in the Helper. The pairing UUID remains internal to Helper polling
and activation; the coach confirmation response does not return it.

Claim, confirmation, activation, expiry, replacement, and cleanup lock
`BrowserEndpoint` first, then pairing, installation, and credential. Confirmation
does not activate authority. Activation requires durable keyring storage first,
valid bootstrap state, credential possession, current endpoint assignment, and an
unexpired pairing. It atomically activates installation and credential and binds
the latest unexpired provisional launch intent as specified by the launch ADR.

## CSRF And Origin

`GET /api/rack/v1/csrf/` sets a host-only, `Secure`, non-HttpOnly
`ea_rack_csrf` cookie with `SameSite=Strict` and `Path=/api/rack/v1/`, and returns
the same value as `{"csrf_token":"<opaque token>"}` in its no-store response.
The Rack keeps the response value in memory because browsers do not expose an
API-path cookie to JavaScript running at `/rack`. Every endpoint-cookie mutation
sends that value in `X-CSRFToken`.

The server accepts an endpoint-cookie mutation only when all of these are true:

- The request has exactly one `Origin` header.
- Its parsed scheme, ASCII host, and effective port equal the one configured
  canonical public application origin.
- The origin uses HTTPS, contains no user information, path, query, or fragment,
  and is neither `null` nor a suffix/subdomain match.
- The CSRF header and cookie are present, bounded, well formed, and equal under
  constant-time comparison.

There is no `Referer` fallback. Missing, duplicate, malformed, HTTP, foreign, or
`null` Origin fails before domain lookup or write. CORS does not weaken this rule.

## Status And Freshness

An activated helper may write status only after its current boot consumed a launch
intent. It posts every 15 seconds while running. Each new idempotency UUID commits
one endpoint cursor increment and one server receipt time; retrying the same UUID
and body returns the original response without another increment. Reusing the UUID
with changed bytes returns `409 status_request_conflict`.

The accepted cloud status enum remains:

```text
pairing_required | launching | no_sensor | scanning | verifying | ready
active_online | active_offline | stopping | draining | released | stale
credential_revoked | authentication_blocked | sensor_reconnecting
queue_full | queue_corrupt | keychain_unavailable | update_required
queue_unsafe | queue_read_only | queue_write_failed
endpoint_reassigned | recovery_required
```

`pairing_required`, `stale`, and `released` are server-derived and cannot be posted
by the helper. `launching` is written only by launch-intent consumption. The helper
may post the other values, although this ADR does not authorize the physical
behavior implied by `scanning`, `verifying`, `ready`, either active state, or sensor
reconnection.

Freshness uses server receipt time only. A heartbeat-derived status is fresh while
`server_now < helper_status_at + 60 seconds`; at equality it is stale. Endpoint
reads return `stale` without first writing a row when an active installation has a
heartbeat-derived or `launching` status at or beyond that deadline. The next valid
status write advances the cursor and replaces stale display. `pairing_required`
applies when no active installation exists. `released` remains released without
heartbeats. Missing heartbeat never proves BLE disconnection.

## PostgreSQL Throttling

The control plane uses `ControlPlaneThrottleBucket` rows rather than process memory
or a new cache service. A row contains scope enum, HMAC-SHA-256 key digest, fixed
window start, count, and expiry, unique on `(scope, key_digest, window_start)`.
An atomic upsert increments the row before business lookup; rejected requests count.
Source keys use the address supplied by the only trusted proxy after it strips
inbound forwarding headers. Raw addresses, codes, tokens, and endpoint IDs are not
stored in throttle rows.

Initial limits are:

| Operation | Limits |
|---|---|
| Endpoint pairing create | 10/source/15 minutes; 1,000/service/minute |
| Endpoint coach claim | 5/code; 20/coach/hour; 50/organization/hour; 1,000/service/minute |
| Helper claim | 5/pairing; 10/source/15 minutes; 20/endpoint/hour; 50/organization/hour; 1,000/service/minute |
| Helper confirm | 20/coach/hour; 50/organization/hour; 10/pairing; 20/endpoint/hour; 1,000/service/minute |
| Helper activate | 10/pairing; 20/endpoint/hour; 1,000/service/minute |
| Endpoint status read | 120/endpoint/minute; 2,000/service/minute |
| Helper status write | 20/installation/minute; 2,000/service/minute |

The launch-intent limits in its ADR use the same PostgreSQL bucket service. A limit
may be lowered without a contract change but not removed or raised without security
review. Every limit response is `429`, carries integer `Retry-After`, and returns
`{"code":"rate_limited","detail":"Too many requests.","retry_after_seconds":N}`.

## Cleanup And Retention

A non-overlapping task runs once per minute for at most 45 seconds and processes at
most ten transactions of 1,000 rows. It uses server time and the endpoint-first lock
order.

- Pending endpoint/helper pairings become expired at five minutes. Code and
  bootstrap digests are cleared immediately; terminal rows leave the writable
  primary within 24 hours.
- A helper pending activation expires when its pairing expires. Its pending
  credential digest is destroyed and the row leaves the primary within 24 hours.
- Active helper authorization expires after 24 hours without authenticated contact.
  Expiry revokes its credential and cancels its pending launch intent atomically.
- Revoked endpoint/helper credential rows remain for 24 hours to make in-flight
  authentication fail closed, then are deleted with terminal pairing and launch
  authorization history where foreign-key constraints permit.
- Throttle buckets are deleted after their window plus 24 hours.
- Launch intents and consume receipts follow the launch ADR's stricter rules.
- Each installation's replay-safe consume ledger is capped at 10,000 rows. The
  service denies new launch admission at capacity without deleting replay evidence.

Cleanup failure denies new pairings and launch creates before any backlog can cross
its promised primary-database retention. Encrypted backup retention belongs to the
deployment ADR and is not covered by primary-row deletion.

The backend dependency is pinned to `Django==5.2.17`, the current available 5.2 LTS
patch returned by the public Python package index on 2026-08-10. This repository
does not claim an external artifact digest because no reviewed digest source is
maintained here; image builds resolve the exact version from the configured index.

## Stable Failure Rules

All control-plane responses use JSON and `Cache-Control: no-store`. Empty mutations
accept exactly `{}`; no body, `null`, arrays, or extra fields return `400
invalid_request`. Malformed JSON is `400 invalid_json`. Unsupported methods return
`405`; public routes not explicitly allowlisted return Nginx `404`.

Endpoint authentication failure is `401 endpoint_authentication_failed`. Helper
authentication failure is `401 helper_authentication_failed`. CSRF or Origin failure
is `403 csrf_failed`. A foreign, unknown, or malformed scoped identifier returns the
same `404 not_found`. Authentication, CSRF, and throttling failures create no domain
write. Exact bodies for accepted operations are in `_MESSAGE_CONTRACT.md`.

## Security And Privacy

- Pairing codes are onboarding correlation, not persistent credentials.
- Coach claims require one active organization membership and authorization to
  manage the selected TrainingGroup. Global `is_staff` alone grants no hosted
  endpoint-management authority.
- Endpoint and helper requests derive every scope from the authenticated credential.
- Logs may contain route name, status code, stable result code, and aggregate count.
  They exclude credentials, cookies, CSRF values, codes, pairing/endpoint/
  installation IDs, source addresses, request bodies, and arbitrary exceptions.
- The helper credential cannot read rosters, act as a coach, select an endpoint,
  create a set, upload an event, or consume another installation's launch intent.
- Endpoint pairing and helper pairing are independent. Protocol launch may show an
  inert pairing UI but cannot claim, confirm, or activate a pairing.

## Migration And Rollback

The migration is additive. Before public use, rollback may disable exact ingress
routes, expire pairing and launch rows under endpoint locks, revoke credentials,
delete control-plane rows, and reverse the schema. After a customer endpoint is
paired, rollback must export endpoint-to-organization/TrainingGroup assignment and
revocation history; silently dropping ownership would merge tenant authority and is
forbidden.

## Consequences And Gates

This ADR and the revised message contract satisfy the endpoint identity, endpoint
cookie/CSRF, endpoint pairing, helper pairing/credential, status snapshot, freshness,
PostgreSQL throttle, and cleanup gates in the launch ADR. The thin implementation
may add only the listed models, services, exact routes, tests, and development helper
integration.

The following remain blocked:

1. BLE scan, connection, frame decoding, detector acceptance, and physical rep
   qualification.
2. Derived-event queue/upload, recoverable rep state, completion, and permanent
   `Rep` creation.
3. Signed installers, release catalog/download UI, autoupdate, and production
   package claims.
4. Endpoint reassignment, sensor binding/transfer, acquisition lease, set context,
   stop/release, and public coach registration.

Required implementation evidence includes model constraints, endpoint-first race
tests, tenant-escape tests, cookie and exact-Origin tests, token parser vectors,
pairing expiry and replay tests, PostgreSQL throttle concurrency tests, status
freshness boundary tests at 59.999 and 60 seconds, cleanup bounds, forbidden-log
scans, Nginx exact-route tests, and proof that no physical or permanent-rep write is
reachable.
