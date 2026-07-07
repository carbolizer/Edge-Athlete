import os
import paho.mqtt.client as mqtt

from event_handler.notification_flow.mqtt_ingester.parser import ( parse_motion_payload, parse_pulse_payload)
from event_handler.notification_flow.event_processor.process_motion import process_motion_event
from event_handler.notification_flow.event_processor.process_pulse import process_pulse_event

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_MOTION_TOPIC = os.getenv("MQTT_MOTION_TOPIC", "edgeathlete/events/motion")
MQTT_PULSE_TOPIC = os.getenv("MQTT_PULSE_TOPIC", "edgeathlete/nodes/heartbeat")
MQTT_QOS = int(os.getenv("MQTT_QOS", "1"))


def on_connect(client: mqtt.Client, userdata: object, flags: dict, rc: int) -> None:
    """Subscribe to motion and pulse topics after connecting to MQTT."""
    if rc == 0:
        print(f"[MQTT] Connected to broker at {MQTT_HOST}:{MQTT_PORT}")

        client.subscribe(MQTT_MOTION_TOPIC, qos=MQTT_QOS)
        print(f"[MQTT] Subscribed to motion topic: {MQTT_MOTION_TOPIC}")

        client.subscribe(MQTT_PULSE_TOPIC, qos=MQTT_QOS)
        print(f"[MQTT] Subscribed to pulse topic: {MQTT_PULSE_TOPIC}")

    else:
        print(f"[MQTT] Failed to connect. Return code: {rc}")


def on_message(client: mqtt.Client, userdata: object, msg: mqtt.MQTTMessage) -> None:
    """Route MQTT messages to the correct processing pipeline."""
    try:
        print(f"[MQTT] Message received on topic: {msg.topic}")

        if msg.topic == MQTT_MOTION_TOPIC:
            payload = parse_motion_payload(msg.payload)
            process_motion_event(payload)

        elif msg.topic == MQTT_PULSE_TOPIC:
            payload = parse_pulse_payload(msg.payload)
            process_pulse_event(payload)

        else:
            print(f"[MQTT] Ignored message on unknown topic: {msg.topic}")

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