# The APIs

How everything talks to the server. Every route is listed below, grouped by what it
touches — the summary is visible, the detail is one click away.

The few things at the top cut across all of them.

## The permission rule

**Anything a rack tablet must do is open. Anything that changes the plan or the room
needs a coach login.** 15 routes open, 36 coach-only.

**What forced it.** A rack tablet is a kiosk. It boots unattended into full-screen
mode, nobody signs in to it, and there is no keyboard in front of a squat rack. But it
still has to register itself, ask which rack it is, read a plan, and submit a set.

**What we rejected, and why.** Giving each tablet its own credential — provisioning,
storing and rotating a secret on a device that lives in a public room and gets
periodically wiped, for a network that is already private, offline, and has no route
to the internet.

**What it cost — say this out loud.** **Anyone who joins the gym Wi-Fi can read
training data and submit sets.** That is an accepted trade. It is why the Wi-Fi
password matters more than it looks, and why the wall display shows no names
(see {doc}`dashboard`). If this ever runs on a network that is not private, this is
the first decision to revisit.

## "Coach" means "logged in", and nothing more

The check is one line: is this request authenticated?

**What we rejected.** A role system — coach, assistant, athlete, admin. There is
exactly one kind of privileged user in a weight room running this, and a role system
that is never exercised is a system that is wrong the first time someone needs it.

**What it cost.** Any authenticated account has full coach powers. Fine for one gym
with two staff logins; not fine the moment athletes get accounts.

## One path through authentication

Every authenticated request from the front end goes through a single helper. Adding a
coach screen? Import that, rather than writing another fetch wrapper.

Scattered token handling is how one screen quietly ends up unauthenticated, or how a
token refresh fixes three screens and misses the fourth. The token lives in browser
storage on purpose, so a page refresh does not sign a coach out mid-session.

## Route order is load-bearing

Some routes are catch-alls — `racks/<device_id>/` matches almost anything in that
position, including the literal word `register`.

**They are registered last on purpose.** The specific routes above them must match
first, or the catch-all swallows them and they all break at once. **Add new routes
above the catch-alls.** This produces a confusing 404 on an endpoint you can see in
the file.

## System

Health, and the settings an operator changes before a real gym uses the box.


### `/api/health/`

200 when the app can serve and the database answers, 503 when it cannot.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | open — no login |
| **Handler** | `health` |

200 when the app can serve and the database answers, 503 when it cannot. Open on purpose. A health check that needs a login cannot be used by the thing whose job is to notice that logins are broken.

#### Why it is first and open

It answers one question: can this container serve a request and reach the database?

Registered first and deliberately unauthenticated, because **nothing else should have
to be working for it to answer**. It is what the container healthcheck uses, and a
health check that needs a login or a working session is one that lies during exactly
the outage you built it for.

:::::


### `/api/system/status/`

Coach-only.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | 🔒 coach only |
| **Handler** | `system_status` |

Coach-only. What still needs changing before this box faces a real gym. Coach-only on purpose: this is an operator's checklist, not something the whole gym network should be able to read the security posture from.

:::::


### `/api/system/wifi-password/`

Queue a Wi-Fi password change for the host agent to apply.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `POST` |
| **Access** | 🔒 coach only |
| **Handler** | `change_wifi_password` |

Queue a Wi-Fi password change for the host agent to apply. Body: { "coach_password": "...", "new_password": "..." }

:::::


## The room

Rack screens and the sensors on them.


### `/api/racks/register/`

A rack tablet announces itself.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `POST` |
| **Access** | open — no login |
| **Handler** | `rack_register` |

A rack tablet announces itself. Make (or find) its RackScreen row by device_id; rack_number stays empty until a coach assigns it. Body: { device_id }.

:::::


### `/api/racks/racknumber/`

A waiting tablet asks "which rack am I?" Returns its rack_number (empty until a coach assigns it).

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | open — no login |
| **Handler** | `rack_racknumber` |

A waiting tablet asks "which rack am I?" Returns its rack_number (empty until a coach assigns it). Query: ?device_id=...

:::::


### `/api/racks/unassigned/`

Coach-only: list every tablet still waiting for a rack (rack_number empty).

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | 🔒 coach only |
| **Handler** | `racks_unassigned` |

:::::


### `/api/racks/<int:rack_number>/checkin/`

