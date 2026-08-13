# Reconciles duplicate rack-node mappings before enforcing one node per rack.
# Ambiguous mappings become unassigned and require rack-side reselection.
from django.db import migrations, models


def clear_ambiguous_assignments(apps, schema_editor):
    """Require rack-side selection when legacy data mapped several nodes to one rack."""
    Node = apps.get_model("event_handler", "Node")
    duplicate_racks = (
        Node.objects.exclude(rack_number=None)
        .values("rack_number")
        .annotate(node_count=models.Count("id"))
        .filter(node_count__gt=1)
        .values_list("rack_number", flat=True)
    )
    Node.objects.filter(rack_number__in=list(duplicate_racks)).update(rack_number=None)


class Migration(migrations.Migration):
    dependencies = [
        ("event_handler", "0017_slot_day_cascade"),
    ]

    operations = [
        # Reverse cannot infer legacy mappings. It safely leaves current assignments intact.
        migrations.RunPython(clear_ambiguous_assignments, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="node",
            constraint=models.UniqueConstraint(
                fields=("rack_number",),
                condition=models.Q(("rack_number__isnull", False)),
                name="node_one_per_assigned_rack",
            ),
        ),
    ]
