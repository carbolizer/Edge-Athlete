"""Generate realistic room traffic until real sensor hardware is available."""

import json
import math
import random
import signal
import time
import uuid

import paho.mqtt.client as mqtt
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Max
from django.utils import timezone

from event_handler.models import Athlete, Node, Program, Session, Set
from event_handler.notification_flow.mqtt_ingester.parser import parse_rep_payload
from event_handler.serializers import SetCompleteSerializer
from event_handler.services.set_completion import complete_set, SetAlreadyComplete


SIMULATED_ATHLETES = [
    "[SIM] Athlete 1",
    "[SIM] Athlete 2",
    "[SIM] Athlete 3",
    "[SIM] Athlete 4",
    "[SIM] Athlete 5",
    "[SIM] Athlete 6",
    "[SIM] Athlete 7",
    "[SIM] Athlete 8",
]
EXERCISES = [
    ("Back squat", 225, 0.65, 0.90),
    ("Bench press", 155, 0.55, 0.80),
    ("Deadlift", 275, 0.50, 0.75),
    ("Power clean", 135, 0.85, 1.15),
]
PULSE_INTERVAL_SECONDS = 5.0


def build_pulse_payload(node_id, battery_level, randomizer):
    return {
        "node_id": node_id,
        "event_type": "pulse",
        "battery_level": battery_level,
        "signal_strength": randomizer.randint(-68, -42),
        "firmware_version": "sim-1.0.0",
        "timestamp": timezone.now().isoformat(),
    }


def build_rep_payload(node_id, rep_number, starting_velocity, randomizer):
    fatigue = (rep_number - 1) * randomizer.uniform(0.015, 0.045)
    mean_velocity = round(max(0.25, starting_velocity - fatigue + randomizer.uniform(-0.025, 0.025)), 3)
    peak_velocity = round(mean_velocity + randomizer.uniform(0.10, 0.24), 3)
    duration_ms = round(max(450, 1150 - mean_velocity * 430 + randomizer.randint(-60, 60)))
    return {
        "node_id": node_id,
        "rep_number": rep_number,
        "mean_velocity": mean_velocity,
        "peak_velocity": peak_velocity,
        "duration_ms": duration_ms,
        "timestamp": timezone.now().isoformat(),
    }


def velocity_color(mean_velocity, minimum, maximum):
    if mean_velocity < minimum:
        return "red"
    if mean_velocity > maximum:
        return "yellow"
    return "green"


