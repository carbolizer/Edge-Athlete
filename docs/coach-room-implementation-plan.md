# Coach assignment implementation plan

## Outcome and architectural boundary

A coach must have an explicit assignment to this base station's weight room before
opening its coach workspace or using its authenticated data APIs. The existing
architecture is one offline base station/database/broker per room. This change
makes that boundary explicit; it does not turn the local database into a shared
multi-room cloud service. Athletes, equipment, training data and reports belong
to the installation's room. Training-group coaching roles remain descriptive
within that room and do not grant room access.

## 1. Relationships and migration

- Add School (name) and WeightRoom (name, school). A school can have many rooms.
- Bind the existing InstallationSetup singleton to one WeightRoom. Its dashboard
  is derived as `/coach/rooms/<room-id>` rather than a separate mutable record.
- Add nullable CoachProfile.weight_room. Many coaches can share a room; each
  account has one assigned room. Null means no dashboard access, including staff.
- Seed a clearly named default school/room for the existing installation and
  explicitly backfill existing users, preserving passwords and account state.
- New users created outside the enrollment/account APIs remain unassigned. First
  enrollment and administrator-created accounts receive the installation's room.
- Use protected foreign keys so deleting a room/school cannot orphan accounts.

## 2. Server authorization and management

- Centralize the current-room lookup and live database assignment check. Never
  trust a room supplied by the browser or a stale room claim in a JWT.
- Require active users assigned to the installation for coach and staff actions.
- Enforce the assignment during JWT authentication for data endpoints, including
  endpoints with public rack/wall variants when called with a coach token.
- Keep login, session inspection and password change available to unassigned
  users so the client can explain why access is denied.
- Return room, school, and canonical dashboard path in login/session responses.
- Expose the current installation room to authorized administrators and permit
  assigning/revoking access through account management. Reject other room IDs,
  malformed values, self-revocation and changes that leave no assigned admin.

## 3. Frontend

- Gate both `/coach` and `/coach/setup` on the server session before loading
  private data. Show an actionable unassigned-account state with sign-out.
- Redirect `/coach` to the server-provided canonical dashboard after login.
  Validate direct room URLs against the confirmed session and refuse mismatches.
- Display the school/room identity and show assignments in coach management.
- Recheck authorization on API requests and discard private live snapshots when
  an authorization response indicates that access has been revoked.
- Preserve first-login password changes and the public wall/rack workflows.

## 4. Verification

- Backend: assigned, unassigned, wrong-room, inactive and staff cases; real JWT
  requests; direct data endpoints; forged room selection; revocation with an
  existing token; enrollment/creation defaults; admin-only assignment changes;
  migration backfill and preserved profile state.
- Frontend: canonical navigation, direct-route mismatch, unassigned state,
  no private fetch before session confirmation, room labels and assignment UI.
- Run the existing backend/frontend suites, migration drift check and production
  frontend build. Record infrastructure limitations rather than claiming checks
  that could not run.

## 5. Documentation and rollout

- Update the system specification and API contract, and document setup, assignment,
  revocation and recovery. Existing installations run the new migration before
  deploying the frontend. Rename seeded school/room labels in Django admin.
- Public wall and rack APIs remain trusted-LAN device interfaces; account room
  assignments do not authenticate hardware or secure an internet-exposed broker.
  Separate base stations must retain distinct signing keys/databases/brokers.
- No production deployment, shared branch push or real account changes are part
  of this implementation.

## Completion record — 2026-09-18

All five implementation steps are complete for the one-room-per-installation
architecture described above. Schema migration 0025 and data migration 0026 are
separate to avoid PostgreSQL pending-trigger/index conflicts on populated profiles.

Verified:

- Full Django suite: 481 tests passed against isolated PostgreSQL 16.
- Final account/room regression run after adding private session cache headers:
  34 tests passed.
- Frontend suite using package-lock dependencies: 198 tests in 25 files passed.
- Production Vite build passed; the existing large-bundle advisory remains.
- Django `makemigrations --check --dry-run`: no changes detected.
- `git diff --check`: passed.

Legacy endpoint fixtures now create explicitly assigned coaches. Migration tests
restore the latest schema instead of an obsolete hardcoded migration. The rack
controller concurrency fixture now models two tabs on one assigned screen,
consistent with the existing unique-screen-per-rack constraint.

MQTT network startup was mocked for backend tests; live hardware/broker operation
was not exercised. No production database was changed. Generated distribution
files were restored after build verification; source changes remain uncommitted
in the local `Carl's-Branch` checkout and have not been pushed or deployed.
