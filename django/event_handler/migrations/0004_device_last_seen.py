from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('event_handler', '0003_device_battery_device_connection_interrupted_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='device',
                    name='last_seen',
                    field=models.DateTimeField(blank=True, null=True),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE event_handler_device ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP WITH TIME ZONE NULL;",
                    reverse_sql="ALTER TABLE event_handler_device DROP COLUMN IF EXISTS last_seen;",
                ),
            ],
        ),
    ]
