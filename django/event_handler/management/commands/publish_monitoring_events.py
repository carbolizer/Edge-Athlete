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
        # Reconnect fast and keep trying: the broker comes and goes during an
        # update, and a publisher that wedges on a dead socket stops the room
        # updating until someone restarts it. That is exactly the failure this
        # worker exists to survive.
        client.reconnect_delay_set(min_delay=1, max_delay=10)
        client.connect(settings.MQTT_HOST, settings.MQTT_PORT, 60)
        client.loop_start()
        self.stdout.write("Monitoring publisher connected.")
        try:
            while True:
                try:
                    # If the connection dropped (broker restart, network blip),
                    # reconnect before doing anything. publish_pending_event
                    # raises "connection already closed" on a dead socket, and
                    # without this the worker would sleep-and-retry forever,
                    # draining nothing and stalling the room.
                    if not client.is_connected():
                        self.stderr.write("Monitoring broker connection lost — reconnecting.")
                        client.reconnect()
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