Record that an athlete signed in at this rack (Phase 11 Step 2).

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `POST` |
| **Access** | open — no login |
| **Handler** | `rack_checkin` |

Record that an athlete signed in at this rack (Phase 11 Step 2). Append-only: writes a new RackCheckIn, which makes THIS rack the athlete's current one for the session (newest wins). This is the one thing that "moves" an athlete to a rack — a hand tap on the check-in screen today, an NFC tap later. Body: { athlete }.

:::::


### `/api/racks/<int:rack_number>/checkins/`

The rack's HOT LIST: athletes this rack currently 'owns' — those whose NEWEST check-in this session is this rack.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | open — no login |
| **Handler** | `rack_checkins` |

The rack's HOT LIST: athletes this rack currently 'owns' — those whose NEWEST check-in this session is this rack. Surfaced first on the check-in screen for fast re-pick. Derived from RackCheckIn (newest-wins per athlete); nothing new stored; session-scoped.

:::::


### `/api/nodes/`

Open: list every sensor node and its latest status.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | open — no login |
| **Handler** | `nodes_list` |

:::::


### `/api/racks/<str:device_id>/`

Coach-only: give a waiting tablet its rack number.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `PATCH` |
| **Access** | 🔒 coach only |
| **Handler** | `rack_assign` |

Coach-only: give a waiting tablet its rack number. Body: { rack_number }.

#### Known gap: nothing can un-assign a rack

This only ever *sets* a rack number. **Nothing clears one**, and the waiting list
above only shows tablets with no number — so a tablet assigned once can never return
to it. See the deadlock in {doc}`rack-tablet`.

:::::


### `/api/nodes/<str:node_id>/`

Coach-only: reassign a node to a different rack (or update its fields).

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `PATCH` |
| **Access** | 🔒 coach only |
| **Handler** | `node_detail` |

:::::


## People

Athletes, the groups they train in, and the staff who run those groups.


### `/api/athletes/`

GET: list all lifters (open).

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,POST` |
| **Access** | open — no login |
| **Handler** | `athletes_view` |

GET: list all lifters (open). POST: add a lifter (coach only).

:::::


### `/api/athletes/<int:athlete_id>/`

Coach-only: read or update one lifter.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,PATCH` |
| **Access** | 🔒 coach only |
| **Handler** | `athlete_detail` |

Coach-only: read or update one lifter. GET matters more than it looks. `notes` is a plain field on Athlete rather than its own resource (merge canon R1), so this is the ONLY way to read a coach's notes on someone — there is no notes route to fall back on. A detail endpoint that could be written but not read forced the coach screen to pull the entire roster just to see one athlete's note.

:::::


### `/api/training-groups/`

Coach-only: list or create TrainingGroups.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,POST` |
| **Access** | 🔒 coach only |
| **Handler** | `training_groups_view` |

Coach-only: list or create TrainingGroups. A TrainingGroup is a NAMED SUBSET of athletes who train the same plan — not the whole roster. A gym runs several at once (a team TrainingGroup, a position TrainingGroup, a rehab group), and an athlete can be in more than one. Staff are a LIST, not a field: see `training_group_coaches_view`. Whoever creates a group becomes its head coach, because a group with no staff at all is never what someone meant to make.

:::::


### `/api/training-groups/<int:group_id>/athletes/`

Coach-only: who is in this TrainingGroup.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,POST,DELETE` |
| **Access** | 🔒 coach only |
| **Handler** | `training_group_athletes_view` |

Coach-only: who is in this TrainingGroup. POST adds, DELETE removes; both take {"athletes": [ids]}. Membership is current-state only — taking someone out never rewrites what they already trained, because history lives on the sets they actually did.

:::::


### `/api/training-groups/<int:group_id>/coaches/`

