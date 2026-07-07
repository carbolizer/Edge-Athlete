"""
apps.py — App Configuration
-----------------------------
This file registers the event_handler app with Django.
Django reads this automatically when the app is listed in INSTALLED_APPS.

What it does:
  Defines configuration for the event_handler app including the app name
  and the default primary key type for all database models in this app.

Works with:
  - basestation_config/settings.py — INSTALLED_APPS references this app
  - event_handler/models.py — default_auto_field applies to all models here
"""
from django.apps import AppConfig


class EventHandlerConfig(AppConfig):
    # Default primary key type for all models in this app
    # BigAutoField is a 64 bit integer — supports very large numbers of records
    default_auto_field = 'django.db.models.BigAutoField'
    # Must match the folder name exactly
    name = 'event_handler'