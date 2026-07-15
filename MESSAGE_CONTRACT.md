# Edge Athlete — Message Contract

The one place that says exactly what every message looks like: the reps and
heartbeats coming off the nodes, the live broadcasts Django pushes to the
screens, and the body of the batch set-complete request. If you're building a
screen, a simulator, or an endpoint, build to the shapes here so nothing
misreads anything else.

This is the raw reference — Carl folds it into the shared-setup story; Derrilon's
simulator and Braydon's tablet both publish/consume against it.

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
- **Published by:** the node firmware (Phase 9) and `simulate_node --mode rack`.
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

### `edgeathlete/dashboard/state` — privacy-safe room invalidation
```jsonc
{
  "schema_version": 1,
  "type": "room_state_changed",
  "reason": "set_completed", // or "node_health_changed"
  "revision": 184,
  "event_id": "7bfba173-809a-44ee-a8ca-b2f603962f88",
  "occurred_at": "2026-07-13T19:42:31.482Z"
}
```
- **QoS 1, retained.** This event says persisted state changed; it does not carry
  the changed state. Wall and coach clients refetch their privacy-appropriate REST
  snapshot and ignore revisions at or below the revision they already hold.
- This public browser topic never includes athlete, set, session, rack, node,
  screen, weight, target, rep, note, credential, or token fields.
- Wall clients ignore `node_health_changed`; authenticated coach clients reconcile
  hardware state. Node events are created only for material health changes, not
  every five-second pulse.

### `edgeathlete/coach/state` — reserved for future private alerts
```jsonc
{ "type": "fatigue_alert", "athlete": {"id":4,"name":"Jordan Lee"}, "rack_number": 3 }
```
- Fatigue detection is Phase 11 — treat this topic's exact fields as **provisional**
  until then. The envelope (`type` + `athlete`) is stable; extra fields may be added.
- Production monitoring does not subscribe to this topic while the broker permits
  anonymous clients. Coach details are fetched through JWT-protected REST.

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
- Rack requests and `simulate_node --mode monitoring` both call the same atomic
  set-completion service. Monitoring mode does not publish rep MQTT messages, so
  a rack client cannot save the same generated stream a second time. The shared
  completion service is the only code path that creates `Rep` rows.

---

## 4. Derived values — who computes what (read this)

These fields are *not* sent raw by the hardware; something computes them. Getting
this wrong is the most likely way two parts disagree.

| Field | Who computes it | How |
|---|---|---|
| `velocity_color` | **the rack tablet**, per rep | Compare the rep's velocity to the athlete's program zone (`velocity_zone_min/max`, fetched via `GET /api/programs/?athlete={id}`). `green` = on target, `yellow` = dropping, `red` = fatigued. Included when the tablet sends the set-complete body. |
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
| `edgeathlete/dashboard/state` | Django | the team wall display |
| `edgeathlete/coach/state` | Django | the coach tablet |
