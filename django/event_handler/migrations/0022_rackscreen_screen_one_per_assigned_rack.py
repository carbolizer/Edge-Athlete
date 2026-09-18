# One screen per assigned rack, the same rule Node has for sensors.
#
# A stale browser could hold rack 1 while the real screen was assigned to it
# too, and the room-state snapshot returned whichever row it found first — a
# ghost screen the coach could not reassign. The data step clears every screen
# except the most recently seen one on any rack with duplicates, mirroring what
# migration 0018 did for nodes, so the constraint below never fails to apply.
from django.db import migrations, models


def reconcile_duplicate_screens(apps, schema_editor):
    RackScreen = apps.get_model("event_handler", "RackScreen")
    claimed = set()
    for screen in RackScreen.objects.filter(rack_number__isnull=False).order_by("-last_seen"):
        if screen.rack_number in claimed:
            screen.rack_number = None
            screen.save(update_fields=["rack_number"])
        else:
            claimed.add(screen.rack_number)


class Migration(migrations.Migration):

    dependencies = [
        ("event_handler", "0021_node_acquisition_and_receipt_index"),
    ]

    operations = [
        migrations.RunPython(reconcile_duplicate_screens, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="rackscreen",
            constraint=models.UniqueConstraint(
                condition=models.Q(("rack_number__isnull", False)),
                fields=("rack_number",),
                name="screen_one_per_assigned_rack",
            ),
        ),
    ]
