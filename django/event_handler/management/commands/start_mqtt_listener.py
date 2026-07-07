# Import Django's built-in base class for custom terminal commands
# This is what lets us run:
# python manage.py start_mqtt_listener
from django.core.management.base import BaseCommand

# Import our MQTT startup function
# This function connects to Mosquitto and starts listening for messages
from event_handler.notification_flow.mqtt_ingester.subscriber import (
    start_mqtt_subscriber,
)


# Every custom Django terminal command uses a class named "Command"
# Django automatically looks for this exact class name
class Command(BaseCommand):

    # Short description shown if someone runs:
    # python manage.py help
    help = "Start the MQTT listener for motion and heartbeat events"

    # This function runs automatically when the command is started
    def handle(self, *args, **options):

        # Print a startup message into the terminal
        self.stdout.write("Starting MQTT listener...")

        # Start the MQTT subscriber
        # This connects Django to the Mosquitto broker
        # and begins listening for ESP32 messages
        start_mqtt_subscriber()

        # Import Python's built-in time library
        import time

        # Keep this command running forever
        # If this file exits, the MQTT listener would stop
        while True:

            # Sleep for 60 seconds repeatedly
            # This keeps the process alive without wasting CPU
            time.sleep(60)
