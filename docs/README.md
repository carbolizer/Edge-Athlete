# `docs/` — the reference shelf

Write-ups of work that is **done**, and guides for doing common things. One file
per topic.

This is not the place for plans, designs, or open questions — those live in
[`../SPEC.md`](../SPEC.md), the single authority for the system. (The merge canon
was folded into it on 2026-07-30.) A document only arrives here once the work it
describes is finished and on the branch.

## What changed, and how to see it

| File | What it is |
|---|---|
| [`PATCH_NOTES.md`](PATCH_NOTES.md) | Everything that changed on `merge-braydon`, by phase, with the files touched and a click path to see each one working |
| [`NAMING_CHANGES.md`](NAMING_CHANGES.md) | The P9 rename reference — old name → new name → why |

## How things work

| File | What it is |
|---|---|
| [`DATABASE-OVERVIEW.md`](DATABASE-OVERVIEW.md) | A plain-English tour of all 24 tables — no engineering background needed |
| [`MIGRATION_PLAYBOOK.md`](MIGRATION_PLAYBOOK.md) | How to change the schema safely. **Read before touching `models.py`** — the container bakes its source, and that has already cost us a migration |
| [`IMPORTING_SPREADSHEETS.md`](IMPORTING_SPREADSHEETS.md) | The coach-facing guide to the CSV importers — roster, maxes, workout plans |
| [`../MESSAGE_CONTRACT.md`](../MESSAGE_CONTRACT.md) | Exact request/response shapes for every endpoint and MQTT topic |

## Team history

| | |
|---|---|
| [`sprints/`](sprints/) | Scrum planning artifacts from past sprints |

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
