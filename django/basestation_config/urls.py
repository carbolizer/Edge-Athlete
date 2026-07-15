"""
URL configuration for basestation_config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
"""

"""
URL Configuration — Project Level Router
-----------------------------------------
This is the TOP LEVEL url router for the entire Django project.
Every incoming request hits this file first before going anywhere else.

This file does NOT handle requests directly — it reads the URL and
hands the request off to the correct app to handle it.

Think of this file as a switchboard operator:
  - Request comes in
  - This file reads the URL
  - Forwards it to the right app based on the URL prefix

Works with:
  - event_handler/urls.py — handles all /api/ requests
  - Django's built in admin panel — handles all /admin/ requests

URL flow example:
  Browser hits /api/motion/
      ↓
  This file sees /api/ → hands off to event_handler/urls.py
      ↓
  event_handler/urls.py sees /motion/ → calls motion_detected view
"""
from django.contrib import admin
from django.conf import settings
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.throttling import AnonRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    rate = "100/min" if settings.DEBUG else "10/min"


class CoachTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [LoginRateThrottle]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        response["Pragma"] = "no-cache"
        return response


class NoStoreTokenRefreshView(TokenRefreshView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        response["Pragma"] = "no-cache"
        return response


urlpatterns = [
    # Django's built in admin panel — visit /admin/ in browser to manage data
    path('admin/', admin.site.urls),

    # Any URL starting with /api/ gets forwarded to event_handler/urls.py
    # This is where all ESP32 and React dashboard requests are handled
    path('api/', include('event_handler.urls')),

    # React login - POST {username, password} returns {access, refresh} tokens
    path('api/auth/login/', CoachTokenObtainPairView.as_view(), name='token_obtain_pair'),

    # Silent token refresh - POST {refresh} returns a new {access} token
    path('api/auth/refresh/', NoStoreTokenRefreshView.as_view(), name='token_refresh'),
]
