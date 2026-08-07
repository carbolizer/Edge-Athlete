# The data model

The part of the system where a wrong assumption does lasting damage, because it
changes numbers a coach then trains people against.

## The one idea to take away

**A plan stores a percentage. It never stores a weight.**

A coach prescribes "Back Squat 5×3 at 80%" once, for a whole group. There is no
target-weight column anywhere in the database. The actual number on the bar is worked
out *when the screen asks for it*, against that athlete's own current max.

Everything below follows from that.

---

## The three weights

Confusing any two of these is the most expensive mistake available on this project.
It derailed an earlier attempt at the system, which is why it is written down this
plainly.

| | Weight | Where it lives | What moves it |
|---|---|---|---|
| **a** | **Reference max** — what the athlete can lift *now* | Stored. Add-only, newest wins. | A coach entering a new one, or the automatic recalculation when a session ends |
| **b** | **Prescribed target** — what the plan says to lift today | **Nowhere. Always derived** as a percentage of (a) | Move (a), or set a per-athlete override |
| **c** | **Actual load** — what is on the bar right now | Stored on the set itself | The athlete's on-screen number pad, or a coach adjusting today's load |

**The rule:** to change the *prescription*, move **(a)**. To change only what someone
is lifting *right now*, move **(c)**. **(b) is derived and never written.**

When a coach says "change their weight," they mean one of two different things, and
the system offers a separate lever for each. They do not compete: (a) rewrites future
targets, (c) nudges today without touching the plan.

---

## Decision: a reference max is allowed to go down

**What forced it.** A reference max could have been treated as a personal record —
the best an athlete has ever done.

**What we chose.** It is **what they can do now**, not a lifetime best. It is
add-only and newest-wins, and the newest value can be lower than the last one.
Prescribed weights follow it down.

**What we rejected, and why.** Making it a high-water mark. That produces exactly the
wrong behaviour for the thing this product exists to detect: an athlete coming back
from illness, or deep in a hard block, would be prescribed weights based on their best
day ever. The system is meant to notice fatigue and respond to it.

**What it cost.** It looks like a bug the first time you see it, and the tempting
"fix" (clamp it so it can only rise) breaks the core purpose. This is why it is
flagged in {doc}`../orientation` before anyone reads code.

---

## Decision: the hierarchy names are inverted from gym convention, on purpose

**What forced it.** Coaches, textbooks, and the codebase all needed to use the same
four words for four different things.

**What we chose.**

| Name | What it means here |
|---|---|
| **TrainingGroup** | A named **subset of athletes** who train together on one program. *Not* the list of all athletes. |
| **TrainingBlock** | The reusable **template** a coach designs once and redeploys. |
| **TrainingProgram** | A scheduled **instance** of a block, placed in time for a group. |
| **TrainingSession** | One shared **timeslot**, owned by nobody. Many groups can be on it. |

**The inversion to watch:** in common strength-and-conditioning usage, a "block" is a
dated phase of training. **Here the block is the template** and the *program* is the
dated thing. This is deliberate, and it is the single most likely source of a
misreading.

**What it cost.** Anyone arriving with strength-coaching background reads these names
wrong at first. The table above is the fix, and it is repeated wherever the names
appear.

---

## Three structural calls that look like mistakes

Each of these has been "corrected" by somebody before. They are all intentional.

**Athletes belong to groups many-to-many, not one-to-one.**
An athlete can be in football *and* the speed squad at once, each with its own
program; the session decides which applies. Membership is **current state only** —
adding or removing someone from a group never rewrites past sessions or completed
sets. History stays attached to what actually happened at the time.

**A training session is owned by nobody.**
It is a root record. The link to a group lives on a separate participation record,
which is what allows several groups to share one timeslot.

**The "bigger idea → smaller idea" arrow is not the foreign-key direction.**
Block → Program → Group → Session describes conceptual weight. The actual foreign
keys point differently, and deliberately so. Reading one as the other produces a
confidently wrong mental model.

---

## How a target weight is actually worked out

The full algorithm lives in the spec, but the shape matters here because two steps
are easy to get wrong:

1. Find the athlete's **newest** reference max for that movement.
2. **Normalise it to a one-rep basis.** A max recorded as "225 for 3" is not a
   one-rep max; it is converted with a standard formula first.
3. Apply the prescribed percentage.
4. Apply a per-athlete override if one exists.
5. **Round to the nearest 5 lb**, because that is how plates load.
6. **If the athlete has no reference max, return nothing.**

**Step 6 is a decision, not an oversight.** No max means no target — do not guess, do
not substitute zero, do not error the request. An empty target is a legal value that
the rack screen already handles, and the athlete can enter a load by hand. Failing
soft here keeps one missing number from breaking a whole rack's session.

**Step 2 is the one people skip**, and skipping it silently inflates every prescribed
weight for any athlete whose max was recorded at more than one rep.

---

## Where the training numbers live

Every value a coach or sports scientist might argue with sits in **one file** —
`services/tuning.py` — beside the functions that use them: how generous the one-rep-max
estimate is, which rep counts are trusted, how the bar is rounded, how long "resting"
lasts.

Two deliberate exclusions are documented in that file:

- **Operational limits stay next to the code they protect** (upload size caps, page
  limits). They protect one piece of code rather than expressing a view about
  training, and keeping the tuning file short is what keeps it findable.
- **The rep colour threshold cannot move.** The tablet computes each rep's colour and
  sends it; the server only stores what it was told. There is no second copy to
  change. Moving it means editing the frozen rack contract *and* accepting that every
  colour already stored was computed under the old rule.
