# Coach Admin — State Machine Redesign

> **STATUS: SPEC — ready to build.**
>
> Branch: `coach-admin-state-machine` (off `SprintBranch`) · Owner: Devin ·
> Written 2026-07-30. Folds into [`_SPEC.md`](_SPEC.md) when the work lands, then
> this file goes away.

## The roadmap, in one table

Eight phases. **A–F are a re-shelving** of things that already work; **G and H are
new features.** Full exit criteria for each are in §16 — this table is so nobody
has to reconstruct the shape from 900 lines.

| | Phase | In one line | Status |
|---|---|---|---|
| **A** | The shell | Three routes, the glass navbar, the sliding pill. Each state shows the old tabs unchanged | ✅ `f064d10` |
| **B** | SESSION | The live room + starting a day. Split `TrainingDayPanel`: open-from-scratch → PLANNING, start-staged → SESSION | ✅ `e89a0e1` |
| **E** | The widget | The strip above all three states: elapsed timer, End training day | ✅ absorbed into **B** — ending a day needed a home before B could ship |
| **C** | ANALYTICS | Athlete selector moves here from the topbar; one "choose an athlete" guard instead of four | ✅ `767f33e` |
| **D** | PLANNING | The four sub-tabs — Design · Groups · Workout catalog · Calendar. Deploy/promote become buttons on the thing itself. Calendar gains the mockup's card view | ✅ D1–D4 |
| **F** | Removals | Delete the old 8-tab bar and the Programs card grid. **Only after A–E work** | ✅ code done; tablet walk-through outstanding |
| **G** | Dashboard Settings | A cog on the *wall* display holding Change device role. Genuinely new; may be its own branch | ✅ `d9a1cef` |
| **H** | Group history | *"Who is falling behind?"* — a scope switch on History. The highest-value analytics feature, and **the only thing here that is not free** | ✅ client-side; `?group=` deliberately unspent |

**How to read the order.** A built the frame. B–D fill the three states, in any
order — they do not depend on each other. F is the cleanup that can only happen
once nothing needs the old tabs. G and H are separable products; H in particular
is worth doing on its own merits, not as part of this transition.

**The rule that holds all of it together:** no backend routes change, anywhere in
A–G. H is the one place that rule is allowed to be reconsidered, deliberately.

---

## How to read this

| If you want | Read |
|---|---|
| **The shape of the whole plan** | **the roadmap table above** |
| **What to build** | **§13** the layout · **§14** mechanics · **§15** PLANNING's sub-tabs · **§16** the phases |
| A picture of it | [`_COACH_UI_MOCKUP.html`](_COACH_UI_MOCKUP.html) — open in a browser |
| *Why* something is the way it is | §1–§12, in the order the questions came up |

§1–§12 are a record of reasoning, kept because several decisions reverse an
obvious-looking answer and the reversal is the useful part. **Where §1–§12 and
§13–§16 disagree, §13–§16 win** — they were written last.

⚠️ **Line numbers are as of 2026-07-30 and have already shifted**, because some of
this shipped. Treat them as landmarks, not addresses.

### Already built on this branch

Not part of the phases below — done while the spec was being written.

| | Commit |
|---|---|
| "Rack N is ready" deleted | `27b599c` |
| "No racks assigned" deleted; cog labelled **⚙ ROOM LAYOUT** | `83ae406` |
| Log out moved under the logo; Change device removed from the topbar | `27b599c` |
| Four "Choose an athlete" guards collapsed to one | `27b599c` |
| Summary strip hidden behind `isDevMode()` | `e324110` |
| `ProgramsTab` null-key + exercise-id-as-name bugs fixed | `bd9ee08` |

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

| State | The question |
|---|---|
| **PLANNING** | What is coming up? |
| **SESSION** | What is happening right now? |
| **ANALYTICS** | What happened? |

> **The contents of each state are in §13**, which supersedes the first-pass list
> that used to sit here.

