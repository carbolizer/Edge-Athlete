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
    path('racks/<int:rack_number>/state/', views.rack_workout_state, name='rack_workout_state'),
    path('racks/<int:rack_number>/assignment/', views.rack_catalog_assignment, name='rack_catalog_assignment'),
    path('racks/<int:rack_number>/athlete/', views.rack_athlete_identity, name='rack_athlete_identity'),

    # nodes
    path('nodes/', views.nodes_list, name='nodes_list'),

    # wall and coach dashboards
    path('wall-state/', views.wall_state, name='wall_state'),
    path('room-state/', views.room_state, name='room_state'),

    # athletes
    path('athletes/', views.athletes_view, name='athletes'),
    path('athletes/<int:athlete_id>/', views.athlete_detail, name='athlete_detail'),
    path('athletes/<int:athlete_id>/notes/', views.athlete_notes, name='athlete_notes'),
    path('athletes/<int:athlete_id>/reports/', views.athlete_reports, name='athlete_reports'),
    path('athletes/<int:athlete_id>/reports/<int:report_id>/', views.athlete_report_detail, name='athlete_report_detail'),
    path('athletes/<int:athlete_id>/reports/<int:report_id>/pdf/', views.athlete_report_pdf, name='athlete_report_pdf'),
    path('athletes/<int:athlete_id>/workout-assignment/', views.athlete_workout_assignment, name='athlete_workout_assignment'),
    path('athletes/<int:athlete_id>/workout-exercises/<int:exercise_id>/override/', views.athlete_workout_exercise_override, name='athlete_workout_exercise_override'),

    # training plans
    path('programs/', views.programs_view, name='programs'),

    # reusable workout catalog
    path('workouts/', views.workouts_view, name='workouts'),
    path('workouts/imports/preview/', views.workout_import_preview, name='workout_import_preview'),
    path('workouts/imports/', views.workout_import, name='workout_import'),

    # ordered collections of reusable workouts
    path('workout-programs/', views.workout_programs_view, name='workout_programs'),

    # sessions
    path('sessions/', views.sessions_view, name='sessions'),
    path('sessions/<int:session_id>/', views.session_detail, name='session_detail'),
    path('sessions/<int:session_id>/end/', views.session_end, name='session_end'),

    # immutable daily reports
    path('reports/', views.reports_view, name='reports'),
    path('reports/<int:report_id>/', views.report_detail, name='report_detail'),
    path('reports/<int:report_id>/pdf/', views.report_pdf, name='report_pdf'),

    # sets
    path('sets/', views.set_create, name='set_create'),
    path('sets/<int:set_id>/complete/', views.set_complete, name='set_complete'),
    path('racks/<int:rack_number>/sets/', views.rack_set_create, name='rack_set_create'),
    path('racks/<int:rack_number>/sets/<int:set_id>/complete/', views.rack_set_complete, name='rack_set_complete'),

    # analytics
    path('analytics/session/<int:session_id>/', views.analytics_session, name='analytics_session'),
    path('analytics/athlete/<int:athlete_id>/', views.analytics_athlete, name='analytics_athlete'),

    # catch-alls LAST
    path('racks/<str:device_id>/', views.rack_assign, name='rack_assign'),
    path('nodes/<str:node_id>/', views.node_detail, name='node_detail'),
]
