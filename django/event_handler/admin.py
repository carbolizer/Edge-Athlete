"""
admin.py — Django Admin Panel Registration
-------------------------------------------
Django's built-in admin at /admin/ lets you inspect database records through a
browser UI. Session lifecycle changes must go through the transactional API.

Access needs a superuser: python manage.py createsuperuser
"""
from django.contrib import admin

from .models import Node, RackScreen, RackWorkoutState, Athlete, Program, Session, Set, Rep, MonitoringEvent

@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("id", "label", "started_at", "ended_at", "is_simulated")
    readonly_fields = ("label", "started_at", "ended_at", "athletes", "notes", "is_simulated")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# Other operational models retain their existing editable admin behavior.
admin.site.register(Node)
admin.site.register(RackScreen)
admin.site.register(RackWorkoutState)
admin.site.register(Athlete)
admin.site.register(Program)
admin.site.register(Set)
admin.site.register(Rep)
admin.site.register(MonitoringEvent)