Devin's framing: *"basically this is a glorified grouping of tabs."* Not a
rebuild — a re-shelving. Worth holding onto, because it keeps the work small.

**Notes appears in two states on purpose.** ✅ **APPROVED 2026-07-30.** In SESSION
it is optimised for *adding* — a quick thought about any athlete, fast, without
leaving the floor view. In ANALYTICS it is for *reviewing*. Same data, two
affordances.

> ❌ **The "stripped-down athlete view" once floated for SESSION is cancelled.**
> The rack screen already shows an athlete their live day, and the coach wrote the
> plan. That leaves **Quick Note as the only athlete-scoped thing SESSION needs.**
> See open question 10.

> ✅ **Named "Quick Note"** (§8). Same `Athlete.notes` field as the ANALYTICS notes
> view — the name says *fast*, not *a different kind of note*, because a
> too-distinct name would imply a second store that does not exist.

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
questions, and every coach in a real gym would otherwise see it.

⚠️ An earlier draft guessed this also covered the "Rack N is ready" panel. Checking
the code showed it does not — see §4.

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
| **Stage** a day | **PLANNING → Calendar**, on the slot | Create it; it does not run yet. Then **navigate the coach to SESSION**. See §15 — staging is a slot action, not a control on the program card |
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
> | `Dashboard.jsx:193` — **wall display** header | ✅ Resolved — moves into a "Dashboard Settings" cog, **Phase G** (§10) |
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
| 5 | 330 | "Choose an athlete" | Coach · athlete | ✅ **Collapsed** — `27b599c` |
| 6 | 386 | "Choose an athlete" | Coach · history | ✅ **Collapsed** — `27b599c` |
| 7 | 391 | "No completed training days" | Coach · history | ✅ Keep — real empty state, distinct from #6 |
| 8 | 403 | "Choose an athlete" | Coach · programs | ✅ **Collapsed** — `27b599c` |
| 9 | 411 | "Choose an athlete" | Coach · notes | ✅ **Collapsed** — `27b599c` |
| 10 | 488 | "Loading coach workspace" | Coach | ✅ Keep — whole-screen, sibling-independent |
| 11 | 489 | "Coach view unavailable" | Coach | ✅ Keep — has a retry action |
| 12 | 491 | "No racks assigned" | Coach · room | ✅ **Deleted** — `83ae406`; the cog carries it instead |
| 13 | 510 | "Loading athlete context" | Coach | ✅ Keep |
| 14 | 510 | "Athlete context unavailable" | Coach | ✅ Keep |
| — | 495 | "Rack N is ready" | Coach · room | ✅ **Deleted** — `27b599c` |

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

**✅ Consequence accepted.** An athlete who has **not checked in at any rack** is
unreachable during a session, so Quick Note only covers people on the floor. That
is who a coach has thoughts about. A note on someone who did not show waits for
ANALYTICS, where the full selector lives.

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

### 12. `ProgramsTab` shows pounds and calls them the prescription — ✅ RESOLVED by deletion

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

**✅ Option 3 chosen.** The card grid is deleted (see open question 10), so the
problem goes with it — `AthleteWorkoutPlanning` already shows percent *and*
resolved pounds together, which is the correct model. No fetch to lift, no field
to add.

This is the "does the sibling still do the same job?" test pointing at a duplicate
rather than a stale field — and the duplicate losing.

> Related and still unanswered: **where does the per-athlete `programs` tab live**
> in the three-state grouping? See open question 7.

### 13. The layout — settled 2026-07-30

