# Handoff notes — Devin → Braydon

Written 2026-07-30, at the end of Sprint 3, on branch `merge-braydon`.

This is the short list of things that are **not obvious from the code** and that
cost real time to work out. Everything else is in [`../_SPEC.md`](../_SPEC.md) and
[`_PATCH_NOTES.md`](_PATCH_NOTES.md).

---

## 1. Read this before you "fix" a weight

**An athlete's prescribed weight going DOWN is not a bug. It is the design.**

A plan stores a **percent**, never pounds. The pounds are worked out per athlete
at read time:

```
their newest AthleteReferenceMax row  →  normalised to a 1-rep basis  →  × target_percent  →  rounded to a loadable bar
```

`AthleteReferenceMax` is a **reference** max — what the athlete can do *right
now*. It is deliberately **not** a lifetime best:

- It is **add-only**. A new benchmark writes a new row; the old row is never
  edited. "Current" simply means their newest row.
- **A newer, lower number legitimately supersedes an older, higher one.** Someone
  back from injury or a bad testing block gets a lower reference, and every weight
  prescribed for them drops with it. That is the feature — the plan follows the
  athlete instead of the athlete chasing a number they hit last year.

> **This will get reported as a bug.** A coach will see Jordan squatting 225 in
> March and 205 in April and file it. The correct answer is "his reference max
> came down, so his percentages came down." The wrong answer — and the one that
> looks obvious — is to clamp the max so it can only rise. That silently converts
> the whole system into lifetime-PR programming and quietly overloads anyone
> coming back from time off.

Lifetime bests **do** exist and are a separate idea: derived from `Set` history
and surfaced as the `is_velocity_pr` / `is_weight_pr` flags on set-complete. Never
conflate the two.

### The tablet does not read the max

It reads `targets[exercise_id]` — the already-resolved number of pounds. The
`maxes` map rides along in the payload for coach-side callers, but
`react/src/rack/` **never touches it** (grep it — zero hits).

This is deliberate and it is why the rack screen survived the merge untouched: the
tablet reads a resolved weight, so the server was free to switch from "one typed
weight per athlete" to "percent × reference max" without the tablet noticing. It
is written up as **§6.3** in SPEC.

**So: a wrong weight on a rack screen is almost never a rack-screen bug.** Fix it
in `services/plan_resolution.py`.

---

## 2. Where the formulas live

**One file: [`django/event_handler/services/tuning.py`](../django/event_handler/services/tuning.py).**

Every number a coach or sports scientist might argue with is there, with a comment
saying what turning it does. The *functions* that use those numbers are in
[`lifting_math.py`](../django/event_handler/services/lifting_math.py) next to it.

| You want to change | Where | Notes |
|---|---|---|
| How a 1RM is estimated from a rep-out | `lifting_math.one_rep_max()` | The formula's *shape*. One line. Currently Epley |
| How generous that estimate is | `tuning.EPLEY_DIVISOR` | The number Epley divides by |
| Which rep counts are trusted for an estimate | `tuning.MIN/MAX_REPS_FOR_ESTIMATE` | Outside the window callers get `None`, never a guess |
| Bar rounding (5 lb → 2.5 lb plates) | `tuning.LOADING_INCREMENT_LBS` | Every resolved target snaps to this |
| How long "resting" lasts | `tuning.RESTING_WINDOW` | Past it, an athlete reads as ready / not started |
| When a sensor reads as stale | `tuning.NODE_STALE_AFTER` | Several missed pulses, not one |
| **Rep colour (green/yellow/red)** | **`react/src/rack/velocity.js` — FROZEN** | See below |

### Why colour is the exception

The `0.85` that decides where yellow starts is in the **frozen** rack contract
(SPEC §2.1). The tablet computes each rep's colour and POSTs it; the server only
stores and reads back what it was told, so there is no second copy to consolidate
— it *is* single-source, just not in `tuning.py`. There's a pointer in `tuning.py`
so nobody concludes it doesn't exist.

