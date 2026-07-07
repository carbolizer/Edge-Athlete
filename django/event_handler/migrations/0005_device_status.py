from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('event_handler', '0004_device_last_seen'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('active', 'Active'),
                    ('disabled', 'Disabled'),
                    ('removed', 'Removed'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]
