# Feature Spec: Native Rack Helper

- Ticket: N/A
- Owner: Edge Athlete team
- Date: 2026-08-10
- Status: Thin hosted control plane and unsigned development runtime accepted;
  physical ingestion and production release blocked
- Related vision: [`_PROJECT_VISION_ARCHITECTURE.md`](_PROJECT_VISION_ARCHITECTURE.md)
- Related identity contract: [`_RACK_DASHBOARD_TEAM_REGISTRATION.md`](_RACK_DASHBOARD_TEAM_REGISTRATION.md)
- Related hosted transport: [`_VPS_EDGE_GATEWAY_SPEC.md`](_VPS_EDGE_GATEWAY_SPEC.md)
- Related launch ADR: [`_ADR_RACK_HELPER_LAUNCH_INTENT.md`](_ADR_RACK_HELPER_LAUNCH_INTENT.md)
- Accepted endpoint/helper identity ADR:
  [`_ADR_BROWSER_ENDPOINT_AND_HELPER_IDENTITY.md`](_ADR_BROWSER_ENDPOINT_AND_HELPER_IDENTITY.md)
- Accepted development runtime ADR:
  [`_ADR_RACK_HELPER_RUNTIME_LINUX_WINDOWS.md`](_ADR_RACK_HELPER_RUNTIME_LINUX_WINDOWS.md)

## User Story

As a rack operator, I want an installed helper to reconnect the assigned VBT
sensor, detect reps locally, and synchronize them with the cloud so the rack works
across supported desktop browsers without an Edge Athlete access point or a
browser-dependent Bluetooth implementation.

As a rack operator connecting a sensor, I want the Rack screen to launch an
installed helper or guide me through a signed installation so I do not need to find
the application manually. When I stop the helper, it must release its local BLE
connection so another non-Edge BLE client can connect. This physical release must
not remove helper enrollment, remove the sensor binding, or transfer Edge Athlete
acquisition to another Rack by accident.

## Problem

The browser BLE lab observed no Web Bluetooth API on the available Linux/browser
test environment; no chooser or GATT test ran. Edge Athlete selected a native
helper as its production direction rather than make browser BLE availability a
release dependency. The current Linux WT901 Agent and Pi gateway
contain useful acquisition, detection, queue, and replay behavior, but they are
operator-managed infrastructure processes. They do not provide the per-rack
installation, browser-guided pairing, OS-keychain credential storage, or desktop
package lifecycle required by the hosted product.

The Rack Helper must keep BLE and time-sensitive rep detection on the rack laptop
without creating a localhost or LAN service. It must survive browser restarts and
short internet outages, prevent replay or cross-rack attribution, and send only
derived rep events to the cloud.

## Assumptions

- The rack laptop has a supported Bluetooth adapter and ordinary outbound internet
  access on TCP 443.
- One helper installation owns acquisition for one paired Rack endpoint in the
  first release.
- The cloud already knows the organization, TrainingGroup, Rack endpoint, sensor
  binding, and active set context. Payload fields do not establish those links.
- The helper runs after desktop-user sign-in; unattended machine-wide service
  operation is not required in the first slice.
- The existing WT901 decoder and provisional detector are the reference
  implementation, not production-qualified detector evidence.
- The release process will provide signing identities and a secure update channel
  before any production package ships.
- A browser cannot reliably prove that a native protocol handler is installed and
  cannot silently install or execute a downloaded package. The Rack displays the
  helper's authenticated check-in state without inferring launch causation from
  browser behavior.

## Goals

- Make a downloadable native helper the primary production BLE path.
- Keep BLE notification decoding and rep detection on the rack laptop.
- Use customer internet/Wi-Fi without a Pi, local server, local MQTT broker,
  managed access point, inbound port, or VPN.
- Pair through an authenticated Rack page with a short-lived code and explicit
  coach confirmation.
- Launch the installed helper from an explicit Rack-screen action and provide a
  signed platform download path beside it when a valid release artifact exists.
- Disconnect BLE on helper stop while preserving committed queue rows and cloud
  acquisition fences.
- Store a revocable least-privilege helper credential in the OS keychain.
- Durably queue derived rep events before reporting local capture.
- Deduplicate retries and fence stale endpoint, sensor, acquisition, and set
  context revisions at the cloud boundary.
- Reconcile the Rack browser from cloud state while preserving
  IndexedDB-before-render for delivered events.
- Keep Web Bluetooth as an explicit optional acquisition mode where qualified.

## Non-Goals

- Sending raw IMU frames, BLE addresses, OS device identifiers, advertised names,
  athlete identities, coach tokens, notes, or roster data to the cloud.
- Exposing HTTP, WebSocket, MQTT, Unix-socket, named-pipe, localhost, or LAN APIs
  from the helper.
- Packaging `scripts/gateway/gym_gateway.py` unchanged as a desktop application.
- NFC acquisition, multi-rack ownership, remote shell, plugins, arbitrary command
  execution, or automatic acquisition failover.
- Claiming production detector accuracy before physical qualification passes.
- Starting or completing a hosted set solely from helper data.
- Replacing the local/Pi compatibility profile in this feature.
- Selecting a signed production runtime, installer framework, or customer-supported
  OS matrix. The accepted unsigned development runtime is CPython 3.12 with
  Tkinter, Bleak, and `keyring` on Linux x64 and Windows x64.
- Silent browser installation, automatic execution of a downloaded package, or
  inferring installation or launch causation from browser focus and
  protocol-handler behavior.

## Product Boundary

The helper differs from the existing gym gateway:

| Rack Helper | Pi/Gym Gateway |
|---|---|
| One paired Rack endpoint | One hosted gym and potentially several racks |
| Installed by a rack user | Provisioned by an operator |
| BLE adapter and detector run in-process | Calls host Agents over Unix sockets |
| Credential in the desktop OS keychain | Credential in a permission-restricted file |
| Browser-guided pairing and replacement | Operator CLI provisioning |
| Desktop package signing and updates | Supervised Linux service lifecycle |

The helper may reuse code or exact semantics from:

- `scripts/hardware/wt901_rack_agent.py`: bounded frame decoding, physical
  verification, movement estimation, detector state, stall handling, and private
  sensor binding.
- `scripts/gateway/gym_gateway.py`: canonical JSON, HTTPS restrictions, SQLite
  durability, bounded batching, contiguous acknowledgement, replay, retry, and
  queue failure states.

It must not expose the Agent's local API or inherit the gateway's gym-wide identity.

## Data Flow

```text
WT901 sensor
  -> BLE notifications
  -> Rack Helper bounded decoder
  -> local rep detector
  -> active context and acquisition fence
  -> durable SQLite queue
  -> outbound authenticated HTTPS batch
  -> cloud validation and deduplication
  -> recoverable live rack state
  -> rack-scoped invalidation
  -> Rack browser REST reconciliation
  -> browser IndexedDB before render
  -> proposed cloud-accepted-event completion path
```

The browser never connects to the helper. Closing, refreshing, or changing the
browser does not stop helper acquisition for an already-authorized active context.

Event terms are fixed:

- `detector candidate`: local movement that has not passed detector/context checks.
- `queued derived event`: a context-valid rep committed to the encrypted helper queue.
- `cloud-accepted event`: a queued event with an accepted or duplicate server receipt.
- `browser-delivered event`: cloud-accepted event returned in a scoped snapshot and
  written to IndexedDB.
- `recoverable live Rack state`: endpoint-scoped, non-permanent cloud projection of
  accepted event IDs and metrics used only for snapshot reconciliation. Its exact
  schema, retention, and cursor are ADR decisions.
- `Rep`: permanent database row created only by the future fenced completion contract.

## Identity And Pairing

The helper needs an identity separate from browser and sensor identity:

```text
Organization
  -> TrainingGroup
  -> BrowserEndpoint (`kind=rack`)
  -> Helper installation and credential
  -> Sensor binding revision
  -> Acquisition epoch
  -> Active set context
```

## Data Model Status

The endpoint, endpoint credential/pairing, helper installation/credential/pairing,
launch, status, throttle, and cleanup subset is accepted by
[`_ADR_BROWSER_ENDPOINT_AND_HELPER_IDENTITY.md`](_ADR_BROWSER_ENDPOINT_AND_HELPER_IDENTITY.md).
The sensor, lease, set-context, receipt, and rep-state records below remain proposed.
The full product model is:

