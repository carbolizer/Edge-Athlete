"""
admin.py — Django Admin Panel Registration
-------------------------------------------
Django provides a built in admin panel at /admin/ that lets you
view, add, edit, and delete database records through a browser UI.

What it does:
  Registers the MotionEvent model so it appears in the admin panel.
  This lets you manually inspect motion events in the database
  without writing any SQL or using a database tool.

Works with:
  - event_handler/models.py — MotionEvent model being registered
  - Django admin panel — accessible at http://localhost/admin/
  - PostgreSQL — admin panel reads and writes directly to the database

Note: To access the admin panel you need a superuser account.
Create one with: python manage.py createsuperuser
"""
from django.contrib import admin
from .models import MotionEvent, Device

# Registering these models makes them visible and manageable in the admin panel
admin.site.register(Device)
admin.site.register(MotionEvent)