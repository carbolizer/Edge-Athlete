"""
urls.py — the address book: which web address goes to which handler in views.py.

Requests starting with /api/ are forwarded here from basestation_config/urls.py.
This is the full base-station REST list so far: tablets register/poll/start/finish
sets and read training plans; coaches manage athletes, plans, sessions, nodes, and
rack assignments; and there are two analytics summaries. See _SPEC.md -> "REST API".

Note: the catch-all rack route ("racks/<device_id>/") comes LAST on purpose — the
specific routes above it (register, racknumber, unassigned, assignment) must match
first or they'd get swallowed.
"""
from django.urls import path

from . import views
from . import control_plane_views
from . import health
from . import system_status
from . import wifi_config

urlpatterns = [
    # Can this container serve requests and reach the database? Used by the
    # container healthcheck in docker-compose.yml, which is why it is open and
    # why it is first — nothing else should have to be working for it to answer.
    path('health/', health.health, name='health'),

    # Coach-only: still-default credentials the operator should change before a
    # real gym uses this box. Drives the banner on the coach admin page.
    path('system/status/', system_status.system_status, name='system_status'),

    # Coach-only, re-authenticated: change the base station's Wi-Fi password.
    # Only writes intent; a host agent applies it (see wifi_config.py).
    path('system/wifi-password/', wifi_config.change_wifi_password, name='change_wifi_password'),

    path('gateway/v1/events/', views.gateway_events, name='gateway_events'),
    path('gateways/diagnostics/', views.gateway_diagnostics, name='gateway_diagnostics'),

    # Public hosted Rack control plane. These exact paths are distinct from the
    # private-AP /api/racks/... compatibility surface below.
    path('rack/v1/csrf/', control_plane_views.rack_csrf, name='rack_control_csrf'),
    path('rack/v1/endpoint-pairings/', control_plane_views.endpoint_pairing_create,
         name='endpoint_pairing_create'),
    path('rack/v1/endpoint-pairings/status/', control_plane_views.endpoint_pairing_status,
         name='endpoint_pairing_status'),
    path('coach/v1/rack-endpoint-pairings/claim/', control_plane_views.endpoint_pairing_claim,
         name='endpoint_pairing_claim'),
    path('coach/v1/training-groups/', control_plane_views.coach_training_groups,
         name='coach_training_groups'),
    path('rack/v1/status/', control_plane_views.endpoint_status, name='endpoint_status'),
    path('rack/v1/helper-pairings/', control_plane_views.helper_pairing_create,
         name='helper_pairing_create'),
    path('rack/v1/helper-pairings/status/', control_plane_views.endpoint_helper_pairing_status,
         name='endpoint_helper_pairing_status'),
    path('coach/v1/rack-helper-pairings/confirm/', control_plane_views.helper_pairing_confirm,
         name='helper_pairing_confirm'),
    path('rack-helper/v1/pairings/claim/', control_plane_views.helper_pairing_claim,
         name='helper_pairing_claim'),
    path('rack-helper/v1/pairings/status/', control_plane_views.helper_pairing_status,
         name='helper_pairing_status'),
    path('rack-helper/v1/pairings/activate/', control_plane_views.helper_pairing_activate,
         name='helper_pairing_activate'),
    path('rack-helper/v1/status/', control_plane_views.helper_status, name='helper_status'),
    path('rack/v1/helper-launch-intents/', control_plane_views.launch_intent_create,
         name='launch_intent_create'),
    path('rack/v1/helper-launch-intents/inspect/', control_plane_views.launch_intent_inspect,
         name='launch_intent_inspect'),
    path('rack-helper/v1/launch-intents/consume/', control_plane_views.launch_intent_consume,
         name='launch_intent_consume'),

    # tablet: racks
    path('racks/register/', views.rack_register, name='rack_register'),
    path('racks/racknumber/', views.rack_racknumber, name='rack_racknumber'),
    path('racks/unassigned/', views.racks_unassigned, name='racks_unassigned'),
    path('racks/node-assignment/', views.rack_node_assignment, name='rack_node_assignment'),
    path('ble/scans/', views.ble_scans, name='ble_scans'),
    path('ble/verifications/', views.ble_verifications, name='ble_verifications'),
    path('racks/<int:rack_number>/ble-selection/', views.rack_ble_selection,
         name='rack_ble_selection'),
    path('racks/<int:rack_number>/sensor-health/', views.rack_sensor_health,
         name='rack_sensor_health'),
    path('racks/<int:rack_number>/state/', views.rack_state, name='rack_state'),
    path('racks/<int:rack_number>/controller/acquire/', views.rack_controller_acquire,
         name='rack_controller_acquire'),
    path('racks/<int:rack_number>/controller/heartbeat/', views.rack_controller_heartbeat,
         name='rack_controller_heartbeat'),
    path('racks/<int:rack_number>/controller/release/', views.rack_controller_release,
         name='rack_controller_release'),
    path('racks/<int:rack_number>/checkin/', views.rack_checkin, name='rack_checkin'),
    path('racks/<int:rack_number>/checkins/', views.rack_checkins, name='rack_checkins'),
    path('racks/<int:rack_number>/nfc-tap/', views.rack_nfc_tap, name='rack_nfc_tap'),

    # nodes
    path('nodes/', views.nodes_list, name='nodes_list'),
    path('nodes/<str:node_id>/acquisition-kind/', views.node_acquisition_kind,
         name='node_acquisition_kind'),

    # live room picture (derived; no room-state table). ONE route for both the
    # wall display and the coach tablet — `?details=true` switches to the
    # coach-only detail level. Deliberately replaces his separate `wall-state/`
    # (see the merge canon R3) and the per-rack `racks/{n}/state|assignment|
    # athlete` routes, which are dropped with forward rack-assignment (D8).
    path('room-state/', views.room_state, name='room_state'),

    # athletes
    path('athletes/', views.athletes_view, name='athletes'),
    path('athletes/<int:athlete_id>/', views.athlete_detail, name='athlete_detail'),

    # exercise catalog
    path('exercises/', views.exercises_list, name='exercises_list'),

    # training plans
    path('prescriptions/', views.prescriptions_view, name='prescriptions'),

    # sessions
    path('sessions/', views.sessions_view, name='sessions'),
    path('sessions/active/', views.sessions_active, name='sessions_active'),
    path('sessions/active/athlete/<int:athlete_id>/progress/', views.athlete_progress, name='athlete_progress'),
    path('sessions/active/status/', views.session_status, name='session_status'),
    path('sessions/<int:session_id>/', views.session_detail, name='session_detail'),

    # planning — TrainingGroups, reusable templates, and templates deployed for a TrainingGroup.
    # Route names follow what the coach front end already calls: its
    # "workout-programs" are our reusable TrainingBlocks, and its "workouts" are
    # the days inside one. We bend the URLs to the existing client rather than
    # reshaping its code (canon §3.3).
    path('training-groups/', views.training_groups_view, name='training_groups'),
    path('training-groups/<int:group_id>/athletes/', views.training_group_athletes_view,
         name='training_group_athletes'),
    # Who RUNS the group — several staff, not one. Replaced TrainingGroup.coach
    # in P11 so "Sarah and Mike both run Varsity" is expressible.
    path('training-groups/<int:group_id>/coaches/', views.training_group_coaches_view,
         name='training_group_coaches'),
    path('training-blocks/', views.training_blocks_view, name='training_blocks'),
    # The block's OWN fields (name, categories, duration, cadence). GET and PATCH
    # only — nothing in the product deletes a whole block, and that is on purpose.
    path('training-blocks/<int:block_id>/', views.training_block_detail,
         name='training_block_detail'),
    path('training-blocks/<int:block_id>/workouts/', views.training_block_workouts_view,
         name='training_block_workouts'),
    # The label vocabulary the catalog filters by. Shared department-wide, because
    # labels only help if everyone files things under the same words.
    path('block-categories/', views.block_categories_view, name='block_categories'),

    # editing a template (P10). Reordering takes the WHOLE list, never one item —
    # the position columns carry a non-deferrable unique constraint, so a
    # one-at-a-time swap collides with the row already on that number.
    path('training-blocks/<int:block_id>/workout-order/',
         views.training_block_workout_order, name='training_block_workout_order'),
    path('training-blocks/<int:block_id>/workouts/<int:workout_id>/',
         views.training_block_workout_detail, name='training_block_workout_detail'),
    path('training-blocks/<int:block_id>/workouts/<int:workout_id>/exercise-order/',
         views.training_block_exercise_order, name='training_block_exercise_order'),
    path('training-blocks/<int:block_id>/workouts/<int:workout_id>/exercises/<int:exercise_id>/',
         views.training_block_exercise_detail, name='training_block_exercise_detail'),
    path('training-programs/', views.training_programs_view, name='training_programs'),
    # Turn a program back into a reusable template. COPIES its days and rows up
    # into the new block — pointing the FK alone would leave the block empty.
    path('training-programs/<int:program_id>/promote/', views.training_program_promote,
         name='training_program_promote'),

    # spreadsheet import. ONE pair of routes for all three kinds of sheet (roster,
    # max sheet, workout plan) — which one you uploaded is worked out from its
    # column names, so a coach never has to declare it (canon D16). Preview writes
    # nothing; import re-checks and then saves in one all-or-nothing step.
    path('imports/preview/', views.import_preview, name='import_preview'),
    path('imports/', views.import_commit, name='import_commit'),

    # which TrainingGroups are training in a session — this is what makes one session
    # shared between several TrainingGroups on different plans.
    path('sessions/<int:session_id>/participation/', views.session_participation_view,
         name='session_participation'),
    # Starting is its own route, not a PATCH: `PATCH sessions/{id}/` with an empty
    # body already means "END the day now", and start/end are opposites — one
    # call's meaning should not rest on subtle body differences.
    path('sessions/<int:session_id>/start/', views.session_start, name='session_start'),

    # The calendar (P14). Slots are generated when a block is deployed and frozen
    # after that, so there is deliberately no POST to the list route.
    path('scheduled-sessions/', views.scheduled_sessions_view, name='scheduled_sessions'),
    path('scheduled-sessions/<int:slot_id>/', views.scheduled_session_detail,
         name='scheduled_session_detail'),
    path('scheduled-sessions/<int:slot_id>/session/',
         views.scheduled_session_create_session, name='scheduled_session_create_session'),

    # what one athlete is training. Reads as "this athlete's program"; underneath
    # it is TrainingGroup membership, because a plan belongs to a TrainingGroup (D12/D13). Writes
    # say which TrainingGroups they moved.
    path('athletes/<int:athlete_id>/program/', views.athlete_program_view,
         name='athlete_program'),

    # the per-athlete exception to a TrainingGroup's prescription (rare by design).
    path('athletes/<int:athlete_id>/program-exercises/<int:exercise_id>/override/',
         views.athlete_exercise_override_view, name='athlete_exercise_override'),

    # reports — ONE family. "This athlete's reports" is the same list filtered
    # (?athlete={id}), not a parallel athletes/{id}/reports/... set of routes.
    path('reports/', views.reports_view, name='reports'),
    path('reports/<int:report_id>/', views.report_detail_view, name='report_detail'),
    path('reports/<int:report_id>/pdf/', views.report_pdf_view, name='report_pdf'),

    # reference maxes — the prescription lever (% of these = every target weight).
    # Accepts a list so a whole TrainingGroup's testing day goes in with one call.
    path('reference-maxes/', views.reference_maxes_view, name='reference_maxes'),

    # sets
    path('sets/', views.set_create, name='set_create'),
    path('sets/<int:set_id>/complete/', views.set_complete, name='set_complete'),

    # analytics
    path('analytics/session/<int:session_id>/', views.analytics_session, name='analytics_session'),
    path('analytics/athlete/<int:athlete_id>/', views.analytics_athlete, name='analytics_athlete'),

    # catch-alls LAST
    path('racks/<str:device_id>/', views.rack_assign, name='rack_assign'),
]
