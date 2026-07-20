import django.db.models.deletion
from django.db import migrations, models


def preflight_one_active_session(apps, schema_editor):
    session = apps.get_model("event_handler", "Session")
    active_ids = list(
        session.objects.filter(ended_at__isnull=True)
        .order_by("id")
        .values_list("id", flat=True)[:2]
    )
    if len(active_ids) > 1:
        raise RuntimeError(
            "Migration 0010 requires at most one active Session. End duplicate active sessions before migrating."
        )


IMMUTABLE_REPORT_SQL = """
CREATE FUNCTION event_handler_daily_report_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'DailyReport rows are immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER event_handler_daily_report_immutable_trigger
BEFORE UPDATE OR DELETE ON event_handler_dailyreport
FOR EACH ROW EXECUTE FUNCTION event_handler_daily_report_immutable();
"""


DROP_IMMUTABLE_REPORT_SQL = """
DROP TRIGGER IF EXISTS event_handler_daily_report_immutable_trigger ON event_handler_dailyreport;
DROP FUNCTION IF EXISTS event_handler_daily_report_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0009_athlete_workout_assignments_and_overrides")]

    operations = [
        migrations.RunPython(preflight_one_active_session, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="session",
            constraint=models.UniqueConstraint(
                models.Value(1),
                condition=models.Q(ended_at__isnull=True),
                name="session_one_active_training_day",
            ),
        ),
        migrations.CreateModel(
            name="DailyReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("schema_version", models.PositiveIntegerField(default=1)),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                ("snapshot", models.JSONField()),
                ("session", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="daily_report", to="event_handler.session")),
            ],
            options={"ordering": ["-generated_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="dailyreport",
            constraint=models.CheckConstraint(condition=models.Q(schema_version__gte=1), name="daily_report_positive_schema_version"),
        ),
        migrations.RunSQL(IMMUTABLE_REPORT_SQL, DROP_IMMUTABLE_REPORT_SQL),
    ]
