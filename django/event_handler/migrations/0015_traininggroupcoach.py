# P11 step 3 — several coaches can run one TrainingGroup.
#
# WHAT THIS DOES, in plain terms: a group used to name exactly one coach. A real
# weight room puts several staff on one group ("Sarah and Mike both run
# Varsity"), which one field cannot say. So the single `coach` column is replaced
# by a join table, and each group's existing coach is carried across as that
# group's HEAD coach. Nobody loses their group.
#
# ⚠️ THE ORDER OF THESE THREE OPERATIONS IS THE WHOLE POINT. Django's
# auto-generated version put the column drop FIRST, which would have deleted
# every group's coach before anything could copy it — an unrecoverable loss on a
# real database. Create the table, copy the data across, and only then drop the
# column. If you ever edit this file, keep that order.
#
# Safe on a clean database too: the backfill simply finds no groups and does
# nothing, so a fresh install and an existing one end up in the same shape.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def carry_coaches_into_the_join_table(apps, schema_editor):
    """Copy each group's single coach across as its head coach.

    Uses the HISTORICAL models (apps.get_model), never the imported ones — this
    has to keep working against the schema as it stood at this migration, not
    however models.py looks years from now.
    """
    TrainingGroup = apps.get_model("event_handler", "TrainingGroup")
    TrainingGroupCoach = apps.get_model("event_handler", "TrainingGroupCoach")

    TrainingGroupCoach.objects.bulk_create([
        TrainingGroupCoach(training_group_id=group_id, coach_id=coach_id, role="head")
        # .iterator() rather than loading every group: harmless on a school's
        # data, and it costs nothing to not assume the table is small.
        for group_id, coach_id in TrainingGroup.objects.values_list("id", "coach_id").iterator()
        if coach_id is not None
    ])


def put_the_head_coach_back(apps, schema_editor):
    """Reverse: restore the single `coach` column from each group's head coach.

    Only the head survives a reversal — the column can hold one person, so any
    assistants recorded after this migration ran are dropped on the way back.
    That is a real loss of information, not a rounding error, which is why the
    forward direction is the one to prefer.
    """
    TrainingGroup = apps.get_model("event_handler", "TrainingGroup")
    TrainingGroupCoach = apps.get_model("event_handler", "TrainingGroupCoach")

    for link in TrainingGroupCoach.objects.filter(role="head").iterator():
        TrainingGroup.objects.filter(pk=link.training_group_id).update(coach_id=link.coach_id)


class Migration(migrations.Migration):

    dependencies = [
        ('event_handler', '0014_blockcategory_trainingblock_categories'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. The new table.
        migrations.CreateModel(
            name='TrainingGroupCoach',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('head', 'Head coach'), ('assistant', 'Assistant coach')], default='assistant', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('coach', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='training_group_links', to=settings.AUTH_USER_MODEL)),
                ('training_group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='coach_links', to='event_handler.traininggroup')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('training_group', 'coach'), name='one_row_per_coach_per_group')],
            },
        ),

        # 2. Carry the existing coaches across BEFORE the column disappears.
        migrations.RunPython(carry_coaches_into_the_join_table, put_the_head_coach_back),

        # 3. Now the old field has nothing left to lose.
        migrations.RemoveField(
            model_name='traininggroup',
            name='coach',
        ),
    ]