> 🖼 **Picture of it:** [`_COACH_UI_MOCKUP.html`](_COACH_UI_MOCKUP.html) — open it
> in a browser. Nothing is wired; every number is fake. It exists to agree on
> shape, the same job `edge_athlete_rack_ui.html` did for the rack screen. The
> amber bar at the top is a mockup-only control that toggles "day running" so you
> can see the widget appear and SESSION un-dim.
>
> ⚠️ **THE MOCKUP IS THE TARGET, NOT A SUGGESTION.** ✅ Devin 2026-07-31: *"I want
> to try to model the mockup as much as possible during this transition."* Where
> a phase could go either way, match the mockup. Where the running app already
> disagrees with it, the mockup wins unless there is a stated reason in this doc
> — and the reason gets written down here rather than left in the code.


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
* Stage a training day → navigates to SESSION.
  ⚠️ **Staged FROM THE CALENDAR SLOT**, not from the program card. The calendar is
  where a coach asks "what is Monday?", and the slot already carries the four
  states `schedule.js` defines — `planned` / `ready` / `running` / `done`. "Ready"
  IS the staged-but-not-started state P14 was built for, so staging is a slot
  action, not a separate control.

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

### 14. Mechanics — decided 2026-07-30

**Routes, not internal state.** `/coach/planning`, `/coach/session`,
`/coach/analytics`. `router.js` is a ~40-line custom router and nginx already
serves `index.html` for any path, so this costs almost nothing and gives reload
persistence and the back button for free.

* `/coach` alone → redirect to the last state, or PLANNING on a fresh device.
* ⚠️ **It must not feel like page navigation.** The navbar animates the selection
  between states so it reads as one surface. Only the body swaps; navbar, logo and
  widget never unmount.

**Navbar sits bottom-centre.** Reachable with a thumb on a held tablet.

**Dashboard Settings does not exist yet** — it is new work, not a move. Scope it
as its own small phase, or a separate branch.

### 15. PLANNING's sub-tabs — decided 2026-07-30

Four sub-tabs. One builds, three view.

| Sub-tab | Holds |
|---|---|
| **Design** | The creation flow, in the order a coach thinks |
| **Groups** | View groups — **and `Open` drills into one**, see below |
| **Workout catalog** | View blocks / programs |
| **Calendar** | The schedule — and **where days get staged**. Slots carry the four states from `schedule.js`; staging is an action on a `planned` slot |

**Inside "Design", vertical order follows the coach's own process:**

```
1. Block            ← the reusable template
2. Program          ← the block placed in time for a group
3. Session design   ← a one-off, no template behind it
```

**Two rules for this screen:**

1. **Create is a dropdown, not a form page.** "Create block" and "create session"
   are two dropdowns — compact controls, not full-page builders.
2. **Promote and instantiate are BUTTONS INSIDE the block/program components** —
   not separate panels. Today `WorkoutCatalog` has a standalone deploy panel with
   its own block/group/name/date fields; that becomes an action on the thing
   itself. You promote *this* program; you deploy *this* block.

That second rule is the real change in PLANNING. Everything else is re-shelving.

### 15b. What `Open` on a group opens — ✅ decided 2026-07-31

**The mockup has an `Open` button on every group card and this doc never said
what it opened.** Devin asked. It is the missing home for the one PLANNING item
§13 lists without giving it a sub-tab:

> *Athlete plan assignment + per-athlete overrides — the existing "INDIVIDUAL
> TARGETS · Exercise overrides" block inside `AthleteWorkoutPlanning`.*

```
Groups  →  Open a group  →  its athletes  →  one athlete's plans + overrides
```

**Why Groups and not somewhere else.** Assigning an athlete to a plan *is* putting
them in the group that runs it — `AthleteWorkoutPlanning`'s own header says so,
and the server answers with which groups changed. So the screen where a coach
changes group membership and the screen where they see groups are the same screen.
Anywhere else and a coach edits group membership from a place that never mentions
groups.

**It also answers "who is in this group?"**, which the card alone cannot — it says
*28 athletes* and stops. That number is the only thing a coach cannot act on.

⚠️ **This is where `AthleteWorkoutPlanning` MOVES TO**, out of `ProgramsTab` in
ANALYTICS (open question 7). It passes the sibling test and needs no edits — only
a new parent. The per-athlete override editor is the one genuinely load-bearing
thing inside `ProgramsTab`, and Phase F cannot delete that tab until this lands.

