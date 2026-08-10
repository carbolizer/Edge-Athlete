from django.db import migrations, models


def normalize_and_validate(apps, schema_editor):
    Athlete = apps.get_model("event_handler", "Athlete")
    TrainingGroup = apps.get_model("event_handler", "TrainingGroup")
    TrainingGroupCoach = apps.get_model("event_handler", "TrainingGroupCoach")

    Athlete.objects.filter(nfc_tag_id="").update(nfc_tag_id=None)
    duplicate_group = (
        TrainingGroup.objects.values("organization_id", "name")
        .annotate(row_count=models.Count("id"))
        .filter(row_count__gt=1)
        .exists()
    )
    duplicate_head = (
        TrainingGroupCoach.objects.filter(role="head")
        .values("training_group_id")
        .annotate(row_count=models.Count("id"))
        .filter(row_count__gt=1)
        .exists()
    )
    if duplicate_group or duplicate_head:
        raise RuntimeError("tenant constraints require unique group names and one head per group")


class Migration(migrations.Migration):
    dependencies = [
        ("event_handler", "0023_organization_tenancy_foundation"),
    ]

    operations = [
        migrations.RunPython(normalize_and_validate, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="athlete",
            name="nfc_tag_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddConstraint(
            model_name="athlete",
            constraint=models.UniqueConstraint(
                condition=models.Q(("nfc_tag_id__isnull", False)),
                fields=("organization", "nfc_tag_id"),
                name="organization_nfc_tag_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="traininggroup",
            constraint=models.UniqueConstraint(
                fields=("organization", "name"),
                name="organization_training_group_name_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="traininggroupcoach",
            constraint=models.UniqueConstraint(
                condition=models.Q(("role", "head")),
                fields=("training_group",),
                name="one_head_per_training_group",
            ),
        ),
    ]