- `BrowserEndpoint`: the single Rack/Dashboard endpoint identity from
  [`_RACK_DASHBOARD_TEAM_REGISTRATION.md`](_RACK_DASHBOARD_TEAM_REGISTRATION.md).
  A `kind=rack` endpoint owns organization,
  TrainingGroup, endpoint revision, and current acquisition mode/epoch. The helper
  proposal does not create a parallel Rack endpoint model.
- `RackHelperPairing`: endpoint, code digest, bootstrap digest, helper public key,
  confirmation-phrase digest, encrypted credential envelope, state, attempt
  counters, and expiry timestamps.
- `RackHelperInstallation`: endpoint, public installation ID, software/contract
  version, credential version, paired/revoked timestamps, and last contact.
- `RackHelperCredential`: installation, domain-separated digest, version, issued,
  overlap expiry, revoked, and last-used timestamps.
- `RackSensorBinding`: endpoint, cloud-generated opaque binding ID, binding revision,
  verified timestamp, and replacement state. The opaque ID is not an OS device
  reference, BLE address, or sensor attestation; those remain encrypted locally.
- `RackAcquisitionLease`: endpoint, acquisition mode, epoch, issued/expiry times,
  and current helper or browser owner.
- `RackSetContext`: opaque context ID, endpoint/revisions/epoch, set relationship,
  capture expiry, replay expiry, and revoked timestamp.
- `RackRepReceipt`: installation, boot ID, sequence, event ID, canonical payload
  digest, context, terminal result, server cursor, and received timestamp.

Database constraints must enforce one active helper and acquisition lease per
endpoint, unique `(installation, boot_id, sequence)`, unique event ID per
installation, and immutable receipt identity. Tenant queries start from the
authenticated installation or browser endpoint, never request organization IDs.

The migration plan must include rollback before production data, an audit for
cross-organization endpoint relationships, and a prohibition on dropping helper
ownership after customer data exists.

The HPKE ceremony below remains a production-hardening proposal and does not govern
the accepted thin control plane. The accepted helper generates and durably stores
its `earh1` credential before claim; the server stores only its digest, and
activation proves possession after coach confirmation. Exact operations are in
[`../_MESSAGE_CONTRACT.md`](../_MESSAGE_CONTRACT.md).

Proposed production pairing behavior:

1. An authenticated coach authorized to manage the Rack endpoint requests a helper
   pairing code.
2. A CSPRNG returns eight Crockford Base32 characters, excluding ambiguous glyphs.
   The resulting 40-bit code is one-time, valid for five minutes, and never appears
   in a URL.
3. Before claim, the helper generates an X25519 keypair and stores the private key
   in the OS keychain. It submits the public key, code, and a separate 256-bit
   bootstrap capability over HTTPS; the server rejects invalid or low-order keys.
4. Both helper and Rack page display the same six-word confirmation phrase. It is
   derived with domain-separated SHA-256 from the pairing ID, BrowserEndpoint ID,
   helper public key, and server nonce, then mapped to a fixed 2,048-word list for
   66 bits of comparison entropy. The coach compares it before confirmation.
5. After confirmation, the server creates an RFC 9180 HPKE envelope using X25519,
   HKDF-SHA256, and ChaCha20-Poly1305. Authenticated context binds pairing ID,
   BrowserEndpoint ID, installation ID, helper public key, credential version, and
   expiry. The helper may fetch the same envelope with its bootstrap capability
   until it acknowledges a successful keychain write or the ten-minute bootstrap
   lifetime expires.
6. The helper decrypts the envelope, stores the credential, and proves possession
   with a credential-authenticated activation request bound to the pairing
   transcript. The persistent credential becomes active only after that proof.
   Failure, cancellation, expiry, or process termination leaves no active helper
   credential. A new pairing ceremony is required after bootstrap expiry.

The security ADR must pin HPKE mode and suite identifiers, canonical byte encoding,
domain separators, field ordering for phrase derivation, HPKE `info` and AAD, and
the activation transcript hash. Activation binds the encapsulated key and
ciphertext digest to a one-time server challenge with explicit expiry, concurrent
request behavior, and idempotent replay result. Envelope retry under one bootstrap
capability returns byte-identical ciphertext. Cross-implementation vectors must
cover phrase derivation, envelope decryption, proof of possession, replay, and
altered-field rejection. The ADR must also state the TLS server-authentication
assumption for the selected HPKE mode.

The server stores keyed digests of codes and bootstrap capabilities, the helper
public key, the encrypted envelope, state, expiry, and attempt counters. Claim,
confirmation, activation, cancellation, expiry, and replacement lock the pairing
and endpoint rows in one transaction. Atomic consumption prevents two helpers from
activating from one code.

Initial claim limits are five attempts per pairing, ten per source address per 15
minutes, twenty per Rack endpoint per hour, fifty per organization per hour, and
1,000 service-wide attempts per minute. Every rejection uses one generic response
and reveals neither code validity nor endpoint existence. The security ADR may
lower these limits but cannot remove any scope.

The credential authorizes one helper installation and Rack endpoint; it cannot act
as a coach, select an organization, read a roster, or access another endpoint.
Replacement requires explicit confirmation. The helper never falls back to a coach
token, anonymous MQTT, or Web Bluetooth.

Installation authorization expires after at most 24 hours without authenticated
contact and then requires confirmation by a coach authorized to manage the endpoint
before upload or acquisition resumes. The Rack setup surface can revoke an
installation and every credential version, pending pairing/bootstrap capability,
and launch intent. This bounds server authorization after an offline uninstall;
queued events keep their original fences through any later authorized recovery.

Helper replacement rejects while a set is open unless a later recovery ADR defines
another safe outcome. After the replacement proves durable credential storage and
transcript possession, one transaction locks the endpoint and both installations,
activates the replacement, revokes the prior installation and credentials, bumps
endpoint revision and acquisition epoch, revokes old leases and contexts, fences
old queued events, and invalidates browser snapshots. The 15-minute credential
overlap applies only to rotation within one installation, never to two helper
installations.

## Runtime Contract

The accepted endpoint/helper identity and launch ADRs finalize the thin control-plane
names, schemas, and operations in [`../_MESSAGE_CONTRACT.md`](../_MESSAGE_CONTRACT.md).
Implementation may provide CSRF, endpoint pairing/status, helper pairing/activation/
status, and launch create/inspect/consume. The remaining full-product interface must
eventually provide:

- Create, inspect, confirm, expire, and cancel a pairing session.
- Exchange a confirmed bootstrap capability for one persistent credential.
- Fetch bounded endpoint assignment, acquisition lease, sensor binding revision,
  minimum helper version, and active set context.
- Upload bounded derived-event batches over HTTPS.
- Revoke and rotate helper credentials.
- Create and consume a short-lived, one-time endpoint-scoped launch intent.
- Publish authenticated heartbeat and status tied to the consumed launch intent
  and a server-issued status cursor.
- Persist stop intent and watermark and request idempotent acquisition-lease
  release.
- Return the backend-verified release catalog for supported OS/CPU combinations,
  including unsupported-platform and no-valid-artifact results.
- Publish privacy-safe Rack invalidations for browser reconciliation.

The production binary contains separate allowlists for the ingestion and update
origins. Runtime configuration cannot add a scheme, host, port, credential, query,
or redirect target. Both origins require HTTPS on port 443, certificate and
hostname validation, and signed configuration metadata. Tests cover redirect,
DNS-rebinding, proxy, and local-configuration tampering. An enterprise system proxy
may relay TLS but cannot replace endpoint hostname verification.
The public proxy strips inbound `Forwarded` and `X-Forwarded-*` headers, writes the
validated client address, and is the only proxy hop Django trusts for source-based
pairing throttles. Forged forwarding headers must not change the throttle key.

## Rack Launch And Sensor Release

The Rack sensor panel follows the state/action matrix under Lifecycle. Absent,
`pairing_required`, `stale`, and `released` offer `Launch Helper`; a valid release
catalog also supplies `Download Rack Helper`. Fresh operational or blocking status
shows the cloud-reported state and, except while `launching`, `stopping`, or
`draining`, offers `Open Helper`. These labels do not claim that a process is
running locally.

