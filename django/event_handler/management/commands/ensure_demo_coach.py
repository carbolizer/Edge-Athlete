"""
ensure_demo_coach — create the demo coach login if it is missing.

ConnectionTest and /coach both use username=coach / password=coachpass.
Without this account, JWT login returns "No active account found…".
Safe to re-run: updates the password if the user already exists.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

DEMO_USERNAME = "coach"
DEMO_PASSWORD = "coachpass"


class Command(BaseCommand):
    help = "Ensure the demo coach account (coach / coachpass) exists."

    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={"is_staff": True, "is_active": True},
        )
        user.set_password(DEMO_PASSWORD)
        user.is_active = True
        user.save()
        if created:
            self.stdout.write(self.style.SUCCESS(
                f"Created demo coach account: {DEMO_USERNAME} / {DEMO_PASSWORD}"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Updated demo coach account: {DEMO_USERNAME} / {DEMO_PASSWORD}"
            ))
