from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def initialize_setup(apps, schema_editor):
    app, model = settings.AUTH_USER_MODEL.split('.')
    exists = apps.get_model(app, model).objects.using(schema_editor.connection.alias).exists()
    apps.get_model('event_handler', 'InstallationSetup').objects.using(
        schema_editor.connection.alias
    ).create(pk=1, completed_at=timezone.now() if exists else None)


class Migration(migrations.Migration):
    dependencies = [
        ('event_handler', '0022_rackscreen_screen_one_per_assigned_rack'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(name='InstallationSetup', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('completed_at', models.DateTimeField(blank=True, null=True)),
        ]),
        migrations.AddField(model_name='athlete', name='is_active', field=models.BooleanField(default=True)),
        migrations.RunPython(initialize_setup, migrations.RunPython.noop),
    ]
