"""Maps node pulses to health state and invalidates coach data on material changes."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from event_handler.models import MonitoringEvent, Node


def process_pulse_event(payload):
    timestamp = parse_datetime(payload["timestamp"])
    if timestamp is None or not timezone.is_aware(timestamp):
        raise ValueError("timestamp must be timezone-aware ISO 8601")
    if timestamp > timezone.now() + timedelta(minutes=5):
        raise ValueError("timestamp is too far in the future")

    with transaction.atomic():
        existing = Node.objects.select_for_update().filter(node_id=payload["node_id"]).first()
        if existing is None:
            raise ValueError("node is not registered")
        if existing.last_seen and timestamp <= existing.last_seen:
            return existing
        materially_changed = (
            existing.battery_level != payload.get("battery_level")
            or existing.firmware_version != payload.get("firmware_version")
            or not existing.is_active
            or existing.last_seen is None
            or existing.last_seen < timezone.now() - timedelta(seconds=15)
        )
        existing.battery_level = payload.get("battery_level")
        existing.signal_strength = payload.get("signal_strength")
        existing.firmware_version = payload.get("firmware_version")
        existing.last_seen = timestamp
        existing.is_active = True
        existing.save(update_fields=["battery_level", "signal_strength", "firmware_version", "last_seen", "is_active"])
        if materially_changed:
            MonitoringEvent.objects.create(reason="node_health_changed", is_simulated=existing.is_simulated)
    return existing
