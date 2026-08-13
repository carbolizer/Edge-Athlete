# Edge Athlete — Message Contract

:::{note}
The authority on wire formats. For *why* the system is shaped this way — why the
server ignores rep messages, why topics are keyed to the sensor and not the rack —
see {doc}`../journal/real-time`.
:::


The one place that says exactly what every message looks like: the reps and
heartbeats coming off the nodes, the live broadcasts Django pushes to the
screens, and the body of the batch set-complete request. If you're building a
screen, a simulator, or an endpoint, build to the shapes here so nothing
misreads anything else.

This is the raw reference — Carl folds it into the shared-setup story; Derrilon's
simulator and Braydon's tablet both publish/consume against it.

**v2 note:** updated against the v2 spec's Phase 5–8 insertion and renumbering.
Two things changed here: the phase numbers below now match v2's numbering, and
`velocity_color`'s zone lookup now sources from the session's planned exercise
data instead of the old `Program` model (see §4). Every payload shape in this
document is otherwise unchanged from v1.

---

## Global rules (apply to every message)

- **Everything is JSON.**
- **All topics live under `edgeathlete/`.** Never `rack/{n}/...`.
- **Timestamps are ISO 8601 in UTC**, e.g. `"2026-07-07T07:23:55Z"`. Django and
  JavaScript both parse this natively — don't send epoch numbers.
- **An athlete is always an object: `{ "id": 4, "name": "Jordan Lee" }`** — never a
  bare id or a bare name. You get the stable id (to relate to the database) and
  the display name (to render immediately) in one shot.

---

## 1. Device → broker (nodes / the simulator publish these)

### `edgeathlete/node/{node_id}/rep` — one message per completed rep
```json5
{
  "node_id": "rack_1",
  "rep_number": 1,          // advisory ordering only — see note below
  "mean_velocity": 0.72,
  "peak_velocity": 0.91,
  "duration_ms": 640,
  "timestamp": "2026-07-07T07:23:55Z"
}
```
- **Published by:** the node firmware (Phase 13), Derrilon's `simulate_node`, the
  central WT901 Agent when provisional rep publishing is explicitly enabled for
  demo/qualification, **and — in the per-rack-laptop deployment — the WT901 agent
  that runs on each rack screen** (registered as an ordinary `mqtt`-kind node).
  WT901 raw IMU frames and BLE addresses never appear in this payload.
- **Consumed by:** the rack tablet, subscribed to *its own linked node's* rep topic.
- **Not here:** `velocity_color`. The tablet computes that (see Derived values).

### `edgeathlete/node/{node_id}/pulse` — heartbeat, every ~5s
```json5
{
  "node_id": "rack_1",
  "event_type": "pulse",
  "battery_level": 87,
  "signal_strength": -55,
  "firmware_version": "1.0.0",
  "timestamp": "2026-07-07T07:23:55Z"
}
```
- **Published by:** node firmware + `simulate_node`, **and — in the per-rack-laptop
  deployment — the WT901 agent on each rack screen**, which publishes the same
  heartbeat with `battery_level`/`signal_strength` null (a WT901 has neither).
- **Consumed by:** Django's MQTT subscriber, which listens to `edgeathlete/node/+/pulse`
  **only** and updates the matching `Node` row. Reps never reach Django this way.

---

## 2. Django → broker (broadcasts to the screens)

Every broadcast has a `"type"` string; consumers switch on it. Fields depend on
the type.

### `edgeathlete/rack/{rack_number}/state` — for the tablet at that rack
```json5
// a set was completed
{ "type": "set_complete", "set_id": 12, "athlete": {"id":4,"name":"Jordan Lee"},
  "reps_completed": 5, "avg_velocity": 0.70, "peak_velocity": 0.91, "is_false_set": false }

// an athlete checked in at this rack
{ "type": "athlete_checkin", "athlete": {"id":4,"name":"Jordan Lee"}, "rack_number": 3 }
```

### `edgeathlete/dashboard/state` — for the team wall display
```json5
{ "type": "leaderboard_update",
  "athlete": {"id":4,"name":"Jordan Lee"},
  "rack_number": 3,
  "avg_velocity": 0.70,
  "peak_velocity": 0.91,
  "reps_completed": 5,
  "is_false_set": false,
  "is_velocity_pr": true,     // set a new best peak velocity for this exercise
  "is_weight_pr": false }     // set a new heaviest load for this exercise
```

### `edgeathlete/coach/state` — for the coach tablet
```json5
{ "type": "fatigue_alert", "athlete": {"id":4,"name":"Jordan Lee"}, "rack_number": 3 }
```
- Fatigue detection is Phase 15 — treat this topic's exact fields as **provisional**
  until then. The envelope (`type` + `athlete`) is stable; extra fields may be added.

### `edgeathlete/rack/command` — remote commands to tablets (any/all)
```json5
// send matching tablets to the /rack/setup screen
{ "type": "enter_setup", "target": "all" }
```
- **`target`** selects who acts: `"all"`, a specific `device_id`, or a `rack_number`.
  Every tablet receives the message and acts ONLY if it matches itself.
- **Published by:** a coach action → Django (Phase 14). Testable today with
  `mosquitto_pub -t edgeathlete/rack/command -m '{"type":"enter_setup","target":"all"}'`.
- **Subscribed by:** EVERY rack tablet from boot — assigned or not. Unassigned racks
  have no `rack/{rack_number}/state` topic yet, so this shared channel is the only
  way to reach them.
- **`type` is an extensible envelope.** A future `identify` command (flash a tablet's
  screen so a coach can spot which physical rack it is) is reserved but not built.

---

## 3. REST — request/response bodies the tablet builds against

Not MQTT, but the same data contract, so they live here too.

### `GET /api/sessions/active/` — the rack tablet's one startup fetch (open)
```json5
{
  "session_id": 1,
  "label": "Thursday — Lower + Push",
  "roster": [
    { "athlete_id": 4, "name": "Jordan Lee", "has_data": true,
      "maxes":   { "1": 315.0 },    // { exercise_id: current reference max (lbs) }
      "targets": { "1": 225.0 } }   // { exercise_id: resolved target weight (lbs) }
  ],
  "session_exercises": [
    { "exercise_id": 1, "name": "Back Squat", "target_sets": 5, "target_reps": 3,
      "velocity_zone_min": 0.5, "velocity_zone_max": 0.8 }
  ]
}
```
- **Fetched ONCE** at rack-assignment time, never polled — it drives the whole session.
- `exercise_id` is the **Exercise catalog id** (Program, Set, and reference maxes all
  link to that catalog); `maxes` and `targets` are keyed by it.
