# Adds the rack controller lease, transient snapshot, and durable command
# deduplication. Controller tokens are represented only by SHA-256 digests.
from django.db import migrations, models
import django.db.models.deletion


def create_assigned_rack_runtimes(apps, schema_editor):
    Node = apps.get_model("event_handler", "Node")
    RackRuntime = apps.get_model("event_handler", "RackRuntime")
    for rack_number in Node.objects.exclude(rack_number=None).values_list("rack_number", flat=True):
        RackRuntime.objects.get_or_create(rack_number=rack_number)


class Migration(migrations.Migration):
    dependencies = [
        ("event_handler", "0019_safe_assigned_node_ids"),
    ]

    operations = [
        migrations.CreateModel(
            name="RackRuntime",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rack_number", models.IntegerField(unique=True)),
                ("client_instance_id", models.CharField(blank=True, max_length=255)),
                ("controller_token_digest", models.CharField(blank=True, max_length=64)),
                ("controller_epoch", models.PositiveBigIntegerField(default=0)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("state_version", models.PositiveBigIntegerField(default=0)),
                ("phase", models.CharField(choices=[("idle", "Idle"), ("countdown", "Countdown"), ("active", "Active"), ("summary", "Summary"), ("rest", "Rest"), ("recovery_required", "Recovery required")], default="idle", max_length=24)),
                ("rep_count", models.PositiveIntegerField(default=0)),
                ("latest_mean_velocity", models.FloatField(blank=True, null=True)),
                ("latest_peak_velocity", models.FloatField(blank=True, null=True)),
                ("latest_color", models.CharField(blank=True, max_length=16)),
                ("phase_started_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("controller_screen", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="controlled_runtimes", to="event_handler.rackscreen")),
                ("current_set", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="runtime_states", to="event_handler.set")),
                ("selected_athlete", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="selected_at_runtimes", to="event_handler.athlete")),
                ("selected_exercise", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="selected_at_runtimes", to="event_handler.exercise")),
            ],
        ),
        migrations.CreateModel(
            name="RackCommandReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("command_id", models.UUIDField()),
                ("controller_epoch", models.PositiveBigIntegerField()),
                ("controller_device_id", models.CharField(max_length=255)),
                ("client_instance_id", models.CharField(max_length=255)),
                ("controller_token_digest", models.CharField(max_length=64)),
                ("response_status", models.PositiveSmallIntegerField()),
                ("response_body", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("runtime", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="command_receipts", to="event_handler.rackruntime")),
            ],
        ),
        migrations.AddConstraint(
            model_name="rackcommandreceipt",
            constraint=models.UniqueConstraint(fields=("runtime", "command_id"), name="rack_command_once_per_runtime"),
        ),
        migrations.RunPython(create_assigned_rack_runtimes, migrations.RunPython.noop),
    ]
