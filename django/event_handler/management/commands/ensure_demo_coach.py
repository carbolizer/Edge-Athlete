"""
ensure_demo_coach — create or repair the private-profile demo coach login.

/coach uses username=coach / password=coachpass.
Without this account, JWT login returns "No active account found…".
Safe to re-run: restores the password and active-staff flags.
"""
import uuid

from django.contrib.auth.models import User
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from event_handler.models import Organization, OrganizationMembership

DEMO_USERNAME = "coach"
DEMO_PASSWORD = "coachpass"
LEGACY_ORGANIZATION_ID = uuid.UUID("4ac9f970-4084-4f7f-9cb8-c586c995ed62")


class Command(BaseCommand):
    help = "Ensure the demo coach account (coach / coachpass) exists."

    def handle(self, *args, **options):
        if settings.VPS_DEPLOYMENT:
            raise CommandError("ensure_demo_coach is disabled for VPS deployments")

        with transaction.atomic():
            try:
                organization = Organization.objects.get(pk=LEGACY_ORGANIZATION_ID)
            except Organization.DoesNotExist as exc:
                raise CommandError("legacy organization is missing; run migrations first") from exc

            user, created = User.objects.get_or_create(
                username=DEMO_USERNAME,
                defaults={"is_staff": True, "is_active": True},
            )
            conflicting_membership = OrganizationMembership.objects.filter(
                user=user, is_active=True,
            ).exclude(organization=organization).exists()
            if conflicting_membership:
                raise CommandError("demo coach already belongs to another active organization")

            user.set_password(DEMO_PASSWORD)
            user.is_active = True
            user.is_staff = True
            user.save(update_fields=["password", "is_active", "is_staff"])
            OrganizationMembership.objects.update_or_create(
                organization=organization,
                user=user,
                defaults={"role": OrganizationMembership.OWNER, "is_active": True},
            )
        if created:
            self.stdout.write(self.style.SUCCESS(
                f"Created demo coach account: {DEMO_USERNAME}"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Updated demo coach account: {DEMO_USERNAME}"
            ))