`Launch Helper` requires one user click. The authenticated Rack first creates a
CSRF-protected, short-lived, one-time launch intent for its endpoint, then invokes
exactly the byte string `edgeathlete-rack:launch`. Page load, refresh, timers, and
polling never create an intent or invoke the protocol. The URI contains no endpoint,
organization, team, sensor, context, pairing code, credential, return URL, command,
path, fragment, or query. Invocation may only start or foreground an inert helper
UI. The helper authenticates to the cloud and consumes the pending intent before
BLE connection, capture, upload, queue drain, heartbeat mutation, or lease recovery.
A missing, expired, replayed, wrong-endpoint, or wrong-installation intent leaves
persisted stop intent in force and permits only inert UI and troubleshooting. The
protocol cannot pair, replace or disconnect a sensor, mutate a set or queue, or
install an update.

An unpaired helper has no credential with which to consume the intent. Its
endpoint-scoped intent is provisional and non-consumable. Protocol launch may open
the inert pairing UI, but it publishes no helper check-in and starts no BLE
activity. The Rack timeout guidance says to continue pairing if that UI is open.
The confirmed pairing transaction may atomically bind the latest unexpired
provisional intent to the newly activated installation. The helper can then consume
it and publish the bound check-in. An expired intent requires another explicit
`Launch Helper` click.

The Rack enters local-only `launch_requested` state and waits five seconds for an
authenticated helper acknowledgement bound to that launch-intent ID and issued
after the intent's server timestamp. The browser verifies it through the endpoint
snapshot cursor; browser time, focus, blur, and protocol callbacks are not evidence.
Other helper contact may update current cloud status but cannot prove this launch
caused it. If no bound acknowledgement arrives, the Rack says `Rack Helper has not
checked in. It may not be installed, may be blocked by the operating system, or may
still be starting.` It always shows `If Rack Helper opened and asks to pair,
continue setup` and `Try Launch Helper Again`. If the backend has returned a valid
artifact catalog, the Rack keeps the same signed download action that was available
before timeout and expands its platform install instructions. Unsupported, empty,
failed, or expired catalogs show the AC31c state and catalog retry with no artifact.
The Rack never claims to have detected that the helper is not installed and cannot
silently install or execute a download.

The server locks the endpoint and current installation, if any, when creating an
intent. A database constraint permits at most one pending intent per endpoint;
commit order determines which concurrent creation supersedes the other. The helper
deterministically consumes that sole intent. Consumption and the bound
acknowledgement commit atomically with a later server cursor and server receipt
time; helper time is not authoritative. Exactly one acknowledgement can consume an
intent, so concurrent Rack tabs cannot claim the same acknowledgement.

The backend verifies release metadata against the trust roots approved by the
release ADR before the Rack presents links from the fixed HTTPS release origin.
User-agent detection may prioritize a platform but cannot choose or execute an
installer. The helper accepts exactly one OS-delivered URI argument whose bytes are
`edgeathlete-rack:launch`. It rejects extra arguments, percent encoding, controls,
NULs, malformed Unicode, alternate actions, authorities, ports, paths, fragments,
queries, credentials, and oversized input before dispatch and never passes input
through a shell. Protocol input never enters update configuration, paths, logs, or
credentials. A malicious site can start or foreground only the inert helper UI;
without a valid server launch intent it causes no BLE, lease, set, pairing, sensor,
credential, update, or queue mutation.

The native helper provides `Disconnect and quit`. Normal window close, application
quit, logout, and shutdown use the same graceful release path where the platform
permits it:

1. Close the detector gate so no new candidate can become a queued event.
2. Resolve any event already crossing the durable-commit boundary.
3. Persist a stop intent, then disconnect GATT and wait for the connection handle
   to close.
4. If no set is open and the helper is online, drain eligible committed rows to the
   fixed stop watermark before requesting idempotent cloud lease release.
5. Exit after release acknowledgement or a bounded user-visible timeout. Any
   undrained row remains encrypted with its original identity for later recovery.

Failure to persist stop intent cannot delay local safety: the helper keeps the
detector gate closed, attempts bounded GATT disconnect, exits through normal OS
teardown, and reports no release acknowledgement. A GATT timeout also exits through
the platform-qualified OS teardown path. The browser retains the last cloud state
until heartbeat freshness expires, then shows `stale`; queue rows follow their
existing acknowledgement and retention rules.
Autostart and process restart are always inert until a new valid server launch
intent is consumed, so failed stop-intent persistence cannot trigger automatic BLE
reconnection. A persisted stop intent remains authoritative until an explicit,
intent-backed launch or intent-backed authorized recovery clears it.

Stopping during an active set requires a warning with `Cancel` and `Disconnect and
quit now` and instructs the operator to end the set in Rack first. An
operator-confirmed stop closes BLE but does not complete, delete, mark false, or
reassign the set and does not release or transfer its acquisition lease. It
discards only an incomplete detector candidate;
durably committed rows retain their original context. When cloud contact exists,
the Rack enters `recovery_required`. The same helper may resume only while its
original context and lease remain valid. Otherwise an authorized coach must resolve
the open set before another Edge Athlete acquisition owner can capture.

Offline stop still closes the detector gate and BLE connection and persists stop
intent. The last cloud state remains until heartbeat expiry, then `stale` remains
until the cloud acknowledges release. Lease expiry removes acquisition authority
but does not prove physical BLE release. On relaunch, the helper first attempts to
drain old rows under the original lease and context, then submits pending release.
If those fences expired, the existing quarantine rules apply; release never
reattributes an event. A crash or forced kill relies on OS BLE teardown, preserves
committed rows, and leaves the last cloud state unchanged until heartbeat expiry
marks it `stale`.
Every supported platform must qualify a bounded post-process-death BLE release
time. If an active set was interrupted offline, the next authenticated contact
reports `recovery_required` and cannot release its lease until the set is resolved.

Uninstall is not a recoverable stop path. It warns that pending rows will be
destroyed, attempts bounded drain and release, closes BLE, reports best-effort
recovery status and requests idempotent revocation of the installation, every
credential version, pending pairing/bootstrap capability, and launch intent when
online. It requires authenticated server acknowledgement before reporting online
revocation success, then unconditionally deletes helper credentials, X25519 private
keys, sensor-binding references, queue files and WAL, and encryption keys. Offline
uninstall still deletes all local material; the 24-hour inactivity limit or
explicit Rack/admin revocation bounds remaining server authority. Reinstall
requires a new pairing ceremony. Cancellation leaves the installed helper and queue
unchanged.

Stopping the helper releases the local BLE connection; it does not unpair the
helper, remove the sensor binding, or transfer acquisition to another Rack. Another
Edge Athlete Rack requires an authenticated coach authorized to manage both source
and destination endpoints through the accepted tenant-scoped permission model;
global `is_staff` alone is insufficient. Transfer remains unavailable until that
permission exists. Transfer is same-organization only; cross-organization moves
fail closed pending a separate administrative recovery contract. One transaction
locks both endpoints in deterministic order with the affected binding,
installations, leases, and contexts, then revalidates organization, permissions,
expected revisions, one-time confirmation consumption, and absence of open or
unresolved sets. It records the old queue's quarantine disposition, revokes the old
lease and context, bumps endpoint and binding revisions and acquisition epoch,
fences the old installation, and only then issues destination authority. The old
helper enforces that disposition if it reconnects. BLE availability alone grants no
cloud authority.

A derived rep event contains only:

```json
{
  "schema_version": 1,
  "event_id": "UUID",
  "event_type": "derived_rep",
  "helper_boot_id": "UUID",
  "sequence": 205,
  "endpoint_revision": 14,
  "sensor_binding_revision": 3,
  "acquisition_epoch": 8,
  "occurred_at": "2026-08-10T15:04:05.123Z",
  "context_id": "opaque server-issued identifier",
  "payload": {
    "mean_velocity": 0.72,
    "peak_velocity": 0.91,
    "duration_ms": 640,
    "detector_contract_version": 1
  }
}
```

The credential and server relationships determine organization, TrainingGroup,
Rack endpoint, sensor, athlete, exercise, and set. Client fields never grant scope.
The helper does not create completed `Rep` rows directly.

The endpoint ADR must provide a mutation matrix. Organization or TrainingGroup
reassignment increments `endpoint_revision`; sensor replacement increments
`sensor_binding_revision`; acquisition owner or mode changes increment
`acquisition_epoch`; and helper replacement fences the prior installation. Each
mutation revokes incompatible leases and contexts and invalidates browser render
authorization. Upload acceptance locks current rows and derives every relationship
from the authenticated installation and server-issued context. Database constraints
and transactional services must prevent cross-organization endpoint, binding,
context, athlete, exercise, and set relationships.

