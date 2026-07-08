#simulate_node.py - fake rack sensor for development without hardware. 
# 
# the real nodes don't exist yet, but everything gives something to build and 
# demo against 

import json 
import os 
import random 
import threading 
import time 
from datetime import datetime, timezone

import paho.mqtt.client as mqtt 
from django.core.management.base import BaseCommand

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

PULSE_INTERVAL_SECONDS = 5.0
REST_BETWEEN_SETS_SECONDS = 8.0 

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

class Command(BaseCommand):
    help = "Simulate a rack sensor node, publishing fake pulse + rep traffic over MQTT."

    def add_arguments(self, parser):
        parser.add_argument("--node-id", type=str, required=True, help="Node ID to simulate, e.g. rack_1")
        parser.add_argument("--rack", type=int, default=None, help="Rack number (informational only)")
        parser.add_argument("--interval", type=float, default=3.0, help="Seconds between reps (default: 3.0)")
        parser.add_argument("--reps-per-set", type=int, default=5, help="Reps per set before resting (default: 5)")
    
    def handle(self, *args, **options):
        node_id = options["node_id"]
        rack = options["rack"]
        interval = options["interval"]
        reps_per_set = options["reps_per_set"]

        self.stdout.write(f"Starting simulate_node for {node_id} (rack {rack})...")

        client = mqtt.Client()
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()

        pulse_topic = f"edgeathlete/node/{node_id}/pulse"
        rep_topic = f"edgeathlete/node/{node_id}/rep"

        # Pulse runs on its own timer in the background, completely independent 
        # of rep/rest cycle below

        stop_event = threading.Event()

        def pulse_loop():
            while not stop_event.is_set():
                payload = build_pulse_payload(node_id)
                client.publish(pulse_topic, json.dumps(payload), qos=1)
                print(f"[simulate_node] PULSE -> {pulse_topic}: {payload}")
                stop_event.wait(PULSE_INTERVAL_SECONDS)
        
        pulse_thread = threading.Thread(target=pulse_loop, daemon=True)
        pulse_thread.start()

        #Main loop: run sets forever. Each set publishes reps_per_set reps, 
        # one every `interval` seconds, then rests before starting the next 
        # set with rep numbers reset back to 1. 
        try: 
            while True: 
                for rep_number in range(1, reps_per_set + 1):
                    payload = build_rep_payload(node_id, rep_number)
                    client.publish(rep_topic, json.dumps(payload), qos=1)
                    print(f"[simulate_node] REP -> {rep_topic}: {payload}")
                    time.sleep(interval)

                print(f"[simulate_node] Set complete. Resting {REST_BETWEEN_SETS_SECONDS}s before next set...")
                time.sleep(REST_BETWEEN_SETS_SECONDS)
        except KeyboardInterrupt:
            self.stdout.write("\nStopping simulate_node...")
        finally: 
            stop_event.set()
            client.loop_stop()
            client.disconnect()

            
