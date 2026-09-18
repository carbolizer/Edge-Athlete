"""
admin.py — Django Admin Panel Registration
-------------------------------------------
Django's built-in admin at /admin/ lets you view, add, edit, and delete
database records through a browser UI — no SQL needed. This file registers the
seven Edge Athlete models so each shows up there, which is how you'll eyeball
data (nodes checking in, sets, reps) while building.

Access needs a superuser: python manage.py createsuperuser
"""
from django.contrib import admin

from .models import Node, RackScreen, Athlete, TrainingSession, Set, Rep

# Registering each model makes it visible and editable in the admin panel.
admin.site.register(Node)
admin.site.register(RackScreen)
admin.site.register(Athlete)
admin.site.register(TrainingSession)
admin.site.register(Set)
admin.site.register(Rep)

# Installation identity is provisioned once. Account membership is managed here
# for recovery, or through the staff-only coach management API.
from .models import School, WeightRoom, CoachProfile
admin.site.register(School)
admin.site.register(WeightRoom)
admin.site.register(CoachProfile)
