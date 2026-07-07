"""
serializers.py — the "shape-checkers" for data coming in and going out.

Before we trust data a screen sends us (like a finished set), we run it through a
shape-checker here that confirms every field is present and the right type — so we
never save garbage to the database. The same tools also format data going back out
as clean JSON. Think: a bouncer checking every field at the door, plus a
receptionist handing back a tidy summary.
"""
from rest_framework import serializers

from .models import Set, Rep, RackScreen


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
    """The Set record itself. Used two ways: to CHECK the fields when a tablet
    starts a set, and to FORMAT the saved set we send back. The system-filled
    fields (times, totals) are read-only — clients don't get to set them."""
    class Meta:
        model = Set
        fields = ["id", "session", "athlete", "node", "exercise", "set_number",
                  "weight_lbs", "started_at", "ended_at", "reps_completed",
                  "avg_velocity", "peak_velocity", "is_false_set"]
        read_only_fields = ["id", "started_at", "ended_at", "reps_completed",
                            "avg_velocity", "peak_velocity", "is_false_set"]


class RackScreenSerializer(serializers.ModelSerializer):
    """A tablet's record — used to list the ones waiting for a rack, and to show
    the result after a coach assigns one. Only rack_number is set by a coach; the
    id and last-seen time are managed for us."""
    class Meta:
        model = RackScreen
        fields = ["device_id", "rack_number", "last_seen"]
        read_only_fields = ["device_id", "last_seen"]
