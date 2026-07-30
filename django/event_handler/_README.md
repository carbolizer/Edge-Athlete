# `event_handler/` — the whole backend

One Django app. Everything the base station does server-side is in here.

The name is a leftover from the reference project this was bootstrapped from; it
handles far more than events now. Renaming it would touch every migration, so it
stays.

```
event_handler/
├── models.py          The 24 tables, with the reasoning in comments. The source of truth
├── views.py           HTTP only — auth, status codes, shapes. Calls services/ to think
├── serializers.py     Model ↔ JSON, plus the validation that protects the data
├── urls.py            ~50 routes, grouped and commented
├── permissions.py     IsCoach. ⚠️ It means "is authenticated" — see below
├── admin.py           Django admin registration
├── dev_views.py       Demo-only endpoints behind the dev panel. Not for production
├── tests.py           280 tests
├── migrations/        0001 → 0017. Four are data migrations — see the RUNBOOK
├── services/          The thinking: derived reads, planning, reports, the math
├── realtime/          MQTT in and out — pulses in, room invalidations out
└── management/        Commands you run by hand: seeding, the node simulator
```

Each subfolder has its own `_README.md`.

## How a request flows

```
nginx → urls.py → views.py → services/ → models.py → Postgres
                     ↑            ↑
                serializers   the actual logic, no request object
```

`views.py` is deliberately thin. If you are writing business logic in a view,
it probably belongs in `services/`.

## Four things that will catch you

| | |
|---|---|
| **`IsCoach` means "is authenticated"** | Not "is a coach of *this* group". Coach assignment filters views; it enforces nothing. Deliberate — SPEC §9 |
| **The container bakes the source** | No volume mount. `makemigrations` writes *inside* the container — copy it back or lose it. [`docs/MIGRATION_PLAYBOOK.md`](../../docs/MIGRATION_PLAYBOOK.md) |
| **Derived, not stored** | There is no room-state table and no cached target weight. That is a rule, not an omission — `services/_README.md` |
| **`Set.is_coach_adjustment`** | A coach-written row that looks exactly like a completed set. Every new query over `Set` must decide whether to include it — SPEC §6.5 |

## Where to start

- New to the product? [`docs/DATABASE-OVERVIEW.md`](../../docs/DATABASE-OVERVIEW.md) — plain English, no Django needed.
- Picking up the project? [`docs/HANDOFF.md`](../../docs/HANDOFF.md).
- Need an exact request shape? [`MESSAGE_CONTRACT.md`](../../MESSAGE_CONTRACT.md).
