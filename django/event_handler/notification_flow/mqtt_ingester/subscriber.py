"""Runs the sole inbound MQTT listener for node health pulses."""

import paho.mqtt.client as mqtt
from django.conf import settings

from event_handler.notification_flow.event_processor.process_pulse import process_pulse_event
from event_handler.notification_flow.mqtt_ingester.parser import parse_pulse_payload

MQTT_PULSE_TOPIC = "edgeathlete/node/+/pulse"
MQTT_QOS = 1


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe(MQTT_PULSE_TOPIC, qos=MQTT_QOS)


def on_message(client, userdata, message):
    try:
        topic_parts = message.topic.split("/")
        if len(topic_parts) != 4 or topic_parts[:2] != ["edgeathlete", "node"] or topic_parts[3] != "pulse":
            raise ValueError("unexpected pulse topic")
        payload = parse_pulse_payload(message.payload)
        if topic_parts[2] != payload["node_id"]:
            raise ValueError("topic node_id does not match payload")
        process_pulse_event(payload)
    except Exception:
        print("[MQTT] Ignored invalid pulse")


def start_mqtt_subscriber():
    client = mqtt.Client(client_id="edgeathlete-pulse-listener")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(settings.MQTT_HOST, settings.MQTT_PORT, 60)
    client.loop_forever()
