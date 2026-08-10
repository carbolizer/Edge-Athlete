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
  - monitoring-publisher container — drains the MonitoringEvent outbox to MQTT

For more information on this file, see
https://docs.djangoproject.com/en/5.2/topics/settings/
For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.2/ref/settings/
"""

from pathlib import Path
from datetime import timedelta
import os
import re

from django.core.exceptions import ImproperlyConfigured


def _environment_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    if value not in {"True", "False"}:
        raise ImproperlyConfigured(f"{name} must be exactly True or False")
    return value == "True"


def _environment_list(name):
    return [value.strip() for value in os.environ.get(name, "").split(",") if value.strip()]

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# BASE_DIR points to the /django folder — the root of the Django project
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: don't run with debug turned on in production!
# .env sets DEBUG=True for development, DEBUG=False for production
# Boolean environment values are parsed strictly to prevent production typos.
DEBUG = _environment_bool("DEBUG")
VPS_DEPLOYMENT = _environment_bool("VPS_DEPLOYMENT")

# SECURITY WARNING: keep the secret key used in production secret!
# Read from .env — never hardcode this value.
#
# ⚠️ THE KEY IN .env.example IS PUBLIC. It is committed, so every clone of this
# repo has it, and it signs the JWTs a coach logs in with. A real base station
# gets its own generated key — setup.sh writes one into .env at provision time.
#
# Missing key + DEBUG off is refused rather than defaulted. A base station that
# quietly ran on a placeholder would look completely healthy while every session
# token in the building was forgeable.
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-fallback-for-local-development-only'
    else:
        raise ImproperlyConfigured(
            "SECRET_KEY is not set and DEBUG is off. Generate one:\n"
            "  python -c \"from django.core.management.utils import get_random_secret_key;"
            " print(get_random_secret_key())\"\n"
            "then put it in .env as SECRET_KEY=..."
        )

# Hosts that Django will respond to — read from .env as a comma separated list
# Example: ALLOWED_HOSTS=localhost,127.0.0.1
ALLOWED_HOSTS = _environment_list("ALLOWED_HOSTS") or ["localhost"]

CSRF_TRUSTED_ORIGINS = _environment_list("CSRF_TRUSTED_ORIGINS")
SECURE_SSL_REDIRECT = _environment_bool("SECURE_SSL_REDIRECT")
SESSION_COOKIE_SECURE = _environment_bool("SESSION_COOKIE_SECURE")
CSRF_COOKIE_SECURE = _environment_bool("CSRF_COOKIE_SECURE")
USE_X_FORWARDED_HOST = _environment_bool("USE_X_FORWARDED_HOST")
SECURE_PROXY_SSL_HEADER = None

if VPS_DEPLOYMENT:
    required_values = {
        "VPS_DOMAIN": os.environ.get("VPS_DOMAIN", ""),
        "SECRET_KEY": SECRET_KEY,
        "POSTGRES_DB": os.environ.get("POSTGRES_DB", ""),
        "POSTGRES_USER": os.environ.get("POSTGRES_USER", ""),
        "POSTGRES_PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
    }
    missing_or_placeholder = [
        name for name, value in required_values.items()
        if not value or "<" in value or ">" in value
    ]
    if missing_or_placeholder:
        raise ImproperlyConfigured(
            "VPS deployment requires non-placeholder values for: "
            + ", ".join(missing_or_placeholder)
        )

    development_defaults = {
        "SECRET_KEY": "django-insecure-edgeathlete-dev-key-replace-for-prod",
        "POSTGRES_DB": "edgeathlete",
        "POSTGRES_USER": "edgeathlete_user",
        "POSTGRES_PASSWORD": "supersafepw",
    }
    unsafe_defaults = [
        name for name, value in development_defaults.items()
        if required_values[name] == value
    ]
    if unsafe_defaults:
        raise ImproperlyConfigured(
            "VPS deployment cannot use repository development defaults for: "
            + ", ".join(unsafe_defaults)
        )
    if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5:
        raise ImproperlyConfigured(
            "VPS SECRET_KEY must contain at least 50 characters with sufficient variety"
        )
    database_password = required_values["POSTGRES_PASSWORD"]
    if len(database_password) < 16 or len(set(database_password)) < 5:
        raise ImproperlyConfigured(
            "VPS POSTGRES_PASSWORD must contain at least 16 characters with sufficient variety"
        )
    if DEBUG:
        raise ImproperlyConfigured("DEBUG must be False for VPS deployment")

    vps_domain = required_values["VPS_DOMAIN"].lower()
    domain_labels = vps_domain.split(".")
    if (
        vps_domain != required_values["VPS_DOMAIN"]
        or len(vps_domain) > 253
        or len(domain_labels) < 2
        or any(
            len(label) > 63 or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) is None
            for label in domain_labels
        )
    ):
        raise ImproperlyConfigured("VPS_DOMAIN must be a lowercase DNS hostname")
    if ALLOWED_HOSTS != [vps_domain]:
        raise ImproperlyConfigured("ALLOWED_HOSTS must contain only VPS_DOMAIN")
    if CSRF_TRUSTED_ORIGINS != [f"https://{vps_domain}"]:
        raise ImproperlyConfigured(
            "CSRF_TRUSTED_ORIGINS must contain only the HTTPS VPS origin"
        )

    required_security_flags = {
        "SECURE_SSL_REDIRECT": SECURE_SSL_REDIRECT,
        "SESSION_COOKIE_SECURE": SESSION_COOKIE_SECURE,
        "CSRF_COOKIE_SECURE": CSRF_COOKIE_SECURE,
        "USE_X_FORWARDED_HOST": USE_X_FORWARDED_HOST,
    }
    disabled_flags = [name for name, enabled in required_security_flags.items() if not enabled]
    if disabled_flags:
        raise ImproperlyConfigured(
            "VPS deployment requires True for: " + ", ".join(disabled_flags)
        )
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

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
    # Our app — handles motion events from ESP32 and serves data to React
    'rest_framework_simplejwt', # JWT token auth
    'corsheaders',  # Allows React to call Django across ports 
    'event_handler',
]

# Middleware — a chain of functions that process every request and response
# Think of it as security checkpoints every request passes through
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware', # Must be first - handles CORS before anything else
    'django.middleware.security.SecurityMiddleware',
    # Directly after SecurityMiddleware, which is where WhiteNoise must sit.
    # It is what serves the admin and DRF stylesheets now that gunicorn runs the
    # app — see the STATIC_ROOT note below for why nothing served them before.
    'whitenoise.middleware.WhiteNoiseMiddleware',
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
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases
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
# Used by event_handler to subscribe to motion events from ESP32 nodes
MQTT_HOST = os.environ.get('MQTT_HOST', 'mosquitto')
MQTT_PORT = int(os.environ.get('MQTT_PORT', 1883))

# The host Agent is reachable only through this provisioned local socket. This is
# intentionally not configurable by a request or environment-provided URL.
BLE_AGENT_SOCKET_PATH = "/run/edgeathlete/ble-agent.sock"
NFC_AGENT_SOCKET_PATH = "/run/edgeathlete/nfc-agent.sock"

# (Ntfy settings removed in merge phase P2 / D5 — the motion-alert notification
# path was inherited from this project's fork parent and never served Edge
# Athlete. Real-time delivery now goes through the MonitoringEvent outbox in
# event_handler/realtime/. Nothing reads NTFY_* anymore.)

# Password validation rules for user accounts
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/
#
# ⚠️ THIS IS NOT THE REACT APP. The front end is built by its own container and
# served by Nginx; nothing here touches it. These are the stylesheets for the
# Django ADMIN and the DRF browsable API — the two pages a coach never sees but
# whoever is debugging at 7am absolutely does.
#
# WHY STATIC_ROOT HAD TO BE ADDED. There was none, so `collectstatic` had
# nowhere to write, and nothing served these files except `runserver`'s
# development hook — which only works while DEBUG is on. That made two unrelated
# things silently load-bearing on DEBUG=True: turning debug off, or moving to a
# real web server, would have left admin and DRF rendering as unstyled HTML with
# nothing in the log to explain it.
#
# Now collectstatic runs at image build and WhiteNoise serves the result, so
# both work under gunicorn, with DEBUG on or off. Nginx keeps proxying
# /static/admin/ and /static/rest_framework/ to Django exactly as before — it
# just gets a real answer now.
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        # Compresses, and no manifest. ManifestStaticFilesStorage would hash every
        # filename for cache-busting, which buys nothing on a closed network with
        # two admin pages — and turns any stylesheet referencing a missing file
        # into a hard build failure.
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}

# Default primary key type for database models
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS - allows React (port 5173) to make API calls to Django (port 8000)
CORS_ALLOWED_ORIGINS = [] if VPS_DEPLOYMENT else [
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
    
}

#JWT token lifetimes 
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
}
