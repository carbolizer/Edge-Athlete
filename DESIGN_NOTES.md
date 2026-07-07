# Design Notes — decisions to revisit

Deliberate choices in the base-station API that are fine for now (demo / Sprint 1)
but we may want to change later. For each: what we did, why, and when to revisit.

## Personal records (PRs)
- **What:** When a set finishes we flag `is_velocity_pr` (fastest peak velocity)
  and `is_weight_pr` (heaviest weight) by comparing the set to the athlete's
  earlier *real* (non-false) sets of the **same exercise**. A first-ever set is
  **not** flagged (nothing to beat). We work these out live and do **not** store
  them on the set.
- **Why:** Simple, needs no extra database columns, and it's enough for a live
  "new PR!" banner on the screens.
- **Revisit when:** we want a page that shows *which past sets* were PRs (a reload
  can't know — nothing is saved), or a smarter definition of "best" (like an
  estimated 1-rep-max, or velocity at a given load) instead of raw peak velocity.

## Rack assignment
- **What:** A coach gives a tablet its rack number with a PATCH. We do **not**
  check whether another tablet already holds that number, there's no way to
  "unassign" a rack back to the pool, and any number value is accepted.
- **Why:** Keeps the assign flow trivial for the demo — one coach assigning a
  handful of racks won't collide.
- **Revisit when:** two tablets could realistically end up with the same rack, or
  a rack needs freeing/reassigning (the spec already flags a related "no unassign
  path" gap). Likely fix: enforce uniqueness, add an unassign endpoint, validate
  the number.

## "Coach" means "any logged-in user"
- **What:** The coach check just asks "are you logged in?" There is no real coach
  role or group yet.
- **Why:** Right now there's only one kind of privileged user, so this is the
  simplest thing that works with the JWT login.
- **Revisit when:** we add other account types (athletes, admins) — then "coach"
  has to become an actual role, not just "authenticated."

## Starting/finishing a set needs no login
- **What:** `POST /api/sets/` and `POST /api/sets/{id}/complete/` are open — any
  device on the gym network can call them, and anyone who knows a set's id can
  complete it.
- **Why:** The tablets have no login, the network is closed/offline, and the spec
  marks these endpoints open. Broker/API auth is a later hardening item (Phase 12).
- **Revisit when:** the network stops being fully trusted, or we want to stop a
  stray/duplicate "complete" from overwriting a set that's already saved.