For detector contract version 1, `mean_velocity` and `peak_velocity` are finite
values from 0 through 3.0 m/s, peak is not below mean, and `duration_ms` is an
integer from 600 through 4,000. Future timestamps more than five minutes ahead of
server receipt are rejected. A context permits capture for at most four hours and
permits upload of events captured before expiry for seven days. The server retains
deduplication receipts for at least fourteen days. The ADR may lower these limits
but must change the detector contract version to alter metric bounds.

## Lifecycle

`launch_requested` and `launch_unconfirmed` are browser-local states. Cloud status
comes from these sources:

| Cloud status | Producer |
|---|---|
| `pairing_required` | Endpoint has no active helper installation |
| `launching` | Paired helper consumed the current launch intent |
| `no_sensor` | Helper internal state is `enrolled_no_sensor` |
| `scanning`, `verifying`, `ready` | Authenticated helper heartbeat reports that exact state |
| `active_online`, `active_offline` | Authenticated helper reports a valid active context and connectivity state |
| `stopping`, `draining` | Authenticated helper reports stop or queue-drain progress |
| `released` | Cloud committed lease release acknowledgement |
| `stale` | Prior helper heartbeat exceeded the ADR freshness limit |
| A blocking-state code | Authenticated helper or server reports the matching blocking state below |

The Rack and helper use this complete action matrix:

| Source state | Available action | Outcome |
|---|---|---|
| absent, `pairing_required`, `stale`, or `released` | `Launch Helper` | `launch_requested` |
| Same states with valid catalog | `Download Rack Helper` | Signed package and install guidance |
| Same states with unsupported/empty/failed/expired catalog | Catalog retry | AC31c unavailable state; no artifact |
| `launch_requested` | Bound acknowledgement | `launching`, then current helper state |
| `launch_requested` | Five-second wait ends | `launch_unconfirmed`; prior cloud state remains |
| `launch_unconfirmed` | `Try Launch Helper Again` | New intent supersedes the old intent |
| `launch_unconfirmed` with valid catalog | `Download Rack Helper` | Same signed package offered before timeout plus expanded install guidance |
| `launch_unconfirmed` with unsupported/empty/failed/expired catalog | Catalog retry | AC31c unavailable state; no artifact |
| Helper absent | Install verified package | Unpaired inert helper; no BLE or helper check-in |
| Unpaired helper UI with current intent | Complete pairing | Pairing binds intent; `launching` then `no_sensor` |
| Unpaired helper UI without current intent | Complete pairing | Credential activates independently; helper remains inert until another Rack click |
| Fresh `no_sensor`, `scanning`, `verifying`, `ready`, either active state, `recovery_required`, or a blocking state | `Open Helper` | `launch_requested`, then same or valid recovered cloud state |
| `launching`, `stopping`, or `draining` | No repeated launch/open action | Current transition continues |
| `released` or `stale` with queued rows | Intent-backed recovery | `launching`, then `draining`, `ready`, or `recovery_required` |
| Valid active context after process restart | `Launch Helper` or `Open Helper` | `launching` then `active_online` |
| Any state | Handler absent/denied or protocol/intent invalid | No helper transition |
| `pairing_required` | Stop | No process to stop |
| `no_sensor`, `scanning`, `verifying`, `ready`, or a blocking state without unresolved set | `Disconnect and quit` | Close detector/BLE; release valid lease after drain, otherwise become stale after heartbeat expiry |
| `active_online` or `active_offline` | Cancel stop warning | Prior active state |
| `active_online` | `Disconnect and quit now` | `stopping` then `recovery_required`; lease retained |
| `active_offline` | `Disconnect and quit now` | Prior state until `stale`; next contact reports `recovery_required` |
| `recovery_required` | `Disconnect and quit` | Close BLE; lease and recovery fence remain until authorized resolution |
| `launching` | Quit | Close UI; consumed intent remains terminal and last status becomes stale after heartbeat expiry |
| `stopping` or `draining` | Repeated quit | No duplicate release; bounded stop continues |
| `released` or `stale` process UI | Quit | Close inert UI; cloud state unchanged |
| Any running state | Crash or forced kill | Last cloud state until heartbeat expiry, then `stale`; OS tears down BLE |
| Any installed state | Confirm uninstall | Delete local identity/queue; revoke online or expire within 24 hours |
| Any stopped process | Autostart or restart without new intent | Inert UI; no BLE or cloud mutation |

Normal states:

```text
unpaired -> pairing -> enrolled_no_sensor -> scanning -> verifying -> ready
ready -> active_online -> active_offline -> draining -> ready
ready -> stopping -> draining -> released
ready -> stopping -> stale
active_online|active_offline -> stopping -> recovery_required
```

Blocking states:

```text
credential_revoked
authentication_blocked
sensor_reconnecting
queue_full
queue_corrupt
queue_unsafe
queue_read_only
queue_write_failed
keychain_unavailable
update_required
endpoint_reassigned
recovery_required
```

Browser-observed state distinguishes local `launch_requested` and
`launch_unconfirmed` from cloud `launching`, `pairing_required`, `no_sensor`,
`scanning`, `verifying`, `ready`, `active_online`, `active_offline`, `stopping`,
`draining`, `released`, `stale`, and every blocking-state code listed above.
Missing heartbeat is never proof that BLE disconnected.

`ready` requires a valid credential, healthy queue, supported contract version,
current endpoint assignment, current acquisition lease, restored sensor binding,
and fresh BLE notifications. A new set cannot start otherwise. An active set may
continue through an outage only while its cached server-issued context remains
valid and every derived event reaches durable storage.

When context arrives, the helper converts server expiry into a monotonic elapsed
deadline using the authenticated server-time anchor. Wall-clock changes cannot
extend it. If the helper restarts offline, loses monotonic continuity, or detects
clock rollback beyond the accepted skew, it fails closed for new capture until it
refreshes server time and context. Existing encrypted queue rows remain eligible
for later replay under their original fences.

## Queue And Replay

Reuse the gateway queue invariants:

- SQLite WAL with `synchronous=FULL`.
- User-private directory and database permissions plus queue encryption with a
  key stored separately in the OS keychain.
- Versioned schema, immutable UUID event IDs, and monotonic sequence per boot.
- One helper boot per batch.
- Bounded event count and encoded batch size.
- HTTPS certificate and hostname verification with no redirect following.
- Bounded exponential retry with full jitter.
- Delete only the contiguous sequence explicitly acknowledged by the cloud.
- Lost responses, timeout, DNS failure, TLS failure, malformed responses, and
  process crashes delete nothing.
- `accepted`, `duplicate`, and item-level permanent rejection results are terminal;
  retryable results and sequence gaps remain queued.

Cloud idempotency uses both `(installation, boot_id, sequence)` and `event_id`.
Each receipt stores a digest of canonical event bytes. A replay returns the prior
result only when both identity and digest match; reused identity with changed bytes
returns `event_integrity_conflict` and advances no cursor.

Item-level schema, metric, or timestamp rejection returns a terminal
receipt for that sequence; after contiguous acknowledgement the helper deletes that
row and shows the stable rejection code. Scope-wide fences such as credential
revocation, endpoint reassignment, binding replacement, acquisition supersession,
context invalidation, replay expiry, or event identity/digest conflict return no
advancing cursor. An authenticated explicit scope disposition stops the batch and
places the entire remaining queue in 24-hour encrypted quarantine before key
destruction. A generic credential failure instead enters non-destructive
`authentication_blocked`, stops capture and upload, and preserves the queue until a
valid authenticated disposition, recovery confirmed by an authorized coach, or
normal seven-day expiry. Sequence gaps and retryable server failures neither
acknowledge nor quarantine rows. Malformed credentials and server configuration
faults cannot start the 24-hour destruction timer.

The authentication ADR must define one status, fixed-size response shape, and
timing policy for every credential failure. That shape may carry either random
padding or a credential-encrypted, server-authenticated scope disposition so only
the affected installation can distinguish confirmed revocation or reassignment.
Failure to authenticate that disposition is non-destructive. The ADR must define
nonce, replay, expiry, and key-rotation behavior for this envelope.

After restart, rows from prior boots retain their original boot IDs and drain
before the helper requests a new capture context. An old boot is not stale merely
because the process restarted. Its queued events receive terminal disposition only
when their replay window or a scope-wide fence applies. Capture expiry stops new
local events; replay expiry governs events already durably captured before that
point.

