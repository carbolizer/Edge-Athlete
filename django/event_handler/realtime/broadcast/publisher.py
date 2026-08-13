"""The one place Django announces things over MQTT.

TWO DIFFERENT KINDS OF ANNOUNCEMENT live here on purpose (merge canon D5) — read
this before adding a third:

1. DURABLE INVALIDATIONS (`publish_pending_event`) — drains committed
   MonitoringEvent rows to a RETAINED message. "Retained" means the broker keeps
   the last one and hands it to any client the moment it subscribes, so a
   dashboard that connects late still learns the room changed. Survives a dropped
   connection: a failed publish just leaves the row unpublished for the next
   attempt instead of losing the update. Driven by the `publish_monitoring_events`
   management command (its own container).

2. FIRE-AND-FORGET RACK/DASHBOARD PUSHES (`publish_rack_state`,
   `publish_dashboard_state`, `publish_coach_state`) — live nudges to the tablets,
   called inline from views. NOT retained and never raise into the caller: a
   missed one is fine because the next event supersedes it, and a lifting athlete
   must never see a request fail because the broker hiccuped.

⚠️ `publish_dashboard_state` and `publish_pending_event` DELIBERATELY SHARE the
`edgeathlete/dashboard/state` topic. This is safe and verified, not an oversight:
the consumer (`roomMonitor.js: parseMonitoringEvent`) hard-validates
`schema_version == 1` AND `type == "room_state_changed"` AND an integer `revision`
AND a UUID `event_id`, so our `leaderboard_update` payload is simply ignored by it.
We never publish with `retain=True` here, so we can never clobber the retained
invalidation. DO NOT "fix" this by renaming either topic — his dashboard and our
rack contract both depend on the current names.
"""

import json
import os

import paho.mqtt.client as mqtt
from django.utils import timezone

from event_handler.models import MonitoringEvent

DASHBOARD_TOPIC = "edgeathlete/dashboard/state"

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# One client, created once when this module is first imported, and reused for
# every broadcast for the lifetime of the process — not reconnecting per-request.
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
    _publish(DASHBOARD_TOPIC, payload)


def publish_coach_state(payload: dict) -> None:
    """Announce something to the coach tablet."""
    _publish("edgeathlete/coach/state", payload)


def publish_enter_setup(target) -> None:
    """Tell tablets to go back to the setup screen.

    `target` is "all", a rack NUMBER, or a screen's device id — the listener in
    App.jsx checks all three, so one command shape covers "this rack", "this
    tablet" and "the whole room".

    ⚠️ THE RECEIVING HALF HAS EXISTED SINCE THE RACK SCREEN WAS BUILT and nothing
    ever sent this. RackCommandListener has been subscribed to
    edgeathlete/rack/command from boot, on every tablet, waiting for a message no
    code published. This is that message.

    It matters because a released screen has no other way to find out. The server
    clears its rack_number, but the tablet is sitting in a live screen it has no
    reason to re-check — so it kept showing a rack it no longer owned until
    somebody walked over and reloaded it.

    Fire-and-forget, like every other broadcast here: a tablet that is off or off
    the network misses it and picks the change up the next time it asks the server
    who it belongs to. This is the fast path, not the only one.
    """
    _publish("edgeathlete/rack/command", {"type": "enter_setup", "target": target})


def publish_wifi_change(new_password: str) -> None:
    """Warn every connected screen that the Wi-Fi password is about to change,
    and hand it the new one so it can show it after it drops off the network.

    This is the "give the bystander screens a heads-up" half of a Wi-Fi change:
    the wall display and rack tablets never typed the new password and go offline
    the instant the AP restarts, so they can only learn it in the short window
    BEFORE that — which is what this broadcast is for. The host agent waits a few
    seconds after this goes out before it actually restarts the AP.

    ⚠️ THIS PUTS THE WI-FI PASSWORD ON THE BROKER IN THE CLEAR. The broker allows
    anonymous connections, so anything on the gym network can read it. That is a
    deliberate, accepted trade for the convenience of showing the new password on
    each screen (a closed network, trusted kiosks). It is FIRE-AND-FORGET and
    NOT retained, so nothing lingers on the broker after delivery — the message is
    handed to whoever is connected right now and then gone.
    """
    _publish("edgeathlete/system/wifi",
             {"type": "wifi_password_changing", "password": new_password})


def event_payload(event):
    return {
        "schema_version": 1,
        "type": "room_state_changed",
        "reason": event.reason,
        "revision": event.id,
        "event_id": str(event.event_id),
        "occurred_at": event.occurred_at.isoformat().replace("+00:00", "Z"),
    }


def publish_pending_event(client):
    event = MonitoringEvent.objects.filter(published_at=None).order_by("id").first()
    if event is None:
        return False

    event.publish_attempts += 1
    event.save(update_fields=["publish_attempts"])
    try:
        result = client.publish(
            DASHBOARD_TOPIC,
            json.dumps(event_payload(event), separators=(",", ":")),
            qos=1,
            retain=True,
        )
        result.wait_for_publish(timeout=2)
        if not result.is_published():
            raise RuntimeError("broker did not acknowledge monitoring event")
    except Exception as error:
        event.last_error = str(error)[:255]
        event.save(update_fields=["last_error"])
        raise

    event.published_at = timezone.now()
    event.last_error = ""
    event.save(update_fields=["published_at", "last_error"])
    return True
