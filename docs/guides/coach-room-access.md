# Coach access to a weight room

Each base station serves one weight room, with its own database, signing key and
MQTT broker. A school may have several rooms, but each room needs its own base
station installation. Room IDs are local database identifiers, not globally
unique addresses. This release does not support hosting several rooms' athlete
or equipment data in one database.

## Relationships

School has many WeightRooms. InstallationSetup row 1 identifies the one room
served by this database. CoachProfile associates a Django user with one room;
several coaches may share that room. A missing profile or null assignment grants
no coach access. The dashboard is the view of that room, with the canonical path
`/coach/rooms/<id>`; it is not a separate assignable database object. All athletes,
nodes, screens, sessions and reports in this database belong to the installation.
TrainingGroupCoach remains a descriptive staffing relationship within the room.

## Upgrade and first setup

1. Back up the database, then run `python manage.py migrate` before deploying the
   updated frontend. Migration 0025 creates the school/room schema; 0026 assigns
   existing accounts to a seeded room. Passwords, active/staff flags and forced
   password-change flags remain intact. Existing accounts retain access.
2. Sign into Django admin as the installation superuser and rename `My school`
   and `Main weight room` under Schools and Weight rooms. Keep the installation's
   room ID stable once it has live data; changing it would relabel all data in
   this local database, not move or partition it.
3. On a fresh installation, claim the first administrator using the normal local
   `setup_code` flow. The account is assigned to the installation room. Accounts
   created in Coaches also receive that room and a temporary password.
4. Sign in at `/coach`. After any required password change, the app confirms the
   assignment and opens `/coach/rooms/<id>`. School and room appear above the
   workspace. The room-layout route `/coach/setup` uses the same gate.

## Assign and revoke access

An active, assigned administrator opens **Coaches**. **Remove room access** sets
an account's assignment to null without deleting its login, workout history or
password. **Assign to this room** restores access. Ordinary coaches cannot make
these changes. Administrators cannot revoke their own assignment, and at least
one assigned active administrator must remain.

Assignment is checked against the live database on authenticated data requests.
Revoking access therefore blocks existing JWTs on their next data request; it
does not require waiting for token expiry. The dashboard clears its live snapshot
on 401/403. An unassigned account can still sign in, inspect its session and
change its password, but gets a "No weight room assigned" screen with a retry
and sign-out option. A direct URL for another room is refused.

Users created directly with Django's `create_user`/`createsuperuser` are not
silently assigned. For operator recovery, a superuser can edit Coach profiles in
Django admin and select the installation room. If the installation link itself
is missing, repair row 1 locally through the Django shell before assigning
accounts. Do not use this as a mechanism for switching among live room datasets.

## Security boundary

The protected coach workspace and coach data APIs require room membership;
`is_staff` and `is_superuser` do not bypass these API checks. Room membership is
not taken from localStorage or JWT room claims. Account-management responses are
only available to assigned administrators. Unknown/nonlocal room IDs in
assignment changes are rejected.

The anonymous wall display, rack-device REST interfaces and existing MQTT
channels retain their trusted private-LAN behavior. They are not a replacement
for authenticated device provisioning and broker ACLs. This change does not make
those public device interfaces private or turn the base station into an
internet-facing multi-tenant service. Separate installations must have different
signing keys and isolated databases/brokers.

## Verification

Backend checks use PostgreSQL, including actual forward/backward migrations and
existing concurrency tests. From the repository root, with project dependencies
installed and a local PostgreSQL account permitted to create test databases:

```sh
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 POSTGRES_USER=your_local_user \
  DJANGO_SETTINGS_MODULE=basestation_config.test_settings \
  python django/manage.py test event_handler --noinput
```

The test settings replace MQTT connection/thread startup with mocks and use a
fast password hasher. They must never be used to serve the application. They do
not mock PostgreSQL or room authorization.

From `react/`, run `npm ci`, `npm test`, and `npm run build`. Build output is
tracked in this repository; review it separately when preparing a deployment.
No generated distribution files are part of this source change.
