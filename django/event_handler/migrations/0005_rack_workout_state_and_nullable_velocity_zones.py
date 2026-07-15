from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import django.db.models.expressions


def validate_existing_velocity_zones(apps, schema_editor):
    program = apps.get_model("event_handler", "Program")
    invalid = program.objects.filter(
        models.Q(velocity_zone_min__lt=0)
        | models.Q(velocity_zone_max__lt=models.F("velocity_zone_min"))
        | models.Q(velocity_zone_min__gt=10)
        | models.Q(velocity_zone_max__gt=10)
    )
    if invalid.exists():
        raise RuntimeError(
            "Program velocity ranges must be nonnegative and ordered before migration 0005."
        )


def prevent_reverse(apps, schema_editor):
    raise RuntimeError(
        "Migration 0005 is irreversible after non-velocity programs exist. Restore a pre-0005 database backup to roll back."
    )


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0004_simulation_ownership")]

    operations = [
        migrations.RunPython(validate_existing_velocity_zones, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="program",
            name="velocity_zone_min",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="program",
            name="velocity_zone_max",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="program",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(velocity_zone_min__isnull=True, velocity_zone_max__isnull=True)
                    | models.Q(
                        velocity_zone_min__isnull=False,
                        velocity_zone_max__isnull=False,
                        velocity_zone_min__gte=0,
                        velocity_zone_min__lte=10,
                        velocity_zone_max__gte=django.db.models.expressions.F("velocity_zone_min"),
                        velocity_zone_max__lte=10,
                    )
                ),
                name="program_velocity_zone_valid",
            ),
        ),
        migrations.CreateModel(
            name="RackWorkoutState",
            fields=[
                (
                    "rack_number",
                    models.PositiveIntegerField(
                        primary_key=True,
                        serialize=False,
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "active_program",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="rack_workout_states",
                        to="event_handler.program",
                    ),
                ),
                (
                    "active_session",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="rack_workout_states",
                        to="event_handler.session",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="rackworkoutstate",
            constraint=models.CheckConstraint(
                condition=models.Q(rack_number__gt=0),
                name="rack_workout_state_positive_rack",
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, prevent_reverse),
    ]
