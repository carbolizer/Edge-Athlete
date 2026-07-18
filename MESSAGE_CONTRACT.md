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

## 3. REST — the batch set-complete body

Not MQTT, but the same data contract, so it lives here too.

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