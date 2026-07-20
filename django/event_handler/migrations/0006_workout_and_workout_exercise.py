import django.core.validators
import django.db.models.deletion
import django.db.models.expressions
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0005_rack_workout_state_and_nullable_velocity_zones")]

    operations = [
        migrations.CreateModel(
            name="Workout",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("normalized_name", models.TextField(editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name", "id"]},
        ),
        migrations.CreateModel(
            name="WorkoutExercise",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("exercise", models.CharField(max_length=255)),
                ("position", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(2147483647)])),
                ("sets", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(2147483647)])),
                ("reps", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(2147483647)])),
                ("default_weight_lbs", models.FloatField(validators=[django.core.validators.MinValueValidator(0)])),
                ("velocity_min", models.FloatField(blank=True, null=True)),
                ("velocity_max", models.FloatField(blank=True, null=True)),
                ("workout", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="exercises", to="event_handler.workout")),
            ],
            options={"ordering": ["position", "id"]},
        ),
        migrations.AddConstraint(
            model_name="workout",
            constraint=models.UniqueConstraint(fields=("normalized_name",), name="workout_normalized_name_unique"),
        ),
        migrations.AddConstraint(
            model_name="workout",
            constraint=models.CheckConstraint(condition=~models.Q(normalized_name=""), name="workout_normalized_name_not_empty"),
        ),
        migrations.AddConstraint(
            model_name="workoutexercise",
            constraint=models.UniqueConstraint(fields=("workout", "position"), name="workout_exercise_unique_position"),
        ),
        migrations.AddConstraint(
            model_name="workoutexercise",
            constraint=models.CheckConstraint(condition=models.Q(exercise__regex="\\S"), name="workout_exercise_nonempty_exercise"),
        ),
        migrations.AddConstraint(
            model_name="workoutexercise",
            constraint=models.CheckConstraint(condition=models.Q(position__gte=1), name="workout_exercise_positive_position"),
        ),
        migrations.AddConstraint(
            model_name="workoutexercise",
            constraint=models.CheckConstraint(condition=models.Q(sets__gte=1), name="workout_exercise_positive_sets"),
        ),
        migrations.AddConstraint(
            model_name="workoutexercise",
            constraint=models.CheckConstraint(condition=models.Q(reps__gte=1), name="workout_exercise_positive_reps"),
        ),
        migrations.AddConstraint(
            model_name="workoutexercise",
            constraint=models.CheckConstraint(condition=models.Q(default_weight_lbs__gte=0, default_weight_lbs__lt=float("inf")), name="workout_exercise_finite_nonnegative_weight"),
        ),
        migrations.AddConstraint(
            model_name="workoutexercise",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(velocity_min__isnull=True, velocity_max__isnull=True)
                    | models.Q(
                        velocity_min__isnull=False,
                        velocity_max__isnull=False,
                        velocity_min__gte=0,
                        velocity_min__lte=10,
                        velocity_max__gte=django.db.models.expressions.F("velocity_min"),
                        velocity_max__lte=10,
                    )
                ),
                name="workout_exercise_velocity_valid",
            ),
        ),
    ]