**Not in scope, and worth saying so:** creating a group, renaming one, moving an
athlete between groups, assigning coaches. None of those exist as UI anywhere
today — groups are made by importing a roster — and building them here would be
new product rather than the re-shelving this phase is.

### 16. Build order — incremental, with exit criteria

**Incremental, not big-bang.** `SprintBranch` stays demoable at every step; the
old tab bar keeps working until the last phase removes it.

Each phase below ends with a check that can be **verified by clicking**, not by a
green test suite — this project has nine bugs on record that tests did not catch.

---

**Phase A — the shell**
Routes + bottom navbar + animated selection. Each state renders the existing tab
content unchanged inside it.

- [ ] `/coach/planning`, `/coach/session`, `/coach/analytics` all load
- [ ] `/coach` redirects; a reload keeps the state
- [ ] Back button moves between states
- [ ] Navbar animates; logo/widget do not unmount on a state change
- [ ] SESSION dims when no day is set, and is not selectable
- [ ] Frozen-file check clean

**Phase B — SESSION**
The current ROOM tab becomes SESSION's body, plus Start training day, Quick Note,
settings cog.

- [ ] Room view identical to today's ROOM tab
- [ ] Start training day works; staged day → running
- [ ] Quick Note saves against the athlete at the selected rack
- [ ] Cog opens Room Layout
- [ ] **The generated report no longer renders outside the states** — see below

⚠️ **The end-of-day report escapes the machine.** Ending a day makes
`TrainingDayPanel` render `GeneratedReport` inline, and `TrainingDayPanel` sits
above the tab bar — so the report draws outside PLANNING, SESSION and ANALYTICS
alike, floating over all three. It behaves like the active-day banner because it
is rendered in the same place as the active-day banner.

This is **pre-existing**, not something the states introduced: the panel has
always been above the tab bar, where a single page made it look like "a thing
appeared at the top". Three states make it read as what it is.

**Nothing is lost when it goes.** `ReportsWorkspace` imports the same
`GeneratedReport` component and reads the same frozen snapshot from
`/api/reports/`, so the report is already in ANALYTICS → Reports before this is
touched.

**Decided fix:** ending a day navigates to ANALYTICS → Reports with that report
open, and SESSION renders nothing after. The day is over, so SESSION has nothing
left to show, and finished days already live in Reports. The deep-link into a
specific report is Phase C's half of this.

**Phase C — ANALYTICS**
Athlete selector + sub-tabs (summary, history, reports, notes).

- [ ] Selector lives here only — gone from the global topbar
- [ ] One "choose an athlete" guard at the state boundary, not per sub-tab
- [ ] Every sub-tab renders for an athlete with data, and for one with none

**Phase D — PLANNING**
Four sub-tabs per §15; promote/deploy become in-component buttons.

Built in four checkpoints, because it reshapes an 836-line file:

| | | |
|---|---|---|
| **D1** | The four sub-tabs, Groups view, Calendar renamed | ✅ `5189e73` |
| **D2** | The calendar's card view | ✅ `b01b0d5` |
| **D3** | Design tab surgery — dropdowns, in-component deploy/promote | ✅ `b9b5192` |
| **D4** | `Open` a group → its athletes → `AthleteWorkoutPlanning` (§15b) | ✅ |

