"""Validate development USB frames before forwarding them to MQTT."""

import json
import re

import paho.mqtt.client as mqtt

from event_handler.realtime.mqtt_ingester.parser import parse_motion_payload, parse_pulse_payload, parse_rep_payload


MAX_USB_FRAME_BYTES = 2300
USB_FRAME_PREFIX = b"EDGE_MQTT\t"
USB_TOPIC_PATTERN = re.compile(r"edgeathlete/node/([A-Za-z0-9_-]{1,64})/(motion|pulse|rep)")


class MotionRateLimiter:
    def __init__(self, minimum_interval=0.09):
        self.minimum_interval = minimum_interval
        self.last_published_at = None

    def allows(self, event_type, now):
        if event_type != "motion":
            return True
        if self.last_published_at is not None and now - self.last_published_at < self.minimum_interval:
            return False
        self.last_published_at = now
        return True


class UsbFrameReader:
    def __init__(self):
        self.discarding_line = False

    def read(self, device):
        while True:
            frame = device.readline(MAX_USB_FRAME_BYTES + 1)
            if not frame:
                return b""
            line_complete = frame.endswith(b"\n")
            if self.discarding_line:
                if line_complete:
                    self.discarding_line = False
                continue
            if not line_complete:
                self.discarding_line = True
                continue
            return frame


def parse_usb_frame(raw_frame):
    if not isinstance(raw_frame, bytes) or len(raw_frame) > MAX_USB_FRAME_BYTES:
        raise ValueError("invalid USB frame size")
    frame = raw_frame.rstrip(b"\r\n")
    if not frame.startswith(USB_FRAME_PREFIX):
        raise ValueError("unexpected USB frame")
    parts = frame.split(b"\t", 2)
    if len(parts) != 3:
        raise ValueError("invalid USB frame fields")
    try:
        topic = parts[1].decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("invalid USB topic") from error
    match = USB_TOPIC_PATTERN.fullmatch(topic)
    if match is None:
        raise ValueError("unexpected USB topic")

    node_id, event_type = match.groups()
    parsers = {"motion": parse_motion_payload, "pulse": parse_pulse_payload, "rep": parse_rep_payload}
    payload = parsers[event_type](parts[2])
    if payload["node_id"] != node_id:
        raise ValueError("USB topic node_id does not match payload")
    return topic, json.dumps(payload, separators=(",", ":"))


def publish_usb_event(client, topic, payload):
    try:
        result = client.publish(topic, payload, qos=0)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            return False
        result.wait_for_publish(timeout=10)
    except (RuntimeError, ValueError):
        return False
    return result.is_published()
