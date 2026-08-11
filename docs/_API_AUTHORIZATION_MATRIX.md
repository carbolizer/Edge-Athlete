# API Authorization Matrix

- Date: 2026-08-10
- Status: Athlete, TrainingGroup, TrainingBlock, and thin hosted Rack control-plane
  scope implemented; registration remains disabled
- Source of truth: `django/event_handler/urls.py`, view decorators, and `nginx/vps.conf.template`

## Boundaries

`IsActiveStaff` requires an authenticated, active Django user with `is_staff=True`.
No credentials or an invalid JWT returns `401`. An authenticated active non-staff
user returns `403`. SimpleJWT may reject an inactive user's token with `401` before
permission evaluation; an inactive user that reaches the permission check returns
`403`.

`AllowAny` routes below are private-AP compatibility surfaces unless identified as
public health. Controller routes also validate their rack capability. Gateway
ingestion disables JWT authentication and validates its versioned gateway bearer.

The VPS proxies health, gateway ingestion, gateway diagnostics, login, refresh,
and the exact hosted Rack control-plane routes below. Every other `/api/` path,
including similarly prefixed private-AP `/api/racks/...` routes, returns `404` at
public Nginx before Django.

## Public And Special Routes

| Route | Methods | Backend gate | Anonymous / non-staff / staff | VPS ingress |
|---|---|---|---|---|
| `/api/health/` | GET | `AllowAny` | `200` when healthy | Public |
| `/api/auth/login/` | POST | SimpleJWT credentials | Public credential exchange | Public, throttled |
| `/api/auth/refresh/` | POST | SimpleJWT refresh token | Public credential exchange | Public |
| `/api/auth/register/` | POST | No route | `404`; creates no user | `404` |
| `/api/gateway/v1/events/` | POST | Gateway bearer | `401` without valid gateway bearer | Public, throttled |
| `/api/gateways/diagnostics/` | GET | `IsActiveStaff` | `401 / 403 / allowed` | Public, staff JWT |

## Hosted Rack Control Plane

The backend gates below are fixed by
[`_ADR_BROWSER_ENDPOINT_AND_HELPER_IDENTITY.md`](_ADR_BROWSER_ENDPOINT_AND_HELPER_IDENTITY.md)
and [`../_MESSAGE_CONTRACT.md`](../_MESSAGE_CONTRACT.md). VPS ingress uses anchored,
method-fenced allowlist entries; similarly prefixed private-AP routes remain `404`.

| Route | Methods | Backend gate | VPS ingress |
|---|---|---|---|
| `/api/rack/v1/csrf/` | GET | CSRF bootstrap; no endpoint authority | Exact public route |
| `/api/rack/v1/endpoint-pairings/` | POST | CSRF + exact Origin + PostgreSQL throttle | Exact public route |
| `/api/rack/v1/endpoint-pairings/status/` | POST | Bootstrap cookie + CSRF + exact Origin | Exact public route |
| `/api/coach/v1/rack-endpoint-pairings/claim/` | POST | Active-staff coach token + active organization membership + TrainingGroup manage permission + exact Origin | Exact public route |
| `/api/coach/v1/training-groups/` | GET | Active-staff coach token + exactly one active organization membership; returns manageable group IDs/names only | Exact public route |
| `/api/rack/v1/status/` | GET | `ea_rack_endpoint` scoped to its own endpoint | Exact public route |
| `/api/rack/v1/helper-pairings/` | POST | Endpoint cookie + CSRF + exact Origin | Exact public route |
| `/api/rack/v1/helper-pairings/status/` | POST | Endpoint cookie + CSRF + exact Origin; own pairing only | Exact public route |
| `/api/coach/v1/rack-helper-pairings/confirm/` | POST | Active-staff coach token + active organization membership + endpoint/TrainingGroup manage permission + exact Origin | Exact public route |
| `/api/rack-helper/v1/pairings/claim/` | POST | Pairing/bootstrap validation + PostgreSQL throttle | Exact public route |
| `/api/rack-helper/v1/pairings/status/` | POST | Pairing bootstrap capability | Exact public route |
| `/api/rack-helper/v1/pairings/activate/` | POST | Pending `earh1` credential scoped to its provisional installation | Exact public route |
| `/api/rack-helper/v1/status/` | POST | Active `earh1` credential + launch consumed by current boot | Exact public route |
| `/api/rack/v1/helper-launch-intents/` | POST | Endpoint cookie + CSRF + exact Origin | Exact public route |
| `/api/rack/v1/helper-launch-intents/inspect/` | POST | Endpoint cookie + CSRF + exact Origin; own intent only | Exact public route |
| `/api/rack-helper/v1/launch-intents/consume/` | POST | Active `earh1` credential scoped to target installation | Exact public route |

