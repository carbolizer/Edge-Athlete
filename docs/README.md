# `docs/` — the reference shelf

Write-ups of completed work, implementation guides, and ADRs explicitly linked
from the governing specification. One file per topic.

[`../_SPEC.md`](../_SPEC.md) remains the authority. Feature specs and ADRs in this
directory refine only the slices that `_SPEC.md` explicitly delegates to them;
open items in those documents are not accepted product behavior.

## Start here

| File | What it is |
|---|---|
| [`_PROJECT_VISION_ARCHITECTURE.md`](_PROJECT_VISION_ARCHITECTURE.md) | Long-term cloud-hosted Rack, VBT, and product architecture north star |
| [`_RACK_DASHBOARD_TEAM_REGISTRATION.md`](_RACK_DASHBOARD_TEAM_REGISTRATION.md) | Team-scoped Rack/Dashboard identity, pairing, persistent credentials, and backend authorization direction |
| [`_RACK_HELPER_SPEC.md`](_RACK_HELPER_SPEC.md) | Native desktop BLE acquisition, pairing, queue, cloud synchronization, security, and implementation blockers |
| [`_ADR_RACK_HELPER_LAUNCH_INTENT.md`](_ADR_RACK_HELPER_LAUNCH_INTENT.md) | Accepted server launch-intent, fixed protocol URI, first-pair binding, concurrency, and implementation gates |
| [`_HANDOFF.md`](_HANDOFF.md) | **Read first.** The things that are not obvious from the code — why a prescribed weight can go *down*, where the formulas live, and what is deliberately unfinished |

## What changed, and how to see it

| File | What it is |
|---|---|
| [`_PATCH_NOTES.md`](_PATCH_NOTES.md) | Everything that changed on `merge-braydon`, by phase, with the files touched and a click path to see each one working |
| [`_NAMING_CHANGES.md`](_NAMING_CHANGES.md) | The P9 rename reference — old name → new name → why |

## How things work

| File | What it is |
|---|---|
| [`_DATABASE-OVERVIEW.md`](_DATABASE-OVERVIEW.md) | A plain-English tour of the database tables — no engineering background needed |
| [`_API_AUTHORIZATION_MATRIX.md`](_API_AUTHORIZATION_MATRIX.md) | Every API route's Django gate and public VPS exposure |
| [`../django/event_handler/_README.md`](../django/event_handler/_README.md) | The backend, folder by folder. Every subfolder has its own `_README.md` too |
| [`../django/event_handler/services/tuning.py`](../django/event_handler/services/tuning.py) | **The training math.** Every tunable number in one file — the 1RM formula's divisor, the trusted rep window, bar rounding, the resting window. The formulas themselves are beside it in `lifting_math.py` |
| [`_MIGRATION_PLAYBOOK.md`](_MIGRATION_PLAYBOOK.md) | How to change the schema safely. **Read before touching `models.py`** — the container bakes its source, and that has already cost us a migration |
| [`_IMPORTING_SPREADSHEETS.md`](_IMPORTING_SPREADSHEETS.md) | The coach-facing guide to the CSV importers — roster, maxes, workout plans |
| [`../_MESSAGE_CONTRACT.md`](../_MESSAGE_CONTRACT.md) | Exact request/response shapes for every endpoint and MQTT topic |

---

## Before you read anything here

Start the stack, then open `http://localhost/`:

```bash
docker compose up -d
```

The first screen is a **role picker** — this device has no role yet. Every click
path in the patch notes starts from there.

> **A device remembers its role.** Once you pick one, `localhost/` redirects
> straight to it forever. To change it, press **Change device** in the top right
> of the coach or wall screen.

The demo login is `coach` / `coachpass`. To get a gym full of realistic data:

```bash
docker compose exec django python manage.py seed_active_session
```
