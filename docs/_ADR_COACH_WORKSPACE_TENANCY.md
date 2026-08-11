# ADR: Public Coach Registration Requires Organization Tenancy

- Date: 2026-08-10
- Status: Accepted; additive ownership foundation implemented in migration `0023`
- Related spec: `docs/_WEB_BLUETOOTH_AND_COACH_ONBOARDING_SPEC.md`
- Related endpoint vision: `docs/_RACK_DASHBOARD_TEAM_REGISTRATION.md`

## Context

SimpleJWT authenticates active users. Before the active-staff fence, coach routes
checked only authentication, while athlete, training, session, report, analytics,
and rack data lacked tenant scope. Those unscoped routes now require active staff;
public registration remains disabled until object queries enforce organization and
team boundaries.

`HostedGym` cannot serve as the account tenant without a migration. It currently
represents the diagnostics gateway's physical deployment, and startup/ingestion
intentionally requires exactly one row. Creating one `HostedGym` per coach would
break the live diagnostics profile.

## Decision

Introduce an account-level `Organization` and `OrganizationMembership`. A public
registration creates one organization and one owner membership. Physical
`HostedGym` rows may belong to an organization in a later gateway migration, but
the two concepts remain separate in the onboarding slice.

Use the existing `TrainingGroup` as the Team model. Add organization ownership to
it rather than creating a parallel `Team` table. Retain
`Athlete.training_groups` as many-to-many because athletes may train with several
groups. Evolve `TrainingGroupCoach` from a descriptive link into the enforced
coach/team authorization relationship. One coach may manage several groups and
several coaches may manage one group; never assume `Coach == Team`.

The first slice permits exactly one active membership per user. A database
constraint enforces that invariant without depending on fields in the user table.
Missing, inactive, or ambiguous
membership resolution returns `403`; request code does not choose an arbitrary
membership. Membership role and organization never come from registration or
domain-object request bodies.

Migration `0023` adds nullable ownership to the five current aggregate roots:
`Athlete`, `TrainingGroup`, `TrainingBlock`, `TrainingSession`, and `DailyReport`.
Authorization moves incrementally: teams and athletes first, then programming,
sessions/sets, reports/analytics, and finally Rack/Dashboard endpoints. Derive
organization scope from the authenticated membership and group scope from an
enforced group role. Return `404` for another organization or unauthorized group's
object IDs.

Self-registered coaches are active but not staff. Until an endpoint is tenant-
scoped, require `IsActiveStaff`. This includes Wi-Fi, BLE enrollment, rack
assignment, gateway diagnostics, imports, unscoped planning, sessions, reports,
analytics, and hardware control.

Before registration issues a JWT, inventory every route and method in
`event_handler/urls.py`. Authenticated endpoints default to `IsActiveStaff` until
their list querysets, detail lookups, related-object validation, writes, reports,
and analytics are organization-scoped. Client-side hiding is never authorization.
Private-AP `AllowAny` routes stay blocked by the VPS Nginx allowlist.

The cloud authentication contract uses a short-lived access token held in memory.
Refresh credentials use a host-only cookie with `HttpOnly`, `Secure`,
`SameSite=Strict`, and `Path=/api/auth/`, with CSRF protection for refresh and
logout. Tokens never enter browser persistence, URLs, analytics, or logs. Existing
localStorage JWT handling must be replaced before public registration is enabled.

## Model Contract

- `Organization`: UUID primary key, bounded display name, created timestamp.
- `OrganizationMembership`: organization, user, `owner` role, active flag, and
  created timestamp.
- `TrainingGroup`: existing Team model with non-null organization ownership and a
  name unique within that organization.
- `TrainingGroupCoach`: links an organization membership to a TrainingGroup with
  head/assistant role and becomes an authorization boundary.
- `Athlete`: organization-owned while retaining the existing many-to-many
  TrainingGroup membership.
