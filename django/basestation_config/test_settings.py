"""Local PostgreSQL tests without a running MQTT broker; never use for serving."""
import os
from unittest.mock import patch

os.environ.setdefault('SECRET_KEY', 'django-insecure-fallback-for-local-development-only')
from .settings import *  # noqa: F403

DATABASES['default'].update(  # noqa: F405
    NAME=os.environ.get('POSTGRES_DB', 'edge_athlete_tests'),
    USER=os.environ.get('POSTGRES_USER', ''),
    HOST=os.environ.get('POSTGRES_HOST', '127.0.0.1'),
    PORT=os.environ.get('POSTGRES_PORT', '5432'),
    TEST={'CHARSET': 'UTF8', 'TEMPLATE': 'template0'},
)
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
# publisher.py connects during import. Tests exercise publishing through mocks,
# while all model operations and migration/locking tests use real PostgreSQL.
patch('paho.mqtt.client.Client.connect', return_value=0).start()
patch('paho.mqtt.client.Client.loop_start', return_value=0).start()
