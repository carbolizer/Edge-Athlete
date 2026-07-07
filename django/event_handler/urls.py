"""
urls.py — App-level URL routes for the event_handler app.

Requests starting with /api/ are forwarded here from basestation_config/urls.py.
Emptied at Phase 2 (the old motion/device routes are gone). The Edge Athlete
endpoints get wired up in Phase 4 — see SPEC.md → "REST API".
"""
from django.urls import path  # noqa: F401 — used once Phase 4 adds routes

urlpatterns = []
