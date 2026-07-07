from typing import Optional

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from event_handler.models import Device, MotionEvent
from event_handler.notification_flow.notification_dispatcher.dispatcher import (
    dispatch_motion_notification,
)


def get_device_for_node(node_id: str) -> Optional[Device]:
    """Find registered device by node ID. @param node_id unique ID sent by the motion node"""
    return Device.objects.filter(node_id=node_id).first()


def _parse_sensor_timestamp(value: object):
    """Return a datetime only when the node sent an ISO timestamp."""
    if not value:
        return None

    parsed = parse_datetime(str(value))
    return parsed


def upsert_device_from_payload(payload: dict) -> Device:
    node_id = payload["node_id"]
    device, _ = Device.objects.update_or_create(
        node_id=node_id,
        defaults={
            "name": payload.get("device_name") or node_id,
            "location": payload.get("location") or "unassigned",
            "battery": payload.get("battery"),
            "firmware_version": payload.get("firmware_version"),
            "signal_strength": payload.get("signal_strength"),
            "connection_interrupted": payload.get("connection_interrupted", False),
            "last_seen": timezone.now(),
            "status": Device.STATUS_ACTIVE,
            "is_active": True,
        },
    )
    return device


def process_motion_event(payload: dict) -> Optional[MotionEvent]:
    """Save MQTT node messages and dispatch alerts for motion events."""
    try:
        device = upsert_device_from_payload(payload)

        if payload["event_type"] != "motion":
            print(f"[EVENT] Device status updated from {payload['event_type']}: {device.node_id}")
            return None

        event_id = payload.get("event_id")
        if event_id and MotionEvent.objects.filter(event_id=event_id).exists():
            print(f"[EVENT] Duplicate motion event ignored: {event_id}")
            return None

        motion_event = MotionEvent.objects.create(
            event_id=event_id,
            node_id=payload["node_id"],
            device=device,
            location=payload.get("location") or device.location,
            event_type=payload.get("event_type", "motion"),
            motion=payload.get("motion", True),
            sensor_timestamp=_parse_sensor_timestamp(payload.get("timestamp")),
            timezone=payload.get("timezone"),
            battery_at_event=payload.get("battery"),
            signal_strength_at_event=payload.get("signal_strength"),
        )

        print(f"[EVENT] Motion event saved: {motion_event}")

        dispatch_motion_notification(motion_event)     # Notify only after DB save succeeds

        return motion_event

    except Exception as error:
        print(f"[EVENT] Failed to process motion event: {error}")
        return None
