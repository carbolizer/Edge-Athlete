import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0006_workout_and_workout_exercise")]

    operations = [
        migrations.CreateModel(
            name="WorkoutProgram",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("normalized_name", models.TextField(editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name", "id"]},
        ),
        migrations.CreateModel(
            name="WorkoutProgramItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(2147483647)])),
                ("workout", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="workout_program_items", to="event_handler.workout")),
                ("workout_program", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="event_handler.workoutprogram")),
            ],
            options={"ordering": ["position", "id"]},
        ),
        migrations.AddConstraint(
            model_name="workoutprogram",
            constraint=models.UniqueConstraint(fields=("normalized_name",), name="workout_program_normalized_name_unique"),
        ),
        migrations.AddConstraint(
            model_name="workoutprogram",
            constraint=models.CheckConstraint(condition=~models.Q(normalized_name=""), name="workout_program_normalized_name_not_empty"),
        ),
        migrations.AddConstraint(
            model_name="workoutprogramitem",
            constraint=models.UniqueConstraint(fields=("workout_program", "position"), name="workout_program_item_unique_position"),
        ),
        migrations.AddConstraint(
            model_name="workoutprogramitem",
            constraint=models.UniqueConstraint(fields=("workout_program", "workout"), name="workout_program_item_unique_workout"),
        ),
        migrations.AddConstraint(
            model_name="workoutprogramitem",
            constraint=models.CheckConstraint(condition=models.Q(position__gte=1), name="workout_program_item_positive_position"),
        ),
    ]
