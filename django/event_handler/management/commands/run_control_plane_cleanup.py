"""Run the bounded hosted Rack cleanup cycle once per minute."""
import time

from django.core.management.base import BaseCommand
from django.db import connection

from event_handler.services.rack_control_plane import cleanup_control_plane


LOCK_ID = 718_225_041


class Command(BaseCommand):
    help = "Run non-overlapping hosted Rack control-plane retention cleanup"

    def handle(self, *args, **options):
        while True:
            cycle_started = time.monotonic()
            acquired = False
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
                    acquired = cursor.fetchone()[0]
                if acquired:
                    cleanup_control_plane()
            finally:
                if acquired:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
            time.sleep(max(1, 60 - (time.monotonic() - cycle_started)))
