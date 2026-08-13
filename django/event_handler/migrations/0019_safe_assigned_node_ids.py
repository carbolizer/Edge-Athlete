# Quarantines assigned node IDs that could alter an MQTT topic before adding a
# database guard. The node record remains available for operator correction.
import re

from django.db import migrations, models


def clear_unsafe_assignments(apps, schema_editor):
    Node = apps.get_model("event_handler", "Node")
    for node in Node.objects.exclude(rack_number=None).iterator():
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", node.node_id) is None:
            node.rack_number = None
            node.save(update_fields=["rack_number"])


class Migration(migrations.Migration):
    dependencies = [
        ("event_handler", "0018_unique_assigned_node_per_rack"),
    ]

    operations = [
        migrations.RunPython(clear_unsafe_assignments, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="node",
            constraint=models.CheckConstraint(
                condition=models.Q(rack_number__isnull=True) | models.Q(node_id__regex="^[A-Za-z0-9_-]{1,64}$"),
                name="assigned_node_id_is_mqtt_safe",
            ),
        ),
    ]
