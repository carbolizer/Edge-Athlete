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


class Tag(models.Model):
    """A label for grouping movements (e.g. 'lower', 'push'). Just a name for now;
    a coach hangs these on Exercises so they can be filtered later."""
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Exercise(models.Model):
    """The catalog entry for one movement — the single official identity that every
    training plan, set, and reference max points at, instead of each one
    hand-typing the name. This is what stops "Back Squat" and "back squat" from
    drifting into two different movements. `is_stub` marks a row auto-created from
    an unrecognized import that a coach hasn't confirmed yet (used later, Phase 6)."""
    name = models.CharField(max_length=255, unique=True)
    tags = models.ManyToManyField(Tag, related_name='exercises', blank=True)
    is_stub = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Program(models.Model):
    """A prescribed training block for one athlete — the targets a set is judged
    against (rep/weight goals and the velocity zone that reads as 'on target')."""
    athlete = models.ForeignKey(Athlete, on_delete=models.CASCADE, related_name='programs')
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name='programs')
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
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name='sets')
    set_number = models.IntegerField()
    weight_lbs = models.FloatField(null=True, blank=True)  # actual load lifted; enables weight PRs + load-velocity analytics
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    reps_completed = models.IntegerField(default=0)
    avg_velocity = models.FloatField(null=True, blank=True)
    peak_velocity = models.FloatField(null=True, blank=True)
    is_false_set = models.BooleanField(default=False)
    is_makeup = models.BooleanField(default=False)  # True when this set is logged
    # retroactively for an athlete who missed the original run. The tablet sets it
    # from the roster's has_data flag (already has data this session => a makeup).

    class Meta:
        ordering = ['set_number']

    def __str__(self):
        return f"Set {self.set_number} — {self.exercise} ({self.athlete.name})"


class AthleteReferenceMax(models.Model):
    """An athlete's CURRENT WORKING reference for one movement — the anchor number
    programs multiply against to build target weights. This is deliberately NOT a
    lifetime personal best: it tracks what the athlete can do about NOW, so it can
    go DOWN as well as up (a rough patch should pull prescribed weights back).
    Lifetime bests are a separate concept, already derivable from Set history and
    surfaced via the is_weight_pr / is_velocity_pr flags — do not conflate the two.

    ADD-ONLY history table: every recorded reference writes a NEW row, and an
    athlete's "current reference" for a movement is simply their newest row for it
    (a newer, lower number legitimately supersedes an older, higher one). We never
    edit or delete an old row. Progression over time is graphable for free, and a
    live session reads a stable snapshot (everyone's newest row) while a value
    entered mid-session just becomes that athlete's newest row and applies forward.

    A reference can be a coach-entered number OR one the system estimates from
    velocity data later — both live here, told apart by `source`, so you can graph
    how close the estimate lands to the manual value. `rep_basis` keeps the honest
    original fact (a 3-rep effort is not a 1-rep effort); targets convert to a
    common 1-rep basis when they're computed.

    `source_session` links an estimated row back to the session that produced it,
    so a later coach "publish"/re-publish (a future phase) can trace and supersede
    its own estimates without mutating history. Null for manual entries and for
    estimates not tied to a single session; SET_NULL so the reference survives if
    that session is ever deleted.

    `exercise` links to the Exercise catalog (same as Program and Set) so every
    reference points at one official movement identity, not a loose name string.
    """
    SOURCE_MANUAL = 'manual'
    SOURCE_ESTIMATED = 'estimated'
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, 'Manual'),
        (SOURCE_ESTIMATED, 'Estimated'),
    ]

    athlete = models.ForeignKey(Athlete, on_delete=models.CASCADE, related_name='reference_maxes')
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name='reference_maxes')
    reference_weight_lbs = models.FloatField()
    rep_basis = models.IntegerField(default=1)  # the N in an N-rep effort (1 = true 1RM)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    source_session = models.ForeignKey(Session, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='produced_reference_maxes')
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # newest-first, and indexed on the lookup we always do: "this athlete's
        # current reference for this movement" == first row of this ordering.
        ordering = ['-recorded_at']
        indexes = [models.Index(fields=['athlete', 'exercise', '-recorded_at'],
                                name='aref_athlete_exercise_idx')]

    def __str__(self):
        return f"{self.exercise} ref {self.reference_weight_lbs}lb ({self.athlete.name}, {self.source})"


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
