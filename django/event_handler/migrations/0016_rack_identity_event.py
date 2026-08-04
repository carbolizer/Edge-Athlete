import django.db.models.deletion
import django.core.validators
from django.db import migrations, models


def prevent_active_schema3_reverse(apps, schema_editor):
    Set = apps.get_model("event_handler", "Set")
    Progress = apps.get_model("event_handler", "AthleteDayProgress")
    DayPlan = apps.get_model("event_handler", "AthleteDayPlan")
    if DayPlan.objects.filter(session__ended_at=None).exists() or Progress.objects.filter(
        day_plan__isnull=False, session__ended_at=None,
    ).exists() or Set.objects.filter(day_plan_workout__isnull=False, ended_at=None).exists():
        raise RuntimeError(
            "Cannot reverse 0016 while an active schema-3 day, active frozen progress, "
            "or unfinished frozen set exists. End the day and all sets first."
        )


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0015_athlete_schedule_tombstone")]

    operations = [
        migrations.CreateModel(
            name="RackIdentityEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_id", models.UUIDField()),
                ("rack_number", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("result", models.CharField(choices=[("set_started", "Set started"), ("set_active", "Set active"), ("confirmed", "Identity confirmed")], max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("athlete", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rack_identity_events", to="event_handler.athlete")),
                ("resulting_set", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="rack_identity_events", to="event_handler.set")),
                ("screen", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="identity_events", to="event_handler.rackscreen")),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rack_identity_events", to="event_handler.session")),
            ],
        ),
        migrations.AddConstraint(
            model_name="rackidentityevent",
            constraint=models.UniqueConstraint(fields=("screen", "event_id"), name="rack_identity_event_screen_uuid_unique"),
        ),
        migrations.AddConstraint(
            model_name="rackidentityevent",
            constraint=models.CheckConstraint(condition=models.Q(("rack_number__gt", 0)), name="rack_identity_event_positive_rack"),
        ),
        migrations.AddIndex(
            model_name="rackidentityevent",
            index=models.Index(fields=["screen", "session", "created_at"], name="rack_identity_retention_idx"),
        ),
        migrations.RunPython(migrations.RunPython.noop, prevent_active_schema3_reverse),
    ]
