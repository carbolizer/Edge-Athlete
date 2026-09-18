# Coach accounts and team roster

## First boot

There is no public registration. A new installation is claimed once, by someone
who can reach the base station itself.

1. Start the stack with `docker compose up -d --build`.
2. On the base station, print a one-time setup code:

   ```bash
   docker compose exec django python manage.py setup_code
   ```

   The code is shown only on that terminal, is valid for 24 hours, and works
   once. Re-running the command replaces any previous code, which is also how you
   revoke one that was seen by the wrong person.
3. Open the base station in a browser. The app shows **Create your first coach
   account** before the role picker or dashboard.
4. Enter a username, password, matching confirmation, and the setup code. Django
   validates the username syntax and rejects short, common, entirely numeric, or
   overly similar passwords.
5. The account is created as a Django staff/superuser administrator. The browser
   signs in and opens `/coach`.

**Why the code exists.** Without it, whoever loaded the website first would become
the administrator. The code proves the enrolling person had access to the machine,
so a student who finds the website cannot claim the system. Only a hash of the code
is stored, so a database leak does not reveal it.

Setup is installation-wide, not per device and not repeated on every reboot.
Migrations `0023_coach_setup_and_athlete_archive` and
`0024_setup_code_and_coach_profiles` create a persistent singleton setup marker.
Enrollment locks that row and creates the account and completion marker in one
transaction. Two simultaneous requests cannot both enroll an admin. Installations
with existing users skip enrollment; deleting the initial account after enrollment
does not reopen setup, and the code is cleared on success.

## Login and sessions

Both `/coach` and `/coach/setup` use the same login/setup component. Authentication
uses the existing Simple JWT implementation: `/api/auth/login/` accepts username
and password and returns access/refresh tokens. The coach browser retains the access
token in localStorage and sends it as a Bearer credential. The existing access
lifetime is eight hours; expiry requires signing in again. Logout clears the
browser credential. It does not revoke copies of an already-issued JWT.

Passwords use Django's salted PBKDF2 password hasher; plaintext passwords are
never persisted, and temporary passwords returned by the account API are the only
time a password is visible in plaintext. Usernames remain ordinary identifiers.
Invalid credentials show a generic error without identifying which field matched.
Inactive accounts cannot log in or use previously issued tokens.

Nginx rate-limits POST requests to login and setup by source IP (10/minute,
burst of five), across nginx workers. Rejected requests return 429; the UI asks
the user to wait. Status reads do not consume the allowance. This protection is
on the nginx entry point, not direct access to Django's internal port.

Coach roster reads/writes require authentication on the backend. Existing
rack-controller and public wall-display interfaces retain their device-facing
behavior. This change does not add broker authentication or encrypt the existing
HTTP deployment. Use HTTPS for confidentiality when deploying on an untrusted
network.

The first-run wrapper remembers successful configuration only to allow previously
configured rack screens to reopen their offline shell. This local flag does not
grant API access or replace the database setup marker.

### First sign-in with a temporary password

When an administrator creates a coach (or resets one), the account starts with a
temporary password and a flag that forces a change. After signing in, that coach
sees **Choose your own password** before the rest of the app opens, and cannot
reach the workspace until the password is replaced. Any coach can change their own
password later from **Coaches → Change my password**; the current password is
required, so holding a borrowed token is not enough.

## Managing coaches

The head coach (an administrator) opens **Coach → coaches** to:

- **Add a coach** — create an individual login. Leave the password blank to have a
  strong temporary one generated. It is shown once and cannot be read back.
- **Reset password** — issue a fresh temporary password for a coach who forgot
  theirs. They are forced to choose a new one at next sign-in.
- **Make administrator / Make coach** — grant or remove account-management rights.
- **Deactivate / Reactivate** — immediately stop or restore a login.

Everyone shares one database: an account says *who* is coaching, it does not
partition athletes or reports. Ordinary coaches use the whole workspace but the
**coaches** tab is hidden for them and the API refuses account-management calls
regardless of what the browser sends.

