"""
urls.py — the address book: which web address goes to which handler in views.py.

Requests starting with /api/ are forwarded here from basestation_config/urls.py.
This is the full base-station REST list so far: tablets register/poll/start/finish
sets and read training plans; coaches manage athletes, plans, sessions, nodes, and
rack assignments; and there are two analytics summaries. See SPEC.md -> "REST API".

Note: the catch-all routes ("racks/<device_id>/", "nodes/<node_id>/") come LAST on
purpose — the specific routes above them (register, racknumber, unassigned, list)
must match first or they'd get swallowed.
"""
from django.urls import path

from . import views

urlpatterns = [
    # tablet: racks
    path('racks/register/', views.rack_register, name='rack_register'),
    path('racks/racknumber/', views.rack_racknumber, name='rack_racknumber'),
    path('racks/unassigned/', views.racks_unassigned, name='racks_unassigned'),
    path('racks/<int:rack_number>/checkin/', views.rack_checkin, name='rack_checkin'),
    path('racks/<int:rack_number>/checkins/', views.rack_checkins, name='rack_checkins'),

    # nodes
    path('nodes/', views.nodes_list, name='nodes_list'),

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
    path('programs/', views.programs_view, name='programs'),

    # sessions
    path('sessions/', views.sessions_view, name='sessions'),
    path('sessions/active/', views.sessions_active, name='sessions_active'),
    path('sessions/active/athlete/<int:athlete_id>/progress/', views.athlete_progress, name='athlete_progress'),
    path('sessions/active/status/', views.session_status, name='session_status'),
    path('sessions/<int:session_id>/', views.session_detail, name='session_detail'),

    # reports — ONE family. "This athlete's reports" is the same list filtered
    # (?athlete={id}), not a parallel athletes/{id}/reports/... set of routes.
    path('reports/', views.reports_view, name='reports'),
    path('reports/<int:report_id>/', views.report_detail_view, name='report_detail'),
    path('reports/<int:report_id>/pdf/', views.report_pdf_view, name='report_pdf'),

    # reference maxes — the prescription lever (% of these = every target weight).
    # Accepts a list so a whole squad's testing day goes in with one call.
    path('reference-maxes/', views.reference_maxes_view, name='reference_maxes'),

    # sets
    path('sets/', views.set_create, name='set_create'),
    path('sets/<int:set_id>/complete/', views.set_complete, name='set_complete'),

    # analytics
    path('analytics/session/<int:session_id>/', views.analytics_session, name='analytics_session'),
    path('analytics/athlete/<int:athlete_id>/', views.analytics_athlete, name='analytics_athlete'),

    # catch-alls LAST
    path('racks/<str:device_id>/', views.rack_assign, name='rack_assign'),
    path('nodes/<str:node_id>/', views.node_detail, name='node_detail'),
]
