<!--
MINISPEC-exercise-catalog.md — a scoping doc, not canon (yet).
Purpose: lay out exactly what it takes to replace free-text exercise names with a
real Exercise catalog, so we can judge the effort honestly before committing to it.
Snapshot taken 2026-07-17 against branch rack-screen-and-active-session.
-->

# Mini-Spec: Exercise Catalog

## Why this exists
Right now every exercise is a hand-typed string (`"Back Squat"`) in three tables.
That works, but there's nothing stopping the same movement being spelled two ways,
and it means "which movement is this max for?" is answered by matching text, not a
real link. The catalog gives every movement one official identity. This doc scopes
what it costs to add, so we can decide *when* it's worth doing.

## Snapshot: where exercise-identity lives today (5 files)
- **models.py** — `Program.exercise`, `Set.exercise`, `AthleteReferenceMax.exercise` are all `CharField`.
- **serializers.py** — `ProgramSerializer` and `SetSerializer` expose `exercise`.
- **views.py** — `set_create` (accepts it), `set_complete`/`_personal_records` (filters sets by it), `programs_view` (creates with it), `sessions_active` (keys `session_exercises`, `targets`, and `maxes` by the name), `analytics_athlete` (returns it).
- **seed_active_session.py** — creates programs/sets/maxes with name strings.
- **tests.py** — uses name strings.

Nothing in the **MQTT message contract** references an exercise (reps, pulses,
and the set-complete body carry none). Exercise identity is a REST + models
concern only.

## What canon intends (and the gap)
Canon Phase 5 adds `Exercise` (name unique, tags M2M, is_stub, created_at) + `Tag`,
and FKs the *new* models (`SessionExercise`, `AthleteMax`) to it. **It does not
convert `Program.exercise` or `Set.exercise`** — those stay text in the spec as
written. That's the fork:

- **Scope A — canon-literal:** catalog + FK the new models only; leave Program/Set on text.
  → **Trap:** the rack endpoint keys `session_exercises` off Program (text) but `maxes`
  off AthleteReferenceMax (catalog id). The frontend lookup `roster[a].maxes[exercise_id]`
  then compares an id to a name and silently breaks. Half-normalizing is incoherent
  for our own endpoint. **Not recommended.**
- **Scope B — full normalize:** convert all three (`Program`, `Set`, `AthleteReferenceMax`)
  to FK the catalog. Everything speaks catalog ids; the endpoint and picker line up
  with canon Phase 10/11's `exercise_id` semantics for free. **Recommended.** The rest
  of this doc scopes Scope B.

## The story
> As the infrastructure owner, I want every exercise to resolve to one catalog
> entry, so maxes, plans, sets, and targets all agree on movement identity and the
> team can build Phase 6 (CSV import / stub exercises) on a real foundation.

**Acceptance:** all three models FK `Exercise`; the active-session endpoint returns
real catalog ids; existing data migrates with no loss; set-logging still works
end-to-end; catalog is listable for pickers.

## Change list (Scope B)
**Models (2 new, 3 converted)**
1. Add `Exercise` (name unique, tags M2M→`Tag`, is_stub bool, created_at) + `Tag` (name unique).
2. Convert `Program.exercise`, `Set.exercise`, `AthleteReferenceMax.exercise` from `CharField` → `ForeignKey(Exercise)`.

**Migration (the fiddly bit — a data migration)**
3. Per column: add a nullable FK, `RunPython` to `get_or_create` an `Exercise` for each
   distinct existing name and populate the FK, then drop the old `CharField`. Write the
   reverse step (copy `exercise.name` back into a text column) so it stays rollback-safe.
   ~1 migration file, mechanical, fully testable.

**Serializers (2)**
4. `ProgramSerializer` + `SetSerializer`: exercise becomes an id in / id+name out.

**Views (5)**
5. `set_create` — accept exercise id (Phase 11's picker already sends `session_exercises[].exercise_id`).
6. `_personal_records` — filter by the FK (essentially unchanged).
7. `programs_view` POST — create with the FK.
8. `sessions_active` — `exercise_id` = real `Exercise.id`; `maxes`/`targets`/`session_exercises` all keyed by it. **Net simplification** — everything's one id type.
9. `analytics_athlete` — return `{id, name}`.

**New endpoint**
10. `GET /api/exercises/` — list the catalog (pickers/management). Small.
11. *(Deferred, Phase 6)* `PATCH /api/exercises/{id}/confirm/` stub-confirmation — out of scope here.

**Support**
12. Seed command → create `Exercise` rows, reference by FK.
13. Tests → swap name strings for `Exercise` objects; add 1–2 catalog tests.

**Frontend (rack screen — being built now)**
14. Picker already reads `exercise_id` from the fetch; it just becomes an int instead
    of a string, treated opaquely. set-create POSTs the id. Minimal — *and* only cheap
    to keep minimal if we do this BEFORE building the Phase 10/11 picker, not after.

**Docs**
15. SPEC: note Program/Set/AthleteReferenceMax now FK `Exercise` (a deliberate step
    past canon's leave-them-as-text); update the endpoint's `exercise_id` note; flag
    that `POST /api/sets/` now takes an id. No MQTT-contract change.
16. A short migration playbook (the bus-factor insurance for whoever comes after).

## Who this collides with
- **Braydon (sensor + message contract):** not affected — exercise isn't in any MQTT
  payload or the set-complete body. The `POST /api/sets/` id change is on the rack-screen
  (our) side, not his.
- **Derrilon (MQTT / simulator):** not affected — reps/pulses carry no exercise.
- **Carl (backend models/API):** the ONE overlap. If Carl touches Program/Set,
  serializers, or the set endpoints this sprint, we must coordinate: either we own the
  catalog and Carl builds on top, or we collide. This is the main non-code cost — and
  it's cheapest right now, before Carl has started.

## Risk & mitigation
- **Data migration correctness** — mechanical (distinct names → rows); covered by a
  round-trip test on real seed data. Reversible if we write the reverse step.
- **Touching "built" Phase 1–4 models (Set/Program)** — low logic risk; re-run the set
  flow + full test suite after.
- **Coordination with Carl** — a conversation, not code.

## Effort read
Contained to one Django app + a trivial frontend tweak; design mostly handed to us by
canon; migration mechanical; blast radius maps to 5 files + one teammate to sync with.
The only genuinely fiddly part is the data migration. **Scope estimate: ~6/10.**
