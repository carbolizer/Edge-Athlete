"""
settings.py — Master Configuration File
----------------------------------------
This is the single most important file in the Django project.
It controls everything about how Django runs — database, security,
installed apps, middleware, and custom service connections.

All sensitive values are read from environment variables via the .env file.
Nothing secret is ever hardcoded here. This means the same codebase
can run in development and production just by swapping the .env file.

Works with:
  - .env file at the repo root — provides all environment variables
  - docker-compose.yml — passes .env variables into the container
  - basestation_config/urls.py — ROOT_URLCONF points Django to the router
  - postgres container — DATABASES connects Django to PostgreSQL
  - mosquitto container — MQTT settings tell Django where the broker is

For more information on this file, see
https://docs.djangoproject.com/en/5.1/topics/settings/
For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.1/ref/settings/
"""

from pathlib import Path
from datetime import timedelta
import os

from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# BASE_DIR points to the /django folder — the root of the Django project
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
# Read from .env — never hardcode this value
SECRET_KEY = os.environ.get('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
# .env sets DEBUG=True for development, DEBUG=False for production
# The '== True' converts the string from .env into an actual boolean
DEBUG = os.environ.get('DEBUG', 'False') == 'True'
POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD') or ''
BIND_ADDRESS = os.environ.get('EDGEATHLETE_BIND_ADDRESS', '127.0.0.1')
LOOPBACK_BIND = BIND_ADDRESS in {'127.0.0.1', '::1'}
PLACEHOLDER_CREDENTIALS = (
    SECRET_KEY in {None, '', 'change-me-local-only'}
    or POSTGRES_PASSWORD in {'', 'change-me-local-only'}
)
if DEBUG and not LOOPBACK_BIND:
    raise ImproperlyConfigured('DEBUG=True requires a loopback bind address.')
if PLACEHOLDER_CREDENTIALS and (not DEBUG or not LOOPBACK_BIND):
    raise ImproperlyConfigured('Local placeholder credentials require DEBUG=True and a loopback bind address.')
if (not DEBUG or not LOOPBACK_BIND) and (len(SECRET_KEY or '') < 32 or len(POSTGRES_PASSWORD) < 16):
    raise ImproperlyConfigured('Shared-deployment credentials do not meet minimum length requirements.')

# Hosts that Django will respond to — read from .env as a comma separated list
# Example: ALLOWED_HOSTS=localhost,127.0.0.1
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost').split(',')

# Application definition
# Every Django app and third party package must be listed here
# or Django will not recognize it exists
INSTALLED_APPS = [
    # Django's built in apps — admin panel, authentication, database, etc.
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party — adds tools for building JSON APIs for React to consume
    'rest_framework',
    # Our app handles athlete, workout, sensor-health, and monitoring data.
    'rest_framework_simplejwt', # JWT token auth
    'corsheaders',  # Allows React to call Django across ports 
    'event_handler',
]

# Middleware — a chain of functions that process every request and response
# Think of it as security checkpoints every request passes through
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware', # Must be first - handles CORS before anything else
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Tells Django which file contains the top level URL routing
ROOT_URLCONF = 'basestation_config.urls'

# Template engine configuration — how Django renders HTML pages
# APP_DIRS=True tells Django to look for templates inside each app's folder
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# Points Django to the WSGI application for serving requests
WSGI_APPLICATION = 'basestation_config.wsgi.application'

# Database configuration
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases
# Uses PostgreSQL instead of SQLite — required for production and Docker
# HOST is 'postgres' because that is the compose service name on the Docker network
# All credentials come from .env — never hardcoded here
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB'),
        'USER': os.environ.get('POSTGRES_USER'),    
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD'),
        'HOST': 'postgres',
        'PORT': '5432',
    }
}

# MQTT Configuration
# Mosquitto broker connection settings — read from .env
# MQTT_HOST is 'mosquitto' because that is the compose service name on the Docker network
# Used by event_handler to subscribe to ESP32 node-health pulses.
MQTT_HOST = os.environ.get('MQTT_HOST') or 'mosquitto'
MQTT_PORT = int(os.environ.get('MQTT_PORT') or 1883)
SIMULATOR_ENABLED = os.environ.get('SIMULATOR_ENABLED', 'False') == 'True'

# Password validation rules for user accounts
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/
STATIC_URL = 'static/'

# Default primary key type for database models
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS - allows React (port 5173) to make API calls to Django (port 8000)
CORS_ALLOWED_ORIGINS = [
    "http://localhost", 
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "x-csrftoken",
]

# Django REST Framework - sets JWT as the default auth method 
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'NUM_PROXIES': 1,
}

#JWT token lifetimes 
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
}
