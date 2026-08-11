# ADR: Rack Helper Development Runtime For Linux And Windows

- Date: 2026-08-10
- Status: Accepted for unsigned development use
- Related helper spec: [`_RACK_HELPER_SPEC.md`](_RACK_HELPER_SPEC.md)
- Identity contract: [`_ADR_BROWSER_ENDPOINT_AND_HELPER_IDENTITY.md`](_ADR_BROWSER_ENDPOINT_AND_HELPER_IDENTITY.md)
- Launch contract: [`_ADR_RACK_HELPER_LAUNCH_INTENT.md`](_ADR_RACK_HELPER_LAUNCH_INTENT.md)

## Context

The thin hosted control plane needs one executable helper client to prove endpoint
pairing, keyring persistence, activation, launch-intent consumption, and status on
the two current development desktop targets. Selecting a development runtime does
not establish installer trust or qualify BLE measurements.

## Decision

Use CPython 3.12, Tkinter, Bleak, and `keyring` for the exact-protocol development
runtime on Linux x64 and Windows x64.

- CPython is exactly major/minor 3.12; CI and the lock file pin the patch runtime and
  every third-party wheel used by a tested revision.
- Tkinter owns the small inert pairing/status window. No embedded browser or local
  web server is allowed.
- Bleak is the selected BLE adapter boundary so later qualified work can reuse the
  existing Python decoder. This ADR does not authorize calling that boundary.
- `keyring` stores the pending bootstrap capability, pending/active `earh1`
  credential, and local installation metadata. Plaintext files and environment
  variables are forbidden credential stores.
- The HTTPS client uses the CPython trust store behavior approved by the deployment,
  validates hostname and certificate, follows no redirects, and contacts only the
  configured canonical application origin on port 443.

The development runtime is run from a locked virtual environment. It is not a
production package, installer, service, daemon, or update client. No download link
or release catalog may present it to customers.

## Supported Development Matrix

| Platform | Architecture | Python/UI | Keyring backend | Protocol registration |
|---|---|---|---|---|
| Linux desktop | x86-64 | CPython 3.12 + Tkinter | Secret Service through `keyring`; fail closed if unavailable | Per-user XDG desktop entry and MIME handler |
| Windows 10/11 development host | x86-64 | CPython 3.12 `pythonw.exe` + Tkinter | Windows Credential Locker through `keyring`; fail closed if unavailable | Per-user `HKCU\\Software\\Classes` registration |

Headless Linux, ARM, macOS, 32-bit Windows, machine-wide services, and fallback
plaintext keyrings are unsupported. An unavailable or locked keyring shows
`keychain_unavailable`; it does not claim, activate, consume, or write status.

## Exact Protocol Handling

The only accepted URI is the 23 ASCII bytes:

```text
edgeathlete-rack:launch
```

The process entry point receives either no protocol argument for a manual inert UI
start or exactly one OS-delivered protocol argument. Protocol dispatch proceeds
only when the argument's encoded bytes equal the string above. It rejects extra
arguments, alternate case, whitespace, percent encoding, controls, NULs, malformed
Unicode, authorities, slashes, paths, queries, fragments, credentials, and trailing
bytes. It never passes protocol input to a shell, path, URL builder, log, or update
mechanism.

On Linux, the per-user `.desktop` entry declares
`MimeType=x-scheme-handler/edgeathlete-rack;` and an `Exec` command whose final and
only substitution is `%u`. Registration uses `xdg-mime default`; the handler still
enforces the argument and byte checks above. No `%U`, shell wrapper, or command
interpolation is accepted.

On Windows, the per-user URL Protocol key is
`HKCU\\Software\\Classes\\edgeathlete-rack`. Its command quotes the absolute
`pythonw.exe` path, the absolute helper entry script path, and one final `"%1"`.
No `cmd.exe`, PowerShell, batch file, unquoted executable path, machine-wide key, or
additional substitution is accepted.

Manual start and OS autostart open inert UI only. They perform no authenticated
mutation and no BLE work. A valid protocol dispatch may attempt the accepted launch
consume operation; only successful consumption permits the 15-second status loop.

## Process And Network Boundary

One per-user process owns the UI. A second invocation uses an OS-supported
single-instance foreground mechanism that carries only the fixed launch signal and
does not expose a general listener. If a qualifying no-listener mechanism is not
available on a target, the second process independently attempts consume and exits;
server idempotency and the single pending intent determine the winner.

The process binds no TCP, UDP, Unix-socket, named-pipe, localhost HTTP, WebSocket,
or MQTT listener. It executes no downloaded code, plugins, commands, or scripts.
The thin runtime may call only helper pairing claim/status/activation, launch
consume, and helper status operations in `_MESSAGE_CONTRACT.md`.

## Development Scope

The accepted development flow is:

1. Start the helper manually or through the exact protocol and show inert UI.
2. Generate and persist the pending `earh1` token and bootstrap capability in the
   approved keyring.
3. Claim a Rack-displayed helper pairing code, display the confirmation phrase,
   poll pairing status, and activate after coach confirmation.
4. Consume a current launch intent.
5. Report only control-plane status every 15 seconds and stop after authentication,
   endpoint, launch, or keyring failure.

For this slice the runtime reports `no_sensor` after launch. It may report
`keychain_unavailable`, `authentication_blocked`, `update_required`, or
`endpoint_reassigned` when that exact control-plane condition occurs. It must not
report `scanning`, `verifying`, `ready`, `active_online`, `active_offline`,
`sensor_reconnecting`, queue states, stopping/draining/released, or
`recovery_required` because their underlying behavior is outside this ADR.

## Exclusions

This ADR explicitly does not accept:

- Signed production artifacts, installers, publisher identity, notarization,
  provenance, SBOM, release catalog, download UI, update metadata, rollback, or
  vulnerability policy.
- Production OS support claims or customer distribution of the source runtime.
- BLE discovery, connection, notification decoding, sensor enrollment, physical
  release timing, detector accuracy, rep metrics, queueing, upload, or completion.
- Autostart with authority, background services, machine-wide installation, or any
  inbound local API.

Bleak's presence is not BLE evidence. No physical rep may reach cloud live state,
`Set`, `Rep`, ranking, report, reference-max, or analytics paths under this ADR.

## Validation Gate

Implementation must provide, on both targets:

- Exact Python/dependency lock evidence and a clean-environment launch.
- Keyring write/read/delete tests with a locked/unavailable failure case and no
  plaintext fallback.
- Protocol parser vectors and registration inspection showing exactly one quoted
  URI substitution and no shell.
- Manual start, cold protocol start, foreground invocation, missing intent,
  consumed intent, restart-without-intent, and stale-after-60-seconds evidence.
- Process and port inspection showing no helper listener in unpaired, paired,
  launching, status, failure, and exit states.
- HTTPS no-redirect/origin tests and forbidden-log scans.
- Server assertions that the development flow writes no sensor, event, set, rep,
  ranking, report, reference-max, or analytics row.

Signed production packaging and all BLE/rep work require separate accepted ADRs and
physical evidence after this development runtime passes.
