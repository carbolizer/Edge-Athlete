# run_mqtt_subscriber.py — the base station's one and only MQTT listener process.
# This is the long-running "ear" of the base station: it opens the connection to
# the broker and then just stays awake, listening, for as long as the container
# lives.
#
# There is no keep-alive loop here on purpose: start_mqtt_subscriber() ends in
# paho's loop_forever(), which BLOCKS for the life of the process and reconnects
# on its own if the broker drops. (An older variant used the non-blocking
# loop_start() and needed a `while True: sleep()` here to stop the container
# exiting instantly — if you ever switch back, that loop must come back too.)
from django.core.management.base import BaseCommand

from event_handler.realtime.mqtt_ingester.subscriber import start_mqtt_subscriber


class Command(BaseCommand):
    help = "Subscribe to Edge Athlete MQTT topics and save node events."

    def handle(self, *args, **options):
        self.stdout.write("Starting Edge Athlete MQTT subscriber...")
        start_mqtt_subscriber()
