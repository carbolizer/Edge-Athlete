# A scheduled slot dies with the day it runs.
#
# WHY THIS EXISTS ONE MIGRATION AFTER 0016: `ScheduledSession.training_program_workout`
# was created as PROTECT, on the reasoning "don't let a day the calendar points at
# disappear". That protected nothing and broke something real.
#
# Nothing deletes a program day directly — there is no route for it; P10's delete
# routes are for BLOCK days. What PROTECT actually did was make the whole
# TrainingProgram undeletable: deleting a program cascades to its days, and the
# slots then blocked their own parent's cleanup with a ProtectedError. The seeder's
# --reset path deletes programs, so it broke there first.
#
# A slot for a day that no longer exists is meaningless. It goes with it.
#
# Schema-only and safe: changing on_delete does not touch a single row. Django
# enforces cascade behaviour in Python, not as a database constraint, so this
# alters the field's declaration and nothing else.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('event_handler', '0016_scheduled_sessions'),
    ]

    operations = [
        migrations.AlterField(
            model_name='scheduledsession',
            name='training_program_workout',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                    related_name='scheduled_sessions',
                                    to='event_handler.trainingprogramworkout'),
        ),
    ]
