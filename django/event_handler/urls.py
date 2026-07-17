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

    # nodes
    path('nodes/', views.nodes_list, name='nodes_list'),

    # athletes
    path('athletes/', views.athletes_view, name='athletes'),
    path('athletes/<int:athlete_id>/', views.athlete_detail, name='athlete_detail'),

    # training plans
    path('programs/', views.programs_view, name='programs'),

    # sessions
    path('sessions/', views.sessions_view, name='sessions'),
    path('sessions/active/', views.sessions_active, name='sessions_active'),
    path('sessions/<int:session_id>/', views.session_detail, name='session_detail'),

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