The initial design target is 10,000 events or 16 MiB, whichever comes first. The
ADR must align queue capacity, maximum supported outage, context lifetime, and
server deduplication retention. The helper never evicts the oldest event. At
capacity it preserves the queue, enters `queue_full`, stops accepting new events,
blocks new sets, and publishes cloud-visible helper status `queue_full` plus
active-set field `capture_stopped=true` when a connection exists. During an active
offline set the native UI shows that reps are
no longer captured and requires the operator to stop. Recovery requires freeing
disk space through the platform-approved operator procedure or completing the
release runbook's reviewed queue recovery; automatic eviction is forbidden.

Unacknowledged events remain encrypted for at most seven days. Acknowledgement
deletes rows transactionally; SQLite secure-delete and encrypted-at-rest key
separation limit recoverability from free pages and WAL files. The helper excludes
the queue, keychain material, and crash dumps from normal backup/telemetry paths.
Uninstall deletes the queue and encryption key by default. Queue retention at
uninstall is forbidden until a platform mechanism can enforce the seven-day limit.
Authenticated revocation or reassignment quarantines the queue for 24 hours,
permits no upload under a replacement installation, and then destroys the queue
encryption key and files. There is no raw event export path.

Credential rotation increments a version and permits a 15-minute overlap. The
helper writes the replacement atomically to the keychain before acknowledging it;
storage failure leaves the old credential active. Queued events belong to the
installation rather than a credential version and may upload under the replacement
credential while all original event fences remain unchanged.

## Browser Synchronization

The cloud commits a rep receipt and recoverable live Rack state before
publishing a Rack-scoped invalidation. The browser treats the invalidation as a
hint, fetches an endpoint-scoped snapshot, deduplicates by `event_id`, writes each
delivered event to IndexedDB, and only then renders it.

IndexedDB keys include organization, endpoint, endpoint revision, acquisition
epoch, context, and event ID. Before rendering cached state, startup verifies all
scope fields against the authenticated endpoint snapshot. Reassignment,
replacement, revocation, logout, or any scope mismatch purges inaccessible cache
before any subsequent render.

The browser does not render cached Rack performance after a fresh page load until
an authenticated snapshot succeeds. If startup is offline, it shows connection
unavailable and no prior-team metrics. A browser already open when connectivity is
lost may keep its current view, but remote reassignment or revocation takes effect
when connectivity returns or its 15-minute render authorization expires, whichever
comes first. The browser enforces that deadline with monotonic elapsed time and
hides performance data after offline restart or clock rollback. This bounded
limitation is explicit user-facing behavior. The helper may continue capture under
its separate context rules.

The authenticated invalidation channel carries only endpoint revision, monotonic
snapshot cursor, and change type. Subscription and every snapshot fetch recheck
endpoint authorization. Cursor gaps trigger a full bounded snapshot; cursors never
authorize access. Snapshot pagination, retention, and full-response schema remain
ADR decisions.

The cloud-accepted-event completion boundary is proposed, not implemented. The ADR
must choose receipt event IDs or a server cursor, define idempotency and error
bodies, and explicitly revise [`../_MESSAGE_CONTRACT.md`](../_MESSAGE_CONTRACT.md) and
[`_RACK_BLE_LIVE_WORKFLOW_SPEC.md`](_RACK_BLE_LIVE_WORKFLOW_SPEC.md) before
implementation. Helper ingestion alone cannot change rankings, reports, records,
reference maxima, or permanent `Rep` rows.

## Web Bluetooth Mode

Web Bluetooth uses the same normalized detector, event, context, and cloud
contracts where physical qualification passes. A server-owned acquisition lease
selects exactly one mode:

```text
native_helper | web_bluetooth
```

Switching modes increments `acquisition_epoch`. Events from an older epoch are
rejected. Selection is explicit; helper outage, credential revocation, or queue
failure never triggers automatic failover.

## Failure Behavior

- BLE disconnect or a two-second notification stall stops detector acceptance,
  reports `sensor_reconnecting`, and retries with bounded backoff.
- Missing GATT services, malformed frames, non-finite values, and out-of-domain
  metrics reject the candidate or event without uploading raw diagnostics.
- Internet, DNS, or TLS failure retains the queue. Acquisition continues only
  under valid cached context.
- A response lost after cloud commit causes replay; deduplication returns the prior
  result and does not increment live or permanent counts twice.
- Queue full, corrupt, read-only, unsafe path, or failed durable write blocks new
  acceptance and preserves queue files.
- The server rejects uploads immediately after revocation. An offline helper stops
  only when it receives that response or its cached capture context expires.
- Missing, malformed, expired, or otherwise failed helper authentication stops
  capture and upload in `authentication_blocked` but cannot trigger queue
  destruction without an authenticated scope disposition or authorized recovery.
- Endpoint reassignment, sensor replacement, acquisition-epoch change, replay
  expiry, or unsupported version fences delayed events. The helper records the
  terminal reason, shows `recovery_required`, and follows the 24-hour encrypted
  quarantine policy; it never silently reassigns an event.
- Browser closure does not stop an active helper context. Reopening reconciles from
  cloud state.
- Clock skew cannot extend credentials or context. Monotonic elapsed time controls
  a running offline context; offline restart or rollback blocks new capture until
  authenticated server time is refreshed.
- An update does not interrupt an active set unless the accepted update policy
  explicitly permits recovery of its queue and context.
- A denied or missing protocol handler changes no cloud or helper state. The Rack
  offers applicable download and retry guidance after the five-second
  acknowledgement wait.
- Graceful stop reports `released` only after authenticated lease acknowledgement.
  After timeout, offline exit, crash, or forced kill, the last state remains until
  heartbeat expiry, then cloud status is `stale` until a later authenticated release
  acknowledgement. Lease expiry removes old acquisition authority but does not
  prove physical BLE release.
- If another BLE client cannot connect after helper exit, the Rack shows platform
  troubleshooting; it does not force cloud transfer or discard queued rows.

## Security And Privacy

- The helper opens outbound TLS connections on port 443 only and binds no listener.
- BLE names, services, frame lengths, values, and timing are untrusted input.
- WT901 identity is possession-based, not cryptographic attestation. A nearby
  spoofing device can imitate advertisements and GATT behavior. Enrollment requires
  a 30-second timed movement challenge and replacement confirmation by an
  authenticated coach authorized to manage the Rack endpoint.
  The local encrypted binding stores the OS-resolved device reference, expected
  services, and verification fingerprint. If address randomization prevents the OS
  from resolving the prior identity, automatic reconnect stops and reverification
  is required.
- Pairing and replacement require explicit intent from an authenticated coach
  authorized to manage the Rack endpoint.
- BLE labels use bounded decoding, replace invalid Unicode, remove control
  characters, and render as text only. BLE input never enters HTML, shell commands,
  format strings, paths, update configuration, or unstructured exception logs.
- The pairing code may appear only in the pairing response, Rack/helper pairing UI,
  and helper claim body. The bootstrap capability appears only in the claim body
  and dedicated pairing authorization header. The encrypted envelope appears only
  in the pairing response and encrypted server pairing record. Private keys and
  credentials persist only in the OS keychain and may enter protected process
  memory only while performing pairing or authenticated requests. Credentials are
  sent only in their dedicated authorization headers. None enter URLs, analytics,
  browser storage, logs, crash reports, rep events, or updates.
- Normal logs may contain helper version, state transitions, stable error codes,
  queue count/bytes, and acknowledged counts.
- Helper- and application-controlled logs must exclude event bodies and IDs, raw
  frames, BLE identifiers, sensor names, athlete/team/session identifiers, tokens,
  host usernames, local paths, IP addresses, and arbitrary exception text.
- Context IDs, event IDs, timestamps, and VBT metrics are pseudonymous private
  performance data. The encrypted helper queue retains them for at most seven days.
  Endpoint-scoped browser IndexedDB retains delivered events until context
  completion plus 24 hours. Encrypted cloud database volumes and backups retain rep
  receipts for fourteen days and recoverable live state until completion plus 24
  hours; permanent `Rep` retention follows the existing athlete-data policy. Access
  is role- and tenant-scoped. Audit records contain stable result codes and digests,
  not event bodies. Cloud ingress necessarily observes source IP metadata; its
  retention and access policy belongs to the deployment security ADR.
