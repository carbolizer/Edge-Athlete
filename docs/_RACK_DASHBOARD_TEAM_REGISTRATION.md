# Rack and Dashboard Team Registration Vision

- Source: `EDGE_ATHLETE_RACK_DASHBOARD_REGISTRATION_UPDATED.md`, supplied by the
  product owner on 2026-08-10
- Status: Product and architecture direction; database implementation pending
- Related vision: `docs/_PROJECT_VISION_ARCHITECTURE.md`
- Related ADR: `docs/_ADR_COACH_WORKSPACE_TENANCY.md`

## Problem

Edge Athlete must support multiple coaches, teams/groups, racks, and dashboard
displays. Rack and dashboard pages must never receive one global roster,
leaderboard, workout list, or room state containing another team's information.
Backend authorization and query scoping enforce this boundary; React filtering is
not authorization.

The product hierarchy is:

```text
Organization
  -> Coaches
  -> Teams / TrainingGroups
     -> Athletes
     -> Workouts and assignments
     -> Rack endpoints
     -> Dashboard endpoints
```

A coach may manage several teams, and several coaches may manage one team. Do not
model `Coach == Team`.

## Existing Domain Mapping

- Existing `TrainingGroup` is the Team concept. Do not create a parallel `Team`
  table.
- Existing `TrainingGroupCoach` becomes an enforced coach/team authorization
  relationship rather than its current descriptive-only link.
- Existing `Athlete.training_groups` remains many-to-many. An athlete can belong
  to more than one team or position/speed group.
- An account-level `Organization` owns teams and domain data. The first onboarding
  slice may restrict one user to one organization while still allowing that user
  to manage several teams inside it.
- `HostedGym` remains a physical diagnostics gateway deployment and is not the
  account organization.

## Persistent Endpoint Identity

Every physical Rack browser and Dashboard display has a persistent identity that
is separate from its current team assignment:

```text
Browser endpoint identity
  -> kind: rack or dashboard
  -> assigned TrainingGroup
  -> persistent revocable credential
```

The endpoint keeps its identity when reassigned to another team. Reassignment does
not create a new Rack or Dashboard. Normal shutdown, reboot, browser restart, and
returning another day do not require pairing again.

Pairing is required when:

- A browser profile or device is new.
- Browser/site storage has been cleared.
- An endpoint is intentionally reset or unpaired.
- A credential is revoked.
- A lost or replaced computer receives a replacement credential.

The backend remains authoritative for endpoint-to-team assignment. A public ID,
rack number, dashboard ID, URL parameter, or localStorage device ID never grants
access.

## Pairing and Credential Flow

The unregistered browser creates a short-lived pairing session:

```text
Rack or Dashboard browser
  -> request pairing session
  -> receive human code for display
  -> receive separate bootstrap capability in an HttpOnly cookie
Coach
  -> authenticate
  -> select authorized TrainingGroup
  -> submit human code
Backend
  -> lock and consume pairing
  -> assign endpoint to TrainingGroup
Browser poll
  -> receive persistent endpoint credential in an HttpOnly cookie
```

The human code and persistent credential are different:

- Internal endpoint ID: server-generated UUID.
- Pairing code: unambiguous random human code, at least eight characters, expires
  in five to ten minutes, one-time use, rate-limited, and stored as a keyed digest.
- Bootstrap capability: independent 256-bit secret available only to the browser
  that requested the pairing.
- Persistent credential: independent 256-bit versioned secret; the server stores
  only a domain-separated SHA-256 digest and checks revocation on every request.

The coach browser never receives the endpoint credential. The endpoint browser
receives it from its bootstrap-authenticated status poll after the coach claims the
code. This avoids asking a coach to transfer a secret between computers.

Endpoint cookies are host-only, `HttpOnly`, `Secure`, and `SameSite=Strict` with a
narrow API path. Cookie-authenticated writes require CSRF and Origin validation.
Credentials, pairing capabilities, and codes never enter URLs, analytics, logs,
localStorage, or IndexedDB.

