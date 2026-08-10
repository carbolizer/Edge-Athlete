from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from event_handler.models import EdgeGateway, HostedGym


class Command(BaseCommand):
    help = "Fail unless the diagnostics-only VPS database is safe to serve."

    def handle(self, *args, **options):
        if not settings.VPS_DEPLOYMENT:
            raise CommandError("VPS_DEPLOYMENT must be True")

        gyms = list(HostedGym.objects.values_list("id", flat=True))
        if len(gyms) != 1:
            raise CommandError("VPS deployment requires exactly one hosted gym")

        active_gateways = EdgeGateway.objects.filter(revoked_at=None)
        if active_gateways.count() != 1:
            raise CommandError("VPS deployment requires exactly one active edge gateway")
        if active_gateways.values_list("gym_id", flat=True).get() != gyms[0]:
            raise CommandError("the active edge gateway must belong to the hosted gym")

        active_staff = get_user_model().objects.filter(is_active=True, is_staff=True)
        if any(user.check_password("coachpass") for user in active_staff.iterator()):
            raise CommandError("active staff accounts cannot use the demo password")

        self.stdout.write(self.style.SUCCESS("VPS deployment preflight passed"))
