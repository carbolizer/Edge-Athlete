"""
serializers.py — the "shape-checkers" for data coming in and going out.

Before we trust data a screen sends us (like a finished set), we run it through a
shape-checker here that confirms every field is present and the right type — so we
never save garbage to the database. The same tools also format data going back out
as clean JSON. Think: a bouncer checking every field at the door, plus a
receptionist handing back a tidy summary. One of these per kind of record.
"""
from rest_framework import serializers

from .models import Node, RackScreen, Athlete, Program, Session, Set, Rep, Exercise


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
    read-only — clients don't get to set them."""
    class Meta:
        model = Set
        fields = ["id", "session", "athlete", "node", "exercise", "set_number",
                  "weight_lbs", "started_at", "ended_at", "reps_completed",
                  "avg_velocity", "peak_velocity", "is_false_set"]
        read_only_fields = ["id", "started_at", "ended_at", "reps_completed",
                            "avg_velocity", "peak_velocity", "is_false_set"]


class RackScreenSerializer(serializers.ModelSerializer):
    """A tablet's record — list the ones waiting for a rack, and show the result
    after a coach assigns one. Only rack_number is coach-set."""
    class Meta:
        model = RackScreen
        fields = ["device_id", "rack_number", "last_seen"]
        read_only_fields = ["device_id", "last_seen"]


class ProgramSerializer(serializers.ModelSerializer):
    """An athlete's training plan for one exercise — the targets a set is judged
    against, including the speed zone the tablet uses to color reps."""
    class Meta:
        model = Program
        fields = ["id", "athlete", "exercise", "target_sets", "target_reps",
                  "target_weight_lbs", "velocity_zone_min", "velocity_zone_max"]


class AthleteSerializer(serializers.ModelSerializer):
    """A lifter's record."""
    class Meta:
        model = Athlete
        fields = ["id", "name", "nfc_tag_id", "created_at", "notes"]
        read_only_fields = ["id", "created_at"]


class SessionSerializer(serializers.ModelSerializer):
    """One training session. started_at is set for us; a coach sets ended_at to
    finish it."""
    class Meta:
        model = Session
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
        fields = ["node_id", "rack_number", "mount_type", "firmware_version",
                  "battery_level", "signal_strength", "last_seen", "is_active"]
