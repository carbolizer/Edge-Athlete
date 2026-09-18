"""setup_code — print a one-time code for claiming this base station.

Run it on the machine itself:

    docker compose exec django python manage.py setup_code

The browser asks for this code only on a brand-new installation. It proves the
person enrolling had access to the base station, so a student who finds the
website first cannot make themselves the administrator. The code expires, works
once, and re-running this command replaces any previous code — which is also how
you revoke one that has been seen by the wrong person.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand

from event_handler.coach_auth import issue_setup_code, setup_is_required


class Command(BaseCommand):
    help = "Issue a one-time first-run setup code for claiming this installation."

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours', type=float, default=24,
            help='How long the code stays valid (default: 24 hours).')

    def handle(self, *args, **options):
        if not setup_is_required():
            self.stdout.write(self.style.WARNING(
                "This installation is already set up. No code is needed — sign "
                "in with an administrator account and create coaches from the "
                "Coaches screen."
            ))
            return

        code, expires_at = issue_setup_code(ttl=timedelta(hours=options['hours']))
        self.stdout.write(self.style.SUCCESS("Edge Athlete first-run setup code"))
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"    {code}"))
        self.stdout.write("")
        self.stdout.write(
            f"Expires {expires_at:%Y-%m-%d %H:%M} (local server time). "
            "Enter it on the setup screen. It can be used once."
        )
