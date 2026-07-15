"""Turns committed MonitoringEvent rows into retained MQTT invalidations."""

import json

from django.utils import timezone

from event_handler.models import MonitoringEvent

DASHBOARD_TOPIC = "edgeathlete/dashboard/state"


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
        result.wait_for_publish(timeout=10)
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
