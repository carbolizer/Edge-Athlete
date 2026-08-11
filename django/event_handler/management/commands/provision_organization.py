import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from event_handler.models import (
    Organization,
    OrganizationMembership,
    TrainingGroup,
    TrainingGroupCoach,
)


def clean_name(value, label, maximum):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > maximum:
        raise CommandError(f"{label} must be between 1 and {maximum} characters without outer whitespace")
    return value


class Command(BaseCommand):
    help = "Provision an organization owner and initial TrainingGroup."

    def add_arguments(self, parser):
        parser.add_argument("--organization", required=True)
        parser.add_argument("--organization-id", required=True)
        parser.add_argument("--group", required=True)
        parser.add_argument("--staff", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        organization_name = clean_name(options["organization"], "organization", 120)
        group_name = clean_name(options["group"], "group", 255)
        try:
            organization_id = uuid.UUID(options["organization_id"])
        except (ValueError, TypeError, AttributeError) as exc:
            raise CommandError("organization-id must be a UUID") from exc
        user = get_user_model().objects.select_for_update().filter(username=options["staff"]).first()
        if user is None or not user.is_active or not user.is_staff:
            raise CommandError("staff owner must be an active staff user")

        conflicting_membership = OrganizationMembership.objects.select_for_update().filter(
            user=user, is_active=True,
        ).exclude(organization_id=organization_id).exists()
        if conflicting_membership:
            raise CommandError("staff owner already belongs to another active organization")

        organization, created = Organization.objects.get_or_create(
            id=organization_id,
            defaults={"display_name": organization_name},
        )
        if not created:
            if organization.display_name != organization_name:
                raise CommandError("organization-id already belongs to a different display name")
            if not OrganizationMembership.objects.filter(
                organization=organization,
                user=user,
                role=OrganizationMembership.OWNER,
                is_active=True,
            ).exists():
                raise CommandError("existing organization is not owned by the supplied staff user")
        else:
            OrganizationMembership.objects.create(
                organization=organization,
                user=user,
                role=OrganizationMembership.OWNER,
                is_active=True,
            )
        group, _created = TrainingGroup.objects.get_or_create(
            organization=organization,
            name=group_name,
        )
        existing_head = TrainingGroupCoach.objects.select_for_update().filter(
            training_group=group, role=TrainingGroupCoach.HEAD,
        ).first()
        if existing_head is not None and existing_head.coach_id != user.id:
            raise CommandError("initial TrainingGroup already has a different head coach")
        TrainingGroupCoach.objects.update_or_create(
            training_group=group,
            coach=user,
            defaults={"role": TrainingGroupCoach.HEAD},
        )
        self.stdout.write(self.style.SUCCESS(
            f"Organization ready: {organization.id}; TrainingGroup ready: {group.id}",
        ))
