# Hand-written on purpose. Converts the free-text `exercise` column on Program,
# Set, and AthleteReferenceMax into a link to the Exercise catalog, WITHOUT losing
# the existing names. The dance per model: make the old text column temporarily
# nullable, add a temp catalog link, copy each name into a catalog row (creating
# it if new), drop the text column, then rename the link into `exercise`.
#
# Fully reversible: the reverse copies each catalog name back into the text column
# before the link is dropped, and the text column is re-added nullable-first so it
# re-creates cleanly on a populated table.
import django.db.models.deletion
from django.db import migrations, models


def link_to_catalog(apps, schema_editor):
    Exercise = apps.get_model('event_handler', 'Exercise')
    for model_name in ('Program', 'Set', 'AthleteReferenceMax'):
        Model = apps.get_model('event_handler', model_name)
        for row in Model.objects.all():
            exercise, _ = Exercise.objects.get_or_create(name=row.exercise)
            row.exercise_tmp = exercise
            row.save(update_fields=['exercise_tmp'])


def unlink_to_text(apps, schema_editor):
    # Reverse: put the catalog name back into the text column.
    for model_name in ('Program', 'Set', 'AthleteReferenceMax'):
        Model = apps.get_model('event_handler', model_name)
        for row in Model.objects.all():
            row.exercise = row.exercise_tmp.name if row.exercise_tmp_id else ''
            row.save(update_fields=['exercise'])


def _tmp_fk(related_name):
    return models.ForeignKey(
        null=True, on_delete=django.db.models.deletion.PROTECT,
        related_name=related_name, to='event_handler.exercise')


def _final_fk(related_name):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT,
        related_name=related_name, to='event_handler.exercise')


class Migration(migrations.Migration):

    dependencies = [
        ('event_handler', '0004_tag_exercise'),
    ]

    operations = [
        # 0. drop the reference-max index first — it's built on the old `exercise`
        #    text column, and dropping that column would cascade-drop the index out
        #    from under Django's state. We re-add it (on the new link) at the end.
        migrations.RemoveIndex('athletereferencemax', 'event_handl_athlete_943cc6_idx'),
        # 1. make the old text columns nullable (so the reverse can re-add them cleanly)
        migrations.AlterField('program', 'exercise', models.CharField(max_length=255, null=True)),
        migrations.AlterField('set', 'exercise', models.CharField(max_length=255, null=True)),
        migrations.AlterField('athletereferencemax', 'exercise', models.CharField(max_length=255, null=True)),
        # 2. add the temp catalog links (nullable while we backfill)
        migrations.AddField('program', 'exercise_tmp', _tmp_fk('programs')),
        migrations.AddField('set', 'exercise_tmp', _tmp_fk('sets')),
        migrations.AddField('athletereferencemax', 'exercise_tmp', _tmp_fk('reference_maxes')),
        # 3. copy every name into a catalog row and link it
        migrations.RunPython(link_to_catalog, unlink_to_text),
        # 4. drop the old text columns
        migrations.RemoveField('program', 'exercise'),
        migrations.RemoveField('set', 'exercise'),
        migrations.RemoveField('athletereferencemax', 'exercise'),
        # 5. rename the links into place
        migrations.RenameField('program', 'exercise_tmp', 'exercise'),
        migrations.RenameField('set', 'exercise_tmp', 'exercise'),
        migrations.RenameField('athletereferencemax', 'exercise_tmp', 'exercise'),
        # 6. now that every row is linked, require the link
        migrations.AlterField('program', 'exercise', _final_fk('programs')),
        migrations.AlterField('set', 'exercise', _final_fk('sets')),
        migrations.AlterField('athletereferencemax', 'exercise', _final_fk('reference_maxes')),
        # 7. re-add the reference-max index, now on the catalog link, with an
        #    explicit stable name so Django never tries to auto-rename it again.
        migrations.AddIndex('athletereferencemax', models.Index(
            fields=['athlete', 'exercise', '-recorded_at'], name='aref_athlete_exercise_idx')),
    ]