Coach-only: who runs this TrainingGroup.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,POST,PATCH,DELETE` |
| **Access** | 🔒 coach only |
| **Handler** | `training_group_coaches_view` |

Coach-only: who runs this TrainingGroup. This replaced a single `coach` field on the group in P11, because a real weight room puts several staff on one group and one field can only name one of them. GET -> the staff list POST -> add someone: { "coach": 4, "role": "assistant" } PATCH -> change a role: { "coach": 4, "role": "head" } DELETE -> remove someone: { "coach": 4 } ⚠️ Being on this list is a STATEMENT, not a permission. Nothing here is consulted when deciding whether a write is allowed — `IsCoach` still means "is authenticated". That is the canon's filter-not-fence decision, and it is deliberate: recording who runs what is useful on its own, and enforcement can be added later on top of this without undoing any of it.

:::::


### `/api/athletes/<int:athlete_id>/program/`

What this athlete is training, and which TrainingGroup decides it.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,PUT,DELETE` |
| **Access** | 🔒 coach only |
| **Handler** | `athlete_program_view` |

What this athlete is training, and which TrainingGroup decides it. HIS PAGE ASKS A QUESTION OUR MODEL ANSWERS DIFFERENTLY. His planning screen was built where a program is pinned onto one athlete. Here a program belongs to a GROUP, and an athlete trains it by being in that TrainingGroup (D12) — which is what lets one plan serve thirty people and one athlete carry two plans at once (D13). So the route keeps its name and its shape, and the meaning underneath is TrainingGroup membership: GET -> every program that currently applies to them, and via which TrainingGroup PUT -> put them in the TrainingGroup that runs this program DELETE -> take them out of the TrainingGroups currently prescribing to them Writes therefore have a WIDER effect than the wording suggests, and the response says so plainly (`groups_changed`) rather than letting a coach discover it later. Both directions are reversible, and neither touches history — past sessions and sets stay attached to whatever they ran under.

:::::


### `/api/athletes/<int:athlete_id>/program-exercises/<int:exercise_id>/override/`

Coach-only: an exception for one athlete on one prescribed movement.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,PUT,DELETE` |
| **Access** | 🔒 coach only |
| **Handler** | `athlete_exercise_override_view` |

Coach-only: an exception for one athlete on one prescribed movement. For the outlier the TrainingGroup percentage doesn't suit — someone coming back from injury, or a lifter whose bench is far behind their squat. It overrides the PERCENTAGE, never a fixed weight, so their number still tracks their own max instead of freezing in place. `exercise_id` here is the program-exercise row being overridden (the specific line in that TrainingGroup's plan), not the catalog movement. Most athletes never need one of these. It is an escape hatch, not the path.

:::::


## The movement catalog

The shared vocabulary plans are written in.


### `/api/exercises/`

Open: list the movement catalog — the official set of exercises the rack and coach pickers choose from, so nobody hand-types a name into drift.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | open — no login |
| **Handler** | `exercises_list` |

:::::


### `/api/block-categories/`

Coach-only: the catalog's label vocabulary — "Off-season", "Football".

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,POST` |
| **Access** | 🔒 coach only |
| **Handler** | `block_categories_view` |

Coach-only: the catalog's label vocabulary — "Off-season", "Football". Shared by the whole department on purpose: the labels are only useful if everyone files things under the same words. Names are unique, so a second attempt at one that exists comes back 400 rather than quietly creating a near-duplicate.

:::::


## Templates

Reusable training a coach designs once.


### `/api/training-blocks/`

Coach-only: the reusable TEMPLATES a coach designs once and redeploys.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,POST` |
| **Access** | 🔒 coach only |
| **Handler** | `training_blocks_view` |

Coach-only: the reusable TEMPLATES a coach designs once and redeploys. A TrainingBlock has no TrainingGroup and no dates — it is the recipe, not a serving of it. Blocks are GLOBAL ON PURPOSE. The whole department can see and reuse every one, because a good block getting reused is the point of a shared catalog. So `?coach=` is a LENS, NOT A FENCE — it exists so nobody scrolls a department-sized list to find their own work, and the full list is always one request away. It grants nothing and forbids nothing. GET /api/training-blocks/ -> every block (default) GET /api/training-blocks/?coach=me -> only the caller's GET /api/training-blocks/?coach=4 -> only that coach's GET /api/training-blocks/?category=2 -> only blocks with that label GET /api/training-blocks/?category=2&category=5 -> EITHER label (any-of) GET /api/training-blocks/?sort=recent -> most recently EDITED first Several `category` values mean ANY-OF, not all-of, because the labels sit on different axes — "Off-season" and "Football" are not competing answers to one question, and asking for both meaning "must be both" would usually return nothing. Any-of matches how a filter bar with checkboxes reads. `sort=recent` orders by `updated_at`, which P10 maintains whenever anyone edits a block's days or rows. Default order stays alphabetical, because a catalog you are browsing rather than resuming reads better by name.

:::::


### `/api/training-blocks/<int:block_id>/`

Coach-only: read or amend one block's own fields.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,PATCH` |
| **Access** | 🔒 coach only |
| **Handler** | `training_block_detail` |

