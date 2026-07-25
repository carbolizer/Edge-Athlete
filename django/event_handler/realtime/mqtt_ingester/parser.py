"""Validate the MQTT payload contracts shared by hardware and simulation."""

import json
import re
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime


def parse_pulse_payload(raw_payload: bytes) -> dict[str, Any]:
    """Decode, validate, and normalize MQTT pulse payload."""

    if len(raw_payload) > 2048:
        raise ValueError("Pulse payload exceeds 2048 bytes")

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
    if not node_id:
        raise ValueError("node_id cannot be empty")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", node_id):
        raise ValueError("node_id contains unsupported characters")
    if event_type != "pulse":
        raise ValueError("event_type must be pulse")

    battery_level = data.get("battery_level")
    signal_strength = data.get("signal_strength")
    firmware_version = data.get("firmware_version")
    if not isinstance(battery_level, int) or not 0 <= battery_level <= 100:
        raise ValueError("battery_level must be an integer from 0 to 100")
    if not isinstance(signal_strength, int) or not -120 <= signal_strength <= 0:
        raise ValueError("signal_strength must be an integer from -120 to 0")
    if not isinstance(firmware_version, str) or not 1 <= len(firmware_version) <= 50 or not firmware_version.isprintable():
        raise ValueError("firmware_version must be 1 to 50 printable characters")

    return {
        "node_id": node_id,
        "event_type": event_type,
        "timestamp": timestamp,
        "signal_strength": signal_strength,
        "battery_level": battery_level,
        "firmware_version": firmware_version,
    }


def parse_rep_payload(raw_payload: bytes) -> dict[str, Any]:
    """Decode and validate one completed-rep payload."""
    if len(raw_payload) > 2048:
        raise ValueError("Rep payload exceeds 2048 bytes")
    try:
        data = json.loads(raw_payload.decode("utf-8"))
    except Exception as error:
        raise ValueError(f"Invalid payload format: {error}")
    if not isinstance(data, dict):
        raise ValueError("Payload must be a JSON object")

    required = ["node_id", "rep_number", "mean_velocity", "peak_velocity", "duration_ms", "timestamp"]
    for field in required:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    node_id = str(data["node_id"]).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", node_id):
        raise ValueError("node_id contains unsupported characters")
    if not isinstance(data["rep_number"], int) or not 1 <= data["rep_number"] <= 100:
        raise ValueError("rep_number must be an integer from 1 to 100")
    for field in ["mean_velocity", "peak_velocity"]:
        if not isinstance(data[field], (int, float)) or isinstance(data[field], bool) or not 0 <= data[field] <= 10:
            raise ValueError(f"{field} must be a number from 0 to 10")
    if data["peak_velocity"] < data["mean_velocity"]:
        raise ValueError("peak_velocity cannot be lower than mean_velocity")
    if not isinstance(data["duration_ms"], int) or not 0 <= data["duration_ms"] <= 60000:
        raise ValueError("duration_ms must be an integer from 0 to 60000")
    timestamp = str(data["timestamp"]).strip()
    parsed_timestamp = parse_datetime(timestamp)
    if parsed_timestamp is None or not timezone.is_aware(parsed_timestamp):
        raise ValueError("timestamp must be timezone-aware ISO 8601")
    return {
        "node_id": node_id,
        "rep_number": data["rep_number"],
        "mean_velocity": float(data["mean_velocity"]),
        "peak_velocity": float(data["peak_velocity"]),
        "duration_ms": data["duration_ms"],
        "timestamp": timestamp,
    }
