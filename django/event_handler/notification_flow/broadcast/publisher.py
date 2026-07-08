# publisher.py - the one place Django announces things to the screens
# 
# rack tablets, the wall dashboard, and the coach tablet all need to know 
# the instant something happens 

import json 
import os 

import paho.mqtt.client as mqtt 

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# One client, created once when this module is first imported, and reused
# for every broadcast for the lifetime of the process - not reconnecting
# per-request.
_client = mqtt.Client()
_client.connect(MQTT_HOST, MQTT_PORT, 60)
_client.loop_start()


def _publish(topic: str, payload: dict) -> None:
    """Fire-and-forget publish: log failures, never raise into the caller."""
    try:
        _client.publish(topic, json.dumps(payload), qos=1)
    except Exception as error:
        print(f"[BROADCAST] Failed to publish to {topic}: {error}")


def publish_rack_state(rack_number: int, payload: dict) -> None:
    """Announce something to the tablet at a specific rack."""
    _publish(f"edgeathlete/rack/{rack_number}/state", payload)


def publish_dashboard_state(payload: dict) -> None:
    """Announce something to the team wall display."""
    _publish("edgeathlete/dashboard/state", payload)


def publish_coach_state(payload: dict) -> None:
    """Announce something to the coach tablet."""
    _publish("edgeathlete/coach/state", payload)