Coach-only: read or amend one block's own fields. This exists because categories would otherwise be write-once. Every block that already existed before P11 has no labels, and with create-only routes there would be no way to give it any — the feature would only ever apply to blocks made after it shipped. PATCH covers the block's OWN fields (name, categories, duration, cadence). The days and rows inside it have their own routes from P10. ⚠️ There is deliberately NO DELETE here. Nothing in the product deletes a whole block, and the canon's reasoning for `?coach=` being a filter rather than a permission fence rests partly on that. Adding one is a real decision, not a convenience — make it on purpose.

:::::


### `/api/training-blocks/<int:block_id>/workouts/`

Coach-only: the individual days inside a template, and their movements.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,POST` |
| **Access** | 🔒 coach only |
| **Handler** | `training_block_workouts_view` |

Coach-only: the individual days inside a template, and their movements. The block is in the URL rather than the body, because a day cannot exist without one — nesting says that in the address instead of leaving it as a field a caller could forget. POST accepts a whole day at once — its name, its position in the block, and the movements in order — because a coach thinks in days, not in rows: POST /api/training-blocks/1/workouts/ { "name": "Day 1 — Lower", "position": 1, "exercises": [ {"exercise": 3, "sets": 5, "reps": 3, "target_percent": 80} ] } Writing the day in one call also means a half-entered workout can't exist.

:::::


### `/api/training-blocks/<int:block_id>/workout-order/`

Coach-only: set the order of the days in a template.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `PUT` |
| **Access** | 🔒 coach only |
| **Handler** | `training_block_workout_order` |

Coach-only: set the order of the days in a template. Takes the WHOLE list — {"workout_ids": [12, 9, 14]} — not one day at a time. See services/planning.apply_order for why that is the only shape that works against a non-deferrable position constraint, and why it is the better API regardless.

:::::


### `/api/training-blocks/<int:block_id>/workouts/<int:workout_id>/`

Coach-only: rename or remove one day in a template.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `PATCH,DELETE` |
| **Access** | 🔒 coach only |
| **Handler** | `training_block_workout_detail` |

Coach-only: rename or remove one day in a template. Deleting takes its prescription rows with it (they cannot outlive the day they belong to) but leaves every deployed program untouched.

:::::


### `/api/training-blocks/<int:block_id>/workouts/<int:workout_id>/exercise-order/`

Coach-only: set the order of the movements inside one template day.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `PUT` |
| **Access** | 🔒 coach only |
| **Handler** | `training_block_exercise_order` |

:::::


### `/api/training-blocks/<int:block_id>/workouts/<int:workout_id>/exercises/<int:exercise_id>/`

Coach-only: change or remove one prescribed movement in a template day.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `PATCH,DELETE` |
| **Access** | 🔒 coach only |
| **Handler** | `training_block_exercise_detail` |

:::::


## Programs and the calendar

A template placed in time, and the slots it generates.


### `/api/training-programs/`

Coach-only: a template DEPLOYED for a TrainingGroup, starting on a date.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,POST` |
| **Access** | 🔒 coach only |
| **Handler** | `training_programs_view` |

Coach-only: a template DEPLOYED for a TrainingGroup, starting on a date. Two ways to create one, both first-class: with "training_block" — copy that template down for this TrainingGroup without "training_block" — a one-off plan authored directly for the TrainingGroup, no template involved. Turning a program back INTO a reusable template is `POST training-programs/{id}/promote/` — and it copies the days and rows up, because pointing `training_block` at a new block would only record provenance and leave the block empty.

:::::


### `/api/training-programs/<int:program_id>/promote/`

Coach-only: turn this program into a new reusable TrainingBlock.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `POST` |
| **Access** | 🔒 coach only |
| **Handler** | `training_program_promote` |