- Same-user malware can abuse an unlocked keychain or forge local detector output;
  the first release claims no hardware attestation.
- Production packages require platform signing, macOS notarization where
  applicable, signed update metadata, atomic replacement, rollback, and
  queue-preserving schema migration.
- The release ADR must define embedded update trust roots, signing-key rotation and
  revocation, signed artifact hash/size/version/expiry, anti-rollback rules,
  metadata-expiry behavior, dependency lockfiles, SBOM and provenance generation,
  vulnerability thresholds, fixed HTTPS release origin and redirect policy,
  download source-IP/User-Agent retention, platform publisher identities, initial
  installer verification, and the release owner. Update-host compromise cannot
  authorize an artifact without a trusted signature.
- The update channel cannot execute arbitrary commands or load unsigned plugins.
- The protocol URI requires a user gesture and carries no authority or identifier.
  Invocation without a valid server launch intent cannot disconnect BLE or mutate
  cloud state. Repeated clicks are suppressed while one attempt is pending.

## Smallest First Slice

The first authorized slice is the hosted control plane with no physical BLE reps:

1. Add `BrowserEndpoint`, endpoint/helper pairing and credential records, helper
   status/cursor records, PostgreSQL throttle buckets, launch records, and cleanup.
2. Implement only the exact CSRF, endpoint pairing/status, helper pairing/
   activation/status, and launch create/inspect/consume operations in
   [`../_MESSAGE_CONTRACT.md`](../_MESSAGE_CONTRACT.md).
3. Run the unsigned CPython 3.12/Tkinter development helper on Linux x64 and Windows
   x64, storing pending and active secrets through `keyring` and handling only the
   exact `edgeathlete-rack:launch` protocol.
4. After intent consumption, report `no_sensor` every 15 seconds and prove the Rack
   snapshot changes to `stale` at 60 seconds by server time.
5. Prove the helper exposes no listener and that the entire flow creates no sensor,
   event, set, rep, ranking, report, reference-max, insight, or analytics write.

This slice has no fixture ingestion credential, SQLite event queue, upload route,
recoverable rep state, BLE call, set context, release catalog, installer, or update
path. Those remain later slices behind separate accepted ADRs.

### First-Slice Demo

1. Pair a Rack browser to one authorized TrainingGroup and inspect the scoped,
   host-only endpoint cookie.
2. Pair and activate the unsigned development helper through keyring-backed
   credentials and matching six-word confirmation.
3. Create a launch intent, invoke the exact protocol, consume it, and observe the
   intent-bound cursor acknowledgement followed by `no_sensor` status.
4. Stop heartbeats and observe fresh status through 59.999 seconds and `stale` at
   60 seconds. Restart without another intent and show inert UI with no status write.
5. Show PostgreSQL throttle/cleanup evidence, an empty listener scan, zero physical
   or permanent-rep writes, and unchanged local/Pi startup.

## Acceptance Criteria

- [ ] AC1: Given an OS in the approved release matrix, when its signed package is
  installed, restarted, updated, rolled back, and uninstalled, then BLE, keychain,
  autostart, queue preservation outside uninstall, and mandatory queue/key deletion
  at uninstall match that platform's release evidence.
- [ ] AC2a: Given protocol handling, any helper or browser-observed state named in
  Lifecycle, or any blocking state, when TCP/UDP listeners and localhost APIs are
  scanned, then none belong to the helper.
- [ ] AC2b: Given any first-slice unpaired, paired, launching, status, failure, or
  exit state, when TCP/UDP listeners and localhost APIs are scanned, then none
  belong to the helper.
- [ ] AC3: Given a pairing claim, when the code, bootstrap, confirmation phrase,
  expiry, rate limit, organization, or endpoint check fails, then the generic
  response reveals no validity signal and no credential activates.
- [ ] AC4: Given two helpers claim one code concurrently, when the coach confirms
  the matching phrase, then at most the `earh1` credential UUID and digest bound to
  that phrase can activate and every competing claim fails.
- [ ] AC5: Given keyring storage fails before claim, then no claim occurs. Given
  confirmation succeeds but its response is lost or the process dies, when the
  helper retries before bootstrap expiry, then pairing status recovers the same
  confirmed installation and activation requires possession of the durably stored
  `earh1` credential.
- [ ] AC6: Given a missing, malformed, expired, inactive for more than 24 hours,
  superseded-after-overlap, revoked, or wrong-endpoint credential, when context or
  upload is requested, then the server returns one generic authentication failure
  and creates no receipt or Rack state.
- [ ] AC7: Given sensor enrollment, when the candidate lacks `FFE5`/`FFE4`, a fresh
  valid frame, the 30-second movement challenge, or confirmation by an authorized
  Rack-managing coach, then no binding is stored. Cloud data and logs contain no
  BLE identifier.
- [ ] AC8: Given restart, a newly consumed launch intent, and an OS-resolvable
  private binding, when the sensor is present, then the helper reconnects without a
  browser chooser. Restart without a new intent remains inert. Unresolved or
  colliding identities require reverification and create no derived event.
- [ ] AC9: Given detector contract version 1, when a derived event is queued, then
  velocities are finite from 0 through 3.0 m/s, peak is not below mean, duration is
  600 through 4,000 ms, and no raw sample or direct athlete identity is present.
- [ ] AC10: Given no current capture context, endpoint revision, binding revision,
  acquisition epoch, supported event schema, detector contract, or helper version,
  when movement occurs, then no derived event is locally captured or uploaded.
  Wall-clock rollback or offline restart also blocks capture until authenticated
  server time and context refresh.
- [ ] AC11: Given a valid derived event, when local capture is reported in the
  native status UI, then encrypted SQLite durable commit completed first and no
  browser state changed before cloud acceptance.
- [ ] AC12: Given internet loss, process kill, OS restart, or a response lost after
  cloud commit, when connectivity returns within replay expiry, then original-boot
  rows drain first and each canonical event has one receipt and recoverable Rack
  state change.
- [ ] AC13: Given an existing event ID or `(installation, boot, sequence)`, when a
  replay has identical canonical bytes, then the prior result is returned; changed
  bytes return `event_integrity_conflict`, advance no cursor, and quarantine the
  remaining queue.
- [ ] AC14: Given queue full, corruption, unsafe permissions, read-only storage, or
  failed durable write, when another rep occurs, then the same transition that
  detects the fault changes native status respectively to `queue_full`,
  `queue_corrupt`, `queue_unsafe`, `queue_read_only`, or `queue_write_failed` before
  the detector can accept another candidate. The active set reports `capture_stopped`,
  no new set starts, and existing encrypted files remain. The endpoint snapshot
  reports the stable helper blocking code and separate active-set
  `capture_stopped=true` field on the next authenticated connection.
- [ ] AC15: Given endpoint reassignment, sensor replacement, acquisition change,
  revocation, or replay expiry, when an old queued event uploads, then an
  authenticated explicit scope disposition advances no cursor, changes no new
  scope, and enters the defined 24-hour quarantine. Generic authentication failure
  enters `authentication_blocked` and does not start key destruction.
- [ ] AC16: Given cloud acceptance, when an authenticated invalidation arrives, then
  the browser verifies endpoint scope, detects cursor gaps, fetches a bounded
  snapshot, writes scoped IndexedDB state before render, and deduplicates event IDs.
- [ ] AC17: Given endpoint reassignment, replacement, logout, revocation, or scope
  mismatch, when the Rack obtains a fresh authenticated snapshot, then it purges
  inaccessible cached events before rendering. A fresh offline page renders no
  cached performance state, and an already-open offline page hides data when its
  15-minute monotonic render authorization expires.
- [ ] AC18: Given the browser closes during a valid capture context, when it reopens,
  then the server snapshot cursor reconciles without event loss or duplicate
  display.
- [ ] AC19: Given helper and Web Bluetooth clients both submit events, when the
  server validates acquisition epoch, then only the current explicit lease owner is
  accepted and no automatic mode switch occurs.
- [ ] AC20: Given helper ingestion without the future completion request, when
  reports and permanent tables are inspected, then no completed `Rep`, ranking,
  record, report, reference max, or insight changed. Fixture provisioning is absent
  from production configuration, routes, packages, and committed defaults.
- [ ] AC21: Given revocation while online or offline, when the helper next receives a
  server response or its four-hour capture context expires, then capture stops, no
  replacement credential uploads the old queue, and only an authenticated scope
  disposition or authorized recovery starts quarantine before normal expiry.
