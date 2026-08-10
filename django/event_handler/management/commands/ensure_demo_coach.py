"""
ensure_demo_coach — create or repair the private-profile demo coach login.

/coach uses username=coach / password=coachpass.
Without this account, JWT login returns "No active account found…".
Safe to re-run: restores the password and active-staff flags.
"""
from django.contrib.auth.models import User
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

DEMO_USERNAME = "coach"
DEMO_PASSWORD = "coachpass"


class Command(BaseCommand):
    help = "Ensure the demo coach account (coach / coachpass) exists."

    def handle(self, *args, **options):
        if settings.VPS_DEPLOYMENT:
            raise CommandError("ensure_demo_coach is disabled for VPS deployments")

        user, created = User.objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={"is_staff": True, "is_active": True},
        )
        user.set_password(DEMO_PASSWORD)
        user.is_active = True
        user.is_staff = True
        user.save(update_fields=["password", "is_active", "is_staff"])
        if created:
            self.stdout.write(self.style.SUCCESS(
                f"Created demo coach account: {DEMO_USERNAME}"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Updated demo coach account: {DEMO_USERNAME}"
            ))