No accepted hosted route uploads derived events, reads a roster, starts or completes
a set, creates a `Rep`, transfers a sensor, releases an acquisition lease, or serves
a helper package. Those capabilities remain absent and public `404`.

## Active-Staff Routes

All routes in this table return `401` without valid authentication, `403` to an
authenticated non-staff user, and reach domain validation for active staff.

| Route | Methods | VPS ingress |
|---|---|---|
| `/api/system/status/` | GET | `404` |
| `/api/system/wifi-password/` | POST | `404` |
| `/api/racks/unassigned/` | GET | `404` |
| `/api/racks/node-assignment/` | PUT | `404` |
| `/api/ble/scans/` | POST | `404` |
| `/api/ble/verifications/` | POST | `404` |
| `/api/racks/<rack_number>/ble-selection/` | PUT | `404` |
| `/api/nodes/<node_id>/acquisition-kind/` | PUT | `404` |
| `/api/racks/<device_id>/` | PATCH | `404` |
| `/api/sessions/` | POST | `404` |
| `/api/sessions/<session_id>/` | PATCH | `404` |
| `/api/block-categories/` | GET, POST | `404` |
| `/api/sessions/<session_id>/participation/` | GET, POST, DELETE | `404` |
| `/api/sessions/<session_id>/start/` | POST | `404` |
| `/api/scheduled-sessions/` | GET | `404` |
| `/api/scheduled-sessions/<slot_id>/` | GET, PATCH | `404` |
| `/api/scheduled-sessions/<slot_id>/session/` | POST | `404` |
| `/api/athletes/<athlete_id>/program/` | GET, PUT, DELETE | `404` |
| `/api/athletes/<athlete_id>/program-exercises/<exercise_id>/override/` | GET, PUT, DELETE | `404` |
| `/api/reports/` | GET | `404` |
| `/api/reports/<report_id>/` | GET | `404` |
| `/api/reports/<report_id>/pdf/` | GET | `404` |
| `/api/reference-maxes/` | POST | `404` |
| `/api/analytics/session/<session_id>/` | GET | `404` |
| `/api/analytics/athlete/<athlete_id>/` | GET | `404` |

## Organization-Scoped Routes

These routes require exactly one active organization membership. Anonymous or
invalid authentication returns `401`; zero or multiple active memberships return
`403`. Lists, roots, and related IDs resolve only inside that organization, and a
cross-tenant ID returns `404`.

| Route | Methods | VPS ingress |
|---|---|---|
| `/api/athletes/` | GET, POST | `404` |
| `/api/athletes/<athlete_id>/` | GET, PATCH | `404` |
| `/api/training-groups/` | GET, POST | `404` |
| `/api/training-groups/<group_id>/athletes/` | GET, POST, DELETE | `404` |
| `/api/training-groups/<group_id>/coaches/` | GET, POST, PATCH, DELETE | `404` |

Organization comes only from the authenticated membership and is absent from
request/response fields. NFC tag IDs are unique within one organization.

## Active-Staff And Organization-Scoped Routes

These programming and import operations remain unavailable to non-staff coaches.
Active staff must also have exactly one active organization membership. Program,
group, block, athlete, and correction IDs resolve only inside that organization;
foreign IDs return `404`. Reusable blocks are shared by staff coaches inside the
organization; `coach=` remains an author filter, not a team permission.

