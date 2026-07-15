"""Snapshot set racks and add the durable dashboard publication outbox."""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0002_set_weight_lbs")]

    operations = [
        migrations.AddField(
            model_name="set",
            name="rack_number",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="MonitoringEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("reason", models.CharField(max_length=32)),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("publish_attempts", models.PositiveIntegerField(default=0)),
                ("last_error", models.CharField(blank=True, max_length=255)),
            ],
            options={"ordering": ["id"]},
        ),
    ]
