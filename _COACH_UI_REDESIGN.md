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

**The dev-only top bar** — "Last reconciled", "Active racks", etc. — is explicitly
marked dev only. ⚠️ I initially guessed this also covered the "Rack N is ready"
panel. Checking the code showed it does not — see §4.

### 2. The active-session widget lives outside the machine

Stays exactly where it is and how it looks — a persistent bar, not a state.

Longer term this becomes the slot for **other important notifications** too, so
design it as a general strip rather than a session-specific one.

**Add: a derived timer counting up** — how long the current session has been
running.

> ✅ **This needs no new API.** Devin flagged it as the one place a backend change
> might be required. It is not: `services/room_state.py:369` already returns
> `session.started_at` in the room-state payload, unconditionally. The timer is
> `now − started_at`, ticked locally — exactly the pattern the rack screen already
> uses for its own per-second timers. **The zero-backend-change constraint holds
> for the whole redesign.**

### 3. Less chrome on the main screen

| Control | Today | Proposed |
|---|---|---|
| Log out | Top-level button (`Dashboard.jsx:507`) | Under the **Edge Athlete logo** — click the logo to reveal |
| Change device | Top-level button (`Dashboard.jsx:508`) | **Settings → rack setup only** (already exists there, `Dashboard.jsx:193`) |

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

**Decision: delete the `StatePanel` at `Dashboard.jsx:495`.** Nothing is lost — the
observation panel above it answers the same question more accurately. No wording
fix needed, because the line should not exist.

> **The test that produced this answer**, worth reusing on the other nine
> `StatePanel` empty states: not *"did this come from Braydon's branch?"* — P7
> adopted his frontend deliberately, so most of the coach screen did. The question
> is **does the component it was written to sit beside still do the same job?**
> Here it does not.

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
2. Is the state machine **global** (whole screen switches) or does the active
   session widget imply a persistent frame around it?
3. Does entering SESSION require an open day — and if none is open, does the state
   show a "start one" affordance, or is the state itself unreachable?
4. Do the three states persist across reload? (Device role already does.)
5. Does the navbar show *where you can go* differently from *where you are* — e.g.
   Analytics dimmed until a session has ever completed?
6. What does a brand-new gym with zero data see? The empty state is the honest
   test of a state machine.

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
- **2026-07-30** — **Session timer needs no API.** `started_at` is already in the
  room-state payload; compute elapsed client-side. No backend change anywhere in
  this redesign.
