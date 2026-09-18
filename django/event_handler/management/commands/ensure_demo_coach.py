"""
ensure_demo_coach — create the DEMO coach login (coach / coachpass).

This exists so a laptop or demo box can sign into /coach with published
credentials. It is NOT part of normal startup and must never run on a real base
station: a known password on a live box is an open door, no matter who can reach
the network.

⚠️ The default password is public. That is acceptable on a laptop and never
acceptable in a gym. So this command REFUSES to run unless DEBUG is on, and the
only way past that is the explicit, hard-to-type `--i-know-this-is-a-demo-box`
flag — a deliberate speed bump, not a permission level. The real first coach is
created at /coach with a one-time setup code (see coach_auth.py); ordinary coach
accounts are created by an administrator from the coaches screen.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from event_handler.models import CoachProfile
from event_handler.room_access import installation_room

DEMO_USERNAME = "coach"
DEMO_PASSWORD = "coachpass"


class Command(BaseCommand):
    help = "Create the demo coach login (coach / coachpass). Refused unless DEBUG is on."

    def add_arguments(self, parser):
        parser.add_argument(
            "--i-know-this-is-a-demo-box",
            action="store_true",
            help="Override the DEBUG check. Creates a PUBLIC password on this box.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["i_know_this_is_a_demo_box"]:
            raise CommandError(
                "Refusing to create the demo login (coach / coachpass) while DEBUG is "
                "off. That password is public, and this looks like a real base "
                "station. Create the first coach at /coach with `manage.py "
                "setup_code`, or, if this really is a throwaway demo box, re-run "
                "with --i-know-this-is-a-demo-box."
            )

        room = installation_room()
        if room is None:
            raise CommandError('Run migrations and configure the installation weight room first.')
        user, created = User.objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={"is_staff": True, "is_active": True},
        )
        user.set_password(DEMO_PASSWORD)
        user.is_active = True
        user.save()
        CoachProfile.objects.update_or_create(user=user, defaults={'weight_room': room})
        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.WARNING(
            f"{verb} demo coach account: {DEMO_USERNAME} / {DEMO_PASSWORD} — "
            "public credentials, demo use only."
        ))
