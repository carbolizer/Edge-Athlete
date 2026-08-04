"""Forward validated development USB sensor frames to Mosquitto."""

import signal
import time

import paho.mqtt.client as mqtt
import serial
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from event_handler.realtime.serial_bridge import MotionRateLimiter, UsbFrameReader, parse_usb_frame, publish_usb_event


class Command(BaseCommand):
    help = "Forward framed ESP32 USB events to MQTT in development."

    def add_arguments(self, parser):
        parser.add_argument("--device", default="/dev/ttyACM0")
        parser.add_argument("--baud", type=int, default=115200)

    def handle(self, *args, **options):
        if not settings.USB_BRIDGE_ENABLED:
            raise CommandError("USB bridge is disabled. Set USB_BRIDGE_ENABLED=True only for development.")
        if options["baud"] < 1200 or options["baud"] > 2000000:
            raise CommandError("USB baud must be from 1200 to 2000000.")

        mqtt_client = mqtt.Client(client_id="edgeathlete-usb-bridge")
        mqtt_client.max_queued_messages_set(1)
        mqtt_client.reconnect_delay_set(min_delay=1, max_delay=10)
        try:
            mqtt_client.connect(settings.MQTT_HOST, settings.MQTT_PORT, 60)
        except Exception as error:
            raise CommandError(f"Could not connect USB bridge to MQTT: {error}") from error
        mqtt_client.loop_start()
        stopping = False

        def stop_bridge(_signum, _frame):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop_bridge)
        signal.signal(signal.SIGINT, stop_bridge)
        self.stdout.write("[USB bridge] MQTT connection started")
        try:
            while not stopping:
                try:
                    with serial.Serial(options["device"], options["baud"], timeout=1, exclusive=True) as device:
                        self.stdout.write("[USB bridge] Serial device connected")
                        time.sleep(3)
                        next_time_sync = 0.0
                        frame_reader = UsbFrameReader()
                        motion_rate_limiter = MotionRateLimiter()
                        while not stopping:
                            now = time.monotonic()
                            if now >= next_time_sync:
                                device.write(f"EDGE_TIME\t{int(time.time())}\n".encode("ascii"))
                                device.flush()
                                next_time_sync = now + 30
                            frame = frame_reader.read(device)
                            if not frame:
                                continue
                            try:
                                topic, payload = parse_usb_frame(frame)
                            except ValueError:
                                continue
                            event_type = topic.rsplit("/", 1)[-1]
                            if not motion_rate_limiter.allows(event_type, time.monotonic()):
                                continue
                            if not publish_usb_event(mqtt_client, topic, payload):
                                if event_type != "motion":
                                    self.stderr.write("[USB bridge] MQTT publish failed")
                                continue
                            if event_type != "motion":
                                self.stdout.write(f"[USB bridge] Published {event_type}")
                except serial.SerialException:
                    if not stopping:
                        self.stderr.write("[USB bridge] Serial device unavailable; retrying")
                        time.sleep(2)
        finally:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
