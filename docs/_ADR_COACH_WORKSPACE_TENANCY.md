# ADR: Public Coach Registration Requires Organization Tenancy

- Date: 2026-08-10
- Status: Accepted design direction; implementation pending
- Related spec: `docs/_WEB_BLUETOOTH_AND_COACH_ONBOARDING_SPEC.md`

## Context

SimpleJWT currently authenticates any active user, `IsCoach` checks only that the
user is authenticated, and most athlete, training, session, report, analytics, and
rack data has no tenant owner. Publicly creating users against those APIs would
allow one coach to read or mutate another coach's data.

`HostedGym` cannot serve as the account tenant without a migration. It currently
represents the diagnostics gateway's physical deployment, and startup/ingestion
intentionally requires exactly one row. Creating one `HostedGym` per coach would
break the live diagnostics profile.

## Decision

Introduce an account-level `Organization` and `OrganizationMembership`. A public
registration creates one organization and one owner membership. Physical
`HostedGym` rows may belong to an organization in a later gateway migration, but
the two concepts remain separate in the onboarding slice.

The first slice permits exactly one active membership per user. A database
constraint enforces that invariant without depending on fields in the user table.
Missing, inactive, or ambiguous
membership resolution returns `403`; request code does not choose an arbitrary
membership. Membership role and organization never come from registration or
domain-object request bodies.

Add organization ownership to domain roots incrementally. Start with `Athlete`,
then groups/programming, sessions/sets, reports/analytics, and finally racks and
devices. Derive scope from the authenticated membership. Return `404` for another
organization's object IDs.

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
   reads and writes. Keep private-AP open routes out of public ingress.
3. Add organization and membership schema with the one-active-membership invariant.
4. Add nullable `Athlete.organization`; create a legacy organization and explicit
   staff memberships; backfill athletes; verify counts; then make it non-null.
5. Tenant-scope athlete list, create, detail, update, associations, reports, and
   analytics needed by the limited onboarding surface.
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
rows. It creates one operator-named legacy organization, records pre/post athlete
counts, and assigns only explicitly selected staff memberships. Ambiguous users are
reported for operator mapping rather than granted access.

Rollback is allowed before public registration by removing the new foreign key and
organization tables after exporting membership mappings. After public registration
creates tenant-owned data, rollback requires a reviewed data export or migration;
dropping ownership columns would merge tenants and is forbidden.

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
