import django.contrib.postgres.indexes
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0010_daily_report_and_one_active_session")]

    operations = [
        migrations.AddIndex(
            model_name="dailyreport",
            index=models.Index(
                fields=["-generated_at", "-id"],
                name="daily_report_newest_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="dailyreport",
            index=django.contrib.postgres.indexes.GinIndex(
                models.Func(
                    models.F("snapshot"),
                    models.Value("$.athletes[*].athlete.id"),
                    function="jsonb_path_query_array",
                ),
                name="daily_report_athlete_ids_gin",
            ),
        ),
    ]
