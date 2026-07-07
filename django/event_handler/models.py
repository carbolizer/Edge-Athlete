"""
*** IMPORTANT — how to regenerate migrations after editing this file ***
1. docker exec -it edgeathlete-django python manage.py makemigrations event_handler
2. docker exec -it edgeathlete-django python manage.py migrate
3. copy the generated migration file back into ./django/event_handler/migrations/
4. git add + commit the migration file

models.py — the seven Edge Athlete database tables.
------------------------------------------------------
Each class below is one table; each attribute is one column. This file is the
whole data model for the base station: the hardware (Node), the tablet screens
(RackScreen), and the training data (Athlete → Program, and Session → Set → Rep).

Two things worth understanding before you read:
  • A RackScreen (the tablet at a rack) and a Node (the sensor on the bar) are
    SEPARATE identities. They are NOT linked by a foreign key — they only share
    a `rack_number`, and a coach assigns each one to a rack independently.
  • Rep rows are created ONLY by the batch set-complete endpoint, never one at a
    time and never from a live MQTT message.

See https://docs.djangoproject.com/en/5.1/topics/db/models/
"""
from django.db import models


class Node(models.Model):
    """An ESP32 + sensor unit on a rack. Identified by node_id; a coach links it
    to a physical rack via rack_number. Its live fields are updated by pulses."""
    MOUNT_BAR = 'bar'
    MOUNT_WAIST = 'waist'
    MOUNT_WRIST = 'wrist'
    MOUNT_CHOICES = [
        (MOUNT_BAR, 'Bar'),
        (MOUNT_WAIST, 'Waist'),
        (MOUNT_WRIST, 'Wrist'),
    ]

    node_id = models.CharField(max_length=255, unique=True)
    rack_number = models.IntegerField(null=True, blank=True)
    mount_type = models.CharField(max_length=10, choices=MOUNT_CHOICES, default=MOUNT_BAR)
    firmware_version = models.CharField(max_length=50, null=True, blank=True)
    battery_level = models.IntegerField(null=True, blank=True)
    signal_strength = models.IntegerField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        rack = self.rack_number if self.rack_number is not None else "unassigned"
        return f"Node {self.node_id} (rack {rack})"


class RackScreen(models.Model):
    """A tablet PWA standing at a rack. Its device_id is generated in the browser
    on first setup; rack_number is null until a coach assigns it. Separate from
    Node — a screen and its sensor are assigned independently."""
    device_id = models.CharField(max_length=255, unique=True)
    rack_number = models.IntegerField(null=True, blank=True)
    last_seen = models.DateTimeField(auto_now=True)

    def __str__(self):
        rack = self.rack_number if self.rack_number is not None else "awaiting assignment"
        return f"RackScreen {self.device_id} (rack {rack})"


class Athlete(models.Model):
    """A lifter. Optionally carries an NFC tag id for tap-to-identify at a rack."""
    name = models.CharField(max_length=255)
    nfc_tag_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Program(models.Model):
    """A prescribed training block for one athlete — the targets a set is judged
    against (rep/weight goals and the velocity zone that reads as 'on target')."""
    athlete = models.ForeignKey(Athlete, on_delete=models.CASCADE, related_name='programs')
    exercise = models.CharField(max_length=255)
    target_sets = models.IntegerField()
    target_reps = models.IntegerField()
    target_weight_lbs = models.FloatField()
    velocity_zone_min = models.FloatField()
    velocity_zone_max = models.FloatField()

    def __str__(self):
        return f"{self.exercise} for {self.athlete.name}"


class Session(models.Model):
    """One training session in the gym — a window of time containing many sets
    across the athletes who took part."""
    label = models.CharField(max_length=255)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    athletes = models.ManyToManyField(Athlete, related_name='sessions')
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.label


class Set(models.Model):
    """One set an athlete performed. Created when the set starts; its summary
    fields (reps_completed, velocities, is_false_set) are filled in by the batch
    set-complete write when the set ends."""
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='sets')
    athlete = models.ForeignKey(Athlete, on_delete=models.CASCADE, related_name='sets')
    node = models.ForeignKey(Node, on_delete=models.SET_NULL, null=True, blank=True, related_name='sets')
    exercise = models.CharField(max_length=255)
    set_number = models.IntegerField()
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    reps_completed = models.IntegerField(default=0)
    avg_velocity = models.FloatField(null=True, blank=True)
    peak_velocity = models.FloatField(null=True, blank=True)
    is_false_set = models.BooleanField(default=False)

    class Meta:
        ordering = ['set_number']

    def __str__(self):
        return f"Set {self.set_number} — {self.exercise} ({self.athlete.name})"


class Rep(models.Model):
    """One completed rep inside a set. Written only in bulk by the set-complete
    endpoint. velocity_color is the green/yellow/red zone read for the rep."""
    set = models.ForeignKey(Set, on_delete=models.CASCADE, related_name='reps')
    rep_number = models.IntegerField()
    timestamp = models.DateTimeField()
    mean_velocity = models.FloatField()
    peak_velocity = models.FloatField()
    duration_ms = models.IntegerField()
    velocity_color = models.CharField(max_length=16)

    class Meta:
        ordering = ['rep_number']

    def __str__(self):
        return f"Rep {self.rep_number} of set {self.set_id}"
