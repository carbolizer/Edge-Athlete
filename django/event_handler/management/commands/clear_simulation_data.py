"""Remove records owned by the reserved development simulator identities."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Q

from event_handler.models import Athlete, MonitoringEvent, Node, Program, RackWorkoutState, Session, Set


class Command(BaseCommand):
    help = "Delete simulation sessions, athletes, programs, sets, reps, and nodes."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        if not settings.SIMULATOR_ENABLED:
            raise CommandError("Simulation cleanup is disabled. Set SIMULATOR_ENABLED=True only in development.")
        if not options["confirm"]:
            raise CommandError("Pass --confirm to delete records with reserved simulation identities.")

        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [20260714])
            if not cursor.fetchone()[0]:
                raise CommandError("Stop the running simulator before clearing simulation data.")
        try:
            with transaction.atomic():
                sessions = Session.objects.filter(is_simulated=True)
                athletes = Athlete.objects.filter(is_simulated=True)
                nodes = Node.objects.filter(is_simulated=True)
                sets = Set.objects.filter(is_simulated=True)
                programs = Program.objects.filter(is_simulated=True)
                events = MonitoringEvent.objects.filter(is_simulated=True)
                rack_states = RackWorkoutState.objects.filter(
                    Q(active_session__in=sessions) | Q(active_program__in=programs)
                )
                if Set.objects.filter(is_simulated=False).filter(
                    Q(session__in=sessions) | Q(athlete__in=athletes) | Q(node__in=nodes)
                ).exists() or Program.objects.filter(
                    is_simulated=False, athlete__in=athletes,
                ).exists() or Session.objects.filter(
                    is_simulated=False, athletes__in=athletes,
                ).exists():
                    raise CommandError("Simulation identities are referenced by non-simulation training data; cleanup aborted.")
                counts = {
                    "sessions": sessions.count(),
                    "athletes": athletes.count(),
                    "nodes": nodes.count(),
                    "sets": sets.count(),
                    "programs": programs.count(),
                    "events": events.count(),
                    "rack_states": rack_states.count(),
                }
                rack_states.delete()
                sets.delete()
                programs.delete()
                sessions.delete()
                athletes.delete()
                nodes.delete()
                events.delete()
                if any(counts.values()):
                    MonitoringEvent.objects.create(reason="simulation_cleared")
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [20260714])
        self.stdout.write(self.style.SUCCESS(
            f"Removed {counts['sessions']} simulation session(s), "
            f"{counts['athletes']} athlete(s), {counts['nodes']} node(s), "
            f"{counts['sets']} set(s), {counts['programs']} program(s), "
            f"{counts['rack_states']} rack state(s), and {counts['events']} event(s)."
        ))