- [ ] AC22a: Secrets persist only in their specified server or keychain location and
  enter protected process memory and dedicated TLS fields only when required.
- [ ] AC22b: Logs and crash reports exclude event bodies, secrets, direct identities,
  arbitrary exception text, and the forbidden fields in this spec.
- [ ] AC22c: Helper queue data is encrypted, excluded from backup/telemetry, deleted
  within seven days, and deleted with its key on uninstall.
- [ ] AC22d: Browser cache is scope-keyed, purged or hidden under AC17, and retained
  no longer than context completion plus 24 hours.
- [ ] AC22e: Given approved deployment and release ADRs with explicit limits for
  source IPs, audit data, update artifacts, and update telemetry, when retention and
  field scans run, then cloud receipts, live state, audit data, artifacts, and
  telemetry meet those limits. Production deployment and updates remain blocked
  until those limits exist.
- [ ] AC23a: Given credential rotation for one installation, when replacement
  keychain storage fails, then the still-valid old credential remains active and
  the queue is unchanged. After durable replacement storage, overlap lasts no more
  than 15 minutes and never authorizes another installation.
- [ ] AC23b: Given an update attempt, when signature, trust key, metadata expiry,
  hash, size, version, anti-rollback, migration, or process replacement validation
  fails, then no untrusted artifact executes, the queue remains unchanged, and the
  last trusted compatible executable continues or is restored. A signed minimum
  version takes effect after the active context ends, blocks new capture on the old
  version, and permits safe queue drain.
- [ ] AC24: Given the accepted completion ADR and revised message contract, when the
  same cloud-accepted events are completed or retried, then each permanent rep is
  created once. Until those documents change, physical helper ingestion stays
  disabled.
- [ ] AC25: Given the current local/Pi profile, when it starts after helper work is
  added, then it requires no helper package, credential, VPS, DNS, internet, or
  change to its existing hardware path.
- [ ] AC26: Given each absent, local, cloud, or blocking state defined in Lifecycle,
  when the Rack opens the sensor panel, then its status, `Launch Helper`, `Open
  Helper`, `Download Rack Helper`, retry, and no-action choices match the complete
  state/action matrix. A download appears only with a valid catalog, and no label
  claims that the local process is running.
- [ ] AC27: Given one user click on `Launch Helper`, when the browser invokes the OS
  handler, then it first creates one CSRF-protected launch intent and invokes
  exactly `edgeathlete-rack:launch` once. Page load, refresh, polling, timers, and
  repeated pending clicks create no intent and invoke nothing.
- [ ] AC28: Given a launch attempt, when browser focus changes or a protocol callback
  runs, then the Rack infers no causation. Only an authenticated helper
  acknowledgement atomically committed with intent consumption, a later server
  receipt time, and a later cursor confirms that attempt; other contact only
  updates current cloud status. Concurrent tabs cannot consume or claim the same
  intent acknowledgement.
- [ ] AC29: Given no bound helper acknowledgement within five seconds, when the
  acknowledgement wait ends, then the Rack shows the specified `has not checked in`
  message, pairing guidance for an open unpaired helper, and `Try Launch Helper
  Again`. When the backend supplies a valid catalog, it also shows signed downloads
  and install instructions; otherwise AC31c controls the download state.
- [ ] AC30: Given malformed, oversized, parameterized, or attacker-originated
  protocol input or no valid launch intent, when the helper handles it, then it
  performs no BLE, heartbeat, upload, update, lease, sensor, set, queue, credential,
  or pairing mutation and logs no sensitive field. A later pairing mutation may
  occur only through the separate authenticated, coach-confirmed pairing API;
  opening the inert UI grants that API no authority.
- [ ] AC31a: Given release metadata with invalid signature, trust root, origin,
  redirect, expiry, version, architecture, hash, or size, when the backend builds
  the Rack download list, then it offers no affected artifact and provides no
  unsigned or manual bypass.
- [ ] AC31b: Given an altered, unsigned, unnotarized where required, downgraded, or
  wrong-architecture package, when platform installation is attempted, then the
  approved installer or OS verification rejects it before helper execution.
- [ ] AC31c: Given an unsupported platform, empty valid catalog, catalog retrieval
  failure, or expired catalog metadata, when downloads are requested, then the Rack
  shows `Rack Helper is not available for this computer` for unsupported platforms
  or `Downloads are temporarily unavailable` otherwise, offers no artifact or
  manual bypass, and permits a catalog retry.
- [ ] AC32: Given graceful `Disconnect and quit`, when shutdown begins, then the
  detector gate closes before GATT disconnect, committed rows retain their fences,
  no listener opens, and the helper's BLE handle closes within the platform's
  approved bound. With a qualified sensor, adapter, and second client and no
  unrelated radio fault, that client then connects within the BLE reconnection time
  bound. After stop-intent write failure or GATT timeout, the last cloud state
  remains until heartbeat expiry and then becomes `stale`; no listener opens and
  autostart or restart cannot reconnect BLE without a new valid launch intent.
- [ ] AC33: Given an active set, when stop is requested, then the helper warns before
  disconnecting. `Disconnect and quit now` releases no lease, completes no set,
  deletes no committed row, and reports `recovery_required` immediately when online
  or on the next authenticated contact after an offline stop. Before that contact,
  the prior state remains until heartbeat expiry changes it to `stale`.
- [ ] AC34: Given graceful stop, offline stop, crash, or forced kill, when the helper
  later recovers, then committed rows retain installation, boot, sequence, event,
  context, revisions, and digest; no row is reassigned or deleted outside the
  existing acknowledgement and retention rules. Uninstall instead warns, attempts
  bounded drain/release and acknowledged online revocation, disconnects BLE, and
  deletes every local credential, private key, binding reference, queue/WAL file,
  and encryption key. Offline uninstall still deletes locally, server authorization
  expires within 24 hours without contact, and reinstall requires pairing.
- [ ] AC35: Given online stop with no unresolved set and an empty or drained queue,
  when lease release is acknowledged, then cloud status becomes `released` exactly
  once. Given offline or timed-out stop, the helper initiates bounded local teardown
  while the last cloud state remains until heartbeat expiry, then `stale` remains
  until authenticated release acknowledgement; lease expiry only removes
  acquisition authority.
- [ ] AC36: Given another Rack requests the sensor after local BLE disconnect, when
  cloud transfer is evaluated, then BLE availability grants no authority. A
  same-organization transfer requires accepted tenant-scoped manage permission over
  both endpoints, no open or unresolved set, one-time revision-bound confirmation,
  deterministic locking and permission/revision revalidation, transactional old
  queue disposition and lease/context revocation, revision and epoch changes, and
  old-installation fencing. Global staff alone grants nothing and
  cross-organization transfer fails closed.

## Acceptance Evidence Map

