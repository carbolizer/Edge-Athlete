"""
urls.py — the address book: which web address goes to which handler in views.py.

Requests starting with /api/ are forwarded here from basestation_config/urls.py.
So far: a tablet registers and asks for its rack number, a coach lists waiting
tablets and assigns racks, and a tablet starts and finishes sets. The rest of the
REST API lands as Phase 4 continues. See SPEC.md -> "REST API".

Note: the "racks/<device_id>/" route is LAST on purpose — it's a catch-all, so the
specific routes (register, racknumber, unassigned) must come before it or they'd
get swallowed.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('racks/register/', views.rack_register, name='rack_register'),
    path('racks/racknumber/', views.rack_racknumber, name='rack_racknumber'),
    path('racks/unassigned/', views.racks_unassigned, name='racks_unassigned'),
    path('programs/', views.programs_list, name='programs_list'),
    path('sets/', views.set_create, name='set_create'),
    path('sets/<int:set_id>/complete/', views.set_complete, name='set_complete'),
    path('racks/<str:device_id>/', views.rack_assign, name='rack_assign'),
]
