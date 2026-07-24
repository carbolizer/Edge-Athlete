# Data migration: seed the canonical starter exercise catalog (D1, canon §5.4).
#
# WHY THIS IS HAND-WRITTEN: `makemigrations` only detects *schema* changes — it
# never generates seed *data*. So this RunPython migration is authored by hand
# (canon §5.5 says exactly this), not produced by makemigrations.
#
# WHY IT DEPENDS ON 0008 (not 0004): data-wise it only needs the `Exercise` table,
# which has existed since 0004 — so it is *conceptually* independent of 0008. But
# the migration GRAPH must stay a single linear chain: depending on the current
# leaf (0008) keeps exactly one leaf, so Django never demands a `--merge` (which
# the canon bans, §5.5). "Conceptually independent" != "graph-independent."

from django.db import migrations


# Canonical spelling (canon §5.4). This list *is* the seed — editing it is how the
# starter catalog changes. `is_stub=False`: these are confirmed movements, not the
# auto-created placeholders an unrecognized import would leave behind.
STARTER_MOVEMENTS = [
    "Back Squat",
    "Front Squat",
    "Bench Press",
    "Deadlift",
    "Overhead Press",
    "Hang Clean",
    "Power Clean",
    "Push Press",
    "Barbell Row",
    "Romanian Deadlift",
]


def seed_exercises(apps, schema_editor):
    # Use the HISTORICAL model via apps.get_model — never import Exercise directly.
    # A direct import would bind to today's model; if the model later changes, this
    # old migration would replay against the wrong shape. get_model gives the model
    # as it existed at this point in the migration history.
    Exercise = apps.get_model("event_handler", "Exercise")
    Exercise.objects.bulk_create(
        [Exercise(name=name, is_stub=False) for name in STARTER_MOVEMENTS],
        # Re-runnable / safe against a partially-seeded DB: `name` is unique, so
        # skip any that already exist instead of erroring on a duplicate.
        ignore_conflicts=True,
    )


def unseed_exercises(apps, schema_editor):
    # Reverse deletes EXACTLY the rows this migration adds (canon §5.5: reversible).
    Exercise = apps.get_model("event_handler", "Exercise")
    Exercise.objects.filter(name__in=STARTER_MOVEMENTS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("event_handler", "0008_training_hierarchy_and_columns"),
    ]

    operations = [
        migrations.RunPython(seed_exercises, unseed_exercises),
    ]
