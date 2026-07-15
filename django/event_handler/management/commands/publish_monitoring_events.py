"""Runs the one outbound worker that drains monitoring events in revision order."""

import time

import paho.mqtt.client as mqtt
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from event_handler.realtime.broadcast.publisher import publish_pending_event


class Command(BaseCommand):
    help = "Publish durable room-state invalidations to MQTT."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [20260713])
            if not cursor.fetchone()[0]:
                raise CommandError("Another monitoring publisher already holds the singleton lock.")
        client = mqtt.Client(client_id="edgeathlete-monitoring-publisher")
        client.connect(settings.MQTT_HOST, settings.MQTT_PORT, 60)
        client.loop_start()
        self.stdout.write("Monitoring publisher connected.")
        try:
            while True:
                try:
                    published = publish_pending_event(client)
                    if not published:
                        time.sleep(1)
                except Exception as error:
                    self.stderr.write(f"Monitoring publish failed: {error}")
                    time.sleep(2)
        finally:
            client.loop_stop()
            client.disconnect()
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [20260713])