Coach-only: turn this program into a new reusable TrainingBlock. For the plan a coach tuned until it was better than the template it came from — or wrote from scratch for one group and now wants to run again. Body: `{ "name": "Fall Strength v2" }` — optional, defaults to the program's own name. ⚠️ This COPIES the days and prescription rows up into the new block. It is not a matter of pointing `training_block` at a fresh row: that records provenance and copies nothing, so the block would come out empty and deploying it would hand a group a plan with no movements in it. The program itself is unchanged apart from its `training_block` now naming the block it is a deployment of.

:::::


### `/api/scheduled-sessions/`

Coach-only: the calendar — planned training slots.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | 🔒 coach only |
| **Handler** | `scheduled_sessions_view` |

Coach-only: the calendar — planned training slots. A slot says "this program's Day 2, on the 14th". It is a PLAN: `session` is null until a coach creates that day (see `scheduled_session_create_session`). GET /api/scheduled-sessions/ -> every slot GET /api/scheduled-sessions/?training_program=3 -> one program's calendar GET /api/scheduled-sessions/?training_group=2 -> one group's GET /api/scheduled-sessions/?from=2026-08-01&to=2026-08-31 -> a date window GET /api/scheduled-sessions/?unrun=true -> only slots with no session Slots are generated when a block is deployed and are FROZEN after that (canon D20) — there is deliberately no POST here. A calendar you can hand-append to would drift from the block that produced it, and "where did this extra Tuesday come from" is not a question worth creating.

:::::


### `/api/scheduled-sessions/<int:slot_id>/`

