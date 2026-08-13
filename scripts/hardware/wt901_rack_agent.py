#!/usr/bin/env python3
"""Acquire enrolled WT901BLE sensors and expose privacy-safe local diagnostics."""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import ipaddress
import math
import os
import random
import re
import secrets
import signal
import stat
import struct
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request


SERVICE_UUID = "0000ffe5-0000-1000-8000-00805f9a34fb"
NOTIFY_UUID = "0000ffe4-0000-1000-8000-00805f9a34fb"
FRAME_HEADER = b"\x55\x61"
FRAME_SIZE = 20
MAX_BUFFER_BYTES = FRAME_SIZE * 8
MAX_MOVEMENT_G = 16.0
NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
OPAQUE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MAX_HTTP_BODY_BYTES = 8192
MAX_HTTP_HEADER_BYTES = 8192
DEFAULT_SCAN_SECONDS = 5
DEFAULT_HANDLE_TTL_SECONDS = 60
DEFAULT_VERIFICATION_TTL_SECONDS = 60
MAX_DISCOVERED_DEVICES = 64
MAX_PENDING_VERIFICATIONS = 64
MAX_RACK_NUMBER = 8
MAX_STATE_BYTES = 64 * 1024
MAX_ADDRESS_BYTES = 256
MAX_LABEL_BYTES = 80
VERIFICATION_MOVEMENT_THRESHOLD_G = 0.05
GENERATED_NODE_ID_PATTERN = re.compile(r"^wt901_[0-9a-f]{24}$")
DEFAULT_MQTT_HOST = "127.0.0.1"
DEFAULT_MQTT_PORT = 1883
DEFAULT_BASE_URL = "http://basestation"
DEFAULT_PULSE_INTERVAL_SECONDS = 5.0
REP_START_MOVEMENT_G = 0.07
REP_END_MOVEMENT_G = 0.05
REP_MIN_DURATION_SECONDS = 0.60
REP_MAX_DURATION_SECONDS = 4.0
REP_REFRACTORY_SECONDS = 0.12
MAX_REP_VELOCITY_MPS = 3.0
SAMPLE_INTERVAL_SECONDS = 0.02
REP_ONSET_SAMPLES = 4
REP_SETTLE_SAMPLES = 12
REP_MIN_EXCURSION_METERS = 0.03


@dataclass(frozen=True)
class ImuSample:
    acceleration_g: tuple[float, float, float]
    angular_velocity_dps: tuple[float, float, float]
    angle_degrees: tuple[float, float, float]


class WT901FrameDecoder:
    """Split fragmented or combined BLE notifications into bounded WT901 frames."""

    def __init__(self):
        self._buffer = bytearray()
        self.rejected_bytes = 0

    def feed(self, chunk):
        if not isinstance(chunk, (bytes, bytearray)):
            raise TypeError("BLE notification must be bytes")
        self._buffer.extend(chunk)
        if len(self._buffer) > MAX_BUFFER_BYTES:
            self.rejected_bytes += len(self._buffer)
            self._buffer.clear()
            return []

        samples = []
        while True:
            header_index = self._buffer.find(FRAME_HEADER)
            if header_index < 0:
                keep = 1 if self._buffer.endswith(FRAME_HEADER[:1]) else 0
                self.rejected_bytes += len(self._buffer) - keep
                self._buffer[:] = self._buffer[-1:] if keep else b""
                break
            if header_index:
                self.rejected_bytes += header_index
                del self._buffer[:header_index]
            if len(self._buffer) < FRAME_SIZE:
                break
            samples.append(decode_frame(bytes(self._buffer[:FRAME_SIZE])))
            del self._buffer[:FRAME_SIZE]
        return samples


def decode_frame(frame):
    if len(frame) != FRAME_SIZE or not frame.startswith(FRAME_HEADER):
        raise ValueError("invalid WT901 data frame")
    values = struct.unpack_from("<9h", frame, 2)
    return ImuSample(
        tuple(value / 32768.0 * 16.0 for value in values[:3]),
        tuple(value / 32768.0 * 2000.0 for value in values[3:6]),
        tuple(value / 32768.0 * 180.0 for value in values[6:9]),
    )


class MovementEstimator:
    """Remove stationary gravity magnitude and report diagnostic acceleration.

    The baseline is the average magnitude over the first `calibration_samples`.
    If the sensor is being handled during that window the baseline lands wrong
    (e.g. 0.89g instead of 1.0), and resting afterwards reads as ~0.12g of
    permanent "motion" — which no rep detector can ever qualify. So once the
    sensor is sustained at true rest (magnitude within `rest_tolerance_g` of
    gravity for `rest_anchor_window` consecutive samples) the baseline re-anchors
    to the observed magnitude. During a real rep the magnitude leaves ~1.0g, so
    this never fires mid-set.
    """

    def __init__(self, calibration_samples=50, deadband_g=0.01,
                 rest_anchor_window=25, rest_tolerance_g=0.10):
        if calibration_samples < 1:
            raise ValueError("calibration_samples must be positive")
        self._required = calibration_samples
        self._deadband = deadband_g
        self._total = 0.0
        self._count = 0
        self._baseline = None
        self._rest_window = []
        self._rest_anchor_window = rest_anchor_window
        self._rest_tolerance = rest_tolerance_g

    def update(self, sample):
        magnitude = math.sqrt(sum(axis * axis for axis in sample.acceleration_g))
        if not math.isfinite(magnitude) or magnitude > MAX_MOVEMENT_G:
            return None
        if self._baseline is None:
            self._total += magnitude
            self._count += 1
            if self._count < self._required:
                return None
            self._baseline = self._total / self._count
            return 0.0
        difference = abs(magnitude - self._baseline)
        if difference < 0.03:
            self._baseline = self._baseline * 0.99 + magnitude * 0.01
        if abs(magnitude - 1.0) <= self._rest_tolerance:
            self._rest_window.append(magnitude)
            if len(self._rest_window) >= self._rest_anchor_window:
                self._baseline = sum(self._rest_window) / len(self._rest_window)
                self._rest_window.clear()
        else:
            self._rest_window.clear()
        return round(min(MAX_MOVEMENT_G, max(0.0, difference - self._deadband)), 4)


