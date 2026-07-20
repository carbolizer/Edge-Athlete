import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0007_workout_program_and_items")]

    operations = [
        migrations.AddField(
            model_name="rackworkoutstate",
            name="assigned_program_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="rack_assignments",
                to="event_handler.workoutprogramitem",
            ),
        ),
        migrations.AddField(
            model_name="rackworkoutstate",
            name="assigned_workout",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="rack_assignments",
                to="event_handler.workout",
            ),
        ),
        migrations.AddField(
            model_name="rackworkoutstate",
            name="selected_athlete",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="selected_rack_states",
                to="event_handler.athlete",
            ),
        ),
        migrations.AddConstraint(
            model_name="rackworkoutstate",
            constraint=models.CheckConstraint(
                condition=(
                    (models.Q(active_program__isnull=True) | models.Q(assigned_workout__isnull=True))
                    & (models.Q(active_program__isnull=True) | models.Q(assigned_program_item__isnull=True))
                    & (models.Q(assigned_workout__isnull=True) | models.Q(assigned_program_item__isnull=True))
                ),
                name="rack_workout_state_one_assignment",
            ),
        ),
        migrations.AddConstraint(
            model_name="rackworkoutstate",
            constraint=models.CheckConstraint(
                condition=models.Q(selected_athlete__isnull=True) | (
                    models.Q(active_session__isnull=False)
                    & models.Q(active_program__isnull=True)
                    & (
                        models.Q(assigned_workout__isnull=False, assigned_program_item__isnull=True)
                        | models.Q(assigned_workout__isnull=True, assigned_program_item__isnull=False)
                    )
                ),
                name="rack_selected_athlete_requires_catalog_assignment",
            ),
        ),
    ]
