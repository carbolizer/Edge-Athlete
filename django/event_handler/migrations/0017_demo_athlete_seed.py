import django.db.models.deletion
from django.db import migrations, models


DEMO_NAMES = ["[DEMO] Avery", "[DEMO] Jordan", "[DEMO] Morgan", "[DEMO] Riley"]
DEMO_NFC_IDS = [
    "edgeathlete-demo-wristband-avery",
    "edgeathlete-demo-wristband-jordan",
    "edgeathlete-demo-wristband-morgan",
    "edgeathlete-demo-wristband-riley",
]
DEMO_WORKOUT_NAME = "[demo] wristband workout"
DEMO_PROGRAM_NAME = "[demo] wristband program"


def reject_duplicate_reserved_names(apps, schema_editor):
    Athlete = apps.get_model("event_handler", "Athlete")
    duplicates = (
        Athlete.objects.filter(name__in=DEMO_NAMES)
        .values("name")
        .annotate(count=models.Count("id"))
        .filter(count__gt=1)
    )
    if duplicates.exists():
        raise RuntimeError(
            "Cannot apply 0017 while a reserved demo athlete name is duplicated. "
            "Rename or remove the conflicting rows first."
        )


def prevent_owned_demo_reverse(apps, schema_editor):
    Athlete = apps.get_model("event_handler", "Athlete")
    DemoAthleteSeed = apps.get_model("event_handler", "DemoAthleteSeed")
    Workout = apps.get_model("event_handler", "Workout")
    WorkoutProgram = apps.get_model("event_handler", "WorkoutProgram")
    if (
        DemoAthleteSeed.objects.exists()
        or Athlete.objects.filter(models.Q(name__in=DEMO_NAMES) | models.Q(nfc_tag_id__in=DEMO_NFC_IDS)).exists()
        or Workout.objects.filter(normalized_name=DEMO_WORKOUT_NAME).exists()
        or WorkoutProgram.objects.filter(normalized_name=DEMO_PROGRAM_NAME).exists()
    ):
        raise RuntimeError(
            "Cannot reverse 0017 while the demo seed or reserved athlete, NFC, or catalog rows remain. "
            "Run confirmed demo cleanup first."
        )


class Migration(migrations.Migration):
    dependencies = [("event_handler", "0016_rack_identity_event")]

    operations = [
        migrations.RunPython(reject_duplicate_reserved_names, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="athlete",
            constraint=models.UniqueConstraint(
                condition=models.Q(name__in=DEMO_NAMES),
                fields=("name",),
                name="athlete_reserved_demo_name_unique",
            ),
        ),
        migrations.CreateModel(
            name="DemoAthleteSeed",
            fields=[
                ("key", models.CharField(max_length=32, primary_key=True, serialize=False)),
                ("athlete_1", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="demo_seed_slot_1", to="event_handler.athlete")),
                ("athlete_2", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="demo_seed_slot_2", to="event_handler.athlete")),
                ("athlete_3", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="demo_seed_slot_3", to="event_handler.athlete")),
                ("athlete_4", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="demo_seed_slot_4", to="event_handler.athlete")),
                ("session", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="demo_athlete_seed", to="event_handler.session")),
                ("workout", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="demo_athlete_seed", to="event_handler.workout")),
                ("workout_program", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="demo_athlete_seed", to="event_handler.workoutprogram")),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(key="wristband-v1"),
                        name="demo_athlete_seed_fixed_key",
                    ),
                    models.CheckConstraint(
                    condition=(
                        ~models.Q(athlete_1=models.F("athlete_2"))
                        & ~models.Q(athlete_1=models.F("athlete_3"))
                        & ~models.Q(athlete_1=models.F("athlete_4"))
                        & ~models.Q(athlete_2=models.F("athlete_3"))
                        & ~models.Q(athlete_2=models.F("athlete_4"))
                        & ~models.Q(athlete_3=models.F("athlete_4"))
                    ),
                    name="demo_athlete_seed_distinct_slots",
                    ),
                ],
            },
        ),
        migrations.RunPython(migrations.RunPython.noop, prevent_owned_demo_reverse),
    ]
