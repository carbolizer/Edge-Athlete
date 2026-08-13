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
                    # Drain EVERY pending event this wake, not just one. A set
                    # produces a burst of rep-state events; draining one per
                    # 1s-idle-sleep means the dashboard lags by however many
                    # events queued behind the last one it saw. When there is
                    # nothing left, sleep and wait for the next burst.
                    drained_any = False
                    while publish_pending_event(client):
                        drained_any = True
                    if not drained_any:
                        time.sleep(1)
                except Exception as error:
                    self.stderr.write(f"Monitoring publish failed: {error}")
                    time.sleep(2)
        finally:
            client.loop_stop()
            client.disconnect()
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [20260713])
