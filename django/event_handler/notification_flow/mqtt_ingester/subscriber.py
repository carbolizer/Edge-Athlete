# the base station's single MQTT listener 

# Django only ever needs to know about node health (pulses), never 
# individual reps


import os
import paho.mqtt.client as mqtt

from event_handler.notification_flow.mqtt_ingester.parser import parse_pulse_payload
from event_handler.notification_flow.event_processor.process_pulse import process_pulse_event

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_PULSE_TOPIC = "edgeathlete/node/+/pulse"
MQTT_QOS = int(os.getenv("MQTT_QOS", "1"))


def on_connect(client: mqtt.Client, userdata: object, flags: dict, rc: int) -> None:
    """Subscribe to the pulse topic (and only the pulse topic) after connecting."""
    if rc == 0:
        print(f"[MQTT] Connected to broker at {MQTT_HOST}:{MQTT_PORT}")

        client.subscribe(MQTT_PULSE_TOPIC, qos=MQTT_QOS)
        print(f"[MQTT] Subscribed to pulse topic: {MQTT_PULSE_TOPIC}")

    else:
        print(f"[MQTT] Failed to connect. Return code: {rc}")


def on_message(client: mqtt.Client, userdata: object, msg: mqtt.MQTTMessage) -> None:
    """Every message that reaches is a pulse, parse it and update it in the Node"""

    try:
        print(f"[MQTT] Message received on topic: {msg.topic}")

        payload = parse_pulse_payload(msg.payload)
        process_pulse_event(payload)

    except Exception as error:
        print(f"[MQTT] Failed to process message: {error}")

def start_mqtt_subscriber() -> None:
    """Start MQTT listener in the background."""
    client = mqtt.Client()

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"[MQTT] Connecting to {MQTT_HOST}:{MQTT_PORT}")

    client.connect(MQTT_HOST, MQTT_PORT, 60)

    # Non-blocking: keeps MQTT running without freezing Django startup
    client.loop_start()