Coach-only: read a slot, or MOVE it to another date.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,PATCH` |
| **Access** | 🔒 coach only |
| **Handler** | `scheduled_session_detail` |

Coach-only: read a slot, or MOVE it to another date. Moving is a single `date` write and regenerates nothing — that is the whole design (canon D20). The rest of a slot is decided when the schedule is generated and is read-only here. ⚠️ A slot whose session has already been created can still be moved, and that is deliberate: the coach is correcting the calendar, and the session keeps its own real start time regardless. The plan and the record are separate things.

:::::


### `/api/scheduled-sessions/<int:slot_id>/session/`

Coach-only: turn a planned slot into a real training session.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `POST` |
| **Access** | 🔒 coach only |
| **Handler** | `scheduled_session_create_session` |

Coach-only: turn a planned slot into a real training session. ⚠️ CREATE IS NOT START. The session comes back with `started_at: null` — it exists, it is linked to the slot, its roster and participation are set up, and it holds no racks and captures no check-ins until someone starts it. That is the point of P14: a coach can set Thursday up on Tuesday. The roster is the group's current members, and a SessionParticipation row points the group at the day this slot runs — the two things that were being done by hand in the seed command and by no UI at all. Idempotent: a slot that already has a session returns it rather than making a second one. Two taps on a calendar must not produce two Thursdays.

:::::


## Running a training day

The live session and the room's current picture.


### `/api/room-state/`

The live picture of the room, for the wall display and the coach tablet.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | open — no login |
| **Handler** | `room_state` |

The live picture of the room, for the wall display and the coach tablet. ONE endpoint serves both audiences, chosen by `?details=true` (merge canon R3 — his branch had this split across `wall-state/` and `room-state/`, two routes backed by the identical function one boolean apart; folding them leaves a single thing to document and maintain): GET /api/room-state/ -> WALL view. Open, because the wall screen is a shared display nobody logs into. Names and numbers only: no database ids, no roster. GET /api/room-state/?details=true -> COACH view. Requires a coach login and adds ids, the participant roster, and node health so the UI can link through to records. Everything is DERIVED per request from check-ins and set/rep rows — there is no room-state table (canon D2/D3/D8). See services/room_state.py for how.

:::::


### `/api/sessions/`

Coach-only: start a training session.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `POST` |
| **Access** | 🔒 coach only |
| **Handler** | `sessions_view` |

Coach-only: start a training session. ONE OPEN SESSION AT A TIME (canon D18). A second open session is refused with 409, naming the one already open. Why this matters more than it looks: `_active_session()` is last-one-wins, and the rack screens follow it. So a stray second session did not produce an error — it silently became the one athletes checked into, their sets attached to a session with no participants, and the day's report came out wrong while every tablet looked completely normal. It also made "End training day" look broken, because ending the top session instantly promoted the next one and the panel redrew identically. The refusal names the open session so the caller can offer "end that one first" instead of a dead end. `force` is deliberately NOT offered: there is no honest reason to run two days at once, and an override would just move the quiet corruption behind a flag.

:::::


### `/api/sessions/active/`

The rack tablet's ONE startup fetch (open, no login).

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | open — no login |
| **Handler** | `sessions_active` |

The rack tablet's ONE startup fetch (open, no login). Returns the current session plus everything the rack screen needs to run a whole set-logging session without asking again: who's on the roster, each athlete's current maxes, and the planned exercises with their targets + velocity zones. THE SEAM, AND WHY THIS SHAPE NEVER CHANGED. Each roster entry carries a RESOLVED absolute `targets` map {exercise_id: target_weight_lbs}. The tablet READS that number; it has never computed anything from a percent and a max, and it must not start. That was a deliberate bet made while the plan still stored one typed weight per athlete: keep the resolved number on the wire, and a future percent-of-max system can compute the SAME field server-side without the tablet noticing. The bet paid — plans now store `target_percent`, the pounds are worked out in services/plan_resolution.py, and this response shape did not move by a single field. That is why react/src/rack/ is frozen. See §6.3. 1. `exercise_id` is the Exercise catalog id — every plan row, Set, and reference max links to that one catalog — with the display `name` riding alongside it in session_exercises. 2. `session_exercises[]` carries the velocity zone, which is where the tablet reads it from to color reps. It deliberately does NOT carry `target_percent`: percentages are resolved here, not on the tablet. `maxes` (from AthleteReferenceMax — each athlete's newest row per exercise) rides along for coach-side callers. ⚠️ THE RACK SCREEN DOES NOT READ IT and never has; it reads `targets`. Do not "fix" a weight bug by reaching for this map on the tablet — the fix belongs in plan_resolution.py. ⚠️ REFERENCE max, not a lifetime best. It is what the athlete can do NOW, so it can go DOWN, and prescribed weights are supposed to follow it down. "Active" comes from `_active_session()` — the one definition every endpoint shares, so the rack and the coach tablet can never disagree about which session is live.

:::::


### `/api/sessions/active/athlete/<int:athlete_id>/progress/`

The rack's athlete DAY-VIEW (open, no login).

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | open — no login |
| **Handler** | `athlete_progress` |

The rack's athlete DAY-VIEW (open, no login). For one athlete in the active session, returns their planned movements (from Program) with live progress (derived from their completed Set rows THIS session) — so any rack shows the same, up-to-date view. Everything is DERIVED per request; no new tables. Fetched when an athlete checks in at a rack, and again after each of their sets completes (Phase 11 Step 2). "Active" session is resolved exactly like sessions_active (most recent with ended_at null). Progress rules: - A set counts as COMPLETED once it has an ended_at (set-complete stamps it). - False sets are counted separately and NEVER advance the set number. - next_set_number = completed (non-false) sets + 1 — the authoritative set_number to send at set-create (a client counter can't stay correct across rack moves + supersets, so the server owns it). - Movements are ordered by Program.id (the athlete's program-creation order, which is the intended workout order). - last_weight_lbs = the actual load of this athlete's NEWEST non-false completed set of that movement THIS session (null if none yet). It lets the tablet default the next set to what they last actually lifted — carrying an on-the-fly weight change forward across reloads/rack moves WITHIN the session, while never touching the prescribed target. TrainingSession-scoped only: a prior session's loads are never read, so each session starts at target.

:::::


### `/api/sessions/active/status/`

Room state for the active session: each athlete's live status + since-when.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | open — no login |
| **Handler** | `session_status` |

Room state for the active session: each athlete's live status + since-when. The rack's rest/check-in cards turn this into a ticking timer + status label, and a coach tablet can reuse the exact same data. Derived per request from `Set` + `RackCheckIn` — no new tables. Status per athlete (first match wins): lifting — a set is in progress right now → `since` = when it started resting — their most recent set has ended → `since` = when it ended ready — checked in at a rack, no set yet → `since` = check-in time not_started — no activity this session → `since` = null

:::::


### `/api/sessions/<int:session_id>/`

Coach-only: update a session.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `PATCH` |
| **Access** | 🔒 coach only |
| **Handler** | `session_detail` |

Coach-only: update a session. A PATCH with no ended_at means "end it now". ENDING A SESSION IS A BIG DEAL, and it happens right here — there is no separate `end/` route, because "end the session" is just "set its end time" and this endpoint already did that (merge canon R2). When this PATCH ends a day it hands off to the completion service, which atomically freezes the immutable DailyReport and recalculates everyone's reference maxes (D10). The response gains a `daily_report` block when a report was produced, so a coach tablet can jump straight to the finished report without a second call. Ending an already-ended session is safe: it returns the existing report rather than writing a second one. It also gains an `ended` block naming the day that just ended and whether another is still open (canon D18). Before P12 the coach panel could redraw looking completely unchanged — ending the top of several stacked sessions instantly promoted the next one — so the button appeared to do nothing while working perfectly every time. Saying what happened is the fix for that; the create guard is what stops the stack forming in the first place.

:::::


### `/api/sessions/<int:session_id>/participation/`

Coach-only: which TrainingGroups are training in this session, and what they're doing.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,POST,DELETE` |
| **Access** | 🔒 coach only |
| **Handler** | `session_participation_view` |

