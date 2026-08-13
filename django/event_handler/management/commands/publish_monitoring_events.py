"""Runs the one outbound worker that drains monitoring events in revision order."""

import time

import paho.mqtt.client as mqtt
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from event_handler.realtime.broadcast.publisher import publish_pending_event


class Command(BaseCommand):
    help = "Publish durable room-state invalidations to MQTT."

    def make_client(self):
        client = mqtt.Client(client_id="edgeathlete-monitoring-publisher")
        # Reconnect fast and keep trying: the broker comes and goes during an
        # update. paho's background loop thread owns reconnection — this worker
        # must never touch the socket from the main thread (that race crashes
        # the loop thread with "'NoneType' object has no attribute 'recv'").
        client.reconnect_delay_set(min_delay=1, max_delay=10)
        client.connect(settings.MQTT_HOST, settings.MQTT_PORT, 60)
        client.loop_start()
        return client

    def close_client(self, client):
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [20260713])
            if not cursor.fetchone()[0]:
                raise CommandError("Another monitoring publisher already holds the singleton lock.")
        try:
            while True:
                # Build a FRESH client each pass. paho's loop thread can die on
                # a socket race (see make_client); a dead thread cannot be
                # resurrected, so the only recovery is a brand-new client with a
                # brand-new thread. Any failure below discards the old one.
                # make_client itself can fail when the broker is down — that is
                # the same case, handled the same way: wait and try again.
                try:
                    client = self.make_client()
                    self.stdout.write("Monitoring publisher connected.")
                except Exception as error:
                    self.stderr.write(f"Monitoring broker unavailable: {error}")
                    time.sleep(2)
                    continue
                try:
                    while True:
                        # Wait, never reconnect from here. If the connection is
                        # down the loop thread restores it on its own schedule.
                        if not client.is_connected():
                            time.sleep(1)
                            continue
                        # Drain EVERY pending event this wake, not just one. A
                        # set produces a burst of rep-state events; draining one
                        # per 1s-idle-sleep means the dashboard lags by however
                        # many events queued behind the last one it saw.
                        drained_any = False
                        while publish_pending_event(client):
                            drained_any = True
                        if not drained_any:
                            time.sleep(1)
                except Exception as error:
                    self.stderr.write(f"Monitoring publish failed: {error}")
                    self.close_client(client)
                    time.sleep(2)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [20260713])