- One active membership per user in the first slice.
- At least one active owner must remain for every active organization. Membership
  changes lock the organization row and enforce this in the only supported service;
  direct model deletion and bulk updates are not supported operator paths.
- Membership and organization deletion are operator-only and use protective
  foreign keys while owned domain rows exist.
- Every related object ID is resolved inside the active organization and inside
  the write transaction. Global existence is never checked before tenant scope.

## First Safe Vertical Slice

1. Inventory every URL/method as tenant-scoped, active-staff-only, private-AP-only,
   or public authentication.
2. Default every authenticated but unscoped endpoint to `IsActiveStaff`, including
   reads and writes. Keep private-AP open routes out of public ingress. The
   active-staff fence and route matrix implement this step.
3. Add organization and owner-membership schema with the one-active-membership
   invariant. Migration `0023` implements this schema foundation.
4. Add nullable organization ownership to `Athlete`, `TrainingGroup`,
   `TrainingBlock`, `TrainingSession`, and `DailyReport`. Migration `0023`
   backfills these existing roots together so later slices do not repeat table
   locks and legacy-row classification. Ownership stays nullable until all create
   paths derive it from authenticated membership. Cross-root organization
   consistency is not enforced or trusted in this transitional state.
5. Tenant-scope team and athlete list, create, detail, update, memberships,
   associations, reports, and analytics needed by the limited onboarding surface.
   Athlete and TrainingGroup roots and associations are now organization-scoped;
   reusable TrainingBlock roots and nested editing are also organization-scoped.
   Program deployment and promotion remain staff-only but also enforce active
   organization scope so they cannot bypass the TrainingBlock boundary. Other
   program operations, sessions, reports, and analytics remain active-staff-only
   pending their own slices. CSV preview and commit remain staff-only and now
   scope athletes, groups, blocks, programs, corrections, and writes to the
   active organization because imports otherwise bypass the scoped APIs.
6. Replace browser-persisted JWT handling with the access/refresh contract above.
7. Add transactional `POST /api/auth/register/`, authenticated `GET /api/auth/me/`,
   refresh, and logout with throttling and CSRF tests.
8. Give non-staff coaches a limited athlete onboarding surface. Client hiding
   follows server authorization and does not replace it.
9. Remove demo credentials from client defaults.
10. Enable Nginx registration routes only after route-matrix, tenant-escape, QA,
    and security tests pass.

## Migration and Rollback

The migration first adds nullable ownership and does not delete or reassign domain
rows. It creates the deterministic `Legacy Edge Athlete` organization and verifies
each ownership update count. Every active staff account receives a legacy owner
membership because active staff already have global prototype administration;
inactive staff and non-staff users receive none. This grant applies only to the
closed pre-registration user set. Existing `TrainingGroupCoach`, athlete/group,
and session/athlete links remain unchanged.

Rollback is allowed before public registration by removing the new foreign key and
organization tables after exporting membership mappings. After public registration
creates tenant-owned data, rollback requires a reviewed data export or migration;
dropping ownership columns would merge tenants and is forbidden.

Migration `0023` uses a no-op data reverse because reversing its schema drops the
new ownership columns and organization tables. Before registration, operators must
export membership mappings before rollback. After registration, reversing `0023`
is forbidden because it would discard tenant boundaries.

Migration `0024` changes NFC uniqueness from global to organization-local. Its
schema can reverse only while no NFC tag value is reused across organizations.
After such reuse, rollback requires reconciling duplicate values before restoring
the former global unique constraint.

Before reversing `0024`, detect reused values with:

```sql
SELECT nfc_tag_id, COUNT(*)
FROM event_handler_athlete
WHERE nfc_tag_id IS NOT NULL
GROUP BY nfc_tag_id
HAVING COUNT(*) > 1;
```

Every returned value must be cleared or reassigned until the query returns no rows.

Before applying `0024`, both queries must return no rows:

