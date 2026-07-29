# Renames the Session model to TrainingSession. No behaviour changes.
#
# WHY: "Session" is one of the most overloaded words in web software — Django
# has its own sessions, so does HTTP, so does auth. Ours means something very
# specific and unrelated: one shared training slot that several groups can be
# scheduled into at once. Naming it TrainingSession puts it alongside
# TrainingBlock / TrainingProgram / TrainingGroup, so the whole hierarchy reads
# as one family instead of three named things and one generic one.
#
# RenameModel renames the underlying table and re-points every foreign key that
# referenced it (Set, DailyReport, RackCheckIn, SessionParticipation), so no
# data moves and nothing needs backfilling.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("event_handler", "0011_alter_set_session_delete_program"),
    ]

    operations = [
        migrations.RenameModel(old_name="Session", new_name="TrainingSession"),
    ]
