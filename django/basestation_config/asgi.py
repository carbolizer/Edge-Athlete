"""
asgi.py — Asynchronous Server Gateway Interface
-------------------------------------------------
ASGI is the async version of WSGI. It supports WebSockets and
long lived connections in addition to standard HTTP requests.

What it does:
  Creates an ASGI application object for async capable web servers.
  You will rarely touch this file this sprint.

Works with:
  - basestation_config/settings.py — points to settings module
  - An async web server like Daphne or Uvicorn (future sprint)

Note: Relevant if we ever add real time WebSocket updates to the
React dashboard instead of polling the REST API.
For more information see https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'basestation_config.settings')

application = get_asgi_application()