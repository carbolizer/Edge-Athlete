# run_mqtt_subscriber.py — the base station's one and only MQTT listener process.
# This is the long-running "ear" of the base station: it opens the connection to
# the broker and then just stays awake, listening, for as long as the container
# lives. start_mqtt_subscriber() starts the network loop in a BACKGROUND thread
# and returns immediately, so this command has to block on its own afterward —
# otherwise the process would exit the moment it started and the container would
# restart-loop forever. The keep-alive loop below is that "stay awake" part.
import time

from django.core.management.base import BaseCommand

from event_handler.notification_flow.mqtt_ingester.subscriber import start_mqtt_subscriber


class Command(BaseCommand):
    help = "Subscribe to Edge Athlete MQTT topics and save node events."

    def handle(self, *args, **options):
        self.stdout.write("Starting Edge Athlete MQTT subscriber...")
        start_mqtt_subscriber()

        # start_mqtt_subscriber() uses loop_start() (non-blocking), so keep the
        # main thread alive here or the process exits and the container restarts.
        while True:
            time.sleep(60)
