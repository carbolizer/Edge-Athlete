import django.core.validators
import django.db.models.deletion
import warnings
from django.db import migrations, models
from django.utils import timezone


def backfill_training_dates(apps, schema_editor):
    Session = apps.get_model("event_handler", "Session")
    for session in Session.objects.filter(training_date=None).iterator():
        session.training_date = timezone.localtime(session.started_at).date()
        session.save(update_fields=["training_date"])


def prepare_reverse(apps, schema_editor):
    Set = apps.get_model("event_handler", "Set")
    Progress = apps.get_model("event_handler", "AthleteDayProgress")
    DayPlan = apps.get_model("event_handler", "AthleteDayPlan")
    Report = apps.get_model("event_handler", "DailyReport")
    if DayPlan.objects.filter(session__ended_at=None).exists() or Progress.objects.filter(
        day_plan__isnull=False, session__ended_at=None,
    ).exists() or Set.objects.filter(day_plan_workout__isnull=False, ended_at=None).exists():
        raise RuntimeError(
            "Cannot reverse 0014 while an active schema-3 day, active frozen progress, "
            "or unfinished frozen set exists. End the day and all sets first."
        )
    if DayPlan.objects.exists() or Report.objects.filter(schema_version=3).exists():
        warnings.warn(
            "Reversing 0014 preserves core training rows and schema-3 reports, but the old "
            "application cannot interpret frozen schedule metadata.",
            RuntimeWarning,
        )
    Set.objects.filter(day_plan_workout__isnull=False).update(
        day_plan_workout=None, day_plan_exercise=None, athlete_day_progress=None,
    )
    Progress.objects.filter(day_plan__isnull=False).delete()
    # Flush deferred FK checks before the remaining reverse operations alter tables.
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0013_athlete_rack_participation")]

    operations = [
        migrations.CreateModel(name="AthleteDayPlan", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("schedule_source", models.CharField(max_length=16)),
            ("schedule_version", models.PositiveIntegerField(blank=True, null=True)),
            ("name", models.CharField(max_length=255)),
        ]),
        migrations.CreateModel(name="AthleteDayPlanExercise", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("exercise", models.CharField(max_length=255)),
            ("position", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
            ("sets", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
            ("reps", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
            ("weight_lbs", models.FloatField(validators=[django.core.validators.MinValueValidator(0)])),
            ("velocity_min", models.FloatField(blank=True, null=True)),
            ("velocity_max", models.FloatField(blank=True, null=True)),
        ], options={"ordering": ["position", "id"]}),
        migrations.CreateModel(name="AthleteDayPlanWorkout", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=255)),
            ("position", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
        ], options={"ordering": ["position", "id"]}),
        migrations.CreateModel(name="AthleteSchedule", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("version", models.PositiveIntegerField(default=1, validators=[django.core.validators.MinValueValidator(1)])),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ]),
        migrations.CreateModel(name="AthleteScheduleEntry", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("date", models.DateField(blank=True, null=True)),
            ("weekday", models.PositiveSmallIntegerField(blank=True, null=True)),
            ("is_rest", models.BooleanField(default=False)),
        ], options={"ordering": ["date", "weekday", "id"]}),
        migrations.CreateModel(name="AthleteSchedulePlan", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=255)),
            ("position", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
        ], options={"ordering": ["position", "id"]}),
        migrations.CreateModel(name="AthleteSchedulePlanExercise", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("exercise", models.CharField(max_length=255)),
            ("position", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
            ("sets", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
            ("reps", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
            ("weight_lbs", models.FloatField(validators=[django.core.validators.MinValueValidator(0)])),
            ("velocity_min", models.FloatField(blank=True, null=True)),
            ("velocity_max", models.FloatField(blank=True, null=True)),
        ], options={"ordering": ["position", "id"]}),
        migrations.CreateModel(name="AthleteSchedulePlanWorkout", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=255)),
            ("position", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
        ], options={"ordering": ["position", "id"]}),
        migrations.RemoveConstraint(model_name="athletedayprogress", name="athlete_day_progress_status_fields"),
        migrations.RemoveConstraint(model_name="set", name="set_athlete_progress_binding_complete"),
        migrations.AddField(model_name="session", name="training_date", field=models.DateField(blank=True, null=True)),
        migrations.AlterField(model_name="athletedayprogress", name="workout_program", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="athlete_progress", to="event_handler.workoutprogram")),
        migrations.AddField(model_name="athletedayplan", name="athlete", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="day_plans", to="event_handler.athlete")),
        migrations.AddField(model_name="athletedayplan", name="session", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="athlete_day_plans", to="event_handler.session")),
        migrations.AddField(model_name="athletedayplan", name="source_program", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="frozen_athlete_day_plans", to="event_handler.workoutprogram")),
        migrations.AddField(model_name="athletedayprogress", name="day_plan", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="progress", to="event_handler.athletedayplan")),
        migrations.AddField(model_name="athletedayplanexercise", name="source_exercise", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="frozen_day_occurrences", to="event_handler.workoutexercise")),
        migrations.AddField(model_name="athletedayprogress", name="current_day_plan_exercise", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="current_progress", to="event_handler.athletedayplanexercise")),
        migrations.AddField(model_name="set", name="day_plan_exercise", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="performed_sets", to="event_handler.athletedayplanexercise")),
        migrations.AddField(model_name="athletedayplanworkout", name="day_plan", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="workouts", to="event_handler.athletedayplan")),
        migrations.AddField(model_name="athletedayplanworkout", name="source_workout", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="frozen_day_occurrences", to="event_handler.workout")),
        migrations.AddField(model_name="athletedayplanexercise", name="workout", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="exercises", to="event_handler.athletedayplanworkout")),
        migrations.AddField(model_name="athletedayprogress", name="current_day_plan_workout", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="current_progress", to="event_handler.athletedayplanworkout")),
        migrations.AddField(model_name="set", name="day_plan_workout", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sets", to="event_handler.athletedayplanworkout")),
        migrations.AddConstraint(model_name="athletedayprogress", constraint=models.CheckConstraint(condition=models.Q(models.Q(day_plan__isnull=True, workout_program__isnull=False), models.Q(day_plan__isnull=False, workout_program__isnull=True), _connector="OR"), name="athlete_day_progress_one_plan_binding")),
        migrations.AddConstraint(model_name="athletedayprogress", constraint=models.CheckConstraint(condition=models.Q(models.Q(current_day_plan_exercise__isnull=True, current_day_plan_workout__isnull=True, current_program_item__isnull=True, current_workout_exercise__isnull=True, expected_set_number__isnull=True, status="complete"), models.Q(current_day_plan_exercise__isnull=True, current_day_plan_workout__isnull=True, current_program_item__isnull=False, current_workout_exercise__isnull=False, day_plan__isnull=True, expected_set_number__gte=1, status__in=["ready", "in_set"], workout_program__isnull=False), models.Q(current_day_plan_exercise__isnull=False, current_day_plan_workout__isnull=False, current_program_item__isnull=True, current_workout_exercise__isnull=True, day_plan__isnull=False, expected_set_number__gte=1, status__in=["ready", "in_set"], workout_program__isnull=True), _connector="OR"), name="athlete_day_progress_status_fields")),
        migrations.AddConstraint(model_name="set", constraint=models.CheckConstraint(condition=models.Q(models.Q(athlete_day_progress__isnull=True, day_plan_exercise__isnull=True, day_plan_workout__isnull=True, workout_exercise__isnull=True, workout_program_item__isnull=True), models.Q(athlete_day_progress__isnull=False, day_plan_exercise__isnull=True, day_plan_workout__isnull=True, workout_exercise__isnull=False, workout_program_item__isnull=False), models.Q(athlete_day_progress__isnull=False, day_plan_exercise__isnull=False, day_plan_workout__isnull=False, workout_exercise__isnull=True, workout_program_item__isnull=True), _connector="OR"), name="set_athlete_progress_binding_complete")),
        migrations.AddField(model_name="athleteschedule", name="athlete", field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="schedule", to="event_handler.athlete")),
        migrations.AddField(model_name="athletescheduleentry", name="schedule", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entries", to="event_handler.athleteschedule")),
        migrations.AddField(model_name="athletescheduleplan", name="schedule", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="plans", to="event_handler.athleteschedule")),
        migrations.AddField(model_name="athletescheduleplan", name="source_program", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="athlete_schedule_plans", to="event_handler.workoutprogram")),
        migrations.AddField(model_name="athletescheduleentry", name="plan", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="entries", to="event_handler.athletescheduleplan")),
        migrations.AddField(model_name="athletescheduleplanexercise", name="source_exercise", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="athlete_schedule_occurrences", to="event_handler.workoutexercise")),
        migrations.AddField(model_name="athletescheduleplanworkout", name="plan", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="workouts", to="event_handler.athletescheduleplan")),
        migrations.AddField(model_name="athletescheduleplanworkout", name="source_workout", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="athlete_schedule_occurrences", to="event_handler.workout")),
        migrations.AddField(model_name="athletescheduleplanexercise", name="workout", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="exercises", to="event_handler.athletescheduleplanworkout")),
        migrations.AddConstraint(model_name="athletedayplan", constraint=models.UniqueConstraint(fields=("session", "athlete"), name="athlete_day_plan_unique_session_athlete")),
        migrations.AddConstraint(model_name="athletedayplan", constraint=models.CheckConstraint(condition=models.Q(schedule_version__isnull=True) | models.Q(schedule_version__gte=1), name="athlete_day_plan_positive_schedule_version")),
        migrations.AddConstraint(model_name="athletedayplanworkout", constraint=models.UniqueConstraint(fields=("day_plan", "position"), name="athlete_day_workout_unique_position")),
        migrations.AddConstraint(model_name="athletedayplanworkout", constraint=models.CheckConstraint(condition=models.Q(position__gte=1), name="athlete_day_workout_positive_position")),
        migrations.AddConstraint(model_name="athletedayplanexercise", constraint=models.UniqueConstraint(fields=("workout", "position"), name="athlete_day_exercise_unique_position")),
        migrations.AddConstraint(model_name="athletedayplanexercise", constraint=models.CheckConstraint(condition=models.Q(position__gte=1), name="athlete_day_exercise_positive_position")),
        migrations.AddConstraint(model_name="athletedayplanexercise", constraint=models.CheckConstraint(condition=models.Q(sets__gte=1), name="athlete_day_exercise_positive_sets")),
        migrations.AddConstraint(model_name="athletedayplanexercise", constraint=models.CheckConstraint(condition=models.Q(reps__gte=1), name="athlete_day_exercise_positive_reps")),
        migrations.AddConstraint(model_name="athletedayplanexercise", constraint=models.CheckConstraint(condition=models.Q(weight_lbs__gte=0, weight_lbs__lt=float("inf")), name="athlete_day_exercise_finite_weight")),
        migrations.AddConstraint(model_name="athletedayplanexercise", constraint=models.CheckConstraint(condition=models.Q(models.Q(velocity_max__isnull=True, velocity_min__isnull=True), models.Q(velocity_max__isnull=False, velocity_max__gte=models.F("velocity_min"), velocity_max__lte=10, velocity_min__isnull=False, velocity_min__gte=0), _connector="OR"), name="athlete_day_exercise_velocity_valid")),
        migrations.AddConstraint(model_name="athleteschedule", constraint=models.CheckConstraint(condition=models.Q(version__gte=1), name="athlete_schedule_positive_version")),
        migrations.AddConstraint(model_name="athletescheduleplan", constraint=models.UniqueConstraint(fields=("schedule", "position"), name="athlete_schedule_plan_unique_position")),
        migrations.AddConstraint(model_name="athletescheduleplan", constraint=models.CheckConstraint(condition=models.Q(position__gte=1), name="athlete_schedule_plan_positive_position")),
        migrations.AddConstraint(model_name="athletescheduleentry", constraint=models.CheckConstraint(condition=models.Q(models.Q(date__isnull=False, weekday__isnull=True), models.Q(date__isnull=True, weekday__range=(0, 6)), _connector="OR"), name="athlete_schedule_entry_one_selector")),
        migrations.AddConstraint(model_name="athletescheduleentry", constraint=models.CheckConstraint(condition=models.Q(models.Q(is_rest=True, plan__isnull=True), models.Q(is_rest=False, plan__isnull=False), _connector="OR"), name="athlete_schedule_entry_plan_or_rest")),
        migrations.AddConstraint(model_name="athletescheduleentry", constraint=models.UniqueConstraint(condition=models.Q(date__isnull=False), fields=("schedule", "date"), name="athlete_schedule_entry_unique_date")),
        migrations.AddConstraint(model_name="athletescheduleentry", constraint=models.UniqueConstraint(condition=models.Q(weekday__isnull=False), fields=("schedule", "weekday"), name="athlete_schedule_entry_unique_weekday")),
        migrations.AddConstraint(model_name="athletescheduleplanworkout", constraint=models.UniqueConstraint(fields=("plan", "position"), name="athlete_schedule_workout_unique_position")),
        migrations.AddConstraint(model_name="athletescheduleplanworkout", constraint=models.CheckConstraint(condition=models.Q(position__gte=1), name="athlete_schedule_workout_positive_position")),
        migrations.AddConstraint(model_name="athletescheduleplanexercise", constraint=models.UniqueConstraint(fields=("workout", "position"), name="athlete_schedule_exercise_unique_position")),
        migrations.AddConstraint(model_name="athletescheduleplanexercise", constraint=models.CheckConstraint(condition=models.Q(position__gte=1), name="athlete_schedule_exercise_positive_position")),
        migrations.AddConstraint(model_name="athletescheduleplanexercise", constraint=models.CheckConstraint(condition=models.Q(sets__gte=1), name="athlete_schedule_exercise_positive_sets")),
        migrations.AddConstraint(model_name="athletescheduleplanexercise", constraint=models.CheckConstraint(condition=models.Q(reps__gte=1), name="athlete_schedule_exercise_positive_reps")),
        migrations.AddConstraint(model_name="athletescheduleplanexercise", constraint=models.CheckConstraint(condition=models.Q(weight_lbs__gte=0, weight_lbs__lt=float("inf")), name="athlete_schedule_exercise_finite_weight")),
        migrations.AddConstraint(model_name="athletescheduleplanexercise", constraint=models.CheckConstraint(condition=models.Q(models.Q(velocity_max__isnull=True, velocity_min__isnull=True), models.Q(velocity_max__isnull=False, velocity_max__gte=models.F("velocity_min"), velocity_max__lte=10, velocity_min__isnull=False, velocity_min__gte=0), _connector="OR"), name="athlete_schedule_exercise_velocity_valid")),
        migrations.RunPython(backfill_training_dates, prepare_reverse),
    ]