- **MINIMAL-PATH shape (as actually built on the existing models).** It differs on
  purpose from the fuller shape in the Phase 10/11 prompts: `targets[exercise_id]` is a
  RESOLVED absolute weight (straight from the athlete's `Program`), so
  `session_exercises` omits `target_weight_percent`. When percent-of-max programming
  arrives, that same `targets` number gets computed server-side (percent × reference
  max) and the tablet code does not change. This is the one place the minimal path and
  the full contract diverge — keep them in sync here.
- `has_data` = the athlete has ≥1 completed `Set` in THIS session (drives `is_makeup`).
- An exercise the athlete has no reference max for simply has **no key** in `maxes` —
  that's the "no max on file" case the Phase 11 inline-entry prompt fills.
- **No active session →** `{ "session_id": null, "label": null, "roster": [], "session_exercises": [] }`.

### `GET /api/sessions/active/athlete/{athlete_id}/progress/` — the rack's athlete day-view (open)
```json5
{
  "session_id": 1,
  "athlete": { "id": 4, "name": "Jordan Lee" },
  "current_exercise_id": 1,          // SUGGESTED current = first movement not yet complete (Program.id order)
  "movements": [
    { "exercise_id": 1, "name": "Back Squat",
      "planned_sets": 5, "target_reps": 3,
      "target_weight_lbs": 225.0,    // the PRESCRIPTION from Program (never changes here)
      "last_weight_lbs": 230.0,      // actual load of the newest non-false set THIS session (null if none) — the next-set default
      "velocity_zone_min": 0.5, "velocity_zone_max": 0.8,
      "completed_sets": 2, "false_sets": 0,
      "next_set_number": 3,          // completed (non-false) sets + 1 — authoritative set_number at set-create
      "status": "in_progress" }      // not_started | in_progress | complete
  ]
}
```
- Fetched when an athlete **checks in** at a rack (Phase 11 Step 2), and again after each of their sets completes. **Derived per request** from the athlete's `Program` rows + their completed `Set` rows this session — **no new tables**.
- **`target_weight_lbs` vs `last_weight_lbs` (the weight seam):** `target_weight_lbs` is the coach's prescription (`Program`, `NOT NULL`, untouched by the tablet). `last_weight_lbs` is what the athlete ACTUALLY last lifted this session (newest non-false `Set.weight_lbs`, `null` before their first set). The tablet defaults the next set's load to `last_weight_lbs ?? target_weight_lbs`, so an on-the-fly weight change carries forward across sets, reloads, and rack moves **within the session** — while the prescription stays clean. **TrainingSession-scoped:** a prior session's loads are never read, so each session starts at target. (A local, unsaved numpad edit takes precedence over both until the set is created.)
- **`movements` order = `Program.id`** (the athlete's program-creation order = intended workout order). The server order never changes; the tablet may float an *in-progress* movement to the top presentationally only (see SPEC Phase 11 Step 2).
- **`next_set_number` is the source of truth for `set_number`** on `POST /api/sets/` — NOT a client counter, so numbering stays correct across rack moves + supersets.
- **`completed_sets`** counts non-false `Set` rows for that athlete/exercise this session; **`false_sets`** counts false ones. `status` = `complete` once `completed_sets >= planned_sets`.
- **`current_exercise_id`** is a suggestion only; the athlete may pick any movement.
- **No active session →** `{ "session_id": null, "athlete": {…}, "current_exercise_id": null, "movements": [] }`. **Athlete not in the session roster →** `404`.

### `GET /api/sessions/active/status/` — room state: every athlete's live status (open)
Each session athlete's current status + when it started, so the rack's rest/check-in cards can show a ticking timer + status label, and a coach tablet can reuse the same data. **Derived** from `Set` + `RackCheckIn`; no new tables.
```json5
{
  "session_id": 1,
  "athletes": [
    { "athlete_id": 4, "name": "Jordan Lee", "status": "lifting",
      "since": "2026-07-07T07:35:00Z", "rack_number": 1 }
    // status ∈ lifting | resting | ready | not_started
  ]
}
```
- **`status`** (first match wins): `lifting` = a set is in progress → `since` = when it started; `resting` = their most recent set ended **within the last ~20 min** (actively between sets) → `since` = when it ended; `ready` = checked in, no set (or rested past the window) → `since` = check-in time; `not_started` = no activity → `since` = `null`.
- **The tablet turns `since` into a live timer** (ticks locally every second; the endpoint is polled, not the clock).
- `rack_number` = the athlete's newest check-in rack (or `null`). No active session → `{ "session_id": null, "athletes": [] }`.

### `DELETE /api/racks/{rack_number}/` — force-clear a wedged rack (coach)

The escape hatch for a rack whose screen is physically gone: ends any open set on
the rack as a **false set**, resets the rack runtime to idle (controller lease
released, receipts dropped), and sends its `RackScreen` back to the waiting list.
The sensor/node stays on the rack — a fresh screen on the same rack reuses it.
Returns `200`:

```json5
{ "rack_number": 1, "cleared": true }
```

The normal release (`PATCH /api/racks/{device_id}/` with `{ "rack_number": null }`)
refuses while a set is open; this is the deliberate "kill the rack state" lever a
coach pulls when nobody can finish that set because the screen is unreachable.

### `POST /api/racks/{rack_number}/checkin/` — record an athlete signing in at a rack (open)
Body: `{ "athlete": 4 }`. Writes an append-only `RackCheckIn`, making THIS rack the athlete's current one for the session (newest-wins). Returns `201`:
```json5
{ "session_id": 1, "athlete": { "id": 4, "name": "Jordan Lee" }, "rack_number": 3 }
```
- No active session → `400`. Unknown athlete, or athlete not on the session roster → `404`.
- No active physical sensor assigned to that rack → `409` with
  `{ "code": "rack_sensor_required", "detail": "..." }`; no check-in is written.
- Called when an athlete taps in on the rack's check-in screen (Phase 11 Step 2). This is the ONE thing that "moves" an athlete to a rack; a later NFC tap would shortcut into the same call.

### `GET /api/racks/{rack_number}/checkins/` — the rack's hot list (open)
The athletes this rack currently "owns" — those whose NEWEST `RackCheckIn` this session is this rack. Surfaced first on the check-in screen for fast re-pick; the full roster (from `/api/sessions/active/`) stays reachable below it.
```json5
{ "session_id": 1, "rack_number": 3, "athletes": [ { "athlete_id": 4, "name": "Jordan Lee" } ] }
```
- **Derived** from `RackCheckIn` (newest-wins per athlete); session-scoped; nothing new stored. Polled (~5s) alongside the roster while the check-in screen is up.
- No active session → `{ "session_id": null, "rack_number": 3, "athletes": [] }`.

### `POST /api/racks/{rack_number}/nfc-tap/` — consume a wristband tap

The controlling rack browser polls with the four controller headers while its
check-in list is visible. Two body shapes:

- `{}` — the rack's reader agent is attached to the same host as Django; Django
  consumes from the private Unix-socket NFC Agent.
- `{ "tag_id": "044DF23A1F1D91" }` — the rack screen read the tap from ITS OWN
  local reader (loopback HTTP on the laptop, see below) and forwarded the raw
  tag for server-side resolution. This is the per-rack-laptop deployment.

Responses contain no tag ID except where the client supplied it in the request:

```json5
{ "status": "none" }
{ "status": "recognized", "athlete": { "athlete_id": 4, "name": "Jordan Lee" } }
{ "status": "unknown" }
{ "status": "unavailable" }
```

- Django validates the rack controller before consuming from the private host NFC
  Agent, then resolves the tag against the active session roster.
- Unknown and off-roster tags are intentionally indistinguishable.
- The browser passes a recognized athlete into the existing fenced check-in call;
  this endpoint does not create a `RackCheckIn` itself.
- Raw tag IDs never enter browser responses, URLs, MQTT, or normal logs.

**Per-rack-laptop NFC reader:** in the per-laptop deployment the reader agent
(`ccid_rack_agent.py`) also serves a loopback HTTP endpoint
`GET http://localhost:8766/v1/taps/consume` (CORS-gated to `basestation` /
`192.168.4.1` / localhost origins). The rack screen polls it and forwards the
`tag_id` in the body above. The Unix socket remains for a reader attached to the
base station.

### `POST /api/sets/` — start a set (create) (open)
Called when a set STARTS (Phase 11 Step 3). The server returns the created `Set` incl. its `id`, kept for the complete POST at set end.
```json5
{
  "session": 1,          // session_id from GET /api/sessions/active/
  "athlete": 4,          // the checked-in lifter's athlete_id
  "exercise": 1,         // catalog exercise id (the selected movement)
  "set_number": 3,       // = next_set_number from the athlete's progress — NOT a client counter
  "weight_lbs": 230.0,   // the ACTUAL load (last_weight_lbs / target, or a numpad edit) — NOT the prescription
  "is_makeup": true,     // = the athlete's has_data (already has a set this session)
  "node": 2,             // OPTIONAL: the Node's INTEGER pk (not node_id) — links the set to its sensor
  "rack_number": 3       // REQUIRED when node is present; rejects stale assignment
}
```
- `weight_lbs` and `is_makeup` are set HERE (at create), not at complete.
- `node` may be omitted (nullable) — the set still saves, but then the `set_complete`/`athlete_checkin` broadcasts (which need `node.rack_number`) don't fire.
- A sensor-backed start with no `rack_number` returns `400`; a node no longer
  assigned to that rack returns `409 node_assignment_changed` and creates no set.

### `PUT /api/racks/node-assignment/` — select a legacy MQTT sensor (active staff)
Exact body: `{ "device_id": "...", "node_id": "rack_3" }`. The screen must
already have a rack number. Node IDs use `[A-Za-z0-9_-]{1,64}`. Returns `200`:
```json5
{ "rack_number": 3, "node": { "id": 2, "node_id": "rack_3",
  "rack_number": 3, "acquisition_kind": "mqtt" /* status fields */ } }
```
- Inactive/simulated nodes, implicit transfers, open sets, and concurrent changes
  return stable `409` conflicts without changing the mapping.
- `acquisition_kind` is provisioning-owned: `mqtt` or `wt901_ble`, with `mqtt` as
  the default. Migration `0021` performs a one-time backfill for firmware beginning
  `wt901ble-`; runtime pulse metadata never changes the kind.
- This endpoint rejects unassigned `wt901_ble` nodes as
  `409 wt901_verification_required`. WT901 selection must use the staff-authorized
  scan, verification, and `PUT /api/racks/{rack_number}/ble-selection/` flow.
  MQTT nodes retain the active, non-simulated usability rule.
- Replacement at the same rack atomically unassigns the prior node. One non-null
  node mapping per rack is also enforced by the database.

### `PATCH /api/nodes/{node_id}/rack/` — release a sensor from its rack (active staff)

Exact body: `{ "rack_number": null }`. Returns the node with `rack_number` null.
This is how a coach unassigns a sensor without putting another one on — assigning
can only replace, and `DELETE /api/racks/{n}/` (Remove screen) deliberately
leaves the sensor.

- Extra or missing fields return `400 invalid_node_rack_request`.
- A non-null `rack_number` returns `400 node_assign_retired` — assignment still
  goes through `PUT /api/racks/node-assignment/` and needs a registered screen.
- An open set on that node returns `409 node_assignment_has_open_set`.
- Already unassigned is idempotent `200` and creates no `MonitoringEvent`.
- A real release creates one `MonitoringEvent` with reason `node_assignment_changed`.
- Unknown `node_id` returns `404 node_not_found`.

### `PUT /api/nodes/{node_id}/acquisition-kind/` — provision node transport (active staff)

Exact body: `{ "acquisition_kind": "mqtt" }` or
`{ "acquisition_kind": "wt901_ble" }`. Extra fields return
`400 invalid_acquisition_request`; another value returns
`400 invalid_acquisition_kind`. An open set returns
`409 node_acquisition_has_open_set`. A changed value creates one
`MonitoringEvent` with reason `node_acquisition_changed`; retrying the current
value is idempotent and creates no second event. This narrow route does not restore
the retired generic node PATCH.

### Rack controller capability and mirrored state

The browser generates `controller_token` as exactly 32 random bytes encoded as
canonical unpadded base64url (43 characters). Django stores only its SHA-256
digest. A claim is an exact body with no extra fields:

```json5
// POST /api/racks/3/controller/acquire/
{ "device_id": "rack-screen-id", "client_instance_id": "tab-scoped-id",
  "controller_token": "43-character-canonical-base64url-token" }
```

The registered screen must be assigned to rack 3 and rack 3 must have an active,
non-simulated node. The 20-second lease is measured against `server_time`.
The same holder and token may retry idempotently. Another holder receives
`409 rack_controller_busy`. After expiry, a quiet rack advances to the next
`controller_epoch`; an open set can only be reclaimed by the same screen,
instance, and token and otherwise returns `409 rack_recovery_required`.

All later controller calls send these headers:

```text
X-Rack-Device-ID: rack-screen-id
X-Client-Instance-ID: tab-scoped-id
X-Controller-Token: 43-character-canonical-base64url-token
X-Controller-Epoch: 7
```

`POST .../controller/heartbeat/` has an empty JSON body and extends the lease;
it creates no `MonitoringEvent`. `POST .../controller/release/` takes exactly
`{ "expected_state_version": 12, "command_id": "uuid" }` and refuses release
during an open set. Accepted release retries return the original response.

`GET /api/racks/{rack_number}/state/` is open for observer reconciliation.
Its snapshot contains rack number, controller-active flag, epoch, lease expiry,
state version, phase and phase start, selected athlete/exercise, current set id,
rep count, latest mean/peak/color, update time, and server time. It never contains
the token, digest, screen identity, or client instance identity.

`PATCH` on the same URL requires the four headers plus `command_id` and
`expected_state_version`. It accepts a validated subset of `phase`,
`selected_athlete`, `selected_exercise`, `rep_count`, `latest_mean_velocity`,
`latest_peak_velocity`, and `latest_color`. Phases are `idle`, `countdown`,
`active`, `summary`, `rest`, and `recovery_required`; invalid transitions are
rejected. Accepted commands increment `state_version` and are durably idempotent.
Commands that normalize to the current snapshot return `409 rack_state_unchanged`
without changing the version or creating an event or receipt.
Only privacy-safe room invalidations cross MQTT; observers refetch this snapshot.

Stable conflicts include `rack_controller_busy`, `rack_controller_required`,
`rack_controller_stale`, `rack_state_changed`, `duplicate_checkin`,
`open_set_exists`, and `rack_recovery_required`. A conflict that depends on current
state returns its latest `state_version` and snapshot without the controller token.

### Central WT901 discovery and health

Active staff use `POST /api/ble/scans/`, `POST /api/ble/verifications/`, and
`PUT /api/racks/{rack_number}/ble-selection/`. Scan responses contain only an
advertised label and random, short-lived `device_handle`. Verification returns a
short-lived token and bounded derived movement. Selection returns the assigned
logical node and advertised label; no browser request or response contains a BLE
address.

Rack browsers read `GET /api/racks/{rack_number}/sensor-health/` with the stable
screen identity in `X-Rack-Device-ID`. Query parameters return `400`; a screen not
assigned to that rack returns `403`. Nginx access logs therefore contain no screen ID.

```json5
{
  "node_id": "wt901_<random>",
  "label": "WT901BLE68",
  "state": "reconnecting|live|stale",
  "movement_g": 0.184,
  "sample_age_ms": 42
}
```

Internally, Django calls the Agent's fixed HTTP/JSON API through a private Unix
socket. Successful live health reads update server freshness. MQTT pulses are
rejected for WT901 nodes, so forgeable payload metadata cannot establish trusted
BLE health. No BLE address or raw frame appears in HTTP, MQTT, or normal logs.

Controller-fenced check-in, sensor-backed set start, and controlled set completion
also require the four headers plus UUID `command_id` and integer
`expected_state_version` in their existing bodies. Their successful response shapes
do not change. A repeated semantic check-in returns `duplicate_checkin`; a second
open set for either the rack or athlete returns `open_set_exists`. Node-less sets,
including coach adjustment rows, keep their prior behavior.

Accepted receipt-backed commands are limited to 10 per rack in a rolling second;
the next new command returns `429 rack_command_rate_limited` with
`retry_after_seconds: 1`. Retrying an existing `command_id` is checked before the
limit and returns its stored result. Receipts remain retryable for one hour and
older rows are pruned opportunistically when a new command arrives. The same
`command_id` after one hour is expired before lookup and cannot return its old result.

### `POST /api/sets/{id}/complete/` — the batch set-complete body
```json5
// POST /api/sets/{id}/complete/
{
  "reps_completed": 5,
  "avg_velocity": 0.70,
  "peak_velocity": 0.91,
  "is_false_set": false,
  "reps": [
    { "rep_number": 1, "mean_velocity": 0.70, "peak_velocity": 0.88,
      "duration_ms": 640, "timestamp": "2026-07-07T07:23:55Z", "velocity_color": "green" }
    // ... one object per rep
  ]
}
```
- **Weight is not in this body.** The load (`weight_lbs`) is set when the set is
  *created* (`POST /api/sets/`), not when it completes.
- This is the **only** way `Rep` rows are ever created.
- **`is_makeup` isn't in this body either.** Like `weight_lbs`, it's set at set
  *creation* (`POST /api/sets/`, Phase 7/11) based on whether the selected
  athlete already has data for the session — it just rides along on the `Set`
  row from that point on. Nothing about the batch-complete shape above changes
  for a makeup set.

### `GET /api/room-state/` — the live room picture (wall: open · coach: `?details=true`)

The coach dashboard and the gym wall screen both read this. **One route serves
both**, switched by a query flag — they were two routes on the branch this merged
from, backed by the same function one boolean apart:

| Call | Who | Gets |
|---|---|---|
| `GET /api/room-state/` | the wall display (open — nobody logs into a wall screen) | names + numbers only |
| `GET /api/room-state/?details=true` | the coach tablet (**401 without a coach login**) | adds database ids, the participant roster, and node health |

Everything here is **derived per request** — there is no room-state table. Rack
occupancy comes from the newest `RackCheckIn` per athlete; status/colour/leaderboard
come from that athlete's `Set`/`Rep` rows. Nobody assigns an athlete to a rack in
advance, so there is nothing to store.

```json5
{
  "schema_version": 1,
  "revision": 12,                    // newest MonitoringEvent id — compare against
                                     // the MQTT invalidation to know if you're stale
  "generated_at": "2026-07-25T06:10:53Z",
  "session": { "id": 3, "label": "Thursday — Lower + Push", "started_at": "…" },
                                     // `id` only with ?details=true; null if no live session
  "summary": {
    "participant_count": 4,
    "athletes_with_sets": 2,
    "completed_sets": 2,
    "completed_reps": 4,
    "room_avg_velocity": 0.68,
    "active_racks": 1                // racks with somebody checked in right now
  },
  "racks": [{
    "rack_number": 1,
    "status": "complete",            // idle | active | complete | false set
                                     //   ^ set LIFECYCLE, not a velocity judgement
    "status_color": "green",         // green | yellow | red | neutral
                                     //   ^ velocity zone of the LAST rep (different concept)
    "athlete": { "id": 1, "name": "Jordan Lee" },   // null when nobody is checked in
    "latest_set": {                                  // null when they haven't lifted yet
      "id": 11, "exercise": "Back Squat", "set_number": 1, "weight_lbs": 205.0,
      "reps_completed": 2, "avg_velocity": 0.68, "peak_velocity": 0.82,
      "is_false_set": false,
      "target_zone": { "velocity_min": 0.5, "velocity_max": 0.8 },
      "reps": [{ "rep_number": 1, "mean_velocity": 0.7, "peak_velocity": 0.9,
                 "velocity_color": "green" }]
    },
    "node": { "node_id": "rack_1", "battery_level": null,
              "signal_strength": null, "is_stale": true }   // ?details=true only
  }],
  "movement": {                      // what the room as a whole is working on:
    "id": 1,                         // the most common current movement. null if
    "name": "Back Squat",            // nobody is lifting. `id` = details only.
    "velocity_min": 0.5, "velocity_max": 0.8,
    "participant_count": 1
  },
  "leaderboard": [{ "rank": 1, "athlete": { "id": 1, "name": "Jordan Lee" },
                    "best_avg_velocity": 0.68 }],   // fastest on `movement`, capped at 20
  "insights": [{ "type": "fastest_set_average", "label": "Fastest set average",
                 "athlete_name": "Jordan Lee", "value": 0.68, "unit": "m/s" }],
                                     // also: highest_peak_velocity, most_completed_reps
  "truncated": { "racks": false, "leaderboard": false },   // hit a display cap
  "participants": [{ "id": 3, "name": "Alex Kim" }]        // ?details=true only
}
```

**No live session is not an error.** `session` is `null`, counts are `0`, lists are
empty, HTTP is still 200 — the wall has to render something before the day starts.

### `PATCH /api/sessions/{id}/` — end a training day (coach)

**There is no `sessions/{id}/end/` route.** Ending a day IS this PATCH — it
already meant "set the end time", so a second route would be two ways to do one
thing. Sending `{}` (no `ended_at`) is the shorthand for "end it now".

Ending a day atomically: freezes an immutable `DailyReport`, recalculates every
athlete's reference max from what they actually lifted, and announces the change.
**Idempotent** — ending an already-ended day returns the existing report rather
than writing a second one.

```json5
// PATCH /api/sessions/3/   body: {}
{
  "id": 3, "label": "Thursday — Lower + Push",
  "ended_at": "2026-07-25T06:24:28Z",
  "daily_report": { "id": 1, "generated_at": "2026-07-25T06:24:28Z" },
  "ended": {
    "id": 3, "label": "Thursday — Lower + Push",
    "ended_at": "2026-07-25T06:24:28Z",
    "report_generated": true,
    "still_open": null        // or { id, label } if data predating the P12 guard
  }                           // holds a stack of open sessions
}
```

`ended` exists so the UI can confirm **in words** which day ended. Before P12 the
panel could redraw looking identical — ending the top of several stacked sessions
instantly promoted the next — so the button appeared to do nothing while working
perfectly every time (canon D18).

### `POST /api/training-programs/{id}/promote/` — turn a program into a block (coach)

For a plan a coach tuned until it beat the template it came from, or wrote from
scratch for one group and now wants to run again. Returns the new `TrainingBlock`
(`201`).

Body: `{ "name": "Fall Strength v2" }` — optional, defaults to the program's name.

> ⚠️ **This COPIES the days and prescription rows up into the new block.** It is
> not a matter of pointing `training_block` at a fresh row — that records
> provenance and copies nothing, so the block would come out with **zero days**
> and deploying it would hand a group an empty plan. That false description lived
> in this codebase for weeks; the tests now fail if anyone reimplements it.

- The source program is unchanged, except `training_block` now names the block it
  is a deployment of.
- `cadence_days_of_week` and `duration_weeks` are carried over from the program's
  original block when it had one, so the promoted block still **schedules**.
  Categories are not copied — filing is a decision about the new block.
- A program with **no days** is a `400`, not an empty block.
- Promoting twice makes two independent blocks; each is a snapshot of the program
  at that moment.

**Accepted loss:** if the program came from another block, that link is
overwritten. The FK's job is to answer "what is this a copy of", and after
promotion the honest answer is the new block.

### `GET /api/scheduled-sessions/` — the calendar (coach)

A **slot** is a plan: "this program's Day 2, on the 14th". Slots are generated
when a block is deployed — cadence picks the weekdays, `duration_weeks` says when
to stop — and are **frozen** after that.

```json5
{ "id": 25, "date": "2026-08-05",
  "training_program": 3, "program_name": "Varsity — Base Strength",
  "training_group": 2, "group_name": "Varsity",
  "training_program_workout": 7, "workout_name": "Day 1 — Lower + Push",
  "workout_position": 1,
  "session": null,              // null = planned, nobody has created this day
  "session_label": null, "session_started_at": null, "session_ended_at": null,
  "created_at": "..." }
```

`session` is the field a UI reads to choose between "Create" and "Open".

| Param | Effect |
|---|---|
| `?training_program={id}` | one program's calendar |
| `?training_group={id}` | one group's |
| `?from=YYYY-MM-DD&to=YYYY-MM-DD` | a date window — a month view should not pull every slot ever deployed |
| `?unrun=true` | only slots with no session yet |

> **No POST.** Slots come from deploying a block. A calendar you can hand-append
> to drifts from the block that produced it, and "where did this extra Tuesday
> come from" is not a question worth creating.

### `GET|PATCH /api/scheduled-sessions/{id}/` — move a day (coach)

`date` is the **only** writable field: moving a slot is one date write and
regenerates nothing. Which day runs in a slot is decided when the schedule is
generated.

Moving onto a date that program already trains on is a **409** naming the clash —
one slot per program per day is a database constraint, so it would otherwise
surface as a 500.

A slot whose session already exists can still be moved. The coach is correcting
the calendar; the session keeps its own real start time. The plan and the record
are separate things.

### `POST /api/scheduled-sessions/{id}/session/` — turn a plan into a real day (coach)

Creates the session, sets its roster from the group's current members, and writes
the `SessionParticipation` row that points the group at the day this slot runs.
Optional body: `{"label": "..."}` — otherwise the label is the day name plus the
date.

> ⚠️ **CREATE IS NOT START.** The session comes back with `started_at: null`. It
> holds no racks and captures no check-ins until someone starts it — that is the
> whole point: a coach can set Thursday up on Tuesday. Several future days can be
> prepared at once and none of them conflict.

Idempotent — a slot that already has a session returns it (`200`) rather than
making a second one. Two taps on a calendar must not produce two Thursdays.

### `POST /api/sessions/{id}/start/` — start a prepared day (coach)

> **Why a route and not a PATCH:** `PATCH /api/sessions/{id}/` with an empty body
> already means "END the day now". Start and end are opposites, and one call's
> meaning should not rest on subtle differences in the body. Ending stays the
> PATCH; starting is this.

- Refuses (**409**) while another day is running, naming it — same reason as
  `POST /api/sessions/`: the racks follow the active session.
- Already started → **200**, unchanged. The caller wanted it running.
- Already ended → **409**. Its report is frozen; reopening would make that a lie.

### `POST /api/sessions/` — start a training day (coach)

Body: `{ "label": "Monday — Upper", "athletes": [4, 7, 9] }`. **`athletes` is
required and must not be empty** — a training day with nobody in it is refused.

> ⚠️ **ONE OPEN DAY AT A TIME (P12).** A second open session is a **409** naming
> the one already open, so the caller can offer "end that one first":
>
> ```json5
> { "error": "a training day is already open",
>   "open_session": { "id": 3, "label": "Monday", "started_at": "..." },
>   "detail": "End 'Monday' before starting another day." }
> ```
>
> There is **no `force` override.** `_active_session()` is last-one-wins and the
> racks follow it, so a second open session did not error — it silently became the
> one athletes checked into, their sets landed on a session with no participants,
> and the day's report came out wrong while every tablet looked normal. An
> override would just move that quiet corruption behind a flag.

**Still open by design:** what should happen to a day left open overnight.
Auto-closing writes an immutable `DailyReport` with nobody watching, so it is not
obviously safer than requiring a human to end it.

### `GET /api/analytics/athlete/{id}/` — one athlete's performance context (coach)

Answers both of a coach's questions about a person in one call: **how are they
doing** (`summary`, `exercise_summaries`) and **what did they actually do**
(`sets`, each with its reps). One request rather than three, because the athlete
and history tabs sit side by side and a coach flips between them.

`404` for an unknown athlete id.

```json5
{
  "athlete_id": 4,                    // kept for older callers; prefer `athlete`
  "athlete": { "id": 4, "name": "Jordan Lee", "created_at": "..." },

  // Aggregated across ALL history — see the truncation note below.
  "summary": {
    "completed_sets": 128, "completed_reps": 384,
    "best_average": 0.82,             // null until they have lifted, never 0.0
    "highest_peak": 1.04,
    "heaviest_weight": 315.0
  },

  // Most-trained movement first; name breaks ties so the order is stable.
  "exercise_summaries": [
    { "exercise": "Back Squat", "completed_sets": 64, "completed_reps": 192,
      "best_average": 0.78, "heaviest_weight": 315.0 }
  ],

  "sets": [                           // newest first, 50 most recent
    { "id": 901, "set_number": 3, "exercise": "Back Squat",
      "weight_lbs": 255.0, "reps_completed": 3,
      "avg_velocity": 0.71, "peak_velocity": 0.88,
      "ended_at": "...",
      "rack_number": 2,               // from the set's NODE — `Set` has no rack
      "session": { "id": 12, "label": "Thursday — Lower + Push" },
      "reps": [ { "rep_number": 1, "mean_velocity": 0.75,
                  "peak_velocity": 0.9, "duration_ms": 700 } ],
      "reps_truncated": false,        // true past 100 reps in one set
      "measured": { "first_to_last_change_percent": -8.3 } }
  ],
  "truncated": true                   // older sets exist beyond the 50 returned
}
```

**What counts as work** (canon §6.5): false sets and coach weight adjustments are
excluded — a false set is a mis-record, and an adjustment moves the working load
without anyone lifting. Unfinished sets are excluded too: they have no `ended_at`,
and the history view groups by day, so one would render as an "Invalid Date" day.

> ⚠️ **The summary covers all history; only `sets` is truncated.** The UI tells the
> coach exactly that ("summaries include all history"), so computing totals from
> the returned list would make the screen quietly lie. Totals are aggregated in
> the database.

> ⚠️ **`measured` is always present, even with no reps** — with `null` inside it.
> The coach UI reads `measured.first_to_last_change_percent` without optional
> chaining, so omitting the block is a thrown TypeError, and React unmounts the
> whole coach view on an uncaught render error. A black screen, not a blank field.

`first_to_last_change_percent` is **signed**: negative means they slowed across
the set (ordinary fatigue), positive means they finished faster. Kept as a change
rather than a "loss" so speeding up isn't a negative loss. Needs two reps and a
non-zero first rep, else `null`.

**An athlete who has never lifted** returns `200` with zeroed counts, `null`
bests, and empty lists — a new signing is an ordinary state, not an error.

### `GET /api/reports/` — finished training days (coach)

One family of routes. "This athlete's reports" is the same list **filtered**, not
a parallel set of endpoints:

| Call | Returns |
|---|---|
| `GET /api/reports/` | every finished day, newest first |
| `GET /api/reports/?athlete={id}` | only days that athlete took part in |
| `GET /api/reports/{id}/` | one day in full |
| `GET /api/reports/{id}/?athlete={id}` | that day through one athlete's lens |
| `GET /api/reports/{id}/pdf/` | the same day as a printable PDF (`?athlete=` also works) |

Reports read from a **frozen snapshot**, never from live tables — so a report
says what was true on the day it was generated even after programs or maxes
change later. The PDF renders from that same snapshot, so print and screen can
never disagree.

### `POST /api/reference-maxes/` — record what athletes can lift (coach)

**The prescription lever.** Every target weight is a percentage of these numbers.
Takes a list so a whole TrainingGroup's testing day goes in with one call.

```json5
{ "exercise": 1, "rep_basis": 1,
  "entries": [ { "athlete": 3, "reference_weight_lbs": 315 },
               { "athlete": 4, "reference_weight_lbs": 275 } ] }
```

Every entry writes a **new row**; nothing is overwritten. An athlete's current
reference is their newest row, so re-entering supersedes the old value while the
history stays intact. **Applies forward only** — targets already trained against
are never rewritten.

> Distinct from adjusting the load on a bar today: that rides on the set itself
> and changes nothing about the plan. See §4.

---

## 3b. REST — planning (coach only)

The hierarchy these serve: a **TrainingGroup** (`TrainingGroup`) trains a **plan**
(`TrainingProgram`), which is usually a copy of a reusable **template**
(`TrainingBlock`). Plans store a **percent**, never pounds — the weight is worked
out per athlete from their reference max at read time (§4).

> **Route names lag the model names.** `training-blocks/` is the template and
> `workouts/` is a day inside one, because these URLs were bent to fit the coach
> client that already existed rather than reshaping its code. Scheduled for
> renaming in P9; see the P9 rename list.

### `GET|POST /api/training-groups/` — TrainingGroups (coach)

A TrainingGroup is a *subset* of the gym that trains together, not everyone on file.

```json5
{ "id": 4, "name": "Varsity Football", "athlete_count": 12,
  "coaches": [
    { "id": 1, "coach": 2, "coach_name": "sarah", "role": "head" },
    { "id": 2, "coach": 5, "coach_name": "mike",  "role": "assistant" }
  ],
  "head_coach": { "id": 2, "name": "sarah" } }
```

> ⚠️ **BREAKING (P11):** the single `coach` field is **gone**. A real weight room
> puts several staff on one group, and one field could only name one of them.
> Read `coaches` for the list, or `head_coach` when a screen needs one name —
> `head_coach` is **nullable**, so don't assume it's there.

Whoever creates a group becomes its head coach; a group with no staff at all is
never what someone meant to make.

### `GET|POST|PATCH|DELETE /api/training-groups/{id}/coaches/` — who runs the group (coach)

| Method | Body | Effect |
|---|---|---|
| `GET` | — | The staff list |
| `POST` | `{"coach": 4, "role": "assistant"}` | Add someone. `role` defaults to `assistant`. Adding a coach already listed changes their role instead of erroring. |
| `PATCH` | `{"coach": 4, "role": "head"}` | Change a role. A coach not already listed is a `404`, not a silent add. |
| `DELETE` | `{"coach": 4}` | Remove someone. Removing the last one is allowed — the group reports `head_coach: null`. |

**One head at a time.** Naming a new head demotes the incumbent to assistant, on
both the add and the role-change path, so "make Mike the head" is a single call
and can never leave two heads behind.

> ⚠️ **This list is a statement, not a permission.** Nothing consults it when
> deciding whether a write is allowed — `IsCoach` still means "is authenticated",
> exactly as before. That is the canon's filter-not-fence decision. Recording who
> runs what is useful on its own, and enforcement can be layered on later without
> undoing any of this. A test asserts the current non-enforcement on purpose, so
> that adding a boundary is a deliberate change rather than a broken build.

### `POST /api/training-groups/{id}/athletes/` — set a TrainingGroup's members (coach)

```json5
{ "athletes": [3, 4, 7] }        // → the TrainingGroup's full member list
```

Membership is **current-state only**. Adding or removing never rewrites history:
past sessions and sets stay attached to whatever they ran under.

### `GET|POST /api/training-blocks/` — reusable templates (coach)

```json5
{ "id": 1, "name": "Fall Strength", "duration_weeks": 8,
  "cadence_days_of_week": "Mon,Wed,Fri",
  "coach": 2, "created_at": "...", "updated_at": "..." }
```

`updated_at` moves whenever a coach edits a day or a row **inside the block**. It
does **not** move when someone edits a program deployed from it — a program is a
snapshot and has no link back.

**Query parameters (GET):**

| Param | Effect |
|---|---|
| *(none)* | Every block in the department. This is the default on purpose. |
| `?coach=me` | Only the caller's blocks |
| `?coach={id}` | Only that coach's blocks. A non-numeric value that isn't `me` is a `400`, not a silent full list. |
| `?category={id}` | Only blocks carrying that label. Repeatable. |
| `?category=2&category=5` | **Any-of**, not all-of — the labels sit on different axes, so requiring both would usually match nothing. A block carrying both is still listed once. |
| `?sort=recent` | Most recently edited first. Default order is alphabetical by name. |

Filters combine: `?coach=me&category=2` is "my off-season blocks".

### `GET|PATCH /api/training-blocks/{id}/` — one block's own fields (coach)

PATCH accepts `name`, `categories`, `duration_weeks`, `cadence_days_of_week`.
The days and rows *inside* the block have their own routes (below).

This route exists because categories would otherwise be write-once: every block
created before P11 has no labels, and a create-only API could never give it any.

> ⚠️ **No DELETE, on purpose.** Nothing in the product deletes a whole block, and
> the filter-not-fence reasoning above partly rests on that. Adding one is a real
> decision, not a convenience.

### `GET|POST /api/block-categories/` — the catalog's label vocabulary (coach)

```json5
{ "id": 1, "name": "Off-season", "block_count": 4 }
```

Department-wide and shared: labels only help if everyone files things under the
same words. `name` is unique, so a duplicate is a `400` rather than a quiet
near-copy. `block_count` rides along so the filter bar can show how much sits
behind a label before you click it.

**Not `Tag`.** `Tag` is movement labels on `Exercise` ("lower", "push") with a
globally-unique name. Sharing one table would make a word like "Upper" mean a
body region or a grade level depending on what it hangs off.

> ⚠️ **`?coach=` is a lens, not a fence.** Blocks are global so a good one gets
> reused; the filter exists so nobody scrolls a department-sized catalog to find
> their own work. It grants nothing and forbids nothing — any authenticated coach
> can still read and edit any block. If a real permission boundary is ever wanted,
> it is additive on top of this and the filter does not have to be undone first.

### `GET|POST /api/training-blocks/{id}/workouts/` — one day inside a template (coach)

```json5
{ "name": "Day 1 — Lower", "position": 1,
  "exercises": [
    { "exercise": 1, "sets": 5, "reps": 3, "target_percent": 80,
      "velocity_zone_min": 0.5, "velocity_zone_max": 0.8 },
    { "exercise": 2, "sets": 3, "reps": 5, "target_percent": 75 } ] }
```

The block is in the URL, not the body — a day cannot exist without one.
`position` orders the day and must run 1, 2, 3… with no gaps; omit it to append.

### Editing a template (coach)

| Route | Does |
|---|---|
| `PATCH /api/training-blocks/{id}/workouts/{id}/` | Rename a day — `{"name": "Day 1 — Lower"}` |
| `DELETE` same | Remove a day and its prescription rows |
| `PUT /api/training-blocks/{id}/workout-order/` | `{"workout_ids": [12, 9, 14]}` → positions 1, 2, 3 |
| `PATCH /api/training-blocks/{id}/workouts/{id}/exercises/{id}/` | Change `sets`, `reps`, `target_percent`, `velocity_zone_min/max`, or `exercise` |
| `DELETE` same | Remove one prescribed movement |
| `PUT /api/training-blocks/{id}/workouts/{id}/exercise-order/` | `{"exercise_ids": [7, 3]}` → positions 1, 2 |

**Reordering takes the WHOLE list, never one item.** Both `position` columns
carry a `UniqueConstraint(parent, position)` that Postgres checks after every
statement, so `PATCH {"position": 2}` collides with whichever row is still on 2.
The server renumbers in two passes inside one transaction (shift everything to
`position + 10000`, then write the finals), so no two rows ever share a number
mid-flight. It is also idempotent and cannot leave a gap or a duplicate.

- **`position` is rejected by the row `PATCH`** (`400 nothing_to_change` if it is
  the only field sent) — ordering has exactly one route.
- **A partial id list is refused** (`400 invalid_order`) rather than half-applied;
  naming a subset would silently drop the rest out of the order.
- **The parent is checked**: `/training-blocks/1/workouts/99/` is a `404` when day
  99 belongs to another block.
- **Editing a template never touches a deployed program.** `TrainingProgramWorkout`
  and `TrainingProgramExercise` hold no foreign key back to the block rows — they
  were copied at deploy time — so deleting a day from a template cannot remove it
  from a group currently training it.
- **Every edit here moves the block's `updated_at`**, because changing a day *is*
  changing the template. Editing a deployed program moves nothing on the block.

### `GET|POST /api/training-programs/` — deploy a template for a TrainingGroup (coach)

```json5
{ "training_group": 4, "training_block": 1,
  "name": "Fall Strength — Varsity", "start_date": "2026-08-01" }
```

Deploying **copies** the template's rows down rather than pointing at them, so
editing the template next season cannot rewrite what this TrainingGroup already trained.
`training_block` may be **null** — a one-off plan is a permanent first-class path,
not a shim (D6).

### `POST /api/sessions/{id}/participation/` — which TrainingGroups train today (coach)

```json5
{ "training_group": 4, "training_program": 3 }
```

This is what lets one session hold several TrainingGroups on different plans.

### `GET|PUT|DELETE /api/athletes/{id}/program/` — one athlete's plan (coach)

**Reads as "this athlete's program"; underneath it is TrainingGroup membership**, because
a plan belongs to a TrainingGroup (D12/D13). `PUT { "workout_program_id": 3 }` puts them
in that program's TrainingGroup; `DELETE` takes them out of the TrainingGroups currently
prescribing to them, leaving plan-less TrainingGroups alone.

```json5
{ "athlete": { "id": 1, "name": "Jordan Lee" },
  "assignment": [
    { "training_program": { "id": 3, "name": "Fall Strength — Varsity",
                            "start_date": "2026-08-01", "end_date": null },
      "training_group":   { "id": 4, "name": "Varsity Football" },
      "from_template":    { "id": 1, "name": "Fall Strength" },
      "workouts": [
        { "id": 9, "name": "Day 1 — Lower", "position": 1,
          "exercises": [
            { "id": 21, "exercise": { "id": 1, "name": "Back Squat" },
              "position": 1, "sets": 5, "reps": 3,
              "target_percent": 80,
              "target_weight_lbs": 250.0,      // resolved for THIS athlete; null with no max
              "velocity_zone_min": 0.5, "velocity_zone_max": 0.8 } ] } ] } ],
  "groups_changed": [ { "id": 4, "name": "Varsity Football", "action": "added" } ] }
```

`groups_changed` appears on writes only, and says what actually moved — a write
here has a **wider effect than the route name suggests**.

### `GET|PUT|DELETE /api/athletes/{id}/program-exercises/{id}/override/` — one athlete's exception (coach)

Rare by design: everyone in a TrainingGroup trains the TrainingGroup's plan unless a row like
this says otherwise.

```json5
{ "target_percent": 70, "sets": 3, "reps": 5 }   // any subset; omitted = inherit
```

---

## 3c. REST — spreadsheet import (coach only)

### `POST /api/imports/preview/` · `POST /api/imports/`

`multipart/form-data`. **Preview writes nothing**; import re-checks and then saves
all-or-nothing. Which of three sheets was uploaded is detected from the **column
names** (D16) — the client never declares it.

| Sheet | Detected by | Required columns |
|---|---|---|
| `roster` | `athlete_name`, no `exercise` | `athlete_name` |
| `reference_max` | `athlete_name` + `exercise` | + `max_lbs` **or** `weight_lbs` |
| `plan` | `workout_name` | `workout_name`, `exercise`, `position`, `sets`, `reps`, `target_percent` |

**Form fields:** `file` (required); `training_block` **or** `training_program`
(**required for a plan** — nowhere else to put workouts); `training_group`
(optional on roster/max sheets, and the thing that tells two same-named athletes
apart); `corrections` (optional — see below).

**There is no absolute-weight column on a plan.** `target_percent` (1–150)
replaces the old `default_weight_lbs`; a pounds column would bypass the
reference-max machinery every prescribed weight depends on.

```json5
{ "sheet_type": "reference_max",
  "rows": [ { "row": 2, "athlete_id": 1, "athlete_name": "Jordan Lee",
              "exercise_id": 1, "exercise": "Back Squat",
              "reference_weight_lbs": 360.0, "rep_basis": 4 } ],
  "errors": [ { "row": 3, "field": "athlete_name", "code": "unknown_athlete",
                "detail": "No athlete named 'Jordn Lee'.",
                "value": "Jordn Lee", "suggestions": ["Jordan Lee"] } ],
  "skipped": [ { "row": 4, "athlete_name": "Sam Rivera", "exercise": "Back Squat",
                 "code": "weight_meaning_unknown", "detail": "Skipped: …" } ],
  "counts": { "ready": 1, "errors": 1, "skipped": 1 },
  "created": 1 }                                  // import only, and only when clean
```

**`rows` is present even when `errors` is non-empty** (D17) — that is what lets the
coach screen show the sheet back with the bad cells marked instead of refusing the
file. Status is `400` whenever `errors` is non-empty, `200` otherwise.

**`skipped` is not an error.** A weight whose meaning the sheet never states is
left out and reported rather than guessed: a fabricated max is newest-wins, so it
would outrank the athlete's real tested number and drag every other target down
with it. Ambiguous names (`ambiguous_athlete`) carry `candidates` instead of
`suggestions`.

#### `corrections` — answering "who did you mean?" (D17d)

A JSON string sent alongside the **same file**, so a misspelling is fixed on
screen rather than by editing the spreadsheet and uploading again:

```json5
{ "athlete":        { "Jordn Lee": 42 },      // the raw text -> the record id
  "exercise":       { "Bakc Squat": 7 },
  "training_group": { "Varsty": 3 } }
```

- **Grouped by kind on purpose.** An answer about an athlete must never satisfy a
  movement lookup, even when the misspelling is identical.
- **Matched the same way names are** (case- and spacing-insensitive), so one
  answer repairs *every* row spelled that way — a name mistyped forty times is one
  fix, not forty.
- **An id that doesn't exist is ignored**, not trusted: the row falls back to
  normal matching and re-reports its error. A stale or hand-edited correction can
  never write to whatever row that number happens to be.
- **Malformed JSON is a `400` `invalid_corrections`**, never silently dropped —
  ignoring it would re-raise the errors the coach just fixed and look like their
  fix didn't take.

Corrections are needed because **both endpoints re-read the file from scratch and
never trust a previous preview** (the gym changes between the two calls — someone
gets renamed, another coach imports first). Without them the app would forget the
answer it just asked for.

---

## 4. Derived values — who computes what (read this)

These fields are *not* sent raw by the hardware; something computes them. Getting
this wrong is the most likely way two parts disagree.

| Field | Who computes it | How |
|---|---|---|
| `velocity_color` | **the rack tablet**, per rep | Compare the rep's velocity to the *exercise's* velocity zone (`velocity_zone_min/max`), sourced from `session_exercises[]` in the `GET /api/sessions/active/` response the tablet already fetched once at rack-assignment time (Phase 10/11) — **not** `GET /api/prescriptions/`, which the v2 rack-screen flow no longer calls. `green` = on target, `yellow` = dropping, `red` = fatigued. Included when the tablet sends the set-complete body. |
| `rep_number` (saved) | **the rack tablet** | Numbered `1..N` within the set. The tablet owns set boundaries, so it assigns the authoritative number; the node's `rep_number` is only advisory ordering. |
| `is_velocity_pr` | **Django**, at set-complete | `true` if this set's `peak_velocity` beats the athlete's previous best for that exercise. |
| `is_weight_pr` | **Django**, at set-complete | `true` if this set's `weight_lbs` beats the athlete's previous heaviest for that exercise. |

---

## 5. Who subscribes to what

| Topic | Published by | Subscribed by |
|---|---|---|
| `edgeathlete/node/{node_id}/rep` | node / simulator | the rack tablet linked to that node |
| `edgeathlete/node/{node_id}/pulse` | node / simulator | Django subscriber (`node/+/pulse` only) |
| `edgeathlete/rack/{rack_number}/state` | Django | the rack tablet at that rack |
| `edgeathlete/rack/command` | Django / a coach (Phase 14; `mosquitto_pub` today) | EVERY rack tablet, from boot |
| `edgeathlete/dashboard/state` | Django | the team wall display |
| `edgeathlete/coach/state` | Django | the coach tablet |
