from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_slug
from django.core.exceptions import ValidationError
from django.db import transaction

from event_handler.models import EdgeGateway, HostedGym
from event_handler.services.gateway_ingest import issue_gateway_credential


class Command(BaseCommand):
    help = "Provision the single diagnostics-only hosted edge gateway."

    def add_arguments(self, parser):
        parser.add_argument("--gym", required=True)
        parser.add_argument("--label", required=True)
        parser.add_argument("--staff", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        slug = options["gym"]
        label = options["label"]
        try:
            validate_slug(slug)
        except ValidationError as exc:
            raise CommandError("gym must be a valid slug") from exc
        if not isinstance(label, str) or not label.strip() or label != label.strip() or len(label) > 120:
            raise CommandError("label must be between 1 and 120 characters")

        sponsor = get_user_model().objects.filter(username=options["staff"]).first()
        if sponsor is None or not sponsor.is_active or not sponsor.is_staff:
            raise CommandError("staff sponsor must be an active staff user")

        gyms = list(HostedGym.objects.select_for_update().all())
        if len(gyms) > 1:
            raise CommandError("only one hosted gym is supported")
        if gyms and gyms[0].slug != slug:
            raise CommandError("the provisioned hosted gym does not match --gym")
        gym = gyms[0] if gyms else HostedGym.objects.create(slug=slug, display_name=slug)

        if EdgeGateway.objects.select_for_update().filter(revoked_at=None).exists():
            raise CommandError("an active edge gateway already exists")
        gateway = EdgeGateway.objects.create(gym=gym, label=label)
        _credential, bearer = issue_gateway_credential(gateway, sponsor)
        self.stdout.write(bearer)
