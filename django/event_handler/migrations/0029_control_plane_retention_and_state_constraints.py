# Generated for bounded control-plane retention and accepted state invariants.
import django.db.models.deletion
from django.db import migrations, models


def backfill_terminal_times(apps, schema_editor):
    EndpointPairing = apps.get_model("event_handler", "EndpointPairing")
    RackHelperPairing = apps.get_model("event_handler", "RackHelperPairing")
    RackHelperInstallation = apps.get_model("event_handler", "RackHelperInstallation")
    RackHelperLaunchIntent = apps.get_model("event_handler", "RackHelperLaunchIntent")

    for pairing in EndpointPairing.objects.exclude(state__in=["pending", "claimed"]):
        pairing.terminal_at = pairing.delivered_at or pairing.expires_at
        pairing.save(update_fields=["terminal_at"])
    for pairing in RackHelperPairing.objects.exclude(state__in=["pending", "claimed", "confirmed"]):
        pairing.terminal_at = pairing.activated_at or pairing.expires_at
        pairing.save(update_fields=["terminal_at"])
    for installation in RackHelperInstallation.objects.exclude(state__in=["pending_activation", "active"]):
        installation.terminal_at = installation.revoked_at or installation.activation_expires_at
        installation.pairing_id = None
        installation.save(update_fields=["terminal_at", "pairing"])
    RackHelperInstallation.objects.filter(state="active").update(pairing=None)
    for intent in RackHelperLaunchIntent.objects.exclude(state="pending"):
        intent.terminal_at = (
            intent.consumed_at or intent.superseded_at or intent.cancelled_at or intent.expires_at
        )
        intent.save(update_fields=["terminal_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("event_handler", "0028_remove_rackhelperpairing_confirmation_phrase"),
    ]

    operations = [
        migrations.AddField(
            model_name="endpointpairing",
            name="terminal_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="rackhelperinstallation",
            name="terminal_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="rackhelperlaunchintent",
            name="terminal_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="rackhelperpairing",
            name="terminal_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="rackhelperpairing",
            name="server_nonce",
            field=models.BinaryField(blank=True, max_length=32, null=True),
        ),
        migrations.AlterField(
            model_name="rackhelperinstallation",
            name="pairing",
            field=models.OneToOneField(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="installation", to="event_handler.rackhelperpairing",
            ),
        ),
        migrations.RunPython(backfill_terminal_times, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="apithrottlebucket",
            constraint=models.CheckConstraint(
                condition=models.Q(count__gte=1), name="api_throttle_count_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="endpointpairing",
            constraint=models.CheckConstraint(
                condition=models.Q(state__in=["pending", "claimed", "delivered", "expired", "cancelled"]),
                name="endpoint_pairing_state_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="endpointpairing",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(state__in=["pending", "claimed"], terminal_at__isnull=True)
                    | models.Q(state__in=["delivered", "expired", "cancelled"], terminal_at__isnull=False)
                ),
                name="endpoint_pairing_terminal_time_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="rackhelpercredential",
            constraint=models.CheckConstraint(
                condition=models.Q(state__in=["pending", "active", "revoked"]),
                name="helper_credential_state_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="rackhelperinstallation",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(state__in=["pending_activation", "active"], terminal_at__isnull=True)
                    | models.Q(state__in=["expired", "cancelled", "revoked"], terminal_at__isnull=False)
                ),
                name="helper_installation_terminal_time_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="rackhelperinstallation",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(state="pending_activation", pairing__isnull=False)
                    | models.Q(state__in=["active", "expired", "cancelled", "revoked"], pairing__isnull=True)
                ),
                name="helper_installation_pairing_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="rackhelperlaunchintent",
            constraint=models.CheckConstraint(
                condition=models.Q(state__in=["pending", "consumed", "superseded", "expired", "cancelled"]),
                name="launch_intent_state_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="rackhelperlaunchintent",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(state="pending", terminal_at__isnull=True)
                    | models.Q(state__in=["consumed", "superseded", "expired", "cancelled"], terminal_at__isnull=False)
                ),
                name="launch_intent_terminal_time_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="rackhelperpairing",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(state__in=["pending", "claimed", "confirmed"], terminal_at__isnull=True)
                    | models.Q(state__in=["activated", "expired", "cancelled"], terminal_at__isnull=False)
                ),
                name="helper_pairing_terminal_time_shape",
            ),
        ),
    ]
