# Feature Spec: Browser BLE Lab and Public Coach Onboarding

- Date: 2026-08-10
- Status: BLE lab implemented; physical browser qualification did not run because
  the tested environment exposed no Web Bluetooth API. Native Rack Helper approved
  as product direction; its thin hosted control plane and unsigned development
  runtime are accepted, while physical ingestion and production release remain
  blocked.
  Public registration remains design-gated.
- Related vision: [`_PROJECT_VISION_ARCHITECTURE.md`](_PROJECT_VISION_ARCHITECTURE.md)
- Related production helper proposal: [`_RACK_HELPER_SPEC.md`](_RACK_HELPER_SPEC.md)

## User Stories

As a developer qualifying the rack architecture, I want an isolated browser page
that reads the WT901 notification stream locally so I can decide whether Web
Bluetooth can replace host-side BLE acquisition.

As a new coach, I want to create an account from the login screen and receive a
private workspace so I can use Edge Athlete without operator provisioning and
without seeing another coach's data.

## Goals

- Prove browser discovery, GATT connection, notification parsing, timing, stalls,
  disconnection, and reconnection against the physical WT901.
- Keep the BLE experiment local to the browser and separate from production rack
  assignment, workouts, storage, and cloud APIs.
- Define public registration around enforceable tenant ownership rather than the
  transitional active-staff fence.
- Preserve staff access and the existing local/Pi deployment during migration.
- Do not require an Edge Athlete-managed access point in the hosted product;
  browsers use ordinary customer internet/Wi-Fi.
- Use a packaged native Rack Helper as the primary production BLE path. Keep Web
  Bluetooth as optional zero-install acquisition where qualification passes.

## Non-Goals

- Browser-side rep detection or workout persistence in the BLE lab.
- Production Rack Helper implementation; it receives a separate feature spec.
- Writing any BLE characteristic or changing sensor configuration.
- Uploading raw frames, device identifiers, or diagnostics.
- Enabling public registration before ownership, throttling, and tenant-escape
  tests pass.
- Email verification, password reset, invitations, billing, athlete accounts, or
  shared workspaces in the first onboarding slice.

## BLE Lab Acceptance Criteria

1. `GET https://ble-lab.edgeathlete.online/` serves a dedicated document and
   JavaScript entry with no application router, service worker, API client, coach
   token code, MQTT client, persistent rack collector, or Wi-Fi overlay.
2. The page reports unsupported browsers and insecure contexts without throwing.
3. A user click opens the browser chooser with a `WT901` name-prefix filter and
   requests access only to service `FFE5`.
4. The page connects to service `FFE5`, subscribes to `FFE4`, and never requests
   a writable characteristic.
5. Fragmented, combined, and noise-prefixed notifications decode into bounded
   20-byte `55 61` frames using the same scaling as the Python Agent.
6. The page displays bounded counters, sample rate, last-sample age, acceleration,
   angular velocity, and angles without displaying device IDs or raw frames.
7. A two-second notification gap reports a stalled stream. Device disconnection
   reports disconnected state and permits a new user-initiated connection.
8. Closing or unloading the lab removes listeners, stops notifications
   best-effort, and disconnects GATT, including during an incomplete connection.
9. Beyond loading its static document, JavaScript, CSS, and fonts, the lab makes no
   runtime API, telemetry, sensor-data, WebSocket, MQTT, IndexedDB, localStorage,
   analytics, or service-worker requests or writes.
10. Pure tests cover scaling, fragmentation, combined frames, noise recovery,
    bounded overflow, and invalid input. The production build passes.

## Coach Registration Acceptance Criteria

1. The coach login screen offers `Create coach account`.
2. Public registration creates an active non-staff user, a private organization,
   and an owner membership atomically, then returns a short-lived access token;
   refresh credentials use an `HttpOnly`, `Secure`, `SameSite` cookie.
3. Duplicate usernames, password mismatch, and Django password-validator failures
   return stable field errors and create no partial rows.
4. The server derives organization scope from the authenticated membership and
   never accepts organization IDs from request bodies.
5. Coach A cannot list, retrieve, update, analyze, report on, or associate Coach
   B's athletes by changing an identifier; cross-tenant lookups return `404`.
6. Newly created athletes always belong to the requesting coach's organization.
7. Self-registered users receive `403` from authenticated legacy endpoints that
   are not tenant-scoped. Private-AP `AllowAny` rack routes remain absent from the
   public Nginx allowlist for authenticated and anonymous requests.
8. Existing active staff users retain local/Pi administration behavior.
9. Registration and login apply bounded throttles and return `429` when exceeded.
10. `/coach/setup` no longer pre-fills demo credentials.
11. The VPS proxy exposes registration and identity endpoints only after backend,
    frontend, tenant-isolation, QA, and security tests pass.

## Failure and Privacy Behavior

- Chooser cancellation returns the lab to idle without an error traceback.
- Missing services, characteristics, notification permission, and GATT failures
  produce bounded user-facing errors with no device identifier.
- The lab never logs or transmits raw notification bytes.
- Web Bluetooth permission belongs to the dedicated lab origin and may persist in
  the browser until the user revokes it. Device selection does not authenticate or
  enroll a sensor.
- Registration responses never reveal whether cross-tenant object IDs exist.
- Passwords pass only through Django's configured validators and password hasher.
- Access tokens remain in memory. Refresh credentials never enter JavaScript,
  localStorage, sessionStorage, IndexedDB, URLs, analytics, or logs.
- Authentication cookies are host-only for `app.edgeathlete.online`; they never
  use `Domain=edgeathlete.online` and are not sent to the BLE lab subdomain.

## Test Plan

- Vitest pure protocol decoder and capability tests.
- Production React build.
- Manual physical Chrome/Edge test over HTTPS for chooser, ten-minute stream,
  sample rate, movement values, stall, disconnect, reconnect, and navigation.
- Django registration transaction, hashing, throttling, and tenant-boundary tests
  before public onboarding implementation is enabled.
- Independent security review before any new public API route is added to Nginx.

## Demo Script

1. Open `https://ble-lab.edgeathlete.online/` in a supported browser.
2. Confirm the privacy and local-only notice.
3. Select `Connect WT901`, choose the physical device, and move it.
4. Observe sample rate and scaled values without an identifier or raw packet.
5. Turn off or move the device away; observe stalled/disconnected state.
6. Reconnect through another explicit chooser action.
7. Close the lab and confirm the BLE connection closes.

## Evidence

- `npm test -- --run`: 22 files and 169 tests passed.
- `npm run build`: production build passed; isolated BLE application code is
  8.62 kB before gzip. The existing main-app chunk-size warning remains.
- Built BLE entry scan: no application API, MQTT, storage, analytics, coach-token,
  rack, or service-worker references found.
- `docker compose ... config --quiet`: passed with synthetic VPS and BLE domains.
- `nginx -t`: passed with synthetic domains and certificate fixtures.
- `git diff --check`: passed.
- Physical WT901, dedicated DNS/certificate, live headers, browser storage/network,
  and portrait/landscape evidence remain pending.
- Dedicated origin deployment observed on 2026-08-10: BLE root `200`, unknown/API
  path `404`, app-origin lab path `404`, TLS 1.3 certificate verified, BLE CSP and
  Permissions-Policy present, and main-origin Bluetooth denied.
- The tested browser on the available Linux laptop exposed no `navigator.bluetooth`.
  No chooser/GATT test ran. Browser-only acquisition remains unqualified pending a
  supported Chromium/OS combination with a Bluetooth radio.