Guard rails: you cannot deactivate or demote your own account, and the
installation must always keep at least one active administrator, so the box can
never be locked out of account management. The first-run administrator is the
only superuser created automatically.

### Existing installations and recovery

Normal container startup no longer runs `ensure_demo_coach`. Existing users and
passwords are preserved by the migration. If a prior installation used the demo
password, change it explicitly; upgrades do not silently replace credentials.

From the base-station terminal:

```bash
docker compose exec django python manage.py changepassword YOUR_USERNAME
# If no usable administrator account remains:
docker compose exec django python manage.py createsuperuser
```

The explicitly invoked demo `seed` service still creates its documented demo
account. Use it only for demo installations; it is not part of normal startup.

## Team members

Open **Coach → roster** to add members, edit names, optionally assign an NFC tag,
and remove members. NFC tags remain write-only: editing a name preserves the
existing tag unless **Replace or clear NFC tag** is selected.

Removal archives an athlete (`is_active=false`) rather than deleting their row.
It clears the NFC tag, current training-group memberships, and memberships in
unstarted/unended sessions. Past sessions, sets, reps, and report snapshots remain
intact. An athlete participating in an active session cannot be archived until
that session ends; the API returns 409 with an explanation.

Archived members are excluded from the default roster, new session selections,
group additions, and CSV name resolution. **Show archived members** includes them
in the roster view. They remain selectable in the coach's athlete/history and
report views, marked **(archived)** in the athlete selector. Archival is not data
erasure, and there is no restore UI in this release.

## API contract

| Method and route | Access | Result |
| --- | --- | --- |
| `GET /api/auth/setup/` | Public | `{setup_required, setup_code_pending}`, not cached; never returns the code |
| `POST /api/auth/setup/` | Fresh installation only | `{username,password,setup_code}` → 201 with tokens; 400 validation or bad/expired code; 409 already configured |
| `POST /api/auth/login/` | Public | `{username,password}` → tokens + `must_change_password`; 401 invalid/inactive credentials |
| `GET /api/auth/me/` | Authenticated | Username, staff status, `must_change_password` |
| `POST /api/auth/password/` | Authenticated | `{current_password,new_password}` → 204; 400 wrong current or weak new |
| `GET /api/coaches/` | Administrator | All coach accounts (never includes passwords) |
| `POST /api/coaches/` | Administrator | `{username,password?}` → 201 with `temporary_password` shown once |
| `PATCH /api/coaches/{id}/` | Administrator | `{is_active?,is_staff?}`; self-demotion and last-admin removal → 400 |
| `POST /api/coaches/{id}/reset/` | Administrator | New `temporary_password`; forces a change at next sign-in |
| `GET /api/athletes/` | Coach | Active roster; `?include_archived=true` includes historical records |
| `POST /api/athletes/` | Coach | Create member → 201 |
| `GET /api/athletes/{id}/` | Coach | Member detail, including archived records |
| `PATCH /api/athletes/{id}/` | Coach | Edit name, notes, or NFC tag |
| `DELETE /api/athletes/{id}/` | Coach | Archive → 204; active participant → 409; missing record → 404 |

`is_active` is read-only in serializers; clients cannot reactivate a record by
PATCH. Duplicate nonempty NFC tags and blank names return validation errors.

## Verification

Backend tests require the project's PostgreSQL and MQTT services:

```bash
docker compose exec django python manage.py test event_handler.test_coach_accounts
docker compose exec django python manage.py makemigrations --check --dry-run
```

Frontend checks, from `react/`:

```bash
npm ci
npm test
npm run build
```

Coverage includes fresh/existing installations, missing/expired/replaced setup
codes, invalid input, password hashing, concurrent enrollment, disabled accounts,
administrator-only account management, temporary-password generation and forced
change, self-demotion and last-admin guards, unauthorized roster access, member
creation/editing, active-session removal refusal, preservation of sessions/sets/
reps/report snapshots, NFC reuse, setup/login/password/coach-management form
interactions, roster actions, connection retry, and offline-shell behavior.
