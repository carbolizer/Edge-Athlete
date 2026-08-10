# API Authorization Matrix

- Date: 2026-08-10
- Status: Athlete/TrainingGroup tenant scope implemented; registration remains disabled
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

The VPS proxies only health, gateway ingestion, gateway diagnostics, login, and
refresh. Every other `/api/` path returns `404` at public Nginx before Django.

## Public And Special Routes

| Route | Methods | Backend gate | Anonymous / non-staff / staff | VPS ingress |
|---|---|---|---|---|
| `/api/health/` | GET | `AllowAny` | `200` when healthy | Public |
| `/api/auth/login/` | POST | SimpleJWT credentials | Public credential exchange | Public, throttled |
| `/api/auth/refresh/` | POST | SimpleJWT refresh token | Public credential exchange | Public |
| `/api/auth/register/` | POST | No route | `404`; creates no user | `404` |
| `/api/gateway/v1/events/` | POST | Gateway bearer | `401` without valid gateway bearer | Public, throttled |
| `/api/gateways/diagnostics/` | GET | `IsActiveStaff` | `401 / 403 / allowed` | Public, staff JWT |

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
| `/api/training-blocks/` | GET, POST | `404` |
| `/api/training-blocks/<block_id>/` | GET, PATCH | `404` |
| `/api/training-blocks/<block_id>/workouts/` | GET, POST | `404` |
| `/api/block-categories/` | GET, POST | `404` |
| `/api/training-blocks/<block_id>/workout-order/` | PUT | `404` |
| `/api/training-blocks/<block_id>/workouts/<workout_id>/` | PATCH, DELETE | `404` |
| `/api/training-blocks/<block_id>/workouts/<workout_id>/exercise-order/` | PUT | `404` |
| `/api/training-blocks/<block_id>/workouts/<workout_id>/exercises/<exercise_id>/` | PATCH, DELETE | `404` |
| `/api/training-programs/` | GET, POST | `404` |
| `/api/training-programs/<program_id>/promote/` | POST | `404` |
| `/api/imports/preview/` | POST | `404` |
| `/api/imports/` | POST | `404` |
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
