"""
urls.py — App-level URL routes for the event_handler app.

Requests starting with /api/ are forwarded here from basestation_config/urls.py.
Phase 4 stubs so far — the rack-screen register/poll endpoints (real) and the
set-complete write (stub). The rest of the REST API lands as Phase 4 continues.
See SPEC.md → "REST API" and MESSAGE_CONTRACT.md.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('racks/register/', views.rack_register, name='rack_register'),
    path('racks/racknumber/', views.rack_racknumber, name='rack_racknumber'),
    path('sets/<int:set_id>/complete/', views.set_complete, name='set_complete'),
]
