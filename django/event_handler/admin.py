"""
admin.py — Django Admin Panel Registration
-------------------------------------------
Django's built-in admin at /admin/ lets you view, add, edit, and delete
database records through a browser UI — no SQL needed. This file registers the
nine Edge Athlete models so each shows up there, which is how you'll eyeball
data (nodes checking in, sets, reps) while building.

Access needs a superuser: python manage.py createsuperuser
"""
from django.contrib import admin

from .models import Node, RackScreen, RackWorkoutState, Athlete, Program, Session, Set, Rep, MonitoringEvent

# Registering each model makes it visible and editable in the admin panel.
admin.site.register(Node)
admin.site.register(RackScreen)
admin.site.register(RackWorkoutState)
admin.site.register(Athlete)
admin.site.register(Program)
admin.site.register(Session)
admin.site.register(Set)
admin.site.register(Rep)
admin.site.register(MonitoringEvent)
