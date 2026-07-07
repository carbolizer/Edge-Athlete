"""
wsgi.py — Web Server Gateway Interface
----------------------------------------
WSGI is the standard interface between Django and a traditional web server.
This file is used in production to serve the Django application.

What it does:
  Creates a WSGI application object that a web server like Gunicorn can use
  to serve requests. You will rarely touch this file.

Works with:
  - basestation_config/settings.py — points to settings module
  - A production web server like Gunicorn (future sprint)

Note: In development we use manage.py runserver instead of WSGI.
For more information see https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'basestation_config.settings')

application = get_wsgi_application()