Coach-only: which TrainingGroups are training in this session, and what they're doing. This is what makes one session shared. Several TrainingGroups can be in the gym at the same time on different plans, and each athlete gets their own TrainingGroup's workout — which is exactly how an athlete in two TrainingGroups ends up doing both. POST body: { "training_program": 1, "training_program_workout": 4 } The workout is the day being run. Until it is set, that TrainingGroup has nothing scheduled and its athletes see an empty list — a planning gap, not an error.

:::::


### `/api/sessions/<int:session_id>/start/`

Coach-only: start a session that was created ahead of time.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `POST` |
| **Access** | 🔒 coach only |
| **Handler** | `session_start` |

Coach-only: start a session that was created ahead of time. Its own route rather than a PATCH, deliberately. `PATCH /api/sessions/{id}/` with an empty body already means "END the day now" (canon R2), so making start another PATCH would leave one call's meaning resting on subtle differences in the body — for two actions that are opposites. Ending is still the PATCH; starting is this. Refuses (409) while another day is already running, for exactly the reasons in `sessions_view`: the racks follow the active session, so a second one silently captures check-ins.

:::::


## Performed work

Sets, reps, prescriptions, maxes, and everything derived from them.


### `/api/prescriptions/`

GET: an athlete's training plan for today, ?athlete={id} to filter (open).

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET,POST` |
| **Access** | open — no login |
| **Handler** | `prescriptions_view` |

GET: an athlete's training plan for today, ?athlete={id} to filter (open). SAME ADDRESS, DIFFERENT SOURCE. This used to read a per-athlete table where a coach typed one weight per person. That table is gone: a plan now belongs to a TrainingGroup and says a PERCENT, and the pounds are worked out per athlete from their own reference max. Callers see the same fields either way, which is the point — this is a diagnostic read, and it had no business breaking over where the numbers come from. `id` is null now. There is no longer a single row to point at: what comes back is resolved from the athlete's group plan, not stored per athlete.

:::::


### `/api/reports/`

Coach-only: browse finished training days, newest first.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | 🔒 coach only |
| **Handler** | `reports_view` |

Coach-only: browse finished training days, newest first. ONE family of report routes serves both "all reports" and "this athlete's reports" — the athlete view is just a filter, so it is a query parameter rather than a parallel set of `athletes/{id}/reports/...` endpoints (merge canon R6). Query: ?athlete={id}

:::::


### `/api/reports/<int:report_id>/`

Coach-only: one finished day in full.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | 🔒 coach only |
| **Handler** | `report_detail_view` |

Coach-only: one finished day in full. With ?athlete={id} the report is narrowed to that athlete's own work — the same stored snapshot, read through a single-athlete lens, so an athlete's record and the team record can never disagree.

:::::


### `/api/reports/<int:report_id>/pdf/`

Coach-only: the same finished day, as a printable PDF.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | 🔒 coach only |
| **Handler** | `report_pdf_view` |

Coach-only: the same finished day, as a printable PDF. Coaches hand these to athletes and staff who are nowhere near a tablet, so the PDF renders from the SAME frozen snapshot the JSON detail view reads — a printout and the screen can never disagree. ?athlete={id} narrows it to one athlete's copy.

:::::


### `/api/reference-maxes/`

Coach-only: record what athletes can currently lift.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `POST` |
| **Access** | 🔒 coach only |
| **Handler** | `reference_maxes_view` |

Coach-only: record what athletes can currently lift. THIS IS THE PRESCRIPTION LEVER. Every target weight is a percentage of these numbers, so this is how a coach moves what the whole gym is prescribed. It is a different thing from adjusting the load on a bar today — that rides on the set itself and changes nothing about the plan. Takes a LIST so a coach can enter a whole TrainingGroup's testing day in one go rather than one athlete at a time: { "exercise": 1, "rep_basis": 1, "entries": [ {"athlete": 3, "reference_weight_lbs": 315}, {"athlete": 4, "reference_weight_lbs": 275} ] } Every entry writes a NEW row; nothing is overwritten. An athlete's current reference is simply their newest row, so re-entering a number supersedes the old one while the history stays intact and graphable. Applies forward only — targets an athlete already trained against are never rewritten.

:::::


### `/api/sets/`

Start a set: create the empty set record when an athlete begins, so the finish endpoint has something to fill in.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `POST` |
| **Access** | open — no login |
| **Handler** | `set_create` |

Start a set: create the empty set record when an athlete begins, so the finish endpoint has something to fill in. Body: session, athlete, exercise, set_number, and optionally node + weight_lbs.

:::::


### `/api/sets/<int:set_id>/complete/`

Save a finished set.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `POST` |
| **Access** | open — no login |
| **Handler** | `set_complete` |

Save a finished set. Take all its reps + totals and write them to the database in ONE all-or-nothing step (if anything fails, nothing saves). This is the only code path that creates Rep rows. A false set saves zero reps. We also flag whether it was the athlete's best-ever velocity or weight.

#### The only way rep data reaches the database

This takes a **whole set at once** — the summary plus every rep — written in a single
transaction.

There is no endpoint that accepts an individual rep, and no streaming path. The
server's message subscriber ignores rep topics entirely (see {doc}`real-time`).

**Why that matters as a rule:** the database can never hold a half-written set. Either
the whole set landed or none of it did. Anything adding a per-rep write path is
fighting the design in {doc}`rack-tablet`, not extending it.

:::::


### `/api/analytics/session/<int:session_id>/`

Coach-only: a quick summary of one session — how many sets and reps total, and each athlete's average velocity.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | 🔒 coach only |
| **Handler** | `analytics_session` |

:::::


### `/api/analytics/athlete/<int:athlete_id>/`

Coach-only: everything the athlete and history tabs need (P13).

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `GET` |
| **Access** | 🔒 coach only |
| **Handler** | `analytics_athlete` |

Coach-only: everything the athlete and history tabs need (P13). One call answers both of a coach's questions about a person: how are they doing overall (`summary` and `exercise_summaries`), and what did they actually do (`sets`, each with its reps). One request rather than three, because these tabs sit side by side and a coach flips between them. ⚠️ `summary` is aggregated across ALL history while `sets` is capped at the 50 most recent — the UI tells the coach exactly that, so totals computed from the truncated list would make the screen lie. See services/athlete_analytics.py. This WIDENED an older response that returned only `{athlete_id, sets:[...]}` with a flat velocity trend. `athlete_id` is kept for anything still reading it; the per-set key was `set_id` and is now `id`, matching every other set payload we serve.

:::::


## Spreadsheet import

Two routes for all three kinds of sheet.


### `/api/imports/preview/`

Check an uploaded spreadsheet and write NOTHING.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `POST` |
| **Access** | 🔒 coach only |
| **Handler** | `import_preview` |

Check an uploaded spreadsheet and write NOTHING. Always the first half of the pair: the coach sees what we understood, fixes anything marked wrong, and only then imports. See services/csv_import.py.

:::::


### `/api/imports/`

Re-check an uploaded spreadsheet and, if it is clean, save it in one step.

:::::{dropdown} Detail

| | |
|---|---|
| **Methods** | `POST` |
| **Access** | 🔒 coach only |
| **Handler** | `import_commit` |

Re-check an uploaded spreadsheet and, if it is clean, save it in one step. Re-checked rather than trusting the preview because the gym changes between the two calls — an athlete could be renamed, or another coach could import the same sheet first. Nothing is saved unless every row passes now.

:::::

