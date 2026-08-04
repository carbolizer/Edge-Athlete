from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0014_scheduled_athlete_plans")]

    operations = [
        migrations.AddField(
            model_name="athleteschedule",
            name="active",
            field=models.BooleanField(default=True),
        ),
    ]
