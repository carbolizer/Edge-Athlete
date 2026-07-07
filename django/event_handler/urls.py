"""
urls.py — the address book: which web address goes to which handler in views.py.

Requests starting with /api/ are forwarded here from basestation_config/urls.py.
So far: a tablet registers and asks for its rack number, starts a set, and
finishes a set. The rest of the REST API lands as Phase 4 continues.
See SPEC.md -> "REST API" and MESSAGE_CONTRACT.md.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('racks/register/', views.rack_register, name='rack_register'),
    path('racks/racknumber/', views.rack_racknumber, name='rack_racknumber'),
    path('sets/', views.set_create, name='set_create'),
    path('sets/<int:set_id>/complete/', views.set_complete, name='set_complete'),
]
