"""
serializers.py — the "shape-checkers" for data coming in and going out.

Before we trust data a screen sends us (like a finished set), we run it through a
shape-checker here that confirms every field is present and the right type — so we
never save garbage to the database. The same tools also format data going back out
as clean JSON. Think: a bouncer checking every field at the door, plus a
receptionist handing back a tidy summary. One of these per kind of record.
"""
from rest_framework import serializers

from .models import (Set, Rep, RackScreen, Athlete, TrainingSession, Node, Exercise,
                     TrainingGroup, TrainingBlock, TrainingBlockWorkout, TrainingBlockExercise,
                     TrainingProgram, TrainingProgramWorkout, TrainingProgramExercise)


class RepInputSerializer(serializers.Serializer):
    """One incoming rep from the tablet — one item inside a finished set."""
    rep_number = serializers.IntegerField()
    mean_velocity = serializers.FloatField()
    peak_velocity = serializers.FloatField()
    duration_ms = serializers.IntegerField()
    timestamp = serializers.DateTimeField()
    velocity_color = serializers.CharField(max_length=16)


class SetCompleteSerializer(serializers.Serializer):
    """A whole finished set: its totals, plus the list of reps inside it. A false
    set (didn't count) can arrive with an empty reps list."""
    reps_completed = serializers.IntegerField()
    avg_velocity = serializers.FloatField(required=False, allow_null=True)
    peak_velocity = serializers.FloatField(required=False, allow_null=True)
    is_false_set = serializers.BooleanField(default=False)
    reps = RepInputSerializer(many=True, allow_empty=True)


class SetSerializer(serializers.ModelSerializer):
    """The Set record. Used to CHECK the fields when a tablet starts a set, and to
    FORMAT the saved set we send back. System-filled fields (times, totals) are
    read-only — clients don't get to set them.

    `is_coach_adjustment` marks a set a COACH created to move an athlete's working
    load mid-session (merge canon D15), rather than one the athlete lifted. It
    rides this same endpoint on purpose — it is still a set at a weight — but it
    is excluded everywhere work is counted: set totals, session status, analytics,
    and daily reports. Without the flag it would look like the athlete had trained
    a set they never performed, and would advance their set counter."""
    class Meta:
        model = Set
        fields = ["id", "session", "athlete", "node", "exercise", "set_number",
                  "weight_lbs", "is_makeup", "is_coach_adjustment", "started_at",
                  "ended_at", "reps_completed", "avg_velocity", "peak_velocity",
                  "is_false_set"]
        # is_makeup and is_coach_adjustment are intentionally writable at create;
        # everything system-filled (times, totals, false-set) stays read-only.
        read_only_fields = ["id", "started_at", "ended_at", "reps_completed",
                            "avg_velocity", "peak_velocity", "is_false_set"]


class RackScreenSerializer(serializers.ModelSerializer):
    """A tablet's record — list the ones waiting for a rack, and show the result
    after a coach assigns one. Only rack_number is coach-set."""
    class Meta:
        model = RackScreen
        fields = ["device_id", "rack_number", "last_seen"]
        read_only_fields = ["device_id", "last_seen"]




class AthleteSerializer(serializers.ModelSerializer):
    """A lifter's record."""
    class Meta:
        model = Athlete
        fields = ["id", "name", "nfc_tag_id", "created_at", "notes"]
        read_only_fields = ["id", "created_at"]


class TrainingSessionSerializer(serializers.ModelSerializer):
    """One training session. started_at is set for us; a coach sets ended_at to
    finish it."""
    class Meta:
        model = TrainingSession
        fields = ["id", "label", "started_at", "ended_at", "athletes", "notes"]
        read_only_fields = ["id", "started_at"]


class ExerciseSerializer(serializers.ModelSerializer):
    """One movement in the catalog — the official identity plans/sets/maxes link to."""
    class Meta:
        model = Exercise
        fields = ["id", "name", "tags", "is_stub", "created_at"]
        read_only_fields = ["id", "created_at"]


class NodeSerializer(serializers.ModelSerializer):
    """A sensor node and its latest status (battery, signal, which rack it's on)."""
    class Meta:
        model = Node
        # `id` (the integer primary key) is exposed so the rack tablet can send it
        # as the `node` foreign key when it creates a Set — the tablet only knows
        # the sensor by its string node_id otherwise.
        fields = ["id", "node_id", "rack_number", "mount_type", "firmware_version",
                  "battery_level", "signal_strength", "last_seen", "is_active"]


