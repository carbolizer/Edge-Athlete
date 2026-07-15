"""
serializers.py — the "shape-checkers" for data coming in and going out.

Before we trust data a screen sends us (like a finished set), we run it through a
shape-checker here that confirms every field is present and the right type — so we
never save garbage to the database. The same tools also format data going back out
as clean JSON. Think: a bouncer checking every field at the door, plus a
receptionist handing back a tidy summary. One of these per kind of record.
"""
from rest_framework import serializers
import math

from .models import Node, RackScreen, Athlete, Program, Session, Set, Rep


class RepInputSerializer(serializers.Serializer):
    """One incoming rep from the tablet — one item inside a finished set."""
    rep_number = serializers.IntegerField(min_value=1, max_value=100)
    mean_velocity = serializers.FloatField(min_value=0)
    peak_velocity = serializers.FloatField(min_value=0)
    duration_ms = serializers.IntegerField(min_value=0)
    timestamp = serializers.DateTimeField()
    velocity_color = serializers.ChoiceField(choices=["green", "yellow", "red"])


class SetCompleteSerializer(serializers.Serializer):
    """A whole finished set: its totals, plus the list of reps inside it. A false
    set (didn't count) can arrive with an empty reps list."""
    reps_completed = serializers.IntegerField(min_value=0, max_value=100)
    avg_velocity = serializers.FloatField(required=False, allow_null=True, min_value=0)
    peak_velocity = serializers.FloatField(required=False, allow_null=True, min_value=0)
    is_false_set = serializers.BooleanField(default=False)
    reps = RepInputSerializer(many=True, allow_empty=True, max_length=100)

    def validate(self, attrs):
        if attrs["is_false_set"] and attrs["reps"]:
            raise serializers.ValidationError("A false set cannot contain reps.")
        if attrs["is_false_set"] and attrs["reps_completed"] != 0:
            raise serializers.ValidationError("A false set must have zero completed reps.")
        if not attrs["is_false_set"] and attrs["reps_completed"] != len(attrs["reps"]):
            raise serializers.ValidationError("reps_completed must match the number of reps.")
        if attrs["is_false_set"]:
            attrs["avg_velocity"] = None
            attrs["peak_velocity"] = None
        elif attrs["reps"]:
            attrs["avg_velocity"] = sum(rep["mean_velocity"] for rep in attrs["reps"]) / len(attrs["reps"])
            attrs["peak_velocity"] = max(rep["peak_velocity"] for rep in attrs["reps"])
        else:
            attrs["avg_velocity"] = None
            attrs["peak_velocity"] = None
        return attrs


class SetSerializer(serializers.ModelSerializer):
    """The Set record. Used to CHECK the fields when a tablet starts a set, and to
    FORMAT the saved set we send back. System-filled fields (times, totals) are
    read-only — clients don't get to set them."""
    class Meta:
        model = Set
        fields = ["id", "session", "athlete", "node", "rack_number", "exercise", "set_number",
                  "weight_lbs", "started_at", "ended_at", "reps_completed",
                  "avg_velocity", "peak_velocity", "is_false_set"]
        read_only_fields = ["id", "rack_number", "started_at", "ended_at", "reps_completed",
                            "avg_velocity", "peak_velocity", "is_false_set"]

    def validate(self, attrs):
        session = attrs.get("session", getattr(self.instance, "session", None))
        athlete = attrs.get("athlete", getattr(self.instance, "athlete", None))
        node = attrs.get("node", getattr(self.instance, "node", None))
        if session and athlete and session.is_simulated != athlete.is_simulated:
            raise serializers.ValidationError("Session and athlete simulation ownership must match.")
        if session and node and session.is_simulated != node.is_simulated:
            raise serializers.ValidationError("Session and node simulation ownership must match.")
        return attrs

    def create(self, validated_data):
        validated_data["is_simulated"] = validated_data["session"].is_simulated
        return super().create(validated_data)


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

    def validate(self, attrs):
        minimum = attrs.get("velocity_zone_min", getattr(self.instance, "velocity_zone_min", None))
        maximum = attrs.get("velocity_zone_max", getattr(self.instance, "velocity_zone_max", None))
        if (minimum is None) != (maximum is None):
            raise serializers.ValidationError("Velocity zone bounds must both be null or both be set.")
        if minimum is not None and minimum < 0:
            raise serializers.ValidationError({"velocity_zone_min": "Must be nonnegative."})
        if minimum is not None and (not math.isfinite(minimum) or not math.isfinite(maximum)):
            raise serializers.ValidationError("Velocity zone bounds must be finite numbers.")
        if minimum is not None and maximum < minimum:
            raise serializers.ValidationError({"velocity_zone_max": "Must be at least velocity_zone_min."})
        if maximum is not None and maximum > 10:
            raise serializers.ValidationError({"velocity_zone_max": "Must be at most 10 m/s."})
        return attrs


class PublicProgramSerializer(serializers.ModelSerializer):
    """Rack-safe prescription fields without database identifiers."""
    class Meta:
        model = Program
        fields = ["exercise", "target_sets", "target_reps", "target_weight_lbs", "velocity_zone_min", "velocity_zone_max"]


class AthleteSerializer(serializers.ModelSerializer):
    """A lifter's record."""
    class Meta:
        model = Athlete
        fields = ["id", "name", "nfc_tag_id", "created_at", "notes"]
        read_only_fields = ["id", "created_at"]


class PublicAthleteSerializer(serializers.ModelSerializer):
    """Tablet-safe athlete identity without NFC identifiers or coach notes."""
    class Meta:
        model = Athlete
        fields = ["id", "name"]


class SessionSerializer(serializers.ModelSerializer):
    """One training session. started_at is set for us; a coach sets ended_at to
    finish it."""
    class Meta:
        model = Session
        fields = ["id", "label", "started_at", "ended_at", "athletes", "notes"]
        read_only_fields = ["id", "started_at"]


class NodeSerializer(serializers.ModelSerializer):
    """A sensor node and its latest status (battery, signal, which rack it's on)."""
    class Meta:
        model = Node
        fields = ["node_id", "rack_number", "mount_type", "firmware_version",
                  "battery_level", "signal_strength", "last_seen", "is_active"]
