# TODO: @Brayd-n implement process_pulse_event in event_handler/notification_flow/event_processor_process_pulse
from typing import Any, Optional
from event_handler.models import Device

# FOR REFERENCE PARSER RETURNS:
        # "node_id": node_id,
        # "event_type": event_type,
        # "timestamp": timestamp,
        # "connection_interrupted": connection.get("interrupted", False),
        # "signal_strength": connection.get("signal_strength"),
        # "battery": device_status.get("battery"),
        # "firmware_version": device_status.get("firmware_version"),
        # "raw": data,
def process_pulse_event(payload: dict[str, Any]) -> Optional[Device]:
    """
    Update latest device health/telemetry from a heartbeat/pulse payload.
    Does not create MotionEvent records or send motion notifications.
    """
    try:
        if payload["event_type"] not in ["heartbeat", "pulse"]:
            print(f"[PULSE] Ignored non-pulse event: {payload['event_type']}")
            return None

        node_id = payload["node_id"]

        device, created = Device.objects.update_or_create(
            node_id=node_id,
            defaults={
                "name": payload["raw"].get("device_name", node_id),
                "location": payload["raw"].get("location", "Unknown"),
                "battery": payload.get("battery"),
                "firmware_version": payload.get("firmware_version"),
                "signal_strength": payload.get("signal_strength"),
                "connection_interrupted": payload.get("connection_interrupted", False),
                "is_active": True,
            },
        )

        if created:
            print(f"[PULSE] Registered new device: {device}")
        else:
            print(f"[PULSE] Updated device health: {device}")

        return device

    except Exception as error:
        print(f"[PULSE] Failed to process pulse event: {error}")
        return None