Changing it is not a tweak. It means touching the frozen file (full rack
re-verification on hardware), **and** every `velocity_color` already stored was
computed under the old threshold. Old reps are not recoloured. Treat it like a
schema change.

### What I deliberately did NOT put in `tuning.py`

Operational guards — `MAX_CSV_BYTES`, `MAX_PDF_PAGES`, `SET_LIMIT`,
`MAX_DASHBOARD_RACKS`. Those aren't opinions about training, they're protections
for one specific piece of code, and they belong next to it. Sweeping every
constant in the repo into one file makes things harder to find, not easier. Keep
`tuning.py` short or it stops being useful.

---

## 3. Things that are true and will surprise you

| | |
|---|---|
| **`IsCoach` means "is authenticated"** | Not "is a coach of *this* group". Coach assignment filters views; it enforces nothing. Deliberate — SPEC §9, Phase 16 |
| **Mosquitto is `allow_anonymous true`** | On both listeners. Anything on the gym network can publish fake rep data. The biggest real security hole, bigger than the authorization question |
| **`edgeathlete/coach/state` is dead at both ends** | `publish_coach_state()` is defined and never called; nothing subscribes. `MESSAGE_CONTRACT` documents it as real. Wire it for Phase 15 fatigue alerts or delete it — don't debug a message that was never sent |
| **`default_weight_lbs` is a v1-report field only** | Reports read it for schema-version-1 snapshots. Nothing writes it any more. It is *not* a live plan field — the live plan stores `target_percent` |
| **Coach adjustments look exactly like real sets** | `Set.is_coach_adjustment` marks a row a coach wrote to move an athlete's working weight. It has `ended_at` and `weight_lbs` like any completed set. **Every** new query over `Set` must consciously include or exclude it — SPEC §6.5 has the exhaustive list |
| **NULLs sort FIRST descending in Postgres** | `started_at` is nullable now. Order by `-started_at` without excluding nulls and an unstarted future session comes back as "newest" |
| **The containers bake their source** | No volume mounts. `makemigrations` writes *inside* the container — copy it back or it vanishes on rebuild. [`_MIGRATION_PLAYBOOK.md`](_MIGRATION_PLAYBOOK.md). Same trap with `docker compose run` — it will happily reuse a stale image, so pass `--build` after changing code |
| **`http://basestation` will not resolve on your laptop** | That name is handed out by the base station's own dnsmasq, so it exists only on the gym network — nothing is broken. The stack itself is already correct for it (`basestation` is in `ALLOWED_HOSTS`, nginx has no `server_name` restriction). Test it from a dev host without editing `/etc/hosts`: `curl --resolve basestation:80:127.0.0.1 http://basestation/` |

---

## 4. Known gaps, honestly

Not bugs — decisions nobody made yet, or work that stopped at a sensible line.

- **No group-staff UI.** The API takes several coaches per group
  (`TrainingGroupCoach`); adding an assistant needs Django admin. The backend is
  done; the screen is not.
- **`GET /api/analytics/session/{id}/` is prose-only** in `_MESSAGE_CONTRACT.md`.
  Every other route has an exact shape. This one still needs writing up.
- **Overnight-open-day policy is undecided.** A day left open has no defined
  behaviour. Auto-closing it would write an immutable `DailyReport` with nobody
  watching, which is why it wasn't done — but "nothing happens" isn't a decision
  either.
- **Retroactive max entry doesn't recalculate earlier sets.** Enter a max today
  and yesterday's targets stay as they were. Arguably correct; never decided.
- **Kiosk mode was never made to work** (Sprint 2 tech debt, carried into the
  Sprint 3 hardware story).

## 5. Ship prep that is NOT done

