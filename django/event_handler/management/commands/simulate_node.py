# simulate_node.py - fake rack sensor for development and live demos.
#
# The real nodes don't exist yet. This stands in for one: it publishes the same
# pulse and rep messages on the same topics, so everything downstream — the
# tablet, Django's subscriber, the wall display — can be built and demoed
# against it without any hardware in the room.
#
# IT ALSO KNOWS WHEN TO SHUT UP. A real sensor bolted to a rack nobody is using
# should not be filling the broker with reps, and in a demo a rack that chatters
# while nobody stands at it makes the whole room look like noise. So the rep
# stream is GATED on whether the linked rack is actually busy — see the gate
# section below for what "busy" means and why it is a DB read rather than an
# HTTP call.
#
# The heartbeat is NOT gated, deliberately. Pulses are how Django knows the node
# is alive; going quiet on those would make an idle rack look like a dead one.

import json
import os
import random
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from django.core.management.base import BaseCommand
from django.db import close_old_connections

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

PULSE_INTERVAL_SECONDS = 5.0
# How often the gate re-reads the database. Short enough that a demo feels
# instant when a coach starts a set, long enough that an idle simulator is not
# hammering Postgres all afternoon.
GATE_POLL_SECONDS = 2.0

# The gate's three settings, from strictest to loosest.
MODE_LIFTING = "lifting"
MODE_CHECKIN = "checkin"
MODE_ALWAYS = "always"


