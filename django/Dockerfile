# FROM        # what base image to build on
# WORKDIR     # set the working directory inside the container
# COPY        # copy files from your machine into the container
# RUN         # execute a command during the build
# EXPOSE      # document what port the container listens on
# CMD         # what command runs when the container starts

FROM python:3.11-slim

WORKDIR /backend_container

COPY requirements.txt .

RUN pip install -r requirements.txt

COPY . .

# Gather the admin + DRF stylesheets into STATIC_ROOT so WhiteNoise can serve
# them. Done at BUILD time, not boot: it is the same result every time, and a
# container should not be doing avoidable work while a gym waits for it.
#
# SECRET_KEY is supplied here only because settings.py refuses to import
# without one. It is thrown away with the build step and never reaches a
# running container — collectstatic signs nothing and reads no database.
RUN SECRET_KEY=build-time-only-not-used-at-runtime DEBUG=False \
    python manage.py collectstatic --noinput --clear

EXPOSE 8000

# Migrate, ensure the demo login exists, then hand off to gunicorn.
#
# ⚠️ NOT `runserver`. Django's own docs say never deploy with it. The reason
# that matters here is not speed — runserver is threaded and this is a dozen
# tablets — it is that the autoreloader polls the filesystem forever on a box
# that runs unattended for months and can restart mid-request, nothing reaps a
# stuck request, and one unhandled error takes the whole process down. During a
# training day that means sets not saving.
#
# Migrations stay in front of gunicorn and outside it: this is the SOLE
# migrator (the listener and publisher deliberately do not migrate), and it has
# to finish before any worker starts serving.
#
#   --workers 3        modest, for a mini PC. Each is a separate process, so one
#                      wedged request can no longer take the site with it.
#   --timeout 60       a request that hangs gets its worker killed and replaced
#                      instead of being held forever.
#   --access-logfile - logs to stdout, so `docker compose logs django` shows
#                      requests the way runserver used to.
CMD ["sh", "-c", "python manage.py migrate && python manage.py ensure_demo_coach && python manage.py recover_racks && exec gunicorn basestation_config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60 --graceful-timeout 30 --access-logfile - --error-logfile -"]