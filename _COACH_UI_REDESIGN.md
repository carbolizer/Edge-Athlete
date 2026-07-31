# Coach Admin — State Machine Redesign

> **STATUS: DRAFT / WORKING DOCUMENT.** Nothing here is decided. This is the
> workbench we edit while talking the design through. When it settles, the
> conclusions fold into [`_SPEC.md`](_SPEC.md) and this file goes away.
>
> Branch: `coach-admin-state-machine` (off `SprintBranch`)
> Started: 2026-07-30 · Owner: Devin

---

## The problem, in one sentence

The coach admin surfaces **eight sibling tabs at once**, so a coach can attempt
things in an order that cannot work — and finds out by getting an error back from
the API.

The errors are correct. The backend refusing an impossible action is the safety
net working, and it should stay. But **an error is a bad way to learn that a step
was out of order.** The UI should not offer the step yet.

## The hard constraint

**No backend API changes.** No new routes, no changed shapes, no new fields. This
is entirely a matter of moving existing components and deciding what is visible
when. If a proposal here needs a backend change, that is a signal the proposal is
wrong — say so and find another way.

The rack contract stays frozen. This work never touches `react/src/rack/`.

---

## The vision

### 1. Three states

```
   PLANNING  ──►  SESSION  ──►  ANALYTICS
```

Navigation between them via a **glassmorphism navbar**, colours matched to the
existing UI pattern (`theme.js`).

**RESOLVED 2026-07-30 — the states are a grouping by WHEN, not a re-slicing of
tabs.** The question was "which tab goes where"; the answer is that the tabs were
never the unit. Each state answers one question:

| State | The question | Holds |
|---|---|---|
| **PLANNING** | What is coming up? | TrainingBlock create + **promotion from a TrainingProgram** · TrainingProgram create + instantiation · Calendar · Groups |
| **SESSION** | What is happening right now? | Room view · settings cog → `coach/setup` · quick athlete notes · dev-only top bar · the active-session widget |
| **ANALYTICS** | What happened? | History · Athlete · Notes · Reports |

Devin's framing: *"basically this is a glorified grouping of tabs."* Not a
rebuild — a re-shelving. Worth holding onto, because it keeps the work small.

**Notes appears in two states on purpose.** ✅ **APPROVED 2026-07-30.** In SESSION
it is optimised for *adding* — a quick thought about any athlete, fast, without
leaving the floor view. In ANALYTICS it is for *reviewing*. Same data, two
affordances. A stripped-down athlete view may ride along with the session variant
(TBD).

> **Name needed.** "Mid-floor notes" is a placeholder Devin does not like.
> Candidates to react to: **Quick Note** · **Floor Note** · **Sideline Note** ·
> **Jot**. The name should say *fast and provisional*, not *a different kind of
> note* — it is the same `Athlete.notes` field either way, and calling it
> something too distinct would imply a second store that does not exist.

**The dev-only strip** — "Active racks / Athletes with sets / Sets complete /
Awaiting saved result / Last reconciled" — ✅ **DONE 2026-07-30.** Now hidden
behind `isDevMode()` (`react/src/devMode.js`): always on under `npm run dev`,
and settable in a built container with `localStorage.setItem('ea_dev','1')`.

> **PLANNED, not built — a switch in Room Layout's dev panel.** Console-only means
> it is a feature only someone who has read `devMode.js` can use. Room Layout
> already has a "Dev tools (temporary)" panel with *Seed demo gym* and *Start empty
> session*; the switch belongs there as a third button. Needs a `setDevMode()`
> setter, and the button should say a reload is required, because the coach screen
> reads the flag at render rather than subscribing to it.
Not tied to the coach login — "is a coach" and "is a developer" are different
questions, and every coach in a real gym would otherwise see it. ⚠️ I initially guessed this also covered the "Rack N is ready"
panel. Checking the code showed it does not — see §4.

### 2. The active-session widget lives outside the machine

Outside the three states — a bar, not a state.

**✅ Revised 2026-07-30: it is NOT always visible.** It appears only while a day is
actually running, and disappears when none is. (Earlier draft said always-on;
this supersedes it.) An empty strip on a quiet morning is furniture.

**Ending a day still happens from the widget.** Starting is in SESSION, ending is
in the widget — because ending is something you do while looking at anything, and
the widget is the only thing on screen in all three states.

Longer term this is the slot for **other important notifications** too, so build
it as a general strip that is currently showing a session — not a session bar.

