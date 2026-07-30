# P14 — a program can lay its training days onto real dates.
#
# WHAT THIS DOES, in plain terms: two things, and they go together.
#
# 1. `ScheduledSession` — a new table of planned slots. "This program's Day 2, on
#    the 14th." Its `session` link is empty until a coach actually creates that
#    day, so the calendar can show a whole 8-week plan while only the days that
#    really happened exist as sessions.
#
# 2. `TrainingSession.started_at` becomes NULLABLE. Until now it was
#    auto_now_add, which meant a session existed only once it started — the
#    schema literally could not say "Thursday's session, not yet run". Null now
#    means created-but-not-started.
#
# ⚠️ SAFE ON EXISTING DATA. Dropping auto_now_add only stops Django setting the
# column on INSERT; it does not touch rows already written, and the column keeps
# its type. Every session that has already run keeps its real start time. There
# is deliberately no data migration here, because there is nothing to fix up.
#
# ⚠️ THE CONSEQUENCE THAT MATTERS MORE THAN THE SCHEMA: "the active session" now
# has to mean STARTED and not ended, never merely un-ended. Postgres sorts NULLs
# FIRST in a descending order, so without that filter a session created for next
# Thursday would sort ahead of the day actually being trained and the racks would
# follow it — canon D18 with a calendar bolted on. The filter lives in exactly one
# place: services/active_session.py.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('event_handler', '0015_traininggroupcoach'),
    ]

    operations = [
        migrations.AlterField(
            model_name='trainingsession',
            name='started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='ScheduledSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('session', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='scheduled_slots', to='event_handler.trainingsession')),
                ('training_program', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scheduled_sessions', to='event_handler.trainingprogram')),
                ('training_program_workout', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='scheduled_sessions', to='event_handler.trainingprogramworkout')),
            ],
            options={
                'ordering': ['date', 'id'],
                'constraints': [models.UniqueConstraint(fields=('training_program', 'date'), name='one_slot_per_program_per_day')],
            },
        ),
    ]
