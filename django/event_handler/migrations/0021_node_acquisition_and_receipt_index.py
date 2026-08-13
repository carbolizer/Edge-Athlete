# Classifies WT901 Agent nodes and indexes the bounded controller receipt window.
from django.db import migrations, models


def classify_wt901_nodes(apps, schema_editor):
    Node = apps.get_model("event_handler", "Node")
    Node.objects.filter(firmware_version__startswith="wt901ble-").update(
        acquisition_kind="wt901_ble",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("event_handler", "0020_rack_controller_runtime"),
    ]

    operations = [
        migrations.AddField(
            model_name="node",
            name="acquisition_kind",
            field=models.CharField(
                choices=[("mqtt", "MQTT"), ("wt901_ble", "WT901 BLE")],
                default="mqtt",
                max_length=16,
            ),
        ),
        migrations.RunPython(classify_wt901_nodes, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name="rackcommandreceipt",
            index=models.Index(
                fields=["runtime", "created_at"], name="rack_receipt_runtime_time_idx",
            ),
        ),
    ]