**Add: a derived timer counting up** — how long the current session has been
running.

> ✅ **This needs no new API.** Devin flagged it as the one place a backend change
> might be required. It is not: `services/room_state.py:369` already returns
> `session.started_at` in the room-state payload, unconditionally. The timer is
> `now − started_at`, ticked locally — exactly the pattern the rack screen already
> uses for its own per-second timers. **The zero-backend-change constraint holds
> for the whole redesign.**

### 2b. Staging vs starting a day — ✅ decided 2026-07-30

The two halves live in different states on purpose:

| Act | Where | What it means |
|---|---|---|
| **Stage** a day | **PLANNING** | Create it; it does not run yet. Then **navigate the coach to SESSION** |
| **Start** it | **SESSION** | The day goes live |
| **End** it | **the widget** | Available from any state, while it is running |

**This needs no backend change — the split already exists.** P14 made
`TrainingSession.started_at` nullable precisely so a day can exist before it runs,
and `POST /api/sessions/{id}/start/` is the route that starts a staged one (it
409s if another day is already running). So:

```
PLANNING  POST /api/sessions/            → staged (started_at null)
          → navigate to SESSION
SESSION   POST /api/sessions/{id}/start/ → running
widget    PATCH /api/sessions/{id}/      → ended
```

The UI is being reshaped to match a lifecycle the API already models. That is a
good sign the grouping is right.

⚠️ **Watch the D18 trap.** A staged day is deliberately NOT "active" — "active"
means *started* and not ended. A future staged day must never capture rack
check-ins. The backend already guarantees this; the UI must not imply otherwise by
showing a staged day as if it were live.

### 3. Less chrome on the main screen

| Control | Today | Proposed |
|---|---|---|
| Log out | Top-level button (`Dashboard.jsx:507`) | Under the **Edge Athlete logo** — click the logo to reveal |
| Change device | Top-level button (`Dashboard.jsx:508`) | **Remove.** Room Layout already has it — `CoachTablet.jsx:426` |

> **There are three "change device role" buttons today**, which is the real
> clutter:
>
> | Where | Keep? |
> |---|---|
> | `CoachTablet.jsx:426` — Room Layout header | ✅ Keep — the natural home |
> | `Dashboard.jsx:508` — coach topbar | ❌ Remove (this vision) |
> | `Dashboard.jsx:193` — **wall display** header | ❓ Separate screen, separate call |
>
> An earlier draft of this table cited `Dashboard.jsx:193` as the rack-setup
> button. Wrong — that one is the wall display's.

### 4. "Rack N is ready" — **verdict: delete it**

First, a naming trap that made two earlier answers here confusing:

> **`Dashboard.jsx` is not "the dashboard screen".** It is one file exporting
> `Dashboard({ mode = "wall" })` and rendering **both** roles — the wall display
> (`wall-monitor`, lines 171–187) and the coach tablet (`coach-monitor`, lines
> 488+). There are **two different "ready" strings** in it:
>
> | Line | Screen | String |
> |---|---|---|
> | 177 | **Wall display** | "The room is ready" |
> | 495 | **Coach tablet** | "Rack N is ready" |
>
> Only the second one is in scope here. Splitting this file is probably its own
> cleanup item, since the two screens are meant to be separate.

**Does it serve the coach?** No. Here is the actual render order:

```
coach-detail-workspace
 ├─ no rack selected → StatePanel "No racks assigned"
 └─ rack selected:
     ├─ <RackSelectionControls/>   ← "Rack observation" — ALWAYS renders
     └─ no completed set → StatePanel "Rack N is ready"   ← the thing in question
        otherwise      → set hero + charts + hardware
```

`RackSelectionControls` renders **unconditionally, directly above it**, and already
shows a grid containing:

| Field | What it says when there is no set |
|---|---|
| Movement / Load / Progress | `--` |
| Rack state | the server's `rack.status` |
| **Latest result** | **"No persisted result"** |
| **Hardware** | node id · **"No node assigned"** · **"Node pulse overdue"** |

So the StatePanel restates one field from the panel one line above it — and does it
worse. "Rack 1 is ready" asserts readiness the code never checked, while the
observation grid immediately above can be simultaneously reporting **"Node pulse
overdue"**. The two can contradict each other on screen.

