from django.conf import settings
from django.db import migrations


def assign_existing_coaches(apps, schema_editor):
    alias = schema_editor.connection.alias
    School = apps.get_model('event_handler', 'School')
    Room = apps.get_model('event_handler', 'WeightRoom')
    Setup = apps.get_model('event_handler', 'InstallationSetup')
    Profile = apps.get_model('event_handler', 'CoachProfile')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    school = School.objects.using(alias).create(name='My school')
    room = Room.objects.using(alias).create(school=school, name='Main weight room')
    Setup.objects.using(alias).update_or_create(pk=1, defaults={'weight_room_id': room.pk})
    for user_id in User.objects.using(alias).values_list('pk', flat=True).iterator():
        Profile.objects.using(alias).update_or_create(
            user_id=user_id, defaults={'weight_room_id': room.pk})


class Migration(migrations.Migration):
    # Keep backfill separate: PostgreSQL must finish creating FK indexes before
    # updates enqueue deferred constraint triggers on existing profile rows.
    dependencies = [('event_handler', '0025_coach_weight_room')]
    operations = [migrations.RunPython(assign_existing_coaches, migrations.RunPython.noop)]