- ~~`SprintBranch` has not been fast-forwarded to `merge-braydon`.~~ **Done.** The
  two now hold identical history, and `SprintBranch` has since moved 3 commits
  ahead (the seed service, the simulator gate, the base-station scripts).
  `SprintBranch` is the branch to ship from.

### ⚠️ The `DEBUG=False` cliff — read this before you flip it

`.env.example` ships `DEBUG=True`, and that is the template every deployment
copies. Leaving it on is genuinely unsafe: Django serves full stack traces to
anyone on the gym Wi-Fi, and `/api/dev/seed-session/` goes live — an endpoint
that **wipes and recreates athletes and sessions**. The guard in `dev_views.py`
is written correctly; the shipped default is what disarms it.

But **turning it off is not a one-line change**, and finding that out in a gym
would be a bad afternoon. Three things are load-bearing on `DEBUG=True` right
now:

1. **Static files vanish.** `nginx.conf` proxies `/static/admin/` and
   `/static/rest_framework/` to Django, and there is **no `STATIC_ROOT`** in
   settings — so `collectstatic` has nowhere to write. Today those files are
   served by Django's staticfiles app, which only does that when `DEBUG=True`.
   With it off, `runserver` refuses to serve static at all. The Django admin and
   the DRF browsable API lose every stylesheet. Nothing crashes; the pages just
   come out broken, with nothing useful in the log.
2. **`runserver` is still the web server.** Django's own docs say don't. The
   concurrency argument is weak here — it is multithreaded and this is a dozen
   tablets on a closed network — but three things do bite: the autoreloader
   polls the filesystem forever on a box that runs unattended for months and can
   restart mid-request; nothing reaps a stuck request (no timeout, no worker
   recycling); and one unhandled crash takes the whole process, which during a
   training day means sets not saving until Docker restarts it.
3. **`SECRET_KEY` is the committed dev key**, straight out of `.env.example`.

**Do all of it as one change, not three.** Add `gunicorn` to `requirements.txt`
and make it the `CMD`; set `STATIC_ROOT` and run `collectstatic` in the image
build; generate a real `SECRET_KEY`; then set `DEBUG=False`. Roughly an hour.
Doing gunicorn on its own while keeping `DEBUG=True` gets you the worst of both.

> Keeping `DEBUG=True` for a **demo** is a defensible call and was a deliberate
> one — the coach page's seed button depends on it. Just never hand a real gym a
> base station in that state.
- **Dev tooling is still wired in:** `dev_views.py`, the `/api/dev/` route, and
  `<DevPanel/>` in `CoachTablet.jsx`. All three carry removal instructions.
- `requests==2.31.0` is a dead dependency — its own comment says it was for Ntfy,
  which P2 removed.
- **The rack screen has not been walked through on real hardware since the
  merge.** The frozen-file check passed at all fifteen gates and the loop works in
  a browser — but boot a real tablet and run splash → setup → check-in → set →
  rest → next before you demo it.

---

## 6. The one habit worth keeping

Nine of the bugs found during this merge were found by **clicking**, and none by
the test suite — every one of them a test asserting against a hand-built fixture
instead of the real request path. The suite is 293 backend + 209 frontend tests
and it is worth having, but it did not find the 500 on schedule deploy, the
`PROTECT` that made programs undeletable, or the unvalidated end time that
accepted the year 2020.

When you add a test for a bug, **break the code on purpose and watch the test
fail.** A test that passes against broken code is worse than no test — it is a
green light with nothing behind it.

The one place that habit has since been applied properly is the base-station
scripts (`scripts/basestation/tests/run.sh`). They run the *real* scripts inside
Debian with the hardware commands stubbed, and they caught two bugs nobody would
have seen until the box was in the gym: a boot script that died before starting
the app whenever the Wi-Fi adapter refused AP mode, and an update that silently
did nothing if anyone had ever edited a tracked file. Same idea works anywhere
the thing under test is a script rather than a function.

Good luck. It's a good system.

— Devin