def build_pulse_payload(node_id):
    """One fake heartbeat, battery/signal jitter within a realistic range."""
    return {
        "node_id": node_id,
        "event_type": "pulse",
        "battery_level": random.randint(80, 100),
        "signal_strength": random.randint(-70, -40),
        "firmware_version": "sim-1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_rep_payload(node_id, rep_number):
    """One fake rep, peak velocity is always a bit above mean, like a real lift."""
    mean_velocity = round(random.uniform(0.4, 1.1), 3)
    peak_velocity = round(mean_velocity + random.uniform(0.1, 0.3), 3)
    duration_ms = random.randint(600, 1100)

    return {
        "node_id": node_id,
        "rep_number": rep_number,
        "mean_velocity": mean_velocity,
        "peak_velocity": peak_velocity,
        "duration_ms": duration_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── the gate ────────────────────────────────────────────────────────────────
#
# WHY A DATABASE READ AND NOT A REST CALL. This is a Django management command,
# so it is already inside the ORM — GET /api/sessions/active/status/ would be
# the same rows via an HTTP hop, plus a base URL to configure and a service to
# be up. Reading directly means the simulator has no opinion about where the web
# server lives, and it cannot be broken by nginx.
#
# It reuses active_session() rather than writing its own "which day is live"
# query, because that helper exists precisely so nothing disagrees about it —
# four hand-written copies of that rule is what caused canon D18.


def rack_for_node(node_id):
    """The rack this node is linked to, or None if it isn't linked to one yet.

    Re-read on every poll rather than resolved once at startup, so a coach who
    links the sensor to a rack mid-demo sees it wake up on its own instead of
    having to restart the simulator.
    """
    from ...models import Node

    node = Node.objects.filter(node_id=node_id).values("rack_number").first()
    return node["rack_number"] if node else None


def rack_activity(rack_number, mode):
    """Is this rack busy right now? -> (active, token, why)

    `token` identifies WHAT is happening, so the caller can tell one set from
    the next: when it changes, a new set started and rep numbering restarts at
    1. `why` is a short human phrase for the log — a simulator that goes quiet
    without saying why is indistinguishable from one that has crashed.
    """
    from ...models import RackCheckIn, Set
    from ...services.active_session import active_session

    if mode == MODE_ALWAYS:
        return True, "always", "gate off"

    if rack_number is None:
        return False, None, "node is not linked to a rack"

    session = active_session()
    if session is None:
        return False, None, "no training day is running"

    # Athletes this rack currently owns. Check-ins are add-only and newest-wins
    # (the same shape as reference maxes), so an athlete's current rack is simply
    # their newest row — which is why this walks newest-first and keeps the first
    # one seen per athlete rather than filtering on rack_number in SQL. Filtering
    # directly would match an athlete who checked in here earlier and has since
    # moved to another rack.
    here = set()
    seen = set()
    for row in (RackCheckIn.objects
                .filter(session=session)
                .order_by("athlete_id", "-checked_in_at")
                .values_list("athlete_id", "rack_number")):
        athlete_id, rack = row
        if athlete_id in seen:
            continue
        seen.add(athlete_id)
        if rack == rack_number:
            here.add(athlete_id)

    if not here:
        return False, None, f"nobody is checked in at rack {rack_number}"

    if mode == MODE_CHECKIN:
        token = "checkin:" + ",".join(str(a) for a in sorted(here))
        return True, token, f"{len(here)} checked in at rack {rack_number}"

    # MODE_LIFTING — the strict one. A set with no end time is a set in progress;
    # that is the same test GET /api/sessions/active/status/ uses to call an
    # athlete "lifting", so the simulator and the room screens agree.
    open_set = (Set.objects
                .filter(session=session, athlete_id__in=here, ended_at__isnull=True)
                .order_by("-started_at", "-id")
                .values("id", "athlete_id")
                .first())
    if open_set is None:
        return False, None, f"checked in at rack {rack_number}, but no set is open"

    return True, f"set:{open_set['id']}", f"set {open_set['id']} is open"


class Command(BaseCommand):
    help = ("Simulate a rack sensor node, publishing fake pulse + rep traffic over MQTT. "
            "Reps pause while the linked rack is idle; pulses never stop.")

    def add_arguments(self, parser):
        parser.add_argument("--node-id", type=str, required=True,
                            help="Node ID to simulate, e.g. rack_1")
        parser.add_argument("--rack", type=int, default=None,
                            help="Rack number to watch. Default: whatever rack this "
                                 "node is linked to in the database.")
        parser.add_argument("--interval", type=float, default=3.0,
                            help="Seconds between reps (default: 3.0)")
        parser.add_argument("--reps-per-set", type=int, default=5,
                            help="Reps before a rest, in 'always' mode only (default: 5). "
                                 "In the gated modes the tablet decides where a set ends.")
        parser.add_argument("--active-when", choices=[MODE_LIFTING, MODE_CHECKIN, MODE_ALWAYS],
                            default=MODE_LIFTING,
                            help="When to publish reps. 'lifting' (default): only while a set "
                                 "is open at the rack. 'checkin': whenever anyone is checked in "
                                 "there. 'always': never pause — the old behaviour.")

    def handle(self, *args, **options):
        node_id = options["node_id"]
        fixed_rack = options["rack"]
        interval = options["interval"]
        reps_per_set = options["reps_per_set"]
        mode = options["active_when"]

        self.stdout.write(f"Starting simulate_node for {node_id} "
                          f"(gate: {mode}, rack: {fixed_rack or 'from database'})")

        client = mqtt.Client()
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()

        pulse_topic = f"edgeathlete/node/{node_id}/pulse"
        rep_topic = f"edgeathlete/node/{node_id}/rep"

        # Pulse runs on its own timer in the background, completely independent of
        # the rep loop below — and, since the gate arrived, independent of whether
        # the rack is busy. An idle node is still a healthy node.
        stop_event = threading.Event()

        def pulse_loop():
            while not stop_event.is_set():
                close_old_connections()
                payload = build_pulse_payload(node_id)
                client.publish(pulse_topic, json.dumps(payload), qos=1)
                stop_event.wait(PULSE_INTERVAL_SECONDS)

        pulse_thread = threading.Thread(target=pulse_loop, daemon=True)
        pulse_thread.start()

        rep_number = 0
        last_token = None
        last_why = None

        try:
            while True:
                # Long-running command: the connection can be dropped underneath
                # us (idle timeout, a database restart) and Django will keep
                # handing back the dead one until it is told to let go.
                close_old_connections()

                rack = fixed_rack if fixed_rack is not None else rack_for_node(node_id)
                active, token, why = rack_activity(rack, mode)

                # Say something only when the answer CHANGES. Logging every poll
                # buries the interesting moments in a wall of identical lines.
                if why != last_why:
                    state = "ACTIVE" if active else "idle"
                    self.stdout.write(f"[{node_id}] {state} — {why}")
                    last_why = why

                if not active:
                    rep_number = 0
                    last_token = None
                    stop_event.wait(GATE_POLL_SECONDS)
                    continue

                # A new set means rep numbering starts over. The node's rep_number
                # is advisory anyway — the tablet assigns the authoritative one —
                # but a stream that counts to 40 across five sets looks wrong to
                # anyone watching the topic.
                if token != last_token:
                    rep_number = 0
                    last_token = token

                rep_number += 1
                payload = build_rep_payload(node_id, rep_number)
                client.publish(rep_topic, json.dumps(payload), qos=1)
                self.stdout.write(f"[{node_id}] rep {rep_number} -> "
                                  f"{payload['mean_velocity']} m/s")

                # 'always' has no tablet telling it where a set ends, so it keeps
                # the original count-and-rest rhythm. The gated modes don't need
                # it: the set ends when the coach ends it.
                if mode == MODE_ALWAYS and rep_number >= reps_per_set:
                    rep_number = 0
                    self.stdout.write(f"[{node_id}] set complete, resting")
                    stop_event.wait(interval * 2)
                else:
                    stop_event.wait(interval)

        except KeyboardInterrupt:
            self.stdout.write("\nStopping simulate_node...")
        finally:
            stop_event.set()
            client.loop_stop()
            client.disconnect()