# ─────────────────────────── planning (Training* hierarchy) ───────────────────────────
#
# Read the names carefully, they are not what you'd guess:
#   TrainingGroup   — a TrainingGroup. A NAMED SUBSET of athletes, not everyone.
#   TrainingBlock   — a reusable TEMPLATE. Timeless: no TrainingGroup, no dates.
#   TrainingProgram — that template PLACED IN TIME for one TrainingGroup.
#
# A block is written once and redeployed for years; a program is one deployment
# of it. The block's rows get copied down into the program at that moment, so
# editing the template later changes future deployments but never rewrites what
# a TrainingGroup already trained.

class TrainingGroupSerializer(serializers.ModelSerializer):
    """A TrainingGroup. `athlete_count` rides along because the coach UI lists TrainingGroups by
    size, and it decides plan order when someone is in two TrainingGroups at once."""
    athlete_count = serializers.IntegerField(source="athletes.count", read_only=True)

    class Meta:
        model = TrainingGroup
        fields = ["id", "name", "coach", "athlete_count", "created_at"]
        read_only_fields = ["id", "coach", "created_at"]


class TrainingBlockExerciseSerializer(serializers.ModelSerializer):
    """One prescribed movement in a template.

    `target_percent` is a percentage of each athlete's own max — never a weight.
    That is the whole point: one line serves a whole TrainingGroup, and everyone's number
    follows their own strength."""
    exercise_name = serializers.CharField(source="exercise.name", read_only=True)

    class Meta:
        model = TrainingBlockExercise
        fields = ["id", "exercise", "exercise_name", "position", "sets", "reps",
                  "target_percent", "velocity_zone_min", "velocity_zone_max"]
        read_only_fields = ["id", "exercise_name"]


class TrainingBlockWorkoutSerializer(serializers.ModelSerializer):
    """One day inside a template (e.g. "Day 1 — Lower")."""
    exercises = TrainingBlockExerciseSerializer(many=True, read_only=True)

    class Meta:
        model = TrainingBlockWorkout
        fields = ["id", "name", "position", "exercises"]
        read_only_fields = ["id", "exercises"]


class TrainingBlockSerializer(serializers.ModelSerializer):
    """The reusable template itself.

    `duration_weeks` and `cadence_days_of_week` describe how it is meant to be
    run. Nothing reads them yet — they are here so a future calendar feature can
    lay a block onto dates without a schema change.

    `updated_at` is exposed because the catalog sorts by most-recently-edited
    (`?sort=recent`). The column is maintained server-side whenever a coach
    edits a day or a row inside the block — never by a program built from it."""
    workouts = TrainingBlockWorkoutSerializer(many=True, read_only=True)

    class Meta:
        model = TrainingBlock
        fields = ["id", "name", "coach", "duration_weeks", "cadence_days_of_week",
                  "workouts", "created_at", "updated_at"]
        read_only_fields = ["id", "coach", "workouts", "created_at", "updated_at"]


class TrainingProgramExerciseSerializer(serializers.ModelSerializer):
    """A prescribed movement in a live program — the row the rack ultimately
    resolves a weight from. Editable here without touching the template."""
    exercise_name = serializers.CharField(source="exercise.name", read_only=True)

    class Meta:
        model = TrainingProgramExercise
        fields = ["id", "exercise", "exercise_name", "position", "sets", "reps",
                  "target_percent", "velocity_zone_min", "velocity_zone_max"]
        read_only_fields = ["id", "exercise_name"]


class TrainingProgramWorkoutSerializer(serializers.ModelSerializer):
    exercises = TrainingProgramExerciseSerializer(many=True, read_only=True)

    class Meta:
        model = TrainingProgramWorkout
        fields = ["id", "name", "position", "exercises"]
        read_only_fields = ["id", "exercises"]


class TrainingProgramSerializer(serializers.ModelSerializer):
    """A template deployed for one TrainingGroup, starting on a date.

    `training_block` is deliberately optional. A coach can write a one-off plan
    for a TrainingGroup without ever making a template.

    ⚠️ Turning that one-off INTO a template is not just setting this field —
    that records where a program came from and copies nothing, so it would leave
    a block with no days in it. The real operation copies the program's days and
    prescription rows up into a new block first. Not built yet; see P15."""
    workouts = TrainingProgramWorkoutSerializer(many=True, read_only=True)
    group_name = serializers.CharField(source="training_group.name", read_only=True)

    class Meta:
        model = TrainingProgram
        fields = ["id", "name", "training_group", "group_name", "training_block",
                  "start_date", "end_date", "workouts", "created_at"]
        read_only_fields = ["id", "group_name", "workouts", "created_at"]
