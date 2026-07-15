from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0003_monitoring_event_and_set_rack")]

    operations = [
        migrations.AddField(model_name="athlete", name="is_simulated", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="monitoringevent", name="is_simulated", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="node", name="is_simulated", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="program", name="is_simulated", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="session", name="is_simulated", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="set", name="is_simulated", field=models.BooleanField(default=False)),
    ]
