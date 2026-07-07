"""
parser.py — MQTT Payload Parser
--------------------------------
Parses and validates incoming MQTT motion payloads into a normalized format
used by the event processing layer.

Expected payload structure:
{
  "event_id": str,
  "node_id": str,
  "device_name": str,
  "location": str,
  "event_type": "motion",
  "motion": bool,
  "timestamp": str (ISO 8601),
  "timezone": str,
  "connection": {
    "interrupted": bool,
    "signal_strength": int
  },
  "device_status": {
    "battery": int,
    "firmware_version": str
  }
}
"""

import json
from typing import Any


def parse_motion_payload(raw_payload: bytes, topic: str = "") -> dict[str, Any]:
    """Decode, validate, and normalize MQTT payloads from Edge Athlete nodes."""
    
    # Decode and parse JSON
    try:
        data = json.loads(raw_payload.decode("utf-8"))
    except Exception as error:
        raise ValueError(f"Invalid payload format: {error}")

    # Ensure payload is a JSON object
    if not isinstance(data, dict):
        raise ValueError("Payload must be a JSON object")

    # Some node messages can omit event_type because the topic already says
    # what kind of event it is.
    if "event_type" not in data:
        if topic.endswith("/motion"):
            data["event_type"] = "motion"
        elif topic.endswith("/heartbeat"):
            data["event_type"] = "heartbeat"
        elif topic.endswith("/register"):
            data["event_type"] = "register"

    required_fields = ["node_id", "event_type", "timestamp"]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    # Normalize core fields
    node_id = str(data["node_id"]).strip()
    event_type = str(data["event_type"]).strip()
    timestamp = str(data["timestamp"]).strip()

    # Optional fields
    event_id = data.get("event_id")
    device_name = data.get("device_name") or data.get("name") or node_id
    motion = data.get("motion", event_type == "motion")

    location = data.get("location")
    if location is not None:
        location = str(location).strip()

    # Nested optional fields
    connection = data.get("connection", {})
    if not isinstance(connection, dict):
        connection = {}
    connection_interrupted = connection.get("interrupted", False)
    signal_strength = connection.get("signal_strength")

    device_status = data.get("device_status", {})
    if not isinstance(device_status, dict):
        device_status = {}
    battery = device_status.get("battery")
    firmware_version = device_status.get("firmware_version")

    # Return normalized payload
    return {
        "event_id": str(event_id).strip() if event_id else None,
        "node_id": node_id,
        "device_name": str(device_name).strip(),
        "location": location,
        "event_type": event_type,
        "motion": bool(motion),
        "timestamp": timestamp,
        "timezone": str(data.get("timezone", "")).strip() or None,
        "connection_interrupted": connection_interrupted,
        "signal_strength": signal_strength,
        "battery": battery,
        "firmware_version": firmware_version,
        "raw": data  # keep full payload for future use
    }


def parse_pulse_payload(raw_payload: bytes) -> dict[str, Any]:
    """Decode, validate, and normalize MQTT pulse payload."""

    try:
        data = json.loads(raw_payload.decode("utf-8"))
    except Exception as error:
        raise ValueError(f"Invalid payload format: {error}")

    if not isinstance(data, dict):
        raise ValueError("Payload must be a JSON object")

    required_fields = ["node_id", "event_type", "timestamp"]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    node_id = str(data["node_id"]).strip()
    event_type = str(data["event_type"]).strip()
    timestamp = str(data["timestamp"]).strip()

    connection = data.get("connection", {})
    device_status = data.get("device_status", {})

    return {
        "node_id": node_id,
        "event_type": event_type,
        "timestamp": timestamp,
        "connection_interrupted": connection.get("interrupted", False),
        "signal_strength": connection.get("signal_strength"),
        "battery": device_status.get("battery"),
        "firmware_version": device_status.get("firmware_version"),
        "raw": data,
    }