class Command(BaseCommand):
    help = "Generate bounded simulated readings for monitoring views or an MQTT rack client."

    def add_arguments(self, parser):
        parser.add_argument("--racks", type=int, default=4, help="Number of racks to simulate (default: 4).")
        parser.add_argument(
            "--mode",
            choices=["monitoring", "rack"],
            default="monitoring",
            help="monitoring persists wall/coach data; rack publishes MQTT reps without persistence.",
        )
        parser.add_argument("--rack", type=int, default=1, help="First rack number (default: 1).")
        parser.add_argument("--interval", type=float, default=2.0, help="Seconds between rep rounds (default: 2).")
        parser.add_argument("--rest", type=float, default=8.0, help="Seconds between sets (default: 8).")
        parser.add_argument("--reps-per-set", type=int, default=5, help="Reps generated in each set (default: 5).")
        parser.add_argument("--sets", type=int, default=10, help="Set cycles before exit (default: 10).")
        parser.add_argument("--continuous", action="store_true", help="Run continuously, capped by --max-cycles.")
        parser.add_argument("--max-cycles", type=int, default=100, help="Safety cap for --continuous (default: 100).")
        parser.add_argument("--seed", type=int, help="Optional seed for repeatable velocity values; timestamps stay live.")
        parser.add_argument("--session-label", default="[SIMULATION] Live training")

    def handle(self, *args, **options):
        self._validate_options(options)
        if not settings.SIMULATOR_ENABLED:
            raise CommandError("Simulation is disabled. Set SIMULATOR_ENABLED=True only in a development environment.")
        randomizer = random.Random(options["seed"])
        client = mqtt.Client(client_id=f"edgeathlete-simulator-{uuid.uuid4().hex[:8]}")
        try:
            client.connect(settings.MQTT_HOST, settings.MQTT_PORT, 60)
        except Exception as error:
            raise CommandError(f"Could not connect to MQTT broker: {error}") from error
        client.loop_start()

        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [20260714])
            if not cursor.fetchone()[0]:
                client.loop_stop()
                client.disconnect()
                raise CommandError("Another simulator already holds the singleton lock.")

        try:
            contexts, session = self._prepare_room(options, randomizer)
        except Exception:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [20260714])
            client.loop_stop()
            client.disconnect()
            raise
        previous_sigterm_handler = signal.getsignal(signal.SIGTERM)

        def stop_on_sigterm(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, stop_on_sigterm)

        self.stdout.write(self.style.SUCCESS(
            f"Simulating {len(contexts)} rack(s) in '{session.label}'. Press Ctrl+C to stop."
        ))
        next_pulse_at = 0.0

        def publish(topic, payload):
            result = client.publish(topic, json.dumps(payload, separators=(",", ":")), qos=1)
            if isinstance(result.rc, int) and result.rc != mqtt.MQTT_ERR_SUCCESS:
                raise CommandError(f"MQTT publish failed with code {result.rc}.")
            result.wait_for_publish(timeout=10)
            if not result.is_published():
                raise CommandError("MQTT broker did not acknowledge the simulated reading.")

        def publish_pulses():
            nonlocal next_pulse_at
            for context in contexts:
                payload = build_pulse_payload(context["node"].node_id, context["battery"], randomizer)
                publish(context["pulse_topic"], payload)
            next_pulse_at = time.monotonic() + PULSE_INTERVAL_SECONDS

        def wait_with_pulses(seconds):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if time.monotonic() >= next_pulse_at:
                    publish_pulses()
                time.sleep(min(0.25, max(0, deadline - time.monotonic())))

        completed_cycles = 0
        active_sets = []
        cycle_limit = options["max_cycles"] if options["continuous"] else options["sets"]
        try:
            publish_pulses()
            while completed_cycles < cycle_limit:
                active_sets = self._start_sets(
                    contexts,
                    session,
                    options["reps_per_set"],
                    randomizer,
                    persist=options["mode"] == "monitoring",
                )
                for rep_number in range(1, options["reps_per_set"] + 1):
                    for active in active_sets:
                        payload = build_rep_payload(
                            active["context"]["node"].node_id,
                            rep_number,
                            active["starting_velocity"],
                            randomizer,
                        )
                        payload = parse_rep_payload(json.dumps(payload).encode("utf-8"))
                        active["reps"].append(payload)
                        if options["mode"] == "rack":
                            publish(active["context"]["rep_topic"], payload)
                        self.stdout.write(
                            f"Rack {active['context']['rack']}: rep {rep_number} "
                            f"at {payload['mean_velocity']:.3f} m/s"
                        )
                    wait_with_pulses(options["interval"])

                for active in active_sets:
                    if options["mode"] == "monitoring":
                        self._complete_set(active)
                    active["context"]["battery"] = max(10, active["context"]["battery"] - randomizer.choice([0, 0, 0, 1]))
                active_sets = []
                completed_cycles += 1
                result = (
                    "monitoring views will reconcile"
                    if options["mode"] == "monitoring"
                    else "the rack client owns set persistence"
                )
                self.stdout.write(self.style.SUCCESS(f"Completed simulated set cycle {completed_cycles}; {result}."))
                if completed_cycles < cycle_limit:
                    wait_with_pulses(options["rest"])
        except KeyboardInterrupt:
            self._discard_active_sets(active_sets)
            self.stdout.write("Stopping simulator.")
        except Exception:
            self._discard_active_sets(active_sets)
            raise
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm_handler)
            client.loop_stop()
            client.disconnect()
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [20260714])

    def _validate_options(self, options):
        if not 1 <= options["racks"] <= 32:
            raise CommandError("--racks must be between 1 and 32.")
        if options["rack"] < 1 or options["rack"] + options["racks"] - 1 > 32:
            raise CommandError("The simulated rack range must stay between 1 and 32.")
        if not 1 <= options["reps_per_set"] <= 100:
            raise CommandError("--reps-per-set must be between 1 and 100.")
        if not 1 <= options["sets"] <= 1000 or not 1 <= options["max_cycles"] <= 1000:
            raise CommandError("--sets and --max-cycles must be between 1 and 1000.")
        if not math.isfinite(options["interval"]) or not math.isfinite(options["rest"]):
            raise CommandError("--interval and --rest must be finite numbers.")
        if options["interval"] < 0 or options["rest"] < 0:
            raise CommandError("--interval and --rest cannot be negative.")
        if options["continuous"] and (options["interval"] < 0.25 or options["rest"] < 1):
            raise CommandError("Continuous mode requires --interval >= 0.25 and --rest >= 1.")
        label = options["session_label"]
        if not 1 <= len(label) <= 255 or not label.isprintable() or not label.startswith("[SIMULATION]"):
            raise CommandError("--session-label must be printable, at most 255 characters, and start with [SIMULATION].")

    def _prepare_room(self, options, randomizer):
        contexts = []
        with transaction.atomic():
            conflicting_session = Session.objects.filter(ended_at=None, is_simulated=False).first()
            if conflicting_session:
                raise CommandError("End the active non-simulation session before starting simulated data.")
            session = Session.objects.filter(
                label=options["session_label"], ended_at=None, is_simulated=True,
            ).order_by("-id").first()
            if session is None:
                if Session.objects.filter(label=options["session_label"], is_simulated=False).exists():
                    raise CommandError("The simulation session label is already owned by non-simulation data.")
                session = Session.objects.create(label=options["session_label"], is_simulated=True)

            for offset in range(options["racks"]):
                rack = options["rack"] + offset
                node_id = f"sim-rack-{rack}"
                if Node.objects.filter(node_id=node_id, is_simulated=False).exists():
                    raise CommandError("A reserved simulation node ID is owned by non-simulation data.")
                node, _ = Node.objects.update_or_create(
                    node_id=node_id, is_simulated=True,
                    defaults={
                        "rack_number": rack,
                        "mount_type": Node.MOUNT_BAR,
                        "firmware_version": "sim-1.0.0",
                        "is_active": True,
                    },
                )
                nfc_tag_id = f"simulation-athlete-{rack}"
                if Athlete.objects.filter(nfc_tag_id=nfc_tag_id, is_simulated=False).exists():
                    raise CommandError("A reserved simulation athlete ID is owned by non-simulation data.")
                athlete, _ = Athlete.objects.update_or_create(
                    nfc_tag_id=nfc_tag_id, is_simulated=True,
                    defaults={"name": SIMULATED_ATHLETES[offset % len(SIMULATED_ATHLETES)]},
                )
                session.athletes.add(athlete)
                exercise, weight, minimum, maximum = EXERCISES[offset % len(EXERCISES)]
                if Program.objects.filter(
                    athlete=athlete, exercise=exercise, is_simulated=False,
                ).exists():
                    raise CommandError("A simulation athlete has a program not owned by the simulator.")
                program, _ = Program.objects.update_or_create(
                    athlete=athlete,
                    exercise=exercise,
                    is_simulated=True,
                    defaults={
                        "target_sets": 5,
                        "target_reps": options["reps_per_set"],
                        "target_weight_lbs": weight,
                        "velocity_zone_min": minimum,
                        "velocity_zone_max": maximum,
                    },
                )
                contexts.append({
                    "rack": rack,
                    "node": node,
                    "athlete": athlete,
                    "program": program,
                    "battery": randomizer.randint(78, 98),
                    "pulse_topic": f"edgeathlete/node/{node_id}/pulse",
                    "rep_topic": f"edgeathlete/node/{node_id}/rep",
                })
        return contexts, session

    def _start_sets(self, contexts, session, reps_per_set, randomizer, persist):
        active_sets = []
        with transaction.atomic():
            for context in contexts:
                workout_set = None
                if persist:
                    latest_number = Set.objects.filter(
                        session=session,
                        athlete=context["athlete"],
                        exercise=context["program"].exercise,
                    ).aggregate(number=Max("set_number"))["number"] or 0
                    workout_set = Set.objects.create(
                        session=session,
                        athlete=context["athlete"],
                        node=context["node"],
                        exercise=context["program"].exercise,
                        set_number=latest_number + 1,
                        weight_lbs=context["program"].target_weight_lbs,
                        is_simulated=True,
                    )
                active_sets.append({
                    "context": context,
                    "set": workout_set,
                    "reps": [],
                    "reps_per_set": reps_per_set,
                    "starting_velocity": randomizer.uniform(
                        context["program"].velocity_zone_min - 0.05,
                        context["program"].velocity_zone_max + 0.12,
                    ),
                })
        return active_sets

    def _complete_set(self, active):
        context = active["context"]
        body = {
            "reps_completed": active["reps_per_set"],
            "is_false_set": False,
            "reps": [{
                "rep_number": rep["rep_number"],
                "mean_velocity": rep["mean_velocity"],
                "peak_velocity": rep["peak_velocity"],
                "duration_ms": rep["duration_ms"],
                "timestamp": rep["timestamp"],
                "velocity_color": velocity_color(
                    rep["mean_velocity"],
                    context["program"].velocity_zone_min,
                    context["program"].velocity_zone_max,
                ),
            } for rep in active["reps"]],
        }
        form = SetCompleteSerializer(data=body)
        form.is_valid(raise_exception=True)
        data = form.validated_data

        complete_set(active["set"].id, data)

    def _discard_active_sets(self, active_sets):
        unfinished_ids = [
            active["set"].id for active in active_sets
            if active["set"] is not None and active["set"].ended_at is None
        ]
        if not unfinished_ids:
            return
        for set_id in unfinished_ids:
            try:
                complete_set(set_id, {"is_false_set": True, "reps": [], "reps_completed": 0})
            except SetAlreadyComplete:
                pass
