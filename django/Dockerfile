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

EXPOSE 8000

COPY . .

# Start the container by first applying any pending database migrations
# Start the Django web server on all network interfaces (0.0.0.0)
#   containers like Nginx can reach it at django:8000.
CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]