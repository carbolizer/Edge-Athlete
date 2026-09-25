from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion




class Migration(migrations.Migration):
    dependencies = [
        ('event_handler', '0024_setup_code_and_coach_profiles'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(name='School', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('name', models.CharField(max_length=255)),
        ]),
        migrations.CreateModel(name='WeightRoom', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('name', models.CharField(max_length=255)),
            ('school', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='weight_rooms', to='event_handler.school')),
        ]),
        migrations.AddField(model_name='installationsetup', name='weight_room',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='event_handler.weightroom')),
        migrations.AddField(model_name='coachprofile', name='weight_room',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='coach_profiles', to='event_handler.weightroom')),
    ]
