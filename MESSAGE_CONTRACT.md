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
  "weight_lbs": 230.0,   // the ACTUAL load (last_weight_lbs / target, or a numpad edit) — NOT the prescription
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

```jsonc
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

```jsonc
// PATCH /api/sessions/3/   body: {}
{
  "id": 3, "label": "Thursday — Lower + Push",
  "ended_at": "2026-07-25T06:24:28Z",
  "daily_report": { "id": 1, "generated_at": "2026-07-25T06:24:28Z" }
}
```

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

```jsonc
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
> renaming in P9; see the merge canon's drift table.

### `GET|POST /api/training-groups/` — TrainingGroups (coach)

A TrainingGroup is a *subset* of the gym that trains together, not everyone on file.

```jsonc
{ "id": 4, "name": "Varsity Football", "athlete_count": 12 }
```

### `POST /api/training-groups/{id}/athletes/` — set a TrainingGroup's members (coach)

```jsonc
{ "athletes": [3, 4, 7] }        // → the TrainingGroup's full member list
```

Membership is **current-state only**. Adding or removing never rewrites history:
past sessions and sets stay attached to whatever they ran under.

### `GET|POST /api/training-blocks/` — reusable templates (coach)

```jsonc
{ "id": 1, "name": "Fall Strength", "duration_weeks": 8,
  "cadence_days_of_week": "Mon,Wed,Fri" }
```

### `GET|POST /api/training-blocks/{id}/workouts/` — one day inside a template (coach)

```jsonc
{ "training_block": 1, "name": "Day 1 — Lower", "position": 1,
  "exercises": [
    { "exercise": 1, "sets": 5, "reps": 3, "target_percent": 80,
      "velocity_zone_min": 0.5, "velocity_zone_max": 0.8 },
    { "exercise": 2, "sets": 3, "reps": 5, "target_percent": 75 } ] }
```

`position` orders the day and must run 1, 2, 3… with no gaps.

### `GET|POST /api/training-programs/` — deploy a template for a TrainingGroup (coach)

```jsonc
{ "training_group": 4, "training_block": 1,
  "name": "Fall Strength — Varsity", "start_date": "2026-08-01" }
```

Deploying **copies** the template's rows down rather than pointing at them, so
editing the template next season cannot rewrite what this TrainingGroup already trained.
`training_block` may be **null** — a one-off plan is a permanent first-class path,
not a shim (D6).

### `POST /api/sessions/{id}/participation/` — which TrainingGroups train today (coach)

```jsonc
{ "training_group": 4, "training_program": 3 }
```

This is what lets one session hold several TrainingGroups on different plans.

### `GET|PUT|DELETE /api/athletes/{id}/program/` — one athlete's plan (coach)

**Reads as "this athlete's program"; underneath it is TrainingGroup membership**, because
a plan belongs to a TrainingGroup (D12/D13). `PUT { "workout_program_id": 3 }` puts them
in that program's TrainingGroup; `DELETE` takes them out of the TrainingGroups currently
prescribing to them, leaving plan-less TrainingGroups alone.

```jsonc
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

```jsonc
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

```jsonc
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

```jsonc
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