```sql
SELECT organization_id, name, COUNT(*)
FROM event_handler_traininggroup
GROUP BY organization_id, name
HAVING COUNT(*) > 1;

SELECT training_group_id, COUNT(*)
FROM event_handler_traininggroupcoach
WHERE role = 'head'
GROUP BY training_group_id
HAVING COUNT(*) > 1;
```

Rename duplicate teams inside their organization and demote extra heads to
`assistant` before migration. Migration `0024` repeats these checks and aborts
before adding constraints if either conflict remains.

Before deploying this TrainingBlock slice, this audit must also return no rows:

```sql
SELECT p.id, g.organization_id AS group_organization_id,
       b.organization_id AS block_organization_id
FROM event_handler_trainingprogram p
JOIN event_handler_traininggroup g ON g.id = p.training_group_id
JOIN event_handler_trainingblock b ON b.id = p.training_block_id
WHERE g.organization_id IS DISTINCT FROM b.organization_id;
```

Catalog and promotion queries quarantine a mismatched row even if this operational
audit is skipped. New deployments reject mismatched block/group ownership in both
the HTTP lookup and planning service.

The numeric hardening audit must also return no rows before deployment:

```sql
SELECT id FROM event_handler_trainingblockexercise
WHERE target_percent::text IN ('NaN', 'Infinity', '-Infinity')
   OR target_percent < 1 OR target_percent > 150
   OR velocity_zone_min::text IN ('NaN', 'Infinity', '-Infinity')
   OR velocity_zone_max::text IN ('NaN', 'Infinity', '-Infinity')
   OR velocity_zone_min < 0 OR velocity_zone_min > 10
   OR velocity_zone_max < 0 OR velocity_zone_max > 10
   OR (velocity_zone_min IS NULL) <> (velocity_zone_max IS NULL)
   OR velocity_zone_min > velocity_zone_max;

SELECT id FROM event_handler_trainingblock
WHERE duration_weeks IS NOT NULL
  AND (duration_weeks < 1 OR duration_weeks > 520);
```

Quarantine and correct any returned block before making it deployable. Do not
silently clamp historical prescriptions.

## Foundation Evidence

- `python manage.py makemigrations --check --dry-run`: no changes detected.
- `python manage.py check`: no issues.
- `python manage.py test event_handler.tests.TrainingGroupCoachMigrationTests event_handler.tests.NodeAssignmentMigrationTests event_handler.tests.NodeAcquisitionMigrationTests event_handler.tests.GatewayFoundationMigrationTests event_handler.tests.PublicCoachRegistrationDisabledTests event_handler.tests.OrganizationTenancyMigrationTests`: 9 tests passed against PostgreSQL.
- `python manage.py test event_handler`: 435 tests passed.
- `POST /api/auth/register/` remains absent. Public Nginx permits only
  `/api/auth/login/` and `/api/auth/refresh/` under the authentication prefix.

## Authorization Fence Evidence

- `python manage.py test event_handler.tests.ApiAuthorizationFenceTests event_handler.tests.EnsureDemoCoachCommandTests event_handler.tests.PublicCoachRegistrationDisabledTests`: 10 tests passed.
- `python manage.py test event_handler`: 444 tests passed.
- `python manage.py check`: no issues.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- [`_API_AUTHORIZATION_MATRIX.md`](_API_AUTHORIZATION_MATRIX.md) classifies every
  event-handler route and records public VPS exposure.
- `python3 scripts/vps/check_api_allowlist.py`: passed.
- `python3 -m unittest scripts/vps/test_check_api_allowlist.py`: 2 tests passed,
  including rejection of a proxied `/api/` fallback.

## Athlete And Team Scope Evidence

- `python manage.py test event_handler.tests.OrganizationScopedAthleteGroupTests event_handler.tests.ApiAuthorizationFenceTests event_handler.tests.EnsureDemoCoachCommandTests event_handler.tests.TrainingGroupStaffTests event_handler.tests.AthleteNotesTests`: 36 tests passed.
- `python manage.py test event_handler`: 459 tests passed.
- `python manage.py check`: no issues.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- Cross-tenant athlete, group, association, and coach IDs return `404` and create
  no writes. Organization IDs are not accepted in Athlete or TrainingGroup input.
