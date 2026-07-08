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


def parse_pulse_payload(raw_payload: bytes) -> dict[str, Any]: 
    """
      Decode and normalize a pulse (heartbeat) payload from a node.

    Contract shape (MESSAGE_CONTRACT.md, edgeathlete/node/{node_id}/pulse):
    {
      "node_id": "rack_1",
      "event_type": "pulse",
      "battery_level": 87,
      "signal_strength": -55,
      "firmware_version": "1.0.0",
      "timestamp": "2026-07-07T07:23:55Z"
    }
    """

    try:
        data = json.loads(raw_payload.decode("utf-8"))
    except Exception as error: 
        raise ValueError(f"Invalid payload format: {error}")
    
    if not isinstance(data, dict): 
        raise ValueError("Payload must be a JSON object")
    
    required_fields = ["node_id", "timestamp"]
    for field in required_fields: 
        if field not in data: 
            raise ValueError(f"Missing required field: {field}")
        
    return{
        "node_id": str(data["node_id"]).strip(),
        "event_type": str(data.get("event_type", "pulse")).strip(),
        "timestamp": str(data["timestamp"]).strip(),
        "battery_level": data.get("battery_level"),
        "signal_strength": data.get("signal_strength"),
        "firmware_version": data.get("firmware_version"),
    }

# entirely new function right here for parsing reps
def parse_rep_payload(raw_payload: bytes) -> dict[str, Any]:
    """
    Decode and normalize a rep payload from a node.

    Contract shape (MESSAGE_CONTRACT.md, edgeathlete/node/{node_id}/rep):
    {
      "node_id": "rack_1",
      "rep_number": 1,
      "mean_velocity": 0.72,
      "peak_velocity": 0.91,
      "duration_ms": 640,
      "timestamp": "2026-07-07T07:23:55Z"
    }
    
    """
    try:
        data = json.loads(raw_payload.decode("utf-8"))
    except Exception as error:
        raise ValueError(f"Invalid payload format: {error}")
    
    if not isinstance(data, dict):
        raise ValueError("Payload must be a JSON object")
    
    required_fields = ["node_id", "rep_number", "mean_velocity", "peak_velocity", "duration_ms", "timestamp"]
    for field in required_fields:
        if field not in data: 
            raise ValueError(f"Missing required field: {field}")

    return {
        "node_id": str(data["node_id"]).strip(),
        "rep_number": int(data["rep_number"]),
        "mean_velocity": float(data["mean_velocity"]),
        "peak_velocity": float(data["peak_velocity"]),
        "duration_ms": int(data["duration_ms"]), 
        "timestamp": str(data["timestamp"]).strip(),
    }