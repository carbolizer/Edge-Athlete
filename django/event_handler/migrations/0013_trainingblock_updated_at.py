# Adds TrainingBlock.updated_at so a coach can sort the catalog by what they
# edited most recently.
#
# Existing blocks get their created_at as a starting value rather than "now" —
# backfilling every block to the migration timestamp would claim they were all
# edited at the same instant, which is both false and useless for sorting. A
# block nobody has edited since it was made was, accurately, last changed when
# it was created.
from django.db import migrations, models


def seed_updated_at_from_created_at(apps, schema_editor):
    TrainingBlock = apps.get_model("event_handler", "TrainingBlock")
    for block in TrainingBlock.objects.all().iterator():
        # .update() rather than .save() — auto_now would overwrite this with the
        # current time, which is the exact thing we are avoiding.
        TrainingBlock.objects.filter(pk=block.pk).update(updated_at=block.created_at)


class Migration(migrations.Migration):

    dependencies = [
        ("event_handler", "0012_rename_session_to_trainingsession"),
    ]

    operations = [
        migrations.AddField(
            model_name="trainingblock",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.RunPython(seed_updated_at_from_created_at,
                             migrations.RunPython.noop),
    ]