- `npm test -- --run`: 169 tests passed.
- `npm run build`: passed; the existing main-bundle size warning remains.
- Headless Chrome rendered `/connection-test` at `1440x1000` and `390x844`.
  The open-endpoint card omitted `/api/athletes/`; the rendered DOM placed both
  athlete references under the `organization` badge and the authenticated checks.
  Backend tenant tests supplied the authenticated response evidence.

## TrainingBlock Scope Evidence

### Acceptance Criteria

1. Every TrainingBlock route and supported method requires active staff plus one
   unambiguous active organization membership. Non-staff, missing, inactive, or
   unresolved membership returns `403` before domain validation or writes.
2. Catalog reads include only the active organization's blocks. Creates derive
   organization from membership and reject organization fields in input.
3. Every foreign block, workout, and prescription-row identifier returns `404`
   for every supported read and write method without changing the foreign row.
4. Nested workout creation validates the complete payload before writing and
   appends after the current maximum position when position is omitted.
5. Whole-list reorders lock the parent and child rows, reject partial or foreign
   identifier lists, and avoid unique-position collisions without a fixed offset.
6. Program promotion derives the new block's organization from the source
   program's TrainingGroup rather than client input. Program catalog, deployment,
   and promotion also require active staff and scope all roots to the resolved
   organization.
7. Resetting the legacy demo seed does not delete, close, or rewrite matching
   rows owned by another organization.
8. CSV preview and commit require active staff plus active organization scope.
   Foreign targets return `404`, corrections cannot name foreign athletes, and
   commit locks the target before appending.
9. Prescription numbers reject non-finite or out-of-domain values. Duration is
   capped at 520 weeks in both HTTP validation and schedule generation.

- `python manage.py test event_handler.tests.OrganizationScopedTrainingBlockTests event_handler.tests.SeedActiveSessionTenantIsolationTests event_handler.tests.PlanningEndpointTests event_handler.tests.TemplateEditingTests event_handler.tests.TrainingBlockSnapshotConcurrencyTests event_handler.tests.BlockCatalogLensTests event_handler.tests.BlockCategoryTests event_handler.tests.ProgramPromotionTests event_handler.tests.ScheduleGenerationTests event_handler.tests.CadenceValidationTests event_handler.tests.CsvImportTests event_handler.tests.ApiAuthorizationFenceTests`: 151 tests passed.
- `python manage.py test event_handler`: 487 tests passed.
- `python manage.py check`: no issues.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- `git diff --check`: passed.
- Independent QA, security, and harness reviews: passed after cross-tenant import,
  malformed correction, numeric-domain, snapshot-lock, and seed-isolation fixes.
- Cross-tenant block, workout, and prescription-row paths return `404`. Nested
  payloads validate before writes, ordering locks roots and children in a stable
  order, and promoted blocks inherit ownership from the source program's
  TrainingGroup. Program deployment and promotion cannot bridge organizations.

## Authorization Test Matrix

- Anonymous, self-registered non-staff, inactive member, staff, and gateway bearer.
- Every public URL and supported method.
- Zero, inactive, and conflicting membership states fail `403`.
- Cross-tenant list, detail, update, association, report, and analytics IDs return
  `404` and create no write.
- Private-AP routes return `404` at public Nginx regardless of JWT presence.
- Registration rollback, password hashing, throttling, refresh-cookie flags, CSRF,
  logout revocation, and absence of browser token persistence.

## Consequences

- Public signup cannot be a frontend-only change.
- Existing prototype data needs an explicit legacy organization.
- Some current cross-coach tests describe behavior that must be replaced as each
  domain becomes tenant-scoped.
- Staff retain the current local/Pi administration path during migration.
- Full cloud coach functionality arrives through multiple tested vertical slices,
  not a global ownership rewrite.
