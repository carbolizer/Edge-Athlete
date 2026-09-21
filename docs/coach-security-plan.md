# Coach security implementation plan

1. Review credential creation, reset, change, login, logging and browser storage.
   Preserve Django's salted PBKDF2 hashing and existing passwords; no bespoke hashing.
2. Enforce five failed logins in a rolling ten-minute window per username in Django.
   Use PostgreSQL row locks across workers, count unknown/inactive accounts, return
   429 with Retry-After, and allow login when failures expire. Successful logins
   do not erase recent failures; blocked requests do not extend the window.
3. Preserve and verify the existing School → WeightRoom ← CoachProfile model and
   installation-specific dashboard. Verify unassigned/wrong-room users, direct
   URLs, assignment changes, and immediate revocation of existing tokens.
4. Prevent credential responses from being cached and redact credential requests
   from Django error reports. Verify real production hashing, secret-free reads,
   failed-login persistence, expiration, worker concurrency and frontend behavior.
5. Run backend/frontend checks and migration drift checks. Document deployment,
   acceptance results, and the existing single-room/private-LAN boundary.

## Completed implementation and acceptance

- Credential audit confirmed create/reset/change use Django password APIs and
  login verifies hashes. Production PBKDF2 tests verify salts, old-password
  rejection and no password/hash disclosure in account reads. Added no-store
  responses and error-report redaction (also for Wi-Fi coach reauthentication),
  and removed demo-password terminal output.
- Added migration 0027 and a locked PostgreSQL rolling failure budget. Tests
  exercise eight simultaneous first attempts: exactly five 401s and three 429s.
  Unknown/inactive users, changing IPs, successful login and exact expiry are
  covered. The frontend displays Retry-After and handles nginx HTML errors.
- Preserved the existing room implementation and verified canonical routing,
  wrong-room/unassigned denial, staff checks, revocation and migration backfill.
- Full backend regression: 489 tests passed before final maintenance refinements;
  focused security/account/room checks rerun after refinements. Frontend: 200
  tests passed; production build passed (existing bundle-size warning).
  Migration drift check and git whitespace check passed.

## Deployment

Rebuild the Django image and apply migrations through 0027 before serving the
updated application; publish the rebuilt frontend through the normal deployment
process. Tests used disposable PostgreSQL databases. No running installation was
migrated or deployed by this task. Run `python manage.py prune_login_attempts`
periodically if you want expired username-key records removed.

The existing single-room-per-database and anonymous private-LAN device interfaces
remain the documented deployment boundary. Multi-room hosting in one database is
not implemented by this change.

Implementation references: [Django password management](https://docs.djangoproject.com/en/5.1/topics/auth/passwords/)
and [DRF throttling concurrency limitations](https://www.django-rest-framework.org/api-guide/throttling/#a-note-on-concurrency).