**Why it made sense on Braydon's branch:** there, `RackSelectionControls` was an
**assignment form** — an "Assign" control and athlete dropdowns — not an
observation grid. "Rack N is ready" meant *"ready for you to assign someone"*,
which was true and actionable. D8 removed forward rack-assignment (athletes bind
themselves by checking in), the component became read-only observation, and the
empty state was left restating a field that the replacement already covers.

**✅ DONE 2026-07-30 — deleted.** (Decided here, but not actually removed until later the same day; the first pass cut the *other* rack panel, #12.)

**Decision: delete the `StatePanel` at `Dashboard.jsx:495`.** Nothing is lost — the
observation panel above it answers the same question more accurately. No wording
fix needed, because the line should not exist.

> **The test that produced this answer**, worth reusing on the other nine
> `StatePanel` empty states: not *"did this come from Braydon's branch?"* — P7
> adopted his frontend deliberately, so most of the coach screen did. The question
> is **does the component it was written to sit beside still do the same job?**
> Here it does not.

---

### 4b. The other thirteen `StatePanel` uses — test results

There are **14** in total, not 10. Applying the test — *does the component it was
written to sit beside still do the same job?*

First, the result that kills the shortcut: **every one of these strings exists on
`braydons-dev-branch` verbatim, at identical counts.** Origin discriminates
nothing. The whole coach screen came from there by design (P7).

| # | Line | Panel | Screen | Verdict |
|---|---|---|---|---|
| 1 | 171 | "Opening the weight room" | Wall | ✅ Keep — out of scope |
| 2 | 174 | "Live scoreboard unavailable" | Wall | ✅ Keep — out of scope |
| 3 | 177 | "The room is ready" | Wall | ✅ Keep — the wall's *legitimate* ready: no session started. Not the same bug as §4 |
| 4 | 325 | `No {what} yet` | Coach | ✅ Keep — **ours**, added in P13, replacing one of his. Distinguishes "never trained" from "loading" |
| 5 | 330 | "Choose an athlete" | Coach · athlete | ⚠️ **Collapse** — see below |
| 6 | 386 | "Choose an athlete" | Coach · history | ⚠️ **Collapse** |
| 7 | 391 | "No completed training days" | Coach · history | ✅ Keep — real empty state, distinct from #6 |
| 8 | 403 | "Choose an athlete" | Coach · programs | ⚠️ **Collapse** |
| 9 | 411 | "Choose an athlete" | Coach · notes | ⚠️ **Collapse** |
| 10 | 488 | "Loading coach workspace" | Coach | ✅ Keep — whole-screen, sibling-independent |
| 11 | 489 | "Coach view unavailable" | Coach | ✅ Keep — has a retry action |
| 12 | 491 | "No racks assigned" | Coach · room | ⚠️ **Keep, add the missing action** — see below |
| 13 | 510 | "Loading athlete context" | Coach | ✅ Keep |
| 14 | 510 | "Athlete context unavailable" | Coach | ✅ Keep |
| — | 495 | "Rack N is ready" | Coach · room | ❌ **Delete** — §4 |

#### The four "Choose an athlete" panels (#5, #6, #8, #9)

Not vestigial — the topbar `<select className="coach-athlete-select">` still does
its job. But they exist **four times because there are four sibling tabs**, each
having to guard independently since any of them can be the landing tab.

The state machine removes that reason. Once ANALYTICS owns athlete selection, the
guard belongs **once, at the state boundary**: no athlete chosen → the state shows
the picker, and the sub-views behind it never render unguarded. Four copies become
one, and it stops being possible to add a fifth athlete view that forgets the
guard.

This is the redesign paying for itself in deleted code rather than added code.

#### "No racks assigned" (#12) — ✅ **DONE 2026-07-30: cut it**

Decision: delete the panel, make the cog carry the weight instead. Room Layout
already holds *both* jobs a coach needs here — change device role
(`CoachTablet.jsx:426`) and assign rack numbers — so the panel was a signpost to a
door that should simply be easier to see.

Shipped:

- **Panel removed.** `!selectedRack` now renders nothing.
- **Cog labelled.** It reads **⚙ ROOM LAYOUT**, not a bare icon — new
  `.coach-labeled-button`.
- **It shouts when it matters.** With zero racks the button turns lime
  (`.coach-button-attention`), because that is the one case where it is the only
  way forward.

---

### 5. The athlete selector — ANALYTICS only · ✅ revised 2026-07-30

**Supersedes the earlier "stripped version in SESSION" decision.**

The selector is **local to ANALYTICS**. It does not appear in SESSION or PLANNING.

**Why SESSION does not need it:** picking a rack already picks the athlete.
`CoachRackButton`'s handler is:

```jsx
onSelect={()=>{ setSelectedRackNumber(r.rack_number);
                const athleteId=r.athlete?.id;
                if(athleteId) chooseAthlete(athleteId); }}
```

So during a session the room view *is* the athlete picker, and it picks the way a
coach actually thinks mid-floor — "who is at that rack", not "find a name in a
list". A second selector in the toolbar would be a redundant path to the same
state.

**Why PLANNING does not need it:** planning is group- and program-scoped.

**Consequence to decide:** under this model, an athlete who has **not checked in
at any rack** is unreachable during a session — so quick-notes only covers people
on the floor. Probably correct (that is who you have thoughts about), but it means
"note about someone who didn't show" has no home until ANALYTICS. Flagging rather
than solving.

### 6. Wall vs coach — the rule, for when it comes up again

They are **already separate components** (`WallView` / `CoachView`). Only the file
is shared, because both are driven by one `useLiveRoomState` hook.

**The rule lives in `services/room_state.py` — `include_details`:**

| | Wall (`false`) | Coach (`true`) |
|---|---|---|
| Names, numbers | ✅ | ✅ |
| **Database ids** | ❌ | ✅ |
| **Participant roster** | ❌ | ✅ |

So, to decide where anything belongs:

1. **Needs to be clickable?** → Coach. The wall has no ids, so nothing on it *can*
   link anywhere. This is structural, not a style choice.
2. **Shows people who have not lifted yet?** → Coach. The roster is withheld from
   the wall.
3. **Glanceable across a room, no login, no input?** → Wall.

This is why "wall should surpass and absorb coach features" mostly cannot happen:
the wall's payload deliberately withholds the ids those features need. The detail
level *is* the privilege boundary (§6.4).

**Where the file came from — checked, because memory said otherwise.**
`Dashboard.jsx` did **not** exist before the merge. On `SprintBranch` at
`4b6bfb9`, `/dashboard` was a placeholder:

```jsx
if (pathname === '/dashboard') return <StubRole role="dashboard" />   // App.jsx:168
```

— commented *"base-station display (stub until a later phase)"*. No pre-merge
branch of Devin's had the file at all. Both screens arrived together in P7 from
Braydon's branch, where it **already** carried `mode = "wall"`.

So one-file-two-screens is his structure, adopted wholesale — not something the
merge broke. What Devin remembered was SPEC **Phase 12** (*Team Dashboard Kiosk*,
owner: Devin), which was never built until the merge delivered it.

**File split: deferred**, and now on the merits rather than as a restoration.
The components are already fully separate; only the `useLiveRoomState` hook is
shared, which is a real reason to co-locate. Revisit after the state machine
lands.

### 7. Navigation rules — ✅ decided 2026-07-30

| | |
|---|---|
| **PLANNING** | Always reachable |
| **ANALYTICS** | Always reachable |
| **SESSION** | **Not selectable unless a day is set.** Dimmed in the navbar otherwise |

**Dim, do not hide.** A dimmed SESSION teaches the order — you can see the step
exists and that something is missing. A hidden one just looks like a two-state app.

**Do not build a hard guard.** If a coach somehow lands in SESSION with no day, it
renders dimmed and the existing API errors remain the safety net. We are not
adding UI-side enforcement the backend does not have — that is the second failure
mode in "The principle" below, and it is how the UI becomes a competing source of
truth.

**State survives a reload**, the way the device role already does.

### 8. Naming — ✅ decided 2026-07-30

**Quick Note.** Same `Athlete.notes` field as the ANALYTICS notes view; only the
affordance differs.

### 9. A brand-new gym — ✅ decided 2026-07-30

**Lands in PLANNING.** It is the only state a gym with no data can do anything in.

**No greeting.** ❌ Cancelled 2026-07-30. `Hello {name}` was assumed free; it is
not — there is no user endpoint, and the JWT carries `user_id`, not a username.
Every route to it is either a backend change or client-side bookkeeping at login.
Not worth it for a heading.

### 10. Wall display settings — ✅ decided 2026-07-30

The wall gets a **settings cog** mirroring the coach's, labelled **"Dashboard
Settings"**. For now it holds only **Change device role**, moved off the header
(`Dashboard.jsx:193`).

This answers the ❓ left in §3: the wall keeps the capability, but stops spending
permanent header space on it — the same trade as the coach screen. Room to add
more later without redesigning anything.

### 11. The glassmorphism navbar — ✅ decided 2026-07-30

Translucent / clear, over the near-black background.

| State | Colour |
|---|---|
| **Selected** | **Lime + black** — `--lime #a9f04d` on `#070b0e`-ish, the existing accent-on-dark pairing |
| **Unselected** | A grey or blue from the palette — `--muted #89969d` or `--line #263239` |
| **Dimmed** (SESSION with no day) | Same family, further back |

Colours come from `theme.js` / the `:root` vars in `App.css` — the palette is
already shared by all three screens, so the navbar should not introduce a new one.

> **Open:** the exact grey vs blue for unselected, and how far "dimmed" sits from
> plain "unselected". Those two need to be visually distinct — unselected means
> *you can go here*, dimmed means *you cannot yet* — and that difference is the
> whole navigational teaching.

### 12. `ProgramsTab` shows pounds and calls them the prescription — OPEN

Found 2026-07-30 while testing `AthleteWorkoutPlanning`. Both render the same
prescription, on the same screen, one above the other:

| Component | Shows |
|---|---|
| `AthleteWorkoutPlanning` | `5 sets · 3 reps · 72%` → **`155 lbs`** |
| `ProgramsTab` (directly above) | `5 × 3` → **`155 lbs`** |

`ProgramsTab` is headed **"Recorded prescriptions"** and never shows the percent.
But the percent **is** the prescription — the pounds are derived from it and move
whenever the athlete's reference max moves. So the panel presents a derived,
temporary number as though it were the plan.

This is the exact confusion `docs/_HANDOFF.md` §1 exists to prevent: a coach
watching that number fall after a bad testing block reads it as a bug, because
nothing on screen says it is a percentage of something that changed.

**Not free to fix.** `/api/prescriptions/` returns no `target_percent` — only
sets, reps, resolved `target_weight_lbs`, and the velocity zone. Options:

1. **Read it from a route already in use.** `AthleteWorkoutPlanning`, one component
   lower on the same tab, already fetches `/api/athletes/{id}/program/`, which
   *does* carry the percent. Lift that fetch up and share it. No API change.
2. Add `target_percent` to `/api/prescriptions/` — additive, but a backend change.
3. **Delete `ProgramsTab`'s card grid entirely.** `AthleteWorkoutPlanning` already
   shows the same information, more correctly, immediately below it. Worth asking
   whether the tab needs both.

Option 3 deserves real consideration — this is the "does the sibling still do the
same job?" test pointing at a duplicate rather than a stale field.

> Related and still unanswered: **where does the per-athlete `programs` tab live**
> in the three-state grouping? See open question 7.

### 13. The layout — settled 2026-07-30

**PERSISTENT** (outside the states)

* Edge Athlete logo → log out
* Glassmorphism navbar — 3 states; SESSION dimmed when no day is set
* Active-session widget — only while a day runs; elapsed timer; End training day
* Dev strip — dev mode only

**PLANNING**

* Training blocks — create / edit (`WorkoutCatalog`)
* **Deploy a block → program** for a group, with dates (already built:
  `buildDeployPayload` → `POST /api/training-programs/`)
* **Promote a program → block** (P15, already built)
* Groups
* Calendar / schedule (`ScheduleWorkspace`)
* Athlete plan assignment + **per-athlete overrides** — this is the existing
  *"INDIVIDUAL TARGETS · Exercise overrides"* block inside `AthleteWorkoutPlanning`,
  moved here from the Programs tab
* Stage a training day → navigates to SESSION

**SESSION**

* **The current ROOM tab, essentially as-is** — rack rail, rack observation, set
  detail, charts, hardware. ✅ Devin: *"I really like the entire ROOM tab that is
  currently there. This should be the shape of how session looks and we build
  around that."* SESSION is not a new screen; it is the room view plus the two
  items below.
* Start training day
* Quick Note
* Settings cog → Room Layout (`/coach/setup`)

**ANALYTICS**

* Athlete selector
* Athlete summary
* History
* Reports
* Notes (review)

**Deleted along the way:** the Programs card grid · "Rack N is ready" · "No racks
assigned" · the four duplicate "Choose an athlete" guards · Change device from the
coach topbar.

**Round trip already exists.** Block → program (deploy) and program → block
(promote) are both built and both live in `WorkoutCatalog`. PLANNING inherits them
whole — nothing new to write.

---

## The principle underneath all of it

**Only show what is possible right now.**

This is the part that needs the most thought, because it is the part that can go
wrong quietly. Two failure modes to avoid:

1. **Hiding without explaining.** If a coach cannot find "start a session" because
   no program is deployed, and nothing says so, the UI has replaced a clear error
   with a mystery. *Disabled with a reason* is often better than *absent*.
2. **Encoding rules the backend does not have.** If the UI enforces an order the
   API does not, the two disagree, and the UI becomes a second source of truth
   that drifts. Every gate here should reflect a rule that already exists server
   side.

### To work out: what actually gates what

Rough sketch, all of it TBD — these need checking against real endpoint
behaviour, not assumed:

- A **training day** cannot start without a deployed program for a group
- **Only one day open at a time** (this one is real — 409 from the API, D18)
- **Reports** exist only after a day has ended
- **Analytics** need at least one completed set
- A **block** cannot deploy without at least one day and one prescription row

> The errors Devin hit while demoing are the best available list of what the UI
> should have prevented. Worth reconstructing that list explicitly — each one is
> a gate we know matters, because it actually fired in front of an audience.

---

## Open questions

1. ~~Where do the athlete-scoped tabs live?~~ **Answered — see the state table.**
2. ~~Global vs framed?~~ **Framed** — navbar + (conditional) widget persist; the
   body swaps.
3. ~~Does SESSION require an open day?~~ **Answered** — see §7.
4. ~~Persist across reload?~~ **Yes.**
5. ~~Does the navbar dim?~~ **Yes** — SESSION only, and only when no day is set.
6. ~~What does a brand-new gym see?~~ **Answered** — see §9.
7. ~~Where does the per-athlete `programs` tab live?~~ **Resolved — it stops
   existing.** Its card grid is deleted; `AthleteWorkoutPlanning` (assignment +
   overrides) moves to PLANNING. See §13.
7b. *(superseded)* **Where does the per-athlete `programs` tab live?** The state table gives
   PLANNING "TrainingProgram create + instantiation" (group-scoped) and ANALYTICS
   "History · Athlete · Notes · Reports". The existing **`programs` tab is neither**
   — it is one athlete's *Recorded prescriptions*. It currently has no home.
8. ~~`ProgramsTab` null-key bug?~~ **Fixed** outside this doc — commit `1a9ef38`.
10. ~~Does `ProgramsTab` keep its card grid?~~ **No — deleted.** The rack screen
   already shows an athlete their live day, the coach authored the plan, and at
   100 athletes / 10 racks a per-person plan list answers the wrong question: a
   coach wants *who is behind*, not *what is Jordan doing*. Consequence: the
   "stripped-down athlete view" once floated for SESSION has no content left
   either, so **Quick Note is the only athlete-scoped thing SESSION needs.**
11. *(superseded)* Does `ProgramsTab` keep its card grid at all, given `AthleteWorkoutPlanning`
   sits below it showing the same prescription with the percent included? See §12.

---

## Notes / decisions log

Append as we go. Date each entry.

- **2026-07-30** — Doc created. Vision captured from Devin; nothing decided yet.
- **2026-07-30** — **States resolved.** Grouped by *when a coach needs the thing*
  (before / during / after), not by re-slicing the existing tabs. Notes
  deliberately appears in both SESSION (add) and ANALYTICS (review).
- **2026-07-30** — **Session quick-notes APPROVED** for the SESSION state. Name
  still to be chosen; "mid-floor" rejected.
- **2026-07-30** — **"Rack N is ready": DELETE.** Traced verbatim to
  `braydons-dev-branch` via P7, where it sat beside an assignment form and meant
  "ready to assign someone". D8 removed forward assignment; the component above it
  is now a read-only observation grid that already reports "No persisted result"
  and real hardware state. The panel restates one field worse, and can contradict
  the grid above it ("ready" vs "Node pulse overdue"). I first said keep-and-reword
  — wrong, because I had not checked what renders above it.
- **2026-07-30** — Noted that `Dashboard.jsx` renders BOTH the wall display and the
  coach tablet from one file, with two separate "ready" strings. Splitting it is
  likely its own cleanup item.
- **2026-07-30** — **Summary strip is dev-only now.** New `devMode.js` gate rather
  than deleting it; the five counters are still useful while building. Verified
  hidden by default in the container and restored by the localStorage toggle.
- **2026-07-30** — **Built:** log out moved under the brand mark (click the logo);
  "Change device" removed from the coach topbar; the four "Choose an athlete"
  guards collapsed into one at the athlete-tab boundary; "Rack N is ready"
  finally deleted. Verified in a browser on all four tabs.
- **2026-07-30** — **Fresh gym lands in PLANNING.** The `Hello {name}` greeting is
  **cancelled** — no user endpoint exists and the JWT carries only `user_id`, so it
  is not the free win it looked like.
- **2026-07-30** — **`AthleteWorkoutPlanning` PASSES the sibling test.** Its routes
  were properly rewired in the merge (his `/api/workouts/`,
  `/api/workout-programs/`, `/workout-assignment/` → the current planning routes),
  it renders exercise names correctly, and it shows percent AND resolved pounds
  together. It is the counter-example to `ProgramsTab`: the merge rewired this one
  and missed that one.
- **2026-07-30** — **LAYOUT SETTLED (§13).** SESSION is the existing ROOM tab plus
  Start day, Quick Note and the settings cog. PLANNING gets the block/program round
  trip it already has, plus the overrides block lifted out of the Programs tab.
  ANALYTICS keeps the athlete-scoped reviewing. Programs tab dissolved.
- **2026-07-30** — **New open item (§12):** `ProgramsTab` is headed "Recorded
  prescriptions" but shows only pounds, never the percent — presenting a derived
  number as the plan. Possibly a duplicate of the panel directly below it.
- **2026-07-30** — **Programs tab: two bugs fixed** (outside this doc, commit
  `1a9ef38`). Both had one root cause — it is Braydon's component, carried in by
  P7, still written against the per-athlete `Program` table that P6 dropped. Its
  `key={program.id}` and `{program.exercise}` were both correct on his branch and
  both silently wrong here. **This is the sibling test again**, and the strongest
  case for running it over the rest of the coach screen.
- **2026-07-30** — **Wall gets its own "Dashboard Settings" cog**, holding Change
  device role. Resolves the ❓ in §3.
- **2026-07-30** — **Navbar palette:** translucent; lime+black selected; grey/blue
  unselected; dimmed further back. Open: unselected vs dimmed must stay visually
  distinct, since that difference is what teaches the order.
- **2026-07-30** — **Day lifecycle split across states:** stage in PLANNING (then
  auto-navigate to SESSION), start in SESSION, end from the widget. Verified this
  needs no API change — P14's nullable `started_at` plus
  `POST /api/sessions/{id}/start/` already model exactly this.
- **2026-07-30** — **Widget is conditional, not permanent.** Supersedes the earlier
  always-visible note; it shows only while a day is running.
- **2026-07-30** — **Navigation:** PLANNING and ANALYTICS always reachable; SESSION
  dimmed and unselectable with no day set. No hard guard — if you land there
  anyway, the existing API errors stay the safety net. State survives reload.
- **2026-07-30** — ANALYTICS sub-tabs approved. Quick Note is the name.
- **2026-07-30** — **Athlete selector: ANALYTICS only.** Revises the earlier
  SESSION-stripped + ANALYTICS-full split. Rack selection already calls
  `chooseAthlete()`, so in SESSION the room view is the picker, and it matches how
  a coach thinks mid-floor. Open consequence: an athlete not checked in anywhere is
  unreachable during a session.
- **2026-07-30** — **Wall/coach rule written down:** `include_details` is the
  boundary — ids and roster are coach-only, so anything clickable is structurally
  coach-only. File split deferred; the components are already separate.
- **2026-07-30** — **BUG FOUND, not yet fixed:** `ProgramsTab` renders
  `key={program.id}`, and `/api/prescriptions/` returns `"id": None` for every row
  (the old `Program` table is gone; the replacement is derived). Every React key is
  null — switching athletes can leave stale cards.
- **2026-07-30** — **Ran the test on all 14 `StatePanel` uses.** One delete (§4),
  four to collapse into a single state-level guard, one missing its action link,
  eight fine. Confirmed origin is useless as a signal: all 14 exist verbatim on
  `braydons-dev-branch` at identical counts.
- **2026-07-30** — **Session timer needs no API.** `started_at` is already in the
  room-state payload; compute elapsed client-side. No backend change anywhere in
  this redesign.
