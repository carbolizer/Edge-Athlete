import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("event_handler", "0021_node_acquisition_and_receipt_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="node",
            name="assignment_revision",
            field=models.PositiveBigIntegerField(default=1),
        ),
        migrations.CreateModel(
            name="HostedGym",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("slug", models.SlugField(max_length=64, unique=True)),
                ("display_name", models.CharField(max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="EdgeGateway",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("label", models.CharField(max_length=120)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("last_contact_at", models.DateTimeField(blank=True, null=True)),
                ("last_event_at", models.DateTimeField(blank=True, null=True)),
                ("queue_state", models.CharField(choices=[("unknown", "Unknown"), ("healthy", "Healthy"), ("unhealthy", "Unhealthy"), ("full", "Full"), ("corrupt", "Corrupt"), ("read_only", "Read only")], default="unknown", max_length=16)),
                ("queue_depth", models.PositiveIntegerField(blank=True, null=True)),
                ("oldest_queued_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("gym", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="gateways", to="event_handler.hostedgym")),
            ],
        ),
        migrations.CreateModel(
            name="GatewayCredential",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.PositiveIntegerField()),
                ("secret_digest", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("not_before", models.DateTimeField()),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sponsored_gateway_credentials", to=settings.AUTH_USER_MODEL)),
                ("gateway", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="credentials", to="event_handler.edgegateway")),
            ],
        ),
        migrations.CreateModel(
            name="GatewayNodeGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("assignment_revision", models.PositiveBigIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("gateway", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="node_grants", to="event_handler.edgegateway")),
                ("node", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="gateway_grant", to="event_handler.node")),
            ],
        ),
        migrations.CreateModel(
            name="GatewayBoot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("boot_id", models.UUIDField()),
                ("server_epoch", models.PositiveBigIntegerField()),
                ("acknowledged_through", models.PositiveBigIntegerField(default=0)),
                ("first_received_at", models.DateTimeField(auto_now_add=True)),
                ("last_received_at", models.DateTimeField(auto_now=True)),
                ("superseded_at", models.DateTimeField(blank=True, null=True)),
                ("gateway", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="boots", to="event_handler.edgegateway")),
            ],
        ),
        migrations.AddField(
            model_name="edgegateway",
            name="current_boot",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="current_for_gateways", to="event_handler.gatewayboot"),
        ),
        migrations.CreateModel(
            name="GatewayEventReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_id", models.UUIDField()),
                ("sequence", models.PositiveBigIntegerField()),
                ("event_type", models.CharField(choices=[("sensor_health", "Sensor health")], default="sensor_health", max_length=24)),
                ("result", models.CharField(choices=[("accepted", "Accepted"), ("rejected", "Rejected")], max_length=16)),
                ("result_code", models.CharField(max_length=48)),
                ("occurred_at", models.DateTimeField()),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("boot", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="event_receipts", to="event_handler.gatewayboot")),
                ("gateway", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="event_receipts", to="event_handler.edgegateway")),
            ],
        ),
        migrations.CreateModel(
            name="GatewayNodeHealth",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sensor_state", models.CharField(choices=[("starting", "Starting"), ("live", "Live"), ("stale", "Stale"), ("reconnecting", "Reconnecting")], max_length=16)),
                ("sample_age_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("agent_schema_version", models.PositiveSmallIntegerField()),
                ("gateway_occurred_at", models.DateTimeField()),
                ("server_received_at", models.DateTimeField()),
                ("sequence", models.PositiveBigIntegerField()),
                ("boot", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="node_health_rows", to="event_handler.gatewayboot")),
                ("grant", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="health", to="event_handler.gatewaynodegrant")),
            ],
        ),
        migrations.AddConstraint(
            model_name="edgegateway",
            constraint=models.CheckConstraint(condition=models.Q(("queue_depth__isnull", True), ("queue_depth__lte", 50000), _connector="OR"), name="gateway_queue_depth_bounded"),
        ),
        migrations.AddConstraint(
            model_name="gatewaycredential",
            constraint=models.UniqueConstraint(fields=("gateway", "version"), name="gateway_credential_version_unique"),
        ),
        migrations.AddConstraint(
            model_name="gatewayboot",
            constraint=models.UniqueConstraint(fields=("gateway", "boot_id"), name="gateway_boot_id_unique"),
        ),
        migrations.AddConstraint(
            model_name="gatewayboot",
            constraint=models.UniqueConstraint(fields=("gateway", "server_epoch"), name="gateway_boot_epoch_unique"),
        ),
        migrations.AddConstraint(
            model_name="gatewayeventreceipt",
            constraint=models.UniqueConstraint(fields=("gateway", "event_id"), name="gateway_event_id_unique"),
        ),
        migrations.AddConstraint(
            model_name="gatewayeventreceipt",
            constraint=models.UniqueConstraint(fields=("boot", "sequence"), name="gateway_boot_sequence_unique"),
        ),
        migrations.AddConstraint(
            model_name="gatewaynodehealth",
            constraint=models.CheckConstraint(condition=models.Q(("sample_age_ms__isnull", True), ("sample_age_ms__lte", 600000), _connector="OR"), name="gateway_sample_age_bounded"),
        ),
        migrations.AddConstraint(
            model_name="gatewaynodehealth",
            constraint=models.CheckConstraint(condition=models.Q(("agent_schema_version__gte", 1)), name="gateway_agent_schema_positive"),
        ),
    ]
