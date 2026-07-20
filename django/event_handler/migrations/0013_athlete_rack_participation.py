import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0012_athlete_driven_training_foundation")]

    operations = [
        migrations.CreateModel(
            name="AthleteRackParticipation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rack_number", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("athlete", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rack_participation", to="event_handler.athlete")),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="athlete_rack_participation", to="event_handler.session")),
            ],
        ),
        migrations.AddConstraint(
            model_name="athleterackparticipation",
            constraint=models.UniqueConstraint(fields=("session", "athlete", "rack_number"), name="athlete_rack_participation_unique"),
        ),
        migrations.AddConstraint(
            model_name="athleterackparticipation",
            constraint=models.CheckConstraint(condition=models.Q(("rack_number__gt", 0)), name="athlete_rack_participation_positive_rack"),
        ),
    ]
