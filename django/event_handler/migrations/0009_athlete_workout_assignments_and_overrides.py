import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def clear_identities_incompatible_with_slice_three(apps, schema_editor):
    rack_state = apps.get_model("event_handler", "RackWorkoutState")
    valid_slice_three_context = (
        models.Q(active_session__isnull=False, active_program__isnull=True)
        & (
            models.Q(assigned_workout__isnull=False, assigned_program_item__isnull=True)
            | models.Q(assigned_workout__isnull=True, assigned_program_item__isnull=False)
        )
    )
    rack_state.objects.filter(selected_athlete__isnull=False).exclude(
        valid_slice_three_context
    ).update(selected_athlete=None)


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0008_rack_catalog_assignment_and_identity")]

    operations = [
        migrations.CreateModel(
            name="AthleteWorkoutAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assigned_program_item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="athlete_assignments", to="event_handler.workoutprogramitem")),
                ("assigned_workout", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="athlete_assignments", to="event_handler.workout")),
                ("athlete", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="workout_assignment", to="event_handler.athlete")),
            ],
        ),
        migrations.CreateModel(
            name="AthleteWorkoutExerciseOverride",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sets", models.PositiveIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(2147483647)])),
                ("reps", models.PositiveIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(2147483647)])),
                ("weight_lbs", models.FloatField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("athlete", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="workout_exercise_overrides", to="event_handler.athlete")),
                ("workout_exercise", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="athlete_overrides", to="event_handler.workoutexercise")),
            ],
        ),
        migrations.AddConstraint(
            model_name="athleteworkoutassignment",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(assigned_workout__isnull=False, assigned_program_item__isnull=True)
                    | models.Q(assigned_workout__isnull=True, assigned_program_item__isnull=False)
                ),
                name="athlete_workout_assignment_exactly_one",
            ),
        ),
        migrations.AddConstraint(
            model_name="athleteworkoutexerciseoverride",
            constraint=models.UniqueConstraint(fields=("athlete", "workout_exercise"), name="athlete_workout_exercise_override_unique"),
        ),
        migrations.AddConstraint(
            model_name="athleteworkoutexerciseoverride",
            constraint=models.CheckConstraint(condition=models.Q(sets__isnull=False) | models.Q(reps__isnull=False) | models.Q(weight_lbs__isnull=False), name="athlete_workout_override_not_empty"),
        ),
        migrations.AddConstraint(
            model_name="athleteworkoutexerciseoverride",
            constraint=models.CheckConstraint(condition=models.Q(sets__isnull=True) | models.Q(sets__gte=1), name="athlete_workout_override_positive_sets"),
        ),
        migrations.AddConstraint(
            model_name="athleteworkoutexerciseoverride",
            constraint=models.CheckConstraint(condition=models.Q(reps__isnull=True) | models.Q(reps__gte=1), name="athlete_workout_override_positive_reps"),
        ),
        migrations.AddConstraint(
            model_name="athleteworkoutexerciseoverride",
            constraint=models.CheckConstraint(condition=models.Q(weight_lbs__isnull=True) | models.Q(weight_lbs__gte=0, weight_lbs__lt=float("inf")), name="athlete_workout_override_finite_weight"),
        ),
        migrations.RemoveConstraint(
            model_name="rackworkoutstate",
            name="rack_selected_athlete_requires_catalog_assignment",
        ),
        migrations.AddConstraint(
            model_name="rackworkoutstate",
            constraint=models.CheckConstraint(
                condition=models.Q(selected_athlete__isnull=True) | models.Q(active_session__isnull=False, active_program__isnull=True),
                name="rack_selected_athlete_requires_active_context",
            ),
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            clear_identities_incompatible_with_slice_three,
        ),
    ]