| AC | Planned evidence |
|---|---|
| 1 | Installer/signing/keychain/autostart/update matrix for each supported OS |
| 2a | Listener scan for protocol handling and every lifecycle/blocking state |
| 2b | Listener scan in every first-slice control-plane state |
| 3 | Pairing API rate-limit, expiry, generic-error, and tenant tests |
| 4 | Concurrent claim/confirm transaction test and credential-bound phrase comparison demo |
| 5 | Pre-claim keyring failure, lost-response, process-kill, status-recovery, and credential-possession tests |
| 6 | Credential negative matrix with zero-write assertions |
| 7 | Physical scan/verify/replacement test plus cloud/log field scan |
| 8 | Restart, random-address, collision, missing-device, and reverification tests |
| 9 | Detector/schema unit tests and non-finite/out-of-range fuzzing |
| 10 | Missing/stale context and revision fence integration tests |
| 11 | Kill-after-enqueue durability test and UI/cloud ordering evidence |
| 12 | Multi-boot queue, outage, response-loss, and deduplication tests |
| 13 | Canonical-digest replay and identity-collision tests |
| 14 | Full/corrupt/unsafe/read-only/write-failure injection and exact status evidence |
| 15 | Reassignment/replacement/revocation/expiry terminal-disposition tests |
| 16 | Authenticated invalidation, cursor-gap, snapshot, IndexedDB ordering tests |
| 17 | Online/offline reassignment cache-purge and cross-team rendering tests |
| 18 | Browser close/reopen reconciliation test |
| 19 | Concurrent helper/Web Bluetooth acquisition-lease test |
| 20 | Database and analytics zero-change assertions after ingestion |
| 21 | Online/offline revocation and quarantine-expiry tests |
| 22a | Keychain/server persistence and protected-memory/TLS field inspection |
| 22b | Log and crash-report forbidden-field scans |
| 22c | Queue-at-rest, backup exclusion, expiry, and uninstall inspection |
| 22d | Browser retention, scope-purge, and authorization-expiry tests |
| 22e | Cloud retention and update artifact/telemetry field scans |
| 23a | Credential write failure, bounded overlap, and installation-fence tests |
| 23b | Signature/metadata/rollback/migration and active-context update matrix |
| 24 | Completion idempotency tests after ADR and message-contract approval |
| 25 | Existing local/Pi focused startup and regression commands |
| 26 | Rack panel tests with absent, stale, released, and fresh helper status |
| 27 | User-gesture, single-invocation, refresh, timer, and click-suppression tests |
| 28 | Intent-bound acknowledgement, server-time, focus, and callback tests |
| 29 | Five-second fallback, platform download, instructions, and retry UI tests |
| 30 | Protocol parser fuzzing and zero-mutation/forbidden-log assertions |
| 31a | Backend manifest trust, origin, redirect, expiry, and link-suppression tests |
| 31b | Platform signature/notarization, architecture, and package-tamper matrix |
| 31c | Unsupported/empty/failed/expired catalog UI and no-bypass tests |
| 32 | Shutdown order, stop-write/GATT faults, inert restarts, listener/BLE matrix |
| 33 | Active-set warning, forced-stop, queue preservation, and recovery-state tests |
| 34 | Graceful/offline/crash/kill queue identity and recovery fault matrix |
| 35 | Idempotent release, lost response, offline stop, timeout, and lease-expiry tests |
| 36 | Open-set transfer rejection, revision/epoch fencing, and old-event replay tests |

## Test Plan

- Unit: frame fragmentation/noise, finite numeric bounds, detector state, event
  schema, credential parsing, pairing expiry, queue limits, acknowledgement cursor,
  retry, update metadata, and log redaction.
- Integration: OS keychain adapter, BLE scan/verify/bind/reconnect, SQLite crash
  recovery, TLS/no-redirect behavior, credential rotation/revocation, cloud
  deduplication, stale revision/context fencing, and browser snapshot delivery.
- Concurrency: pairing claim/confirm races, replacement versus upload, duplicate
  batches, context expiry during upload, and helper/Web Bluetooth lease contention.
- Fault injection: DNS/TLS outage, response loss after commit, disk full, read-only
  queue, corrupt database, process kill between enqueue/ack/delete, clock skew,
  browser restart, and update rollback.
- Security: cross-organization and cross-endpoint IDs, code guessing/rate limits,
  forged forwarding headers, credential-failure timing and disposition envelopes,
  keychain failure, no-listener scan, package signature verification, forbidden-log
  scan, dependency review, and malformed BLE labels/advertisements/GATT/cloud
  payload fuzzing.
- Tenant fencing: cross-tenant tests for every client identifier and endpoint,
  group, helper, binding, lease, context, athlete, exercise, and set reassignment
  race, with zero receipt or live-state writes.
- Replacement: open-set rejection, durable keychain proof before cutover, locked
  activation/revocation, revision and epoch bumps, old-context fencing, and proof
  that credential overlap never spans installations.
- Launch: handler absent, OS prompt denied, installed but slow, installed and fresh,
  unsupported platform, intent expiry/replay/wrong endpoint, one invocation per
  gesture, server-time/cursor binding, and no assertion based on focus, callback,
  or timeout.
- Protocol security: extra OS arguments, percent encoding, controls, NULs, malformed
  Unicode, alternate actions, authorities, paths, fragments, queries, credentials,
  oversized input, repeated invocation, and malicious-origin cold start with zero
  BLE or state mutation.
- Release: window close, menu quit, logout, shutdown, uninstall, offline exit,
  response loss, crash, forced kill, adapter removal, active-set interruption, and
  second-client reconnection on every supported platform.
- Stop safety: stop-intent write failure and GATT timeout followed by autostart and
  manual process restart, with zero BLE reconnection before a new intent-backed
  user action.
- Transfer: stale confirmation, simultaneous transfer, create-versus-upload,
  offline prior owner, permission change after confirmation, deterministic lock
  order, and old event replay with zero cross-Rack attribution.
- Physical: the accepted detector qualification matrix from
  [`_RACK_BLE_LIVE_WORKFLOW_SPEC.md`](_RACK_BLE_LIVE_WORKFLOW_SPEC.md), plus
  ten-minute noise, disconnect/reconnect,
  daily restart, and supported-OS Bluetooth permission checks.
- Compatibility: focused local/Pi backend, frontend, Agent, gateway, and firmware
  tests remain unchanged.

## Full Product Demo

1. On a supported test laptop without the helper, open the Rack sensor panel and
   select `Launch Helper`.
2. After no intent-bound helper acknowledgement arrives, follow the signed-download
   guidance, install the package, confirm no listener appears, and select `Launch
   Helper` again to open the inert pairing UI.
3. Display a pairing code, complete pairing, and observe the intent-bound
   authenticated helper check-in.
4. Enroll a WT901 by physical movement, close the browser, and restart the helper.
5. Confirm restart remains inert, reopen the Rack page, select `Launch Helper`, and
   confirm the helper and sensor return to `ready` without a chooser or exposed BLE
   identifier.
6. Start an authorized test context, perform reps, and observe cloud-mediated Rack
   updates with IndexedDB-before-render evidence.
7. Disconnect internet, perform additional reps, restart the browser, restore
   internet, and confirm ordered replay with no duplicate count.
8. Lose an upload response after cloud commit and confirm replay returns a duplicate
   acknowledgement without a second receipt or Rack state change.
9. While the set remains open, select `Disconnect and quit`, observe the active-set
   warning, cancel, and end the set through the Rack workflow.
10. Select `Disconnect and quit` again, confirm acknowledged `released` status and
    BLE reconnection by a qualified second client, and show that the cloud binding
    did not transfer automatically. Disconnect that second client.
11. Select `Launch Helper`, wait for the intent-bound check-in and helper BLE
    reconnection without re-pairing or binding transfer, reach `ready`, then
    revoke the helper and confirm acquisition stops, uploads fail generically, the
    encrypted queue enters quarantine, and no automatic Web Bluetooth fallback
    occurs.

## Open Questions And Stop Conditions

1. Which signed production OS/CPU matrix, installer format, publisher identities,
   dependency/SBOM/provenance process, and autostart mechanism pass release review?
   The unsigned development choice does not answer this.
2. What exact ingestion, receipt, recoverable-live-state, invalidation, pagination,
   and browser event-snapshot schemas follow the accepted control-plane status
   snapshot?
3. Does completion submit receipt event IDs or a server cursor? The chosen ADR
   must revise [`../_MESSAGE_CONTRACT.md`](../_MESSAGE_CONTRACT.md) and
   [`_RACK_BLE_LIVE_WORKFLOW_SPEC.md`](_RACK_BLE_LIVE_WORKFLOW_SPEC.md).
4. Which encryption library and OS-keychain wrapping design protects SQLite on
   every supported platform, including WAL, crash dump, backup, uninstall, and
   secure key-destruction behavior?
5. Which signing identities, embedded trust roots, update origins, metadata format,
   key-rotation process, vulnerability threshold, and release owner control
   production packages?
6. Does the supported network policy permit enterprise TLS proxies, and how are
   proxy trust and source-IP metadata retention reviewed?
7. Who approves the accepted detector/event fencing and physical WT901
   qualification evidence?
8. What lease-release endpoint, idempotency key, lease TTL, stop watermark, queue
   drain timeout, and state transitions implement graceful and offline stop?
9. What measured graceful-exit and forced-process-death BLE release bounds apply to
   each supported OS, and what transfer workflow resolves an offline prior owner?

The endpoint/helper identity ADR, runtime ADR, launch ADR, and revised message
contract authorize only the control-plane first slice above. Queue/ingestion,
browser rep synchronization, BLE, completion, download, stop/release, transfer, and
production packaging must not begin until their applicable decisions and rollback
plans are approved. A production release requires the full signing, packaging,
keychain, BLE, autostart, update, proxy, and validation matrix. Physical rep
ingestion remains disabled until physical qualification and AC24 pass.
