# Edge Athlete — Message Contract

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
```jsonc
{
  "node_id": "rack_1",
  "rep_number": 1,          // advisory ordering only — see note below
  "mean_velocity": 0.72,
  "peak_velocity": 0.91,
  "duration_ms": 640,
  "timestamp": "2026-07-07T07:23:55Z"
}
```
- **Published by:** the node firmware (Phase 13) and Derrilon's `simulate_node`.
- **Consumed by:** the rack tablet, subscribed to *its own linked node's* rep topic.
- **Not here:** `velocity_color`. The tablet computes that (see Derived values).

### `edgeathlete/node/{node_id}/pulse` — heartbeat, every ~5s
```jsonc
{
  "node_id": "rack_1",
  "event_type": "pulse",
  "battery_level": 87,
  "signal_strength": -55,
  "firmware_version": "1.0.0",
  "timestamp": "2026-07-07T07:23:55Z"
}
```
- **Published by:** node firmware + `simulate_node`.
- **Consumed by:** Django's MQTT subscriber, which listens to `edgeathlete/node/+/pulse`
  **only** and updates the matching `Node` row. Reps never reach Django this way.

---

## 2. Django → broker (broadcasts to the screens)

Every broadcast has a `"type"` string; consumers switch on it. Fields depend on
the type.

### `edgeathlete/rack/{rack_number}/state` — for the tablet at that rack
```jsonc
// a set was completed
{ "type": "set_complete", "set_id": 12, "athlete": {"id":4,"name":"Jordan Lee"},
  "reps_completed": 5, "avg_velocity": 0.70, "peak_velocity": 0.91, "is_false_set": false }

// a different sensor was linked to this rack
{ "type": "node_reassigned", "node_id": "rack_1" }

// an athlete checked in at this rack
{ "type": "athlete_checkin", "athlete": {"id":4,"name":"Jordan Lee"}, "rack_number": 3 }
```

### `edgeathlete/dashboard/state` — for the team wall display
```jsonc
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
```jsonc
{ "type": "fatigue_alert", "athlete": {"id":4,"name":"Jordan Lee"}, "rack_number": 3 }
```
- Fatigue detection is Phase 15 — treat this topic's exact fields as **provisional**
  until then. The envelope (`type` + `athlete`) is stable; extra fields may be added.

### `edgeathlete/rack/command` — remote commands to tablets (any/all)
```jsonc
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
```jsonc
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
```jsonc
{
  "session_id": 1,
  "athlete": { "id": 4, "name": "Jordan Lee" },
  "current_exercise_id": 1,          // SUGGESTED current = first movement not yet complete (Program.id order)
  "movements": [
    { "exercise_id": 1, "name": "Back Squat",
      "planned_sets": 5, "target_reps": 3,
      "target_weight_lbs": 225.0,    // resolved from Program; null → inline "starting weight" (SPEC Phase 11)
      "velocity_zone_min": 0.5, "velocity_zone_max": 0.8,
      "completed_sets": 2, "false_sets": 0,
      "next_set_number": 3,          // completed (non-false) sets + 1 — authoritative set_number at set-create
      "status": "in_progress" }      // not_started | in_progress | complete
  ]
}
```
- Fetched when an athlete **checks in** at a rack (Phase 11 Step 2), and again after each of their sets completes. **Derived per request** from the athlete's `Program` rows + their completed `Set` rows this session — **no new tables**.
- **`movements` order = `Program.id`** (the athlete's program-creation order = intended workout order). The server order never changes; the tablet may float an *in-progress* movement to the top presentationally only (see SPEC Phase 11 Step 2).
- **`next_set_number` is the source of truth for `set_number`** on `POST /api/sets/` — NOT a client counter, so numbering stays correct across rack moves + supersets.
- **`completed_sets`** counts non-false `Set` rows for that athlete/exercise this session; **`false_sets`** counts false ones. `status` = `complete` once `completed_sets >= planned_sets`.
- **`current_exercise_id`** is a suggestion only; the athlete may pick any movement.
- **No active session →** `{ "session_id": null, "athlete": {…}, "current_exercise_id": null, "movements": [] }`. **Athlete not in the session roster →** `404`.

### `GET /api/sessions/active/status/` — room state: every athlete's live status (open)
Each session athlete's current status + when it started, so the rack's rest/check-in cards can show a ticking timer + status label, and a coach tablet can reuse the same data. **Derived** from `Set` + `RackCheckIn`; no new tables.
```jsonc
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

### `POST /api/racks/{rack_number}/checkin/` — record an athlete signing in at a rack (open)
Body: `{ "athlete": 4 }`. Writes an append-only `RackCheckIn`, making THIS rack the athlete's current one for the session (newest-wins). Returns `201`:
```jsonc
{ "session_id": 1, "athlete": { "id": 4, "name": "Jordan Lee" }, "rack_number": 3 }
```
- No active session → `400`. Unknown athlete, or athlete not on the session roster → `404`.
- Called when an athlete taps in on the rack's check-in screen (Phase 11 Step 2). This is the ONE thing that "moves" an athlete to a rack; a later NFC tap would shortcut into the same call.

### `GET /api/racks/{rack_number}/checkins/` — the rack's hot list (open)
The athletes this rack currently "owns" — those whose NEWEST `RackCheckIn` this session is this rack. Surfaced first on the check-in screen for fast re-pick; the full roster (from `/api/sessions/active/`) stays reachable below it.
```jsonc
{ "session_id": 1, "rack_number": 3, "athletes": [ { "athlete_id": 4, "name": "Jordan Lee" } ] }
```
- **Derived** from `RackCheckIn` (newest-wins per athlete); session-scoped; nothing new stored. Polled (~5s) alongside the roster while the check-in screen is up.
- No active session → `{ "session_id": null, "rack_number": 3, "athletes": [] }`.

### `POST /api/sets/` — start a set (create) (open)
Called when a set STARTS (Phase 11 Step 3). The server returns the created `Set` incl. its `id`, kept for the complete POST at set end.
```jsonc
{
  "session": 1,          // session_id from GET /api/sessions/active/
  "athlete": 4,          // the checked-in lifter's athlete_id
  "exercise": 1,         // catalog exercise id (the selected movement)
  "set_number": 3,       // = next_set_number from the athlete's progress — NOT a client counter
  "weight_lbs": 225.0,   // the resolved target (or the manually-entered starting weight)
  "is_makeup": true,     // = the athlete's has_data (already has a set this session)
  "node": 2              // OPTIONAL: the Node's INTEGER pk (not node_id) — links the set to its sensor
}
```
- `weight_lbs` and `is_makeup` are set HERE (at create), not at complete.
- `node` may be omitted (nullable) — the set still saves, but then the `set_complete`/`athlete_checkin` broadcasts (which need `node.rack_number`) don't fire.

### `POST /api/sets/{id}/complete/` — the batch set-complete body
```jsonc
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

---

## 4. Derived values — who computes what (read this)

These fields are *not* sent raw by the hardware; something computes them. Getting
this wrong is the most likely way two parts disagree.

| Field | Who computes it | How |
|---|---|---|
| `velocity_color` | **the rack tablet**, per rep | Compare the rep's velocity to the *exercise's* velocity zone (`velocity_zone_min/max`), sourced from `session_exercises[]` in the `GET /api/sessions/active/` response the tablet already fetched once at rack-assignment time (Phase 10/11) — **not** `GET /api/programs/`, which the v2 rack-screen flow no longer calls. `green` = on target, `yellow` = dropping, `red` = fatigued. Included when the tablet sends the set-complete body. |
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