## Rack Behavior

After pairing, a Rack authenticates automatically and the backend resolves its
current TrainingGroup. The Rack may receive only:

- Athletes in the assigned TrainingGroup.
- Workouts/programs assigned to that TrainingGroup.
- Sessions in which that TrainingGroup participates.
- Progress, sets, and VBT results within that scoped roster/session.
- Runtime and sensor state belonging to its own endpoint.

The Rack does not ask the coach to select an organization or team each day.

## Dashboard Behavior

After pairing, a Dashboard authenticates automatically and receives only the
approved aggregate/read model for its assigned TrainingGroup. It never defaults to
a global leaderboard or anonymous global room state.

Dashboard identity is independent from Rack identity. Both use the same pairing
architecture but different endpoint kinds and API permissions.

## Rack and VBT Sensor Separation

The Rack identifies the lifting station and browser. The VBT device identifies the
currently connected local sensor:

```text
TrainingGroup
  -> Rack endpoint
     -> Rack browser/laptop
     -> currently connected VBT sensor
```

Replacing a sensor must not recreate or re-pair the Rack endpoint.

## Coach Management

An authorized team settings page eventually lists registered Racks and Dashboards,
last-seen/online state, and actions to:

- Pair and name an endpoint.
- Rename it.
- Reassign it where permissions allow.
- Unpair it.
- Revoke or replace its credential.

Organization owners may manage every team in the organization. Other coaches may
manage only teams linked through their team membership/coach role.

## Required Backend Scoping

All list, detail, association, write, report, analytics, leaderboard, and live-state
queries derive organization/team scope from the authenticated coach membership or
endpoint credential. Cross-team object IDs return `404` and create no writes.

The following cannot remain global in the cloud profile:

- Active-session resolution.
- Room state and leaderboard snapshots.
- Rack number uniqueness.
- Athlete, workout, set, rep, report, and analytics queries.
- Rack/controller identity based only on browser-provided `device_id`.

Private-AP compatibility routes may remain during migration, but Nginx must not
expose them publicly.

## Data Model Direction

The exact migration requires a reviewed ADR, but the intended roots are:

```text
Organization
OrganizationMembership
TrainingGroup (existing Team model, organization-owned)
TrainingGroupCoach (organization membership + enforced role)
Athlete (organization-owned, existing TrainingGroup M2M retained)
BrowserEndpoint (rack/dashboard, organization + current TrainingGroup)
EndpointCredential (digest-only, versioned, revocable)
EndpointPairing (short-lived code/bootstrap state)
```

`RackScreen` remains a transition adapter and may link to `BrowserEndpoint`.
`RackRuntime`, `Node`, check-ins, and historical sets gain endpoint relationships in
later migrations. `Node` remains sensor identity. `HostedGym` and `EdgeGateway`
remain separate gateway concepts.

## Persistent Registration Requirements

- Reboot and normal browser restart do not unpair an endpoint.
- Team assignment lives authoritatively in PostgreSQL.
- The endpoint presents a strong revocable credential automatically.
- A coach can revoke a lost/replaced endpoint from team settings.
- Pairing codes are temporary onboarding aids, never daily credentials.
- Clearing the browser profile requires re-provisioning the browser credential.
- A replacement browser may attach to the existing physical endpoint through a
  coach-mediated flow, preserving endpoint history.

## North-Star Principle

> A physical screen should know what it is, the cloud should know which team it
> belongs to, and the user should never have to manually filter out another team's
> information.

## Instruction for Coding Agents

Treat Rack and Dashboard registration as a first-class architecture concept.
Preserve endpoint identity, team assignment, and VBT sensor identity as separate
objects. Use temporary human pairing codes and persistent strong credentials.
Enforce team authorization in Django. Preserve multi-team coaches, multi-coach
teams, endpoint reassignment, independent sensor replacement, and incremental
migration from the local/Pi profile.
