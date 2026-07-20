import django.db.models.deletion
import django.core.validators
from django.db import migrations, models


def preflight_selected_athletes(apps, schema_editor):
    rack_state = apps.get_model("event_handler", "RackWorkoutState")
    conflict = (
        rack_state.objects.exclude(selected_athlete_id=None)
        .values("selected_athlete_id")
        .annotate(total=models.Count("rack_number"))
        .filter(total__gt=1)
        .order_by("selected_athlete_id")
        .first()
    )
    if conflict:
        raise RuntimeError(
            "Migration 0012 requires each selected athlete to appear on at most one rack. "
            "Clear duplicate rack selections before migrating."
        )


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0011_daily_report_browse_indexes")]

    operations = [
        migrations.RunPython(preflight_selected_athletes, migrations.RunPython.noop),
        migrations.CreateModel(
            name="AthleteWorkoutProgramAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("athlete", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="workout_program_assignment", to="event_handler.athlete")),
                ("workout_program", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="athlete_program_assignments", to="event_handler.workoutprogram")),
            ],
        ),
        migrations.CreateModel(
            name="AthleteDayProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("expected_set_number", models.PositiveIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(2147483647)])),
                ("status", models.CharField(choices=[("ready", "Ready"), ("in_set", "In set"), ("complete", "Complete")], default="ready", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("athlete", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="day_progress", to="event_handler.athlete")),
                ("current_program_item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="current_athlete_progress", to="event_handler.workoutprogramitem")),
                ("current_workout_exercise", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="current_athlete_progress", to="event_handler.workoutexercise")),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="athlete_progress", to="event_handler.session")),
                ("workout_program", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="athlete_progress", to="event_handler.workoutprogram")),
            ],
        ),
        migrations.AddConstraint(
            model_name="athletedayprogress",
            constraint=models.UniqueConstraint(fields=("session", "athlete"), name="athlete_day_progress_unique_session_athlete"),
        ),
        migrations.AddConstraint(
            model_name="athletedayprogress",
            constraint=models.CheckConstraint(condition=models.Q(models.Q(current_program_item__isnull=True, current_workout_exercise__isnull=True, expected_set_number__isnull=True, status="complete"), models.Q(current_program_item__isnull=False, current_workout_exercise__isnull=False, expected_set_number__gte=1, status__in=["ready", "in_set"]), _connector="OR"), name="athlete_day_progress_status_fields"),
        ),
        migrations.AddConstraint(
            model_name="rackworkoutstate",
            constraint=models.UniqueConstraint(condition=models.Q(("selected_athlete__isnull", False)), fields=("selected_athlete",), name="rack_selected_athlete_unique"),
        ),
        migrations.AddField(
            model_name="set",
            name="athlete_day_progress",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sets", to="event_handler.athletedayprogress"),
        ),
        migrations.AddField(
            model_name="set",
            name="workout_exercise",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="performed_sets", to="event_handler.workoutexercise"),
        ),
        migrations.AddField(
            model_name="set",
            name="workout_program_item",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sets", to="event_handler.workoutprogramitem"),
        ),
        migrations.AddConstraint(
            model_name="set",
            constraint=models.CheckConstraint(condition=models.Q(models.Q(athlete_day_progress__isnull=True, workout_exercise__isnull=True, workout_program_item__isnull=True), models.Q(athlete_day_progress__isnull=False, workout_exercise__isnull=False, workout_program_item__isnull=False), _connector="OR"), name="set_athlete_progress_binding_complete"),
        ),
        migrations.AddConstraint(
            model_name="set",
            constraint=models.UniqueConstraint(condition=models.Q(("athlete_day_progress__isnull", False), ("ended_at__isnull", True)), fields=("athlete_day_progress",), name="set_one_unfinished_per_athlete_progress"),
        ),
    ]