class ProvisionalRepDetector:
    """Accept one rest-to-rest translation cycle; reject bumps and one-way pickup."""

    def __init__(
        self,
        clock=time.monotonic,
        start_threshold_g=REP_START_MOVEMENT_G,
        end_threshold_g=REP_END_MOVEMENT_G,
        min_duration_seconds=REP_MIN_DURATION_SECONDS,
        max_duration_seconds=REP_MAX_DURATION_SECONDS,
        refractory_seconds=REP_REFRACTORY_SECONDS,
        sample_interval_seconds=SAMPLE_INTERVAL_SECONDS,
    ):
        self._clock = clock
        self._start_threshold = start_threshold_g
        self._end_threshold = end_threshold_g
        self._min_duration = min_duration_seconds
        self._max_duration = max_duration_seconds
        self._refractory = refractory_seconds
        self._sample_interval = sample_interval_seconds
        self._state = "idle"
        self._onset_samples = 0
        self._settle_samples = 0
        self._refractory_samples = 0
        self._last_angles = None
        self._baseline_acceleration = None
        self._filtered_linear = (0.0, 0.0, 0.0)
        self._noise_floor = 0.0
        self._axis = None
        self._sample_count = 0
        self._velocity = 0.0
        self._displacement = 0.0
        self._peak_excursion = 0.0
        self._peak_velocity = 0.0
        self._velocity_total = 0.0
        self._velocity_samples = 0
        self._returned = False
        self._rejected_cycles = 0

    def update(self, movement_g, sample=None, activity_score=None):
        if movement_g is None or sample is None:
            return None
        score = self.activity_score(movement_g, sample) if activity_score is None else activity_score
        linear = self._filtered_linear
        start_threshold = self._dynamic_start_threshold()
        end_threshold = self._dynamic_end_threshold()
        if self._state == "refractory":
            self._refractory_samples -= 1
            if self._refractory_samples <= 0:
                self._state = "idle"
            return None

        if self._state == "idle":
            if score >= start_threshold:
                self._onset_samples += 1
            else:
                self._onset_samples = 0
                self._adapt_baseline(sample)
                self._noise_floor = self._noise_floor * 0.98 + score * 0.02
            if self._onset_samples < REP_ONSET_SAMPLES:
                return None
            self._start_cycle(linear)
            return None

        self._sample_count += 1
        if score <= end_threshold:
            self._settle_samples += 1
            self._velocity = 0.0
        else:
            self._settle_samples = 0
            projected_acceleration = sum(
                component * axis for component, axis in zip(linear, self._axis)
            ) * 9.80665
            self._velocity += projected_acceleration * self._sample_interval
            self._displacement += self._velocity * self._sample_interval
            self._peak_velocity = max(self._peak_velocity, abs(self._velocity))
            self._velocity_total += abs(self._velocity)
            self._velocity_samples += 1
        excursion = abs(self._displacement)
        self._peak_excursion = max(self._peak_excursion, excursion)
        return_tolerance = max(0.015, self._peak_excursion * 0.40)
        if self._peak_excursion >= REP_MIN_EXCURSION_METERS and excursion <= return_tolerance:
            self._returned = True

        duration = self._sample_count * self._sample_interval
        if (
            duration >= self._min_duration
            and self._returned
            and self._peak_excursion >= REP_MIN_EXCURSION_METERS
        ):
            mean_velocity = self._velocity_total / max(1, self._velocity_samples)
            peak_velocity = self._peak_velocity
            self._reset_cycle(refractory=True)
            return {
                "duration_ms": max(1, round(duration * 1000)),
                "mean_velocity": round(min(MAX_REP_VELOCITY_MPS, mean_velocity), 3),
                "peak_velocity": round(min(MAX_REP_VELOCITY_MPS, peak_velocity), 3),
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        if duration > self._max_duration:
            self._rejected_cycles += 1
            self._reset_cycle()
            return None
        if self._settle_samples < REP_SETTLE_SAMPLES:
            return None
        self._rejected_cycles += 1
        self._reset_cycle()
        return None

    def diagnostics(self):
        return {
            "state": self._state,
            "noise_floor": round(self._noise_floor, 4),
            "start_threshold": round(self._dynamic_start_threshold(), 4),
            "settle_threshold": round(self._dynamic_end_threshold(), 4),
            "peak_excursion_m": round(self._peak_excursion, 4),
            "rejected_cycles": self._rejected_cycles,
        }

    def _dynamic_start_threshold(self):
        return max(self._start_threshold, self._noise_floor * 2.5)

    def _dynamic_end_threshold(self):
        return min(
            self._dynamic_start_threshold() * 0.8,
            max(self._end_threshold, self._noise_floor * 1.75),
        )

    def _start_cycle(self, linear):
        dominant = max(range(3), key=lambda index: abs(linear[index]))
        direction = 1.0 if linear[dominant] >= 0 else -1.0
        self._axis = tuple(direction if index == dominant else 0.0 for index in range(3))
        self._state = "active"
        self._onset_samples = 0
        self._settle_samples = 0
        self._sample_count = 0
        self._velocity = 0.0
        self._displacement = 0.0
        self._peak_excursion = 0.0
        self._peak_velocity = 0.0
        self._velocity_total = 0.0
        self._velocity_samples = 0
        self._returned = False

    def _reset_cycle(self, refractory=False):
        self._state = "refractory" if refractory else "idle"
        self._refractory_samples = math.ceil(self._refractory / self._sample_interval) if refractory else 0
        self._onset_samples = 0
        self._settle_samples = 0
        self._axis = None

    def _linear_acceleration(self, sample):
        acceleration = self._world_acceleration(sample)
        if self._baseline_acceleration is None:
            self._baseline_acceleration = acceleration
        raw = tuple(
            current - baseline
            for current, baseline in zip(acceleration, self._baseline_acceleration)
        )
        self._filtered_linear = tuple(
            previous * 0.65 + current * 0.35
            for previous, current in zip(self._filtered_linear, raw)
        )
        return self._filtered_linear

    def _adapt_baseline(self, sample):
        acceleration = self._world_acceleration(sample)
        if self._baseline_acceleration is None:
            self._baseline_acceleration = acceleration
            return
        self._baseline_acceleration = tuple(
            baseline * 0.995 + current * 0.005
            for current, baseline in zip(acceleration, self._baseline_acceleration)
        )

    @staticmethod
    def _world_acceleration(sample):
        roll, pitch, yaw = (math.radians(value) for value in sample.angle_degrees)
        cr, sr = math.cos(roll), math.sin(roll)
        cp, sp = math.cos(pitch), math.sin(pitch)
        cy, sy = math.cos(yaw), math.sin(yaw)
        x, y, z = sample.acceleration_g
        return (
            (cy * cp) * x + (cy * sp * sr - sy * cr) * y + (cy * sp * cr + sy * sr) * z,
            (sy * cp) * x + (sy * sp * sr + cy * cr) * y + (sy * sp * cr - cy * sr) * z,
            (-sp) * x + (cp * sr) * y + (cp * cr) * z,
        )

    def activity_score(self, movement_g, sample):
        if sample is None:
            return movement_g
        linear = self._linear_acceleration(sample)
        acceleration_score = math.sqrt(sum(component * component for component in linear))
        gyro_magnitude = math.sqrt(sum(axis * axis for axis in sample.angular_velocity_dps))
        gyro_score = min(MAX_MOVEMENT_G, gyro_magnitude / 400.0)
        angle_score = 0.0
        if self._last_angles is not None:
            angle_delta = math.sqrt(sum(
                min(abs(current - previous), 360.0 - abs(current - previous)) ** 2
                for current, previous in zip(sample.angle_degrees, self._last_angles)
            ))
            angle_score = min(MAX_MOVEMENT_G, angle_delta / 30.0)
        self._last_angles = sample.angle_degrees
        return max(movement_g, acceleration_score, gyro_score, angle_score)


class MqttRepPublisher:
    def __init__(self, host=DEFAULT_MQTT_HOST, port=DEFAULT_MQTT_PORT):
        import paho.mqtt.client as mqtt

        self._host = host
        self._port = port
        self._client = mqtt.Client()
        self._connected = False
        self._rep_numbers = {}

    def publish(self, node_id, rep):
        node_id = validate_node_id(node_id)
        if not self._ensure_connected():
            return False
        rep_number = self._rep_numbers.get(node_id, 0) + 1
        self._rep_numbers[node_id] = rep_number
        payload = {
            "node_id": node_id,
            "rep_number": rep_number,
            "mean_velocity": rep["mean_velocity"],
            "peak_velocity": rep["peak_velocity"],
            "duration_ms": rep["duration_ms"],
            "timestamp": rep["timestamp"],
        }
        try:
            result = self._client.publish(
                f"edgeathlete/node/{node_id}/rep",
                json.dumps(payload, separators=(",", ":")),
                qos=1,
            )
        except Exception:
            self._connected = False
            return False
        if self._return_code(result) != 0:
            self._connected = False
            return False
        return True

    def publish_pulse(self, node_id):
        node_id = validate_node_id(node_id)
        if not self._ensure_connected():
            return False
        payload = {
            "node_id": node_id,
            "event_type": "pulse",
            "battery_level": None,
            "signal_strength": None,
            "firmware_version": "wt901-agent-1",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        try:
            result = self._client.publish(
                f"edgeathlete/node/{node_id}/pulse",
                json.dumps(payload, separators=(",", ":")),
                qos=1,
            )
        except Exception:
            self._connected = False
            return False
        if self._return_code(result) != 0:
            self._connected = False
            return False
        return True

    def _ensure_connected(self):
        if self._connected:
            return True
        try:
            result = self._client.connect(self._host, self._port, 60)
        except Exception:
            return False
        if self._return_code(result) != 0:
            return False
        self._client.loop_start()
        self._connected = True
        return True

    @staticmethod
    def _return_code(result):
        if result is None:
            return 0
        if isinstance(result, int):
            return result
        if isinstance(result, tuple) and result:
            return result[0]
        return getattr(result, "rc", 0)

    def close(self):
        if self._connected:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False


class AgentStatus:
    """Only privacy-safe derived health exposed to the local rack browser."""

    def __init__(self, node_id):
        self.node_id = validate_node_id(node_id)
        self.state = "starting"
        self.movement_g = None
        self.activity_score = None
        self.detector = None
        self.accepted_reps = 0
        self.frames_received = 0
        self.last_sample_monotonic = None

    def sample(self, movement_g, activity_score=None, detector=None):
        self.state = "live"
        self.movement_g = movement_g
        self.activity_score = activity_score
        self.detector = detector
        self.frames_received += 1
        self.last_sample_monotonic = time.monotonic()

    def accepted_rep(self):
        self.accepted_reps += 1

    def payload(self):
        age_ms = None
        if self.last_sample_monotonic is not None:
            age_ms = max(0, round((time.monotonic() - self.last_sample_monotonic) * 1000))
        state = self.state
        if state == "live" and (age_ms is None or age_ms > 1000):
            state = "stale"
        return {
            "schema_version": 1,
            "node_id": self.node_id,
            "state": state,
            "movement_g": self.movement_g if state == "live" else None,
            "activity_score": self.activity_score if state == "live" else None,
            "accepted_reps": self.accepted_reps,
            "detector": self.detector,
            "sample_age_ms": age_ms,
            "frames_received": self.frames_received,
        }


def validate_node_id(node_id):
    if not isinstance(node_id, str) or NODE_ID_PATTERN.fullmatch(node_id) is None:
        raise ValueError("node ID must match ^[A-Za-z0-9_-]{1,64}$")
    return node_id


def is_loopback_bind(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def register_node(base_url, node_id):
    """Announce this node to the base station. Best-effort and idempotent: a
    network blip during a laptop boot must not kill the agent. The server's
    register endpoint is open and get_or_create'd, exactly like a rack screen."""
    node_id = validate_node_id(node_id)
    url = base_url.rstrip("/") + "/api/nodes/register/"
    body = json.dumps({"node_id": node_id}).encode("utf-8")
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                response.read()
            print(f"[*] registered node {node_id} at {url}", flush=True)
            return True
        except (urllib.error.URLError, OSError) as error:
            delay = 2.0 * attempt
            print(
                f"[!] node registration attempt {attempt} failed ({type(error).__name__}); "
                f"retrying in {delay:.0f}s",
                flush=True,
            )
            time.sleep(delay)
    print(f"[!] giving up on node registration until the agent restarts", flush=True)
    return False


def capture_sample(sample, movement_g, activity_score, diagnostics, now=None):
    """One privacy-safe decoded sample for offline detector qualification.

    This is the one place the agent writes sensor data to disk. It is opt-in
    (--capture-path), contains only decoded IMU values and derived movement —
    never raw bytes, never athlete data, never a BLE address — and exists solely
    so the provisional detector can be qualified against real lifts."""
    now = time.monotonic() if now is None else now
    return {
        "kind": "sample",
        "t_ms": round(now * 1000),
        "movement_g": movement_g,
        "activity_score": activity_score,
        "ax": round(sample.acceleration_g[0], 4),
        "ay": round(sample.acceleration_g[1], 4),
        "az": round(sample.acceleration_g[2], 4),
        "gx": round(sample.angular_velocity_dps[0], 2),
        "gy": round(sample.angular_velocity_dps[1], 2),
        "gz": round(sample.angular_velocity_dps[2], 2),
        "rx": round(sample.angle_degrees[0], 2),
        "ry": round(sample.angle_degrees[1], 2),
        "rz": round(sample.angle_degrees[2], 2),
        "detector": diagnostics,
    }


def manual_rep_marker(count, now=None):
    now = time.monotonic() if now is None else now
    return {"kind": "manual_rep", "n": count, "t_ms": round(now * 1000)}


def sanitize_label(label):
    if not isinstance(label, str):
        return "WT901"
    normalized = unicodedata.normalize("NFKC", label)
    cleaned = "".join(
        character for character in normalized
        if not unicodedata.category(character).startswith("C")
    ).strip()
    encoded = bytearray()
    for character in cleaned:
        chunk = character.encode("utf-8")
        if len(encoded) + len(chunk) > MAX_LABEL_BYTES:
            break
        encoded.extend(chunk)
    bounded = encoded.decode("utf-8")
    return bounded if bounded.upper().startswith("WT901") else "WT901"


def is_wt901_label(label):
    if not isinstance(label, str):
        return False
    normalized = unicodedata.normalize("NFKC", label)
    visible = "".join(
        character for character in normalized
        if not unicodedata.category(character).startswith("C")
    ).strip()
    return visible.upper().startswith("WT901")


def validate_private_address(address):
    if not isinstance(address, str) or not address or len(address.encode("utf-8")) > MAX_ADDRESS_BYTES:
        raise ValueError("invalid private device address")
    if any(unicodedata.category(character).startswith("C") for character in address):
        raise ValueError("invalid private device address")
    return address


class ApiError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


class EnrollmentAgent:
    """Keep BlueZ identities and physical bindings inside the Agent."""

    def __init__(
        self, scanner, client_factory, state_path=None, clock=time.monotonic,
        scan_seconds=DEFAULT_SCAN_SECONDS, handle_ttl_seconds=DEFAULT_HANDLE_TTL_SECONDS,
        verification_ttl_seconds=DEFAULT_VERIFICATION_TTL_SECONDS,
        verification_timeout_seconds=5, calibration_samples=50,
        sample_interval_seconds=SAMPLE_INTERVAL_SECONDS,
        sleep=asyncio.sleep, rep_publisher_factory=None,
    ):
        self._scanner = scanner
        self._client_factory = client_factory
        self._state_path = state_path
        self._clock = clock
        self._scan_seconds = scan_seconds
        self._handle_ttl = handle_ttl_seconds
        self._verification_ttl = verification_ttl_seconds
        self._verification_timeout = verification_timeout_seconds
        self._calibration_samples = calibration_samples
        self._sample_interval = sample_interval_seconds
        self._sleep = sleep
        self._handles = {}
        self._verifications = {}
        self._bindings = {}
        self._rollbacks = {}
        self._statuses = {}
        self._binding_tasks = {}
        self._rep_publisher_factory = rep_publisher_factory
        self._rep_publishers = {}
        if state_path:
            self._load_state()

    def start(self):
        for binding_token in self._bindings:
            self._start_binding(binding_token)

    async def close(self):
        tasks = list(self._binding_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._binding_tasks.clear()
        publishers = list(self._rep_publishers.values())
        self._rep_publishers.clear()
        for publisher in publishers:
            publisher.close()

    def _start_binding(self, binding_token):
        if binding_token in self._binding_tasks:
            return
        binding = self._bindings[binding_token]
        status = AgentStatus(binding["node_id"])
        status.state = "reconnecting"
        self._statuses[binding_token] = status
        rep_publisher = None
        if self._rep_publisher_factory is not None:
            rep_publisher = self._rep_publisher_factory()
            self._rep_publishers[binding_token] = rep_publisher
        self._binding_tasks[binding_token] = asyncio.create_task(
            self._acquire_binding(binding_token, binding, status, rep_publisher)
        )

    async def _acquire_binding(self, binding_token, binding, status, rep_publisher):
        retry_seconds = 1.0
        while True:
            notifications = asyncio.Queue(maxsize=32)
            disconnected = asyncio.Event()
            loop = asyncio.get_running_loop()

            def on_disconnect(_client):
                loop.call_soon_threadsafe(disconnected.set)

            def enqueue_notification(data):
                if notifications.full():
                    try:
                        notifications.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                notifications.put_nowait(bytes(data))

            def on_notification(_characteristic, data):
                loop.call_soon_threadsafe(enqueue_notification, data)

            try:
                status.state = "reconnecting"
                async with self._client_factory(
                    binding["address"], timeout=15, disconnected_callback=on_disconnect,
                ) as client:
                    service = client.services.get_service(SERVICE_UUID)
                    if service is None or service.get_characteristic(NOTIFY_UUID) is None:
                        raise RuntimeError("bound device lacks WT901 notify service")
                    decoder = WT901FrameDecoder()
                    estimator = MovementEstimator(self._calibration_samples)
                    detector = ProvisionalRepDetector(
                        sample_interval_seconds=self._sample_interval,
                    )
                    await client.start_notify(NOTIFY_UUID, on_notification)
                    retry_seconds = 1.0
                    last_notification = time.monotonic()
                    while not disconnected.is_set():
                        try:
                            chunk = await asyncio.wait_for(notifications.get(), timeout=1)
                        except asyncio.TimeoutError:
                            if time.monotonic() - last_notification > 2:
                                raise RuntimeError("WT901 notification stream stalled")
                            continue
                        last_notification = time.monotonic()
                        for sample in decoder.feed(chunk):
                            movement = estimator.update(sample)
                            if movement is not None:
                                activity_score = detector.activity_score(movement, sample)
                                rep = detector.update(
                                    movement, sample, activity_score=activity_score,
                                )
                                status.sample(
                                    movement, activity_score, detector.diagnostics(),
                                )
                                if (
                                    rep is not None
                                    and rep_publisher is not None
                                    and rep_publisher.publish(binding["node_id"], rep)
                                ):
                                    status.accepted_rep()
                    raise RuntimeError("WT901 disconnected")
            except asyncio.CancelledError:
                raise
            except Exception:
                status.state = "stale" if status.last_sample_monotonic is not None else "reconnecting"
                status.movement_g = None
                delay = retry_seconds + random.uniform(0, min(1.0, retry_seconds / 4))
                await self._sleep(delay)
                retry_seconds = min(30.0, retry_seconds * 2)

    def _expire_transient(self):
        now = self._clock()
        self._handles = {key: value for key, value in self._handles.items() if value["expires"] > now}
        self._verifications = {
            key: value for key, value in self._verifications.items() if value["expires"] > now
        }

    async def scan(self):
        self._expire_transient()
        try:
            discovered = await self._scanner.discover(timeout=self._scan_seconds, return_adv=True)
        except Exception as error:
            raise ApiError(503, "scan_unavailable") from error
        self._handles.clear()
        devices = []
        entries = discovered.values() if isinstance(discovered, dict) else discovered
        for entry in entries:
            if len(devices) >= MAX_DISCOVERED_DEVICES:
                break
            try:
                device, advertisement = entry
            except (TypeError, ValueError):
                continue
            advertised_label = getattr(advertisement, "local_name", None) or getattr(device, "name", None)
            if not is_wt901_label(advertised_label):
                continue
            label = sanitize_label(advertised_label)
            handle = secrets.token_urlsafe(24)
            self._handles[handle] = {
                "address": device.address,
                "label": label,
                "expires": self._clock() + self._handle_ttl,
            }
            devices.append({"handle": handle, "label": label})
        return {"schema_version": 1, "devices": devices, "expires_in_seconds": self._handle_ttl}

    async def verify(self, handle):
        self._expire_transient()
        selected = self._handles.pop(handle, None)
        if selected is None:
            raise ApiError(404, "scan_handle_expired")
        notifications = asyncio.Queue(maxsize=16)

        def on_notification(_characteristic, data):
            if not notifications.full():
                notifications.put_nowait(bytes(data))

        try:
            async with self._client_factory(selected["address"], timeout=15) as client:
                service = client.services.get_service(SERVICE_UUID)
                if service is None or service.get_characteristic(NOTIFY_UUID) is None:
                    raise ApiError(422, "not_wt901_notify_device")
                decoder = WT901FrameDecoder()
                estimator = MovementEstimator(calibration_samples=self._calibration_samples)
                await client.start_notify(NOTIFY_UUID, on_notification)
                deadline = self._clock() + self._verification_timeout
                decoded_frames = 0
                movement = None
                while movement is None or movement < VERIFICATION_MOVEMENT_THRESHOLD_G:
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        code = "movement_not_confirmed" if decoded_frames else "fresh_frames_unavailable"
                        raise ApiError(422, code)
                    try:
                        chunk = await asyncio.wait_for(notifications.get(), timeout=remaining)
                    except asyncio.TimeoutError as error:
                        code = "movement_not_confirmed" if decoded_frames else "fresh_frames_unavailable"
                        raise ApiError(422, code) from error
                    for sample in decoder.feed(chunk):
                        decoded_frames += 1
                        estimate = estimator.update(sample)
                        if estimate is not None and (movement is None or estimate > movement):
                            movement = estimate
        except ApiError:
            raise
        except asyncio.TimeoutError as error:
            raise ApiError(422, "fresh_frames_unavailable") from error
        except Exception as error:
            raise ApiError(503, "verification_unavailable") from error
        token = secrets.token_urlsafe(32)
        if len(self._verifications) >= MAX_PENDING_VERIFICATIONS:
            oldest = min(self._verifications, key=lambda key: self._verifications[key]["expires"])
            del self._verifications[oldest]
        self._verifications[token] = {
            **selected, "movement_g": movement,
            "expires": self._clock() + self._verification_ttl,
        }
        return {
            "schema_version": 1, "label": selected["label"], "movement_g": movement,
            "verification_token": token, "expires_in_seconds": self._verification_ttl,
        }

    def bind(self, verification_token, rack_number, expected_node_id):
        if type(rack_number) is not int or not 1 <= rack_number <= MAX_RACK_NUMBER:
            raise ApiError(400, "invalid_rack_number")
        if expected_node_id is not None:
            try:
                validate_node_id(expected_node_id)
            except ValueError as error:
                raise ApiError(400, "invalid_expected_node_id") from error
        self._expire_transient()
        verified = self._verifications.get(verification_token)
        if verified is None:
            raise ApiError(404, "verification_expired")
        current = next(
            (
                (token, value) for token, value in self._bindings.items()
                if value["rack_number"] == rack_number
            ),
            None,
        )
        if (
            (expected_node_id is None and current is not None)
            or (expected_node_id is not None and (
                current is None or current[1]["node_id"] != expected_node_id
            ))
        ):
            raise ApiError(409, "binding_reconciliation_required")
        current_token = current[0] if current else None
        if any(
            token != current_token and value["address"] == verified["address"]
            for token, value in self._bindings.items()
        ):
            raise ApiError(409, "device_already_bound")
        binding_token = secrets.token_urlsafe(32)
        node_id = f"wt901_{secrets.token_hex(12)}"
        new_binding = {
            "rack_number": rack_number, "node_id": node_id,
            "address": verified["address"], "label": verified["label"],
        }
        proposed_bindings = dict(self._bindings)
        proposed_rollbacks = dict(self._rollbacks)
        if current is not None:
            del proposed_bindings[current_token]
            proposed_rollbacks.pop(current_token, None)
            proposed_rollbacks[binding_token] = {
                "binding_token": current_token,
                "binding": dict(current[1]),
            }
        proposed_bindings[binding_token] = new_binding
        self._persist_state(proposed_bindings, proposed_rollbacks)

        old_task = self._binding_tasks.pop(current_token, None) if current_token else None
        self._statuses.pop(current_token, None)
        old_publisher = self._rep_publishers.pop(current_token, None) if current_token else None
        if old_publisher is not None:
            old_publisher.close()
        self._bindings = proposed_bindings
        self._rollbacks = proposed_rollbacks
        self._verifications.pop(verification_token, None)
        self._start_binding(binding_token)
        if old_task is not None:
            old_task.cancel()
        return {
            "schema_version": 1, "rack_number": rack_number,
            "node_id": node_id, "label": verified["label"],
            "binding_token": binding_token,
        }

    def unbind(self, binding_token):
        binding = self._bindings.get(binding_token)
        if binding is None:
            raise ApiError(404, "binding_not_found")
        rollback = self._rollbacks.get(binding_token)
        proposed_bindings = dict(self._bindings)
        del proposed_bindings[binding_token]
        proposed_rollbacks = dict(self._rollbacks)
        proposed_rollbacks.pop(binding_token, None)
        if rollback is not None:
            proposed_bindings[rollback["binding_token"]] = dict(rollback["binding"])
        self._persist_state(proposed_bindings, proposed_rollbacks)

        task = self._binding_tasks.pop(binding_token, None)
        if task is not None:
            task.cancel()
        self._statuses.pop(binding_token, None)
        publisher = self._rep_publishers.pop(binding_token, None)
        if publisher is not None:
            publisher.close()
        self._bindings = proposed_bindings
        self._rollbacks = proposed_rollbacks
        if rollback is not None:
            self._start_binding(rollback["binding_token"])
        return {
            "schema_version": 1, "rack_number": binding["rack_number"],
            "node_id": rollback["binding"]["node_id"] if rollback else binding["node_id"],
            "state": "rolled_back" if rollback else "unbound",
        }

    def rack_health(self, rack_number):
        if type(rack_number) is not int or not 1 <= rack_number <= MAX_RACK_NUMBER:
            raise ApiError(400, "invalid_rack_number")
        match = next(
            (
                (token, value) for token, value in self._bindings.items()
                if value["rack_number"] == rack_number
            ),
            None,
        )
        if match is None:
            raise ApiError(404, "rack_not_bound")
        binding_token, binding = match
        status = self._statuses.get(binding_token)
        health = status.payload() if status is not None else {
            "state": "reconnecting", "movement_g": None, "sample_age_ms": None,
        }
        return {
            "schema_version": 1, "rack_number": rack_number, "node_id": binding["node_id"],
            "label": binding["label"], "state": health["state"],
            "movement_g": health["movement_g"],
            "activity_score": health.get("activity_score"),
            "accepted_reps": health.get("accepted_reps", 0),
            "detector": health.get("detector"),
            "sample_age_ms": health["sample_age_ms"],
        }

    def _load_state(self):
        flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self._state_path, flags)
        except FileNotFoundError:
            return
        except OSError as error:
            raise ValueError("unsafe Agent binding state") from error
        try:
            metadata = os.fstat(fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077
                or metadata.st_size > MAX_STATE_BYTES
            ):
                raise ValueError("unsafe Agent binding state")
            chunks = []
            remaining = MAX_STATE_BYTES + 1
            while remaining:
                chunk = os.read(fd, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw_state = b"".join(chunks)
        finally:
            os.close(fd)
        if len(raw_state) > MAX_STATE_BYTES:
            raise ValueError("Agent binding state is too large")
        try:
            stored = json.loads(raw_state.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("invalid Agent binding state") from error
        if (
            not isinstance(stored, dict)
            or stored.get("schema_version") != 1
            or not set(stored).issubset({"schema_version", "bindings", "rollbacks"})
        ):
            raise ValueError("invalid Agent binding state")
        bindings = stored.get("bindings")
        rollbacks = stored.get("rollbacks", [])
        if (
            not isinstance(bindings, list) or len(bindings) > MAX_RACK_NUMBER
            or not isinstance(rollbacks, list) or len(rollbacks) > MAX_RACK_NUMBER
        ):
            raise ValueError("invalid Agent binding state")
        for item in bindings:
            expected = {"binding_token", "rack_number", "node_id", "address", "label"}
            if not isinstance(item, dict) or set(item) != expected:
                raise ValueError("invalid Agent binding state")
            token = item["binding_token"]
            if not isinstance(token, str) or OPAQUE_TOKEN_PATTERN.fullmatch(token) is None:
                raise ValueError("invalid Agent binding state")
            if not isinstance(item["node_id"], str) or GENERATED_NODE_ID_PATTERN.fullmatch(item["node_id"]) is None:
                raise ValueError("invalid Agent binding state")
            if type(item["rack_number"]) is not int or not 1 <= item["rack_number"] <= MAX_RACK_NUMBER:
                raise ValueError("invalid Agent binding state")
            try:
                address = validate_private_address(item["address"])
            except ValueError as error:
                raise ValueError("invalid Agent binding state") from error
            if not isinstance(item["label"], str):
                raise ValueError("invalid Agent binding state")
            self._bindings[token] = {
                "rack_number": item["rack_number"], "node_id": item["node_id"],
                "address": address, "label": sanitize_label(item["label"]),
            }
        racks = [value["rack_number"] for value in self._bindings.values()]
        addresses = [value["address"] for value in self._bindings.values()]
        if (
            len(self._bindings) != len(bindings)
            or len(racks) != len(set(racks))
            or len(addresses) != len(set(addresses))
        ):
            raise ValueError("duplicate Agent binding state")
        for item in rollbacks:
            if not isinstance(item, dict) or set(item) != {
                "binding_token", "previous_binding_token", "previous_binding",
            }:
                raise ValueError("invalid Agent rollback state")
            token = item["binding_token"]
            previous_token = item["previous_binding_token"]
            previous = item["previous_binding"]
            if (
                not isinstance(token, str) or token not in self._bindings
                or not isinstance(previous_token, str)
                or OPAQUE_TOKEN_PATTERN.fullmatch(previous_token) is None
                or previous_token in self._bindings
                or token in self._rollbacks
                or not isinstance(previous, dict)
                or set(previous) != {"rack_number", "node_id", "address", "label"}
                or not isinstance(previous["node_id"], str)
                or GENERATED_NODE_ID_PATTERN.fullmatch(previous["node_id"]) is None
                or previous["rack_number"] != self._bindings[token]["rack_number"]
            ):
                raise ValueError("invalid Agent rollback state")
            try:
                previous_address = validate_private_address(previous["address"])
            except ValueError as error:
                raise ValueError("invalid Agent rollback state") from error
            if not isinstance(previous["label"], str):
                raise ValueError("invalid Agent rollback state")
            self._rollbacks[token] = {
                "binding_token": previous_token,
                "binding": {
                    **previous, "address": previous_address,
                    "label": sanitize_label(previous["label"]),
                },
            }

    def _persist_state(self, bindings=None, rollbacks=None):
        if not self._state_path:
            return
        bindings = self._bindings if bindings is None else bindings
        rollbacks = self._rollbacks if rollbacks is None else rollbacks
        state = {
            "schema_version": 1,
            "bindings": [{"binding_token": token, **value} for token, value in bindings.items()],
            "rollbacks": [
                {
                    "binding_token": token,
                    "previous_binding_token": rollback["binding_token"],
                    "previous_binding": rollback["binding"],
                }
                for token, rollback in rollbacks.items()
            ],
        }
        encoded_state = json.dumps(state, separators=(",", ":")).encode("utf-8")
        if len(encoded_state) > MAX_STATE_BYTES:
            raise ValueError("Agent binding state is too large")
        directory = os.path.dirname(os.path.abspath(self._state_path))
        fd, temporary_path = tempfile.mkstemp(prefix=".wt901-bindings-", dir=directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as state_file:
                state_file.write(encoded_state)
                state_file.flush()
                os.fsync(state_file.fileno())
            os.replace(temporary_path, self._state_path)
            os.chmod(self._state_path, 0o600)
        except Exception:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
            raise


def _require_object(body, keys):
    if not isinstance(body, dict) or set(body) != set(keys):
        raise ApiError(400, "invalid_request_body")
    return body


async def route_uds_request(enrollment, method, path, body):
    rack_match = re.fullmatch(r"/v1/racks/([0-9]+)/health", path)
    binding_match = re.fullmatch(r"/v1/bindings/([A-Za-z0-9_-]+)", path)
    known = path in {"/v1/scans", "/v1/verifications", "/v1/bindings"} or rack_match or binding_match
    if method == "POST" and path == "/v1/scans":
        _require_object(body, set())
        return 200, await enrollment.scan()
    if method == "POST" and path == "/v1/verifications":
        request = _require_object(body, {"handle"})
        handle = request["handle"]
        if not isinstance(handle, str) or OPAQUE_TOKEN_PATTERN.fullmatch(handle) is None:
            raise ApiError(400, "invalid_scan_handle")
        return 200, await enrollment.verify(handle)
    if method == "POST" and path == "/v1/bindings":
        request = _require_object(
            body, {"verification_token", "rack_number", "expected_node_id"},
        )
        token = request["verification_token"]
        if not isinstance(token, str) or OPAQUE_TOKEN_PATTERN.fullmatch(token) is None:
            raise ApiError(400, "invalid_verification_token")
        return 201, enrollment.bind(
            token, request["rack_number"], request["expected_node_id"],
        )
    if method == "DELETE" and binding_match:
        return 200, enrollment.unbind(binding_match.group(1))
    if method == "GET" and rack_match:
        return 200, enrollment.rack_health(int(rack_match.group(1)))
    if known:
        raise ApiError(405, "method_not_allowed")
    raise ApiError(404, "not_found")


async def _handle_uds_connection(enrollment, reader, writer):
    try:
        header_bytes = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2)
        if len(header_bytes) > MAX_HTTP_HEADER_BYTES:
            raise ApiError(431, "headers_too_large")
        lines = header_bytes.decode("ascii").split("\r\n")
        request_parts = lines[0].split(" ")
        if len(request_parts) != 3 or request_parts[2] != "HTTP/1.1":
            raise ApiError(400, "invalid_request")
        method, path, _version = request_parts
        headers = {}
        for line in lines[1:]:
            if not line:
                continue
            if ":" not in line:
                raise ApiError(400, "invalid_request")
            key, value = line.split(":", 1)
            key = key.strip().lower()
            if not key or key in headers:
                raise ApiError(400, "invalid_request")
            headers[key] = value.strip()
        if "transfer-encoding" in headers:
            raise ApiError(400, "invalid_request")
        length_text = headers.get("content-length")
        if method == "POST":
            if headers.get("content-type") != "application/json" or length_text is None:
                raise ApiError(400, "invalid_request")
            try:
                length = int(length_text)
            except ValueError as error:
                raise ApiError(400, "invalid_request") from error
            if length < 2 or length > MAX_HTTP_BODY_BYTES:
                status = 413 if length > MAX_HTTP_BODY_BYTES else 400
                raise ApiError(status, "invalid_body_size")
            raw_body = await asyncio.wait_for(reader.readexactly(length), timeout=2)
            try:
                body = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ApiError(400, "invalid_json") from error
        else:
            if length_text not in (None, "0"):
                raise ApiError(400, "unexpected_body")
            body = None
        status, payload = await route_uds_request(enrollment, method, path, body)
    except ApiError as error:
        status, payload = error.status, {"code": error.code}
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, UnicodeDecodeError):
        status, payload = 400, {"code": "invalid_request"}
    except Exception:
        status, payload = 500, {"code": "internal_error"}
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    reasons = {
        200: "OK", 201: "Created", 400: "Bad Request", 404: "Not Found",
        405: "Method Not Allowed", 409: "Conflict", 413: "Content Too Large",
        422: "Unprocessable Content", 431: "Request Header Fields Too Large",
        500: "Internal Server Error", 503: "Service Unavailable",
    }
    writer.write(
        f"HTTP/1.1 {status} {reasons[status]}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(encoded)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n".encode()
        + encoded
    )
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def serve_uds(enrollment, socket_path):
    try:
        existing = os.stat(socket_path)
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISSOCK(existing.st_mode):
            raise ValueError("Agent socket path exists and is not a socket")
        os.unlink(socket_path)
    server = await asyncio.start_unix_server(
        lambda reader, writer: _handle_uds_connection(enrollment, reader, writer),
        path=socket_path,
        limit=MAX_HTTP_HEADER_BYTES + 1,
    )
    os.chmod(socket_path, 0o600)
    return server


async def serve_status(status, host, port, allowed_origins):
    if not is_loopback_bind(host):
        raise ValueError("Rack Agent health must bind to a loopback address")

    async def handle(reader, writer):
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2)
            lines = request.decode("latin-1").split("\r\n")
            method, path, _version = lines[0].split(" ", 2)
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.lower()] = value.strip()
            origin = headers.get("origin")
            allowed = origin is None or origin in allowed_origins
            if not allowed:
                code, body = "403 Forbidden", {"code": "origin_not_allowed"}
            elif method == "OPTIONS":
                code, body = "204 No Content", None
            elif method == "GET" and path == "/health":
                code, body = "200 OK", status.payload()
            else:
                code, body = "404 Not Found", {"code": "not_found"}
            encoded = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
            response_headers = [
                f"HTTP/1.1 {code}",
                "Content-Type: application/json",
                f"Content-Length: {len(encoded)}",
                "Cache-Control: no-store",
                "Connection: close",
            ]
            if origin and allowed:
                response_headers.extend([
                    f"Access-Control-Allow-Origin: {origin}",
                    "Vary: Origin",
                    "Access-Control-Allow-Methods: GET, OPTIONS",
                ])
            writer.write(("\r\n".join(response_headers) + "\r\n\r\n").encode() + encoded)
            await writer.drain()
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ValueError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    return await asyncio.start_server(handle, host, port)


async def run_agent(options):
    from bleak import BleakClient

    node_id = validate_node_id(options.node_id)
    status = AgentStatus(node_id)
    origins = {origin.strip() for origin in options.allowed_origins.split(",") if origin.strip()}
    server = await serve_status(status, options.bind, options.port, origins)
    retry_seconds = 1.0

    # Registration is best-effort and does NOT block the sensor. Retrying a dead
    # base station can take ~12s; the user is at the bar and the sensor should be
    # connected and calibrating during that window, not waiting for a server that
    # may not be powered on yet.
    threading.Thread(
        target=register_node, args=(options.base_url, node_id), daemon=True,
    ).start()

    publisher = MqttRepPublisher(options.mqtt_host, options.mqtt_port)
    capture_file = None
    marker_counter = {"n": 0}
    if options.capture_path:
        capture_file = open(options.capture_path, "a", encoding="utf-8")

    def write_record(record):
        if capture_file is not None:
            capture_file.write(json.dumps(record, separators=(",", ":")) + "\n")
            capture_file.flush()

    async def pulse_loop():
        while True:
            publisher.publish_pulse(node_id)
            await asyncio.sleep(options.pulse_interval)

    async def marker_loop():
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if line == "":
                return
            if not line.strip():
                continue
            marker_counter["n"] += 1
            write_record(manual_rep_marker(marker_counter["n"]))
            print(f"[*] marked manual rep {marker_counter['n']}", flush=True)

    pulse_task = asyncio.create_task(pulse_loop())
    marker_task = asyncio.create_task(marker_loop()) if capture_file is not None else None

    try:
        async with server:
            while True:
                notifications = asyncio.Queue(maxsize=32)
                disconnected = asyncio.Event()
                loop = asyncio.get_running_loop()

                def on_disconnect(_client):
                    loop.call_soon_threadsafe(disconnected.set)

                def on_notification(_characteristic, data):
                    chunk = bytes(data)
                    if notifications.full():
                        try:
                            notifications.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    notifications.put_nowait(chunk)

                try:
                    status.state = "connecting"
                    async with BleakClient(
                        options.address, timeout=15, disconnected_callback=on_disconnect,
                    ) as client:
                        service = client.services.get_service(SERVICE_UUID)
                        if service is None or service.get_characteristic(NOTIFY_UUID) is None:
                            raise RuntimeError("configured device lacks the WT901BLE notify service")
                        decoder = WT901FrameDecoder()
                        estimator = MovementEstimator(options.calibration_samples)
                        detector = ProvisionalRepDetector(
                            sample_interval_seconds=1.0 / options.hz,
                        )
                        status.state = "calibrating"
                        await client.start_notify(NOTIFY_UUID, on_notification)
                        retry_seconds = 1.0
                        last_notification = time.monotonic()
                        while not disconnected.is_set():
                            try:
                                chunk = await asyncio.wait_for(notifications.get(), timeout=1)
                            except asyncio.TimeoutError:
                                if time.monotonic() - last_notification > 2:
                                    raise RuntimeError("WT901BLE notification stream stalled")
                                continue
                            last_notification = time.monotonic()
                            for sample in decoder.feed(chunk):
                                movement = estimator.update(sample)
                                if movement is not None:
                                    activity_score = detector.activity_score(movement, sample)
                                    rep = detector.update(
                                        movement, sample, activity_score=activity_score,
                                    )
                                    status.sample(
                                        movement, activity_score, detector.diagnostics(),
                                    )
                                    write_record(capture_sample(
                                        sample, movement, activity_score,
                                        detector.diagnostics(),
                                    ))
                                    if rep is not None and publisher.publish(node_id, rep):
                                        status.accepted_rep()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    status.state = "retrying"
                    status.movement_g = None
                    print(f"WT901BLE unavailable ({type(error).__name__}); retrying.", flush=True)
                    delay = retry_seconds + random.uniform(0, min(1.0, retry_seconds / 4))
                    await asyncio.sleep(delay)
                    retry_seconds = min(30.0, retry_seconds * 2)
    finally:
        pulse_task.cancel()
        try:
            await pulse_task
        except asyncio.CancelledError:
            pass
        if marker_task is not None:
            marker_task.cancel()
            try:
                await marker_task
            except asyncio.CancelledError:
                pass
        publisher.close()
        if capture_file is not None:
            capture_file.close()


async def run_central_agent(options):
    from bleak import BleakClient, BleakScanner

    enrollment = EnrollmentAgent(
        BleakScanner,
        BleakClient,
        state_path=options.state_path,
        scan_seconds=options.scan_seconds,
        calibration_samples=options.calibration_samples,
        sample_interval_seconds=1.0 / options.hz,
        rep_publisher_factory=(
            (lambda: MqttRepPublisher(options.mqtt_host, options.mqtt_port))
            if options.enable_provisional_reps else None
        ),
    )
    socket_started = False
    try:
        enrollment.start()
        server = await serve_uds(enrollment, options.socket_path)
        socket_started = True
        async with server:
            await server.serve_forever()
    finally:
        await enrollment.close()
        if socket_started:
            try:
                os.unlink(options.socket_path)
            except FileNotFoundError:
                pass


async def run_scan(options):
    """Find nearby WT901BLE sensors and print their BLE addresses.

    BLE connections need a MAC address, which an interactive enrollment scan
    deliberately hides behind opaque handles. For a per-rack laptop there is no
    second machine in the loop, so discovery can show the real address once and
    a config file can remember it forever."""
    from bleak import BleakScanner

    devices = await BleakScanner.discover(timeout=options.scan_seconds)
    found = []
    for device in devices:
        if is_wt901_label(getattr(device, "name", None)):
            found.append(device)
    if not found:
        print("no WT901BLE sensors discovered; is one powered on and advertising?", flush=True)
        return
    for device in found:
        label = sanitize_label(device.name)
        print(
            f"{label}  address={device.address}  "
            f"rssi={getattr(device, 'rssi', None)}",
            flush=True,
        )
    print(f"discovered {len(found)} sensor(s); put the address in the rack config.", flush=True)


def parse_args(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", help="BLE address selected during physical enrollment")
    parser.add_argument("--node-id", help="logical node ID, never the BLE address")
    parser.add_argument("--socket-path", help="run central enrollment API on this Unix socket")
    parser.add_argument("--state-path", help="private central binding state file")
    parser.add_argument("--scan", action="store_true",
                        help="discover WT901BLE sensors and print their BLE addresses")
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", DEFAULT_BASE_URL),
                        help="base station origin for node registration")
    parser.add_argument("--capture-path", default=None,
                        help="append decoded IMU samples + manual rep markers to this JSONL file")
    parser.add_argument("--pulse-interval", type=float, default=DEFAULT_PULSE_INTERVAL_SECONDS)
    parser.add_argument("--scan-seconds", type=float, default=DEFAULT_SCAN_SECONDS)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--allowed-origins",
        default="http://127.0.0.1,http://localhost,http://basestation,http://192.168.4.1,http://127.0.0.1:8081,http://localhost:8081",
    )
    parser.add_argument("--calibration-samples", type=int, default=50)
    parser.add_argument("--hz", type=float, default=50.0,
                        help="WT901 output rate in samples/second; the detector integrates "
                             "velocity with a 1/Hz step, so this MUST match the sensor's "
                             "configured output rate")
    parser.add_argument("--mqtt-host", default=os.getenv("MQTT_HOST", DEFAULT_MQTT_HOST))
    parser.add_argument("--mqtt-port", type=int, default=int(os.getenv("MQTT_PORT", str(DEFAULT_MQTT_PORT))))
    parser.add_argument(
        "--enable-provisional-reps",
        action="store_true",
        help="publish provisional WT901 reps to MQTT; demo-only until replay/ACL fencing is implemented",
    )
    options = parser.parse_args(args)
    legacy = options.address is not None or options.node_id is not None
    if options.scan:
        if legacy or options.socket_path or options.capture_path:
            parser.error("--scan is standalone; it cannot be combined with address/node/socket/capture")
    elif legacy and (options.address is None or options.node_id is None):
        parser.error("--address and --node-id must be supplied together")
    elif legacy and options.socket_path:
        parser.error("legacy BLE mode and --socket-path are separate launch modes")
    elif not legacy and not options.socket_path:
        parser.error("supply --address/--node-id, --socket-path, or --scan")
    if options.state_path and not options.socket_path:
        parser.error("--state-path requires --socket-path")
    if options.scan_seconds <= 0 or options.scan_seconds > 30:
        parser.error("--scan-seconds must be greater than zero and at most 30")
    if options.hz <= 0 or options.hz > 2000:
        parser.error("--hz must be a positive sample rate at most 2000")
    if options.pulse_interval <= 0 or options.pulse_interval > 3600:
        parser.error("--pulse-interval must be positive and at most one hour")
    if options.mqtt_port <= 0 or options.mqtt_port > 65535:
        parser.error("--mqtt-port must be a valid TCP port")
    if not options.base_url.startswith(("http://", "https://")):
        parser.error("--base-url must start with http:// or https://")
    return options


async def run_until_stopped(options):
    if options.scan:
        target = run_scan
    else:
        target = run_central_agent if options.socket_path else run_agent
    task = asyncio.create_task(target(options))
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass


def main():
    asyncio.run(run_until_stopped(parse_args()))


if __name__ == "__main__":
    main()