⚠️ **`AthleteWorkoutPlanning` now renders in TWO places** — here, and still inside
`ProgramsTab` in ANALYTICS. That is the transition working as §16 intends ("the
old tab bar keeps working until the last phase removes it"), not a mistake — but
it is a real duplicate-editor state, and **Phase F closing it is now unblocked.**

**Correction, recorded because it changed what got built:** an earlier pass of D3
claimed a one-off session could not be built because no route adds days to a
program. That was wrong — Devin pushed back and was right. `_import_target`
(`views.py:1925`) accepts `training_program` and returns `kind="program"`, and
`services/csv_import.py` has carried a `"program"` branch in `_PLAN_TARGETS` all
along. Nothing on the coach screen had ever asked for it. Step 3 is built.

- [ ] Design tab ordered Block → Program → Session design
- [ ] Create block / create session are dropdowns
- [ ] Deploy is a button on a block; promote is a button on a program
- [ ] The standalone deploy panel is gone
- [x] Stage a day → lands in SESSION — **done in Phase B** (`e89a0e1`)
- [ ] Groups / catalog / calendar reachable as view tabs
- [ ] **Calendar is the current Schedule tab RENAMED**, not rebuilt — ✅ Devin
      2026-07-31. `ScheduleWorkspace` keeps its slot states, its move action and
      its past-day toggle; only the label changes
- [ ] **A second calendar view: month cards, per the mockup** — ✅ Devin
      2026-07-31, see below
- [ ] **`Open` on a group card** → its athletes → `AthleteWorkoutPlanning`, per
      §15b. ⚠️ **Phase F cannot delete `ProgramsTab` until this lands** — the
      override editor inside it has nowhere else to go

**The calendar's two views.** The list that exists today answers *"what is
coming up, in order?"*. The mockup's card grid answers a different question —
*"what does this month look like?"* — and a coach asks both. So it is a **view
toggle on one tab**, not a replacement:

| View | Shape | Good for |
|---|---|---|
| **List** (today's) | Vertical, grouped by date, action on the right | Working through the next few days |
| **Cards** (new) | 4-across grid, one card per slot, action on the card | Seeing a month's shape at a glance |

Both read the same slots and the same four `schedule.js` states — `planned` /
`ready` / `running` / `done`. The card grid is a second presentation of one
source, never a second source.

⚠️ **Staging happens on the SLOT, in either view.** That is the whole reason the
calendar is where a coach asks "what is Monday?" — see §15. The card carries its
own action: *Stage this day* on a `planned` card, *Open in session* on a `ready`
one.

**Phase E — the widget** — ✅ **DONE, absorbed into Phase B** (`e89a0e1`)

It could not wait for its own phase: Phase B moved "End training day" out of
`TrainingDayPanel`, and the button needed somewhere to live the moment it left.
Built as `coach/SessionWidget.jsx`.

- [x] Hidden with no running day; appears when one starts
- [x] Timer counts up from `started_at`, client-side, no new API
- [x] End training day works from any state — the strip is outside all three,
      verified as the same DOM node across a state change

Deliberately built as **a strip that currently shows a session**, not as a session
bar, because §2 wants other notifications here later — a node that stopped
reporting, a tablet that dropped off. Adding those should not mean rewriting it.

**Phase F — removals**
Only after A–E are working.

- [ ] Old 8-tab nav deleted
- [ ] Programs card grid deleted
- [ ] Change device gone from the coach topbar
- [ ] No dead CSS left behind
- [ ] Full click-through of all three states on a real tablet

**Phase G — Dashboard Settings** *(new work, may be its own branch)*
A settings cog on the wall display, holding Change device role.

- [ ] Cog on the wall header; `Dashboard.jsx:193` button removed
- [ ] Wall still needs no login

**Phase H — group history** *(new feature, not a re-shelving — after A–F)*

A scope switch on ANALYTICS → History: **Athlete ▾ / Group ▾**. Same question,
wider lens.

**Why it belongs in History, not Reports.** A session can host several groups
(`SessionParticipation` exists for exactly that), so a report is *day*-scoped, not
group-scoped. Filtering reports by group would return days the group trained while
each report still contained everyone else who trained that day — misleading, not
useful. Reports stay per-day and frozen; History is the per-*subject* trend, and
group is just a wider subject.

**Why it matters more than it looks.** It is the direct answer to the scaling
problem: at 100 athletes a coach is not asking *"what is Jordan doing"* — they are
asking *"who is falling behind"*. No per-athlete view can answer that. This is
arguably the highest-value analytics feature in the product.

**⚠️ This is the one thing in this document that is not free.**

| Approach | Cost |
|---|---|
| Client-side today | `GET /training-groups/{id}/athletes/` then **N ×** `GET /analytics/athlete/{id}/`. 28 requests for Varsity. No backend change, but it will feel bad at exactly the gym size that makes the feature worth having |
| `?group={id}` on analytics | One request. **Breaks the no-backend-change rule** — which is why this is a separate phase, where that rule can be reconsidered on purpose rather than by accident |

There is no batch route today: `/analytics/athlete/{id}/` takes one athlete, and
`/api/reports/` filters only by `?athlete=`. The report *list* item carries no
athlete list at all — only metadata and a summary — so reports cannot be grouped
client-side without fetching every detail.

**Recommendation:** build the client-side version first to prove the view is worth
having, then add `?group=` if it is. Do not add the endpoint speculatively.

### ✅ The `?group=` decision — settled 2026-07-31

**Do not add it yet.** The client-side version is built and works, and the cost
turned out lower than the doc feared.

Measured against the running stack, one training group:

| | |
|---|---|
| One `/api/analytics/athlete/{id}/` call | **16 ms** |
| Four in parallel | **19 ms** |
| Projected 28 athletes (7 batches of 4) | **~133 ms** |
| Projected 100 athletes | **~475 ms** |

⚠️ **Those numbers are from Docker on a laptop, not from a Raspberry Pi.** A Pi
serving live rack tablets will be several times slower, so read them as a shape
— the cost grows in batches, not per athlete — rather than as a promise. Even at
5× a squad of 28 lands under a second.

**So the rule is:** the extra requests buy a real feature for no backend change,
and `?group=` stays unspent. **Revisit it if** a group over ~40 feels slow on the
actual base station, or if this view ever needs to poll rather than load once.

**What made it affordable:** requests go out four at a time, not all at once.
The base station is also serving rack tablets mid-set, and a burst of twenty-
eight parallel analytics queries is a real way to make someone's live velocity
feed stutter.

- [x] Scope switch on History: Athlete / Group
- [x] Group view lists members with last-trained, set count, average velocity, trend
- [x] A member who has not trained in the window is visibly distinct — that is the
      whole point of the view. ⚠️ Implemented as **no training in 7 days**, not
      "outside the window": read literally the latter flags nobody on a short
      window and everybody on a long one, so the flag would describe the
      dropdown rather than the athlete
- [x] Decide, explicitly and in writing, whether `?group=` gets added — **no, see above**
- [x] Reports tab unchanged — still per-day, still frozen

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

Everything load-bearing is answered. What remains is listed so it is not mistaken
for settled.

**Answered**

1. Where do the athlete-scoped tabs live? → §13
2. Global vs framed? → **Framed.** Navbar and (conditional) widget persist; only the body swaps
3. Does SESSION require an open day? → §7
4. Persist across reload? → **Yes**, via routes (§14)
5. Does the navbar dim? → **Yes**, SESSION only, when no day is set
6. What does a brand-new gym see? → §9 — lands in PLANNING, no greeting
7. Where does the per-athlete `programs` tab live? → **It stops existing.** Card grid deleted; `AthleteWorkoutPlanning` moves to PLANNING — **specifically to Groups → Open, see §15b** (settled 2026-07-31; "PLANNING" alone was not an address)
8. `ProgramsTab` null-key bug? → **Fixed**, `bd9ee08`
9. Does `ProgramsTab` keep its card grid? → **No.** The rack screen already shows an athlete their live day, the coach wrote the plan, and at 100 athletes a per-person plan list answers the wrong question — a coach wants *who is behind*
10. Does SESSION need a stripped athlete view? → **No**, for the same reason. Quick Note only

**Still open — decide during the phase that hits them**

- **Exact greys.** Unselected vs dimmed in the navbar must read as clearly
  different: unselected means *you can go here*, dimmed means *not yet*. That
  contrast is what teaches the order. **Phase A.**
- **`/coach` with no prior state.** Confirmed to land in PLANNING; not yet decided
  whether a returning device resumes its last state or always lands in PLANNING
  when a day is running. **Phase A.**
- **Animation shape.** The navbar glider slides (see the mockup). Whether the body
  also crossfades is undecided — it changes whether panes need transition
  wrappers. **Phase A.**
- **`?group=` on analytics.** The one place the no-backend-change rule may be
  broken, deliberately. **Phase H**, and only after the client-side version proves
  the view is worth having.
- **`Dashboard.jsx` file split.** Deferred on the merits — the components are
  already separate and share one hook. Revisit after the state machine lands.

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
  `bd9ee08`). Both had one root cause — it is Braydon's component, carried in by
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
- **2026-07-31** — **Phase A built.** The three open Phase-A questions are now
  answered, by building them:
  - **Exact greys.** Unselected `#89969d` (theme `muted`), dimmed `#3c4a52`.
    Unselected also lifts to near-white on hover, so *pressable* is signalled two
    ways and *not yet* is signalled by neither.
  - **`/coach` resume.** A returning device **resumes its last state**, remembered
    per device in `localStorage.coach_state`. No special case for "a day is
    running" — if the remembered state is SESSION and no day is open, the
    ordinary SESSION guard handles it, so there is one rule rather than two.
  - **Animation shape.** **The glider slides; the body does not crossfade.** A
    crossfade would fade the live room's charts on every state change, and on a
    Pi-served tablet that reads as lag rather than polish. Revisit only if the
    swap looks abrupt on real hardware.
  - Also decided: the state a coach is **standing on is never dimmed**. A day can
    end while SESSION is open, and dimming the button under them would put the
    lime "you are here" pill and the grey "you cannot go here" on one button.
    Found by the render test, not by clicking.
  - Also decided: SESSION with no day **does not redirect**. Pulling a coach off
    the screen they were reading — which is what a redirect does the moment a day
    ends — is worse than a screen that says why it is empty.
- **2026-07-31** — **Phase B built** (`e89a0e1`). `TrainingDayPanel` split in two:
  `OpenDayFromScratch` → PLANNING, `StartStagedDay` → SESSION, and the ending
  half became `coach/SessionWidget.jsx` outside all three states. Two decisions
  forced by building it, both confirmed by Devin:
  - **SESSION is gated on a day being SET, not running.** §7's word was already
    "set"; staged counts, because starting a staged day is what SESSION is for.
  - **The from-scratch form lives in PLANNING, not SESSION.** `POST /api/sessions/`
    opens the room immediately — there is no staged step it could reach SESSION
    with — so putting it in a state that dims until a day is set would lock out
    every gym with an empty calendar.
  - The **settings cog stays in the persistent topbar**, against §13's placement,
    for the same lockout reason: Room Layout is the only screen that can assign
    racks, and a gym with no racks has no day and so no SESSION.
  - ⚠️ **§2b's code block is wrong about one route.** It says `POST /api/sessions/`
    creates a staged day with `started_at` null; `views.py:349` saves with
    `started_at=timezone.now()`. Staging is `POST /api/scheduled-sessions/{slot}/session/`.
    The intent was right and both routes exist — only the naming was off.
- **2026-07-31** — **Calendar keeps its list AND gains the mockup's card grid**,
  as a view toggle on one tab. Devin: the card view is the month-at-a-glance
  answer, the list is the next-few-days answer, and a coach asks both. Recorded
  in Phase D. Same slots, same four states, two presentations.
- **2026-07-31** — **Devin found the report escaping the states.** Ending a day
  draws `GeneratedReport` above the tab bar, so it floats over all three states
  like the active-day banner does. Pre-existing; the states only made it legible.
  Logged as a Phase B exit criterion with the fix decided there.
