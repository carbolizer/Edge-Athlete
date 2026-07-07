"""
urls.py — App Level URL Router
--------------------------------
This is the second level of URL routing, specific to the event_handler app.
Requests reach here after basestation_config/urls.py forwards anything
starting with /api/ to this file.

What it does:
  Maps specific URL paths to specific view functions in views.py.

Works with:
  - basestation_config/urls.py — forwards /api/ requests here
  - event_handler/views.py — contains the functions called here

Full URL paths from the browser or ESP32:
  POST http://localhost/api/motion/ -> motion_detected()
  GET  http://localhost/api/events/ -> get_events()
"""
from django.urls import path
from . import views

urlpatterns = [
    # Receives motion events from ESP32 nodes via POST
    path('motion/', views.motion_detected, name='motion_detected'),

    # Returns event history to the React dashboard via GET
    path('events/', views.get_events, name='get_events'),

    # Lists sensors and lets the dashboard manually add one
    path('devices/', views.get_devices, name='get_devices'),

    # Removes a sensor from the active dashboard list
    path('devices/<str:node_id>/', views.device_detail, name='device_detail'),
]

