import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


LEGACY_ORGANIZATION_ID = uuid.UUID("4ac9f970-4084-4f7f-9cb8-c586c995ed62")
OWNED_MODEL_NAMES = (
    "Athlete",
    "TrainingGroup",
    "TrainingBlock",
    "TrainingSession",
    "DailyReport",
)


def create_legacy_organization(apps, schema_editor):
    Organization = apps.get_model("event_handler", "Organization")
    OrganizationMembership = apps.get_model("event_handler", "OrganizationMembership")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    organization, _created = Organization.objects.get_or_create(
        pk=LEGACY_ORGANIZATION_ID,
        defaults={"display_name": "Legacy Edge Athlete"},
    )
    for model_name in OWNED_MODEL_NAMES:
        Model = apps.get_model("event_handler", model_name)
        unowned_count = Model.objects.filter(organization_id=None).count()
        updated_count = Model.objects.filter(organization_id=None).update(
            organization_id=organization.pk,
        )
        if updated_count != unowned_count:
            raise RuntimeError(f"{model_name} organization backfill count changed")

    for user_id in User.objects.filter(is_active=True, is_staff=True).values_list("pk", flat=True):
        OrganizationMembership.objects.get_or_create(
            organization_id=organization.pk,
            user_id=user_id,
            defaults={"role": "owner", "is_active": True},
        )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("event_handler", "0022_vps_gateway_health_foundation"),
    ]

    operations = [
        migrations.CreateModel(
            name="Organization",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("display_name", models.CharField(max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="OrganizationMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("owner", "Owner")], default="owner", max_length=16)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="memberships", to="event_handler.organization")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="organization_memberships", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="organizationmembership",
            constraint=models.UniqueConstraint(fields=("organization", "user"), name="organization_user_membership_unique"),
        ),
        migrations.AddConstraint(
            model_name="organizationmembership",
            constraint=models.UniqueConstraint(condition=models.Q(("is_active", True)), fields=("user",), name="one_active_organization_per_user"),
        ),
        *[
            migrations.AddField(
                model_name=model_name.lower(),
                name="organization",
                field=models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name=related_name,
                    to="event_handler.organization",
                ),
            )
            for model_name, related_name in (
                ("Athlete", "athletes"),
                ("TrainingGroup", "training_groups"),
                ("TrainingBlock", "training_blocks"),
                ("TrainingSession", "training_sessions"),
                ("DailyReport", "daily_reports"),
            )
        ],
        # Reversing the schema drops these transitional mappings. This is safe
        # only before registration creates organizations that must be retained.
        migrations.RunPython(create_legacy_organization, migrations.RunPython.noop),
    ]
