# mqtt_broadcaster.py — Django → Mosquitto broadcasts for the screens.
# When a set finishes, the wall display does NOT poll the REST API — it listens on
# edgeathlete/dashboard/state over MQTT WebSockets. This module builds the
# contract-shaped JSON and publishes it once after set_complete saves.

import json
import os

import paho.mqtt.client as mqtt

from event_handler.models import Set

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DASHBOARD_STATE_TOPIC = "edgeathlete/dashboard/state"


def rack_number_for_set(finished_set: Set) -> int:
    """Rack number comes from the linked sensor node, not the tablet."""
    if finished_set.node_id and finished_set.node.rack_number is not None:
        return finished_set.node.rack_number
    return 0


def build_leaderboard_update_message(
    finished_set: Set,
    is_velocity_pr: bool,
    is_weight_pr: bool,
) -> dict:
    """Shape a leaderboard_update payload per MESSAGE_CONTRACT.md."""
    return {
        "type": "leaderboard_update",
        "athlete": {
            "id": finished_set.athlete_id,
            "name": finished_set.athlete.name,
        },
        "rack_number": rack_number_for_set(finished_set),
        "avg_velocity": finished_set.avg_velocity,
        "peak_velocity": finished_set.peak_velocity,
        "reps_completed": finished_set.reps_completed,
        "is_false_set": finished_set.is_false_set,
        "is_velocity_pr": is_velocity_pr,
        "is_weight_pr": is_weight_pr,
    }


def publish_dashboard_leaderboard_update(
    finished_set: Set,
    is_velocity_pr: bool,
    is_weight_pr: bool,
) -> None:
    """Publish one dashboard broadcast. Never raises — a broker hiccup must not
    roll back an already-saved set."""
    payload = build_leaderboard_update_message(
        finished_set, is_velocity_pr, is_weight_pr
    )
    body = json.dumps(payload)

    client = mqtt.Client()
    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()
        result = client.publish(DASHBOARD_STATE_TOPIC, body, qos=1)
        result.wait_for_publish(timeout=5)
        print(f"[MQTT] Published dashboard state for set {finished_set.id}")
    except Exception as error:
        print(f"[MQTT] Dashboard publish failed for set {finished_set.id}: {error}")
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