| Route | Methods | VPS ingress |
|---|---|---|
| `/api/training-programs/` | GET, POST | `404` |
| `/api/training-programs/<program_id>/promote/` | POST | `404` |
| `/api/training-blocks/` | GET, POST | `404` |
| `/api/training-blocks/<block_id>/` | GET, PATCH | `404` |
| `/api/training-blocks/<block_id>/workouts/` | GET, POST | `404` |
| `/api/training-blocks/<block_id>/workout-order/` | PUT | `404` |
| `/api/training-blocks/<block_id>/workouts/<workout_id>/` | PATCH, DELETE | `404` |
| `/api/training-blocks/<block_id>/workouts/<workout_id>/exercise-order/` | PUT | `404` |
| `/api/training-blocks/<block_id>/workouts/<workout_id>/exercises/<exercise_id>/` | PATCH, DELETE | `404` |
| `/api/imports/preview/` | POST | `404` |
| `/api/imports/` | POST | `404` |

## Mixed Routes

| Route | Methods | Backend behavior | VPS ingress |
|---|---|---|---|
| `/api/room-state/` | GET | `AllowAny`; wall snapshot without IDs or roster | `404` |
| `/api/room-state/?details=true` | GET | `401` anonymous/inactive JWT, `403` active non-staff or force-auth inactive, active staff allowed | `404` |

## Private-AP Compatibility Routes

| Route | Methods | Additional application check | VPS ingress |
|---|---|---|---|
| `/api/racks/register/` | POST | Rack registration validation | `404` |
| `/api/racks/racknumber/` | GET | Device ID lookup | `404` |
| `/api/racks/<rack_number>/sensor-health/` | GET | Assigned screen identity | `404` |
| `/api/racks/<rack_number>/state/` | GET | None | `404` |
| `/api/racks/<rack_number>/state/` | PATCH | Controller capability | `404` |
| `/api/racks/<rack_number>/controller/acquire/` | POST | Assigned screen, sensor, 256-bit token | `404` |
| `/api/racks/<rack_number>/controller/heartbeat/` | POST | Controller capability | `404` |
| `/api/racks/<rack_number>/controller/release/` | POST | Controller capability and revision | `404` |
| `/api/racks/<rack_number>/checkin/` | POST | Controller capability and revision | `404` |
| `/api/racks/<rack_number>/checkins/` | GET | None | `404` |
| `/api/racks/<rack_number>/nfc-tap/` | POST | Controller capability | `404` |
| `/api/nodes/` | GET | None | `404` |
| `/api/exercises/` | GET | None | `404` |
| `/api/prescriptions/` | GET | None | `404` |
| `/api/prescriptions/` | POST | Retired endpoint; always `410` | `404` |
| `/api/sessions/active/` | GET | None | `404` |
| `/api/sessions/active/athlete/<athlete_id>/progress/` | GET | None | `404` |
| `/api/sessions/active/status/` | GET | None | `404` |
| `/api/sets/` | POST | Controller capability for assigned sensor-backed sets | `404` |
| `/api/sets/<set_id>/complete/` | POST | Controller capability for assigned sensor-backed sets | `404` |

## Enforcement Tests

`ApiAuthorizationFenceTests` compares every `event_handler.urls` route name and
method with the classifications above and checks each callback's permission class.
A new route or method fails the suite until classified. Runtime tests cover both
mixed routes, real inactive JWT behavior, and the top-level login/refresh methods.
`scripts/vps/check_api_allowlist.py` fails when public Nginx gains an unreviewed API
location, widens the `/api/` deny fallback, or loses the admin denial.

Validation command:

```bash
docker compose -p edgeathlete-main run --rm --no-deps django \
  python manage.py test event_handler.tests.ApiAuthorizationFenceTests \
  event_handler.tests.EnsureDemoCoachCommandTests \
  event_handler.tests.PublicCoachRegistrationDisabledTests
python3 scripts/vps/check_api_allowlist.py
python3 -m unittest scripts/vps/test_check_api_allowlist.py
```
