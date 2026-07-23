"""
*** IMPORTANT — how to regenerate migrations after editing this file ***
   (drop the `-it` flags if you run these from a script / non-interactive shell —
    an agent with no TTY errors on `-it`; a human at a terminal can keep them.)
1. docker exec edgeathlete-django python manage.py makemigrations event_handler
2. docker exec edgeathlete-django python manage.py migrate
3. copy the generated migration file back into ./django/event_handler/migrations/
4. git add + commit the migration file

models.py — the Edge Athlete database tables.
------------------------------------------------------
Each class below is one table; each attribute is one column. This file is the
whole data model for the base station: the hardware (Node), the tablet screens
(RackScreen), the athlete training data (Session → Set → Rep), and — new,
mid-merge — the Training* org/planning hierarchy that supersedes the legacy
per-athlete Program table (see that block's comment for what it's for). Program
still exists for now; it retires in the later Session→TrainingSession phase.

Two things worth understanding before you read:
  • A RackScreen (the tablet at a rack) and a Node (the sensor on the bar) are
    SEPARATE identities. They are NOT linked by a foreign key — they only share
    a `rack_number`, and a coach assigns each one to a rack independently.
  • Rep rows are created ONLY by the batch set-complete endpoint, never one at a
    time and never from a live MQTT message.

See https://docs.djangoproject.com/en/5.1/topics/db/models/
"""
import uuid

from django.conf import settings
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
    is_simulated = models.BooleanField(default=False)  # stamped by the simulator so demo data is easy to wipe
    # A hardware fact, not a schedule: what this sensor's rack is physically able to
    # run (e.g. a power rack can't be a high-jump pit). Empty = unrestricted, so this
    # costs nothing for a normal rack. Filtered into athlete_progress, never enforced
    # by rejecting a set — see the merge canon D9 for why.
    allowed_exercises = models.ManyToManyField('Exercise', related_name='allowed_on_nodes', blank=True)

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
    is_simulated = models.BooleanField(default=False)
    # Every group this athlete CURRENTLY trains with. Many-to-many on purpose: a
    # football player can also sit in a speed squad, and each group runs its own
    # program. Which of those programs applies on a given day is answered by the
    # session itself — whichever of their groups is participating in it (see
    # SessionParticipation). Membership is current-state only: adding or removing
    # a group never rewrites history, because past Sessions/Sets stay attached to
    # whatever they were actually created under.
    training_groups = models.ManyToManyField('TrainingGroup', related_name='athletes', blank=True)

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


class TrainingGroup(models.Model):
    """A NAMED SUBSET of athletes who train together on one program — e.g.
    "Varsity Football" or "Freshman Speed".

    ⚠️ This is NOT the list of everyone in the system. Every registered person
    lives in the Athlete table; a TrainingGroup is a slice of them that a coach
    hangs a TrainingProgram on. A gym runs many groups at once, each on its own
    program, and several groups can share one session (see SessionParticipation).

    Membership lives on Athlete.training_groups (M2M), not here — an athlete can
    be in several groups at once. Long-lived: a group
    outlives many blocks/programs. It carries no dates and no workouts itself —
    it's "who trains together," not a schedule."""
    coach = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='training_groups')
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class TrainingBlock(models.Model):
    """A reusable, timeless TEMPLATE a coach designs once and redeploys (tweak
    last year's block, run it again next year). Deliberately has no group and no
    dates — those only exist once a TrainingProgram instantiates it. ⚠️ This name
    is intentionally the OPPOSITE of the old, retired meaning ("Block" used to be
    a dated phase owned by a group) — here it's purely the template.

    Carries a duration/cadence so a future calendar-generator feature can
    auto-place sessions from it later. That generator isn't built yet — this
    just keeps the door open without inventing more structure than needed today."""
    coach = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='training_blocks')
    name = models.CharField(max_length=255)
    duration_weeks = models.IntegerField(null=True, blank=True)
    cadence_days_of_week = models.CharField(max_length=100, blank=True)  # e.g. "Mon,Wed,Fri"
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class TrainingBlockWorkout(models.Model):
    """One ordered workout inside a block's template (e.g. "Day 1: Squat")."""
    training_block = models.ForeignKey(TrainingBlock, on_delete=models.CASCADE, related_name='workouts')
    name = models.CharField(max_length=255)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(fields=['training_block', 'position'], name='block_workout_unique_position'),
        ]

    def __str__(self):
        return f"{self.name} (block {self.training_block_id})"


class TrainingBlockExercise(models.Model):
    """One prescription row inside a block workout — the MASTER copy a program
    snapshot-copies from at instantiation. Always a percent of the athlete's
    reference max plus a velocity zone, never an absolute weight."""
    training_block_workout = models.ForeignKey(TrainingBlockWorkout, on_delete=models.CASCADE,
                                               related_name='exercises')
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name='training_block_exercises')
    position = models.PositiveIntegerField()
    sets = models.PositiveIntegerField()
    reps = models.PositiveIntegerField()
    target_percent = models.FloatField()  # percent of the athlete's reference max, e.g. 80.0 = 80%
    velocity_zone_min = models.FloatField(null=True, blank=True)
    velocity_zone_max = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(fields=['training_block_workout', 'position'],
                                    name='block_exercise_unique_position'),
        ]

    def __str__(self):
        return f"{self.exercise} @ {self.target_percent}% (block workout {self.training_block_workout_id})"


class TrainingProgram(models.Model):
    """A scheduled INSTANCE for a group, placed in time. Usually instantiated
    from a TrainingBlock (its prescription gets snapshot-copied down at creation
    time), but training_block is NULLABLE — a coach can also build a standalone
    one-off program with its own prescription and no template behind it. Both
    are permanent, first-class paths, not a migration shim. Promoting a one-off
    into a reusable template later is just adding a TrainingBlock row and
    pointing this FK at it — no data migration, no rewrite."""
    training_group = models.ForeignKey(TrainingGroup, on_delete=models.CASCADE, related_name='programs')
    training_block = models.ForeignKey(TrainingBlock, on_delete=models.PROTECT, null=True, blank=True,
                                       related_name='programs')
    name = models.CharField(max_length=255)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.training_group.name})"


class TrainingProgramWorkout(models.Model):
    """The editable copy of a TrainingBlockWorkout, living on this program
    instance. Editing this affects only this program; editing the block affects
    future instances instantiated from it later."""
    training_program = models.ForeignKey(TrainingProgram, on_delete=models.CASCADE, related_name='workouts')
    name = models.CharField(max_length=255)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(fields=['training_program', 'position'], name='program_workout_unique_position'),
        ]

    def __str__(self):
        return f"{self.name} (program {self.training_program_id})"


class TrainingProgramExercise(models.Model):
    """The editable copy of a TrainingBlockExercise — the runtime prescription
    row. The absolute target is always DERIVED at read time (target_percent ×
    the athlete's CURRENT AthleteReferenceMax, which itself keeps updating as new
    session data comes in) — never stored here as a fixed number."""
    training_program_workout = models.ForeignKey(TrainingProgramWorkout, on_delete=models.CASCADE,
                                                  related_name='exercises')
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name='training_program_exercises')
    position = models.PositiveIntegerField()
    sets = models.PositiveIntegerField()
    reps = models.PositiveIntegerField()
    target_percent = models.FloatField()
    velocity_zone_min = models.FloatField(null=True, blank=True)
    velocity_zone_max = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(fields=['training_program_workout', 'position'],
                                    name='program_exercise_unique_position'),
        ]

    def __str__(self):
        return f"{self.exercise} @ {self.target_percent}% (program workout {self.training_program_workout_id})"


class AthleteWorkoutExerciseOverride(models.Model):
    """A coach-set per-athlete EXCEPTION for one prescription row — for the rare
    outlier where a percent doesn't fit that specific athlete. Overrides the
    PERCENT, never a static weight — the derivation still multiplies whatever's
    overridden here against the athlete's current reference max, so it stays
    dynamic instead of freezing a number in time. Most athletes need no override
    at all; this is a thin escape hatch, not the common path."""
    athlete = models.ForeignKey(Athlete, on_delete=models.CASCADE, related_name='workout_exercise_overrides')
    training_program_exercise = models.ForeignKey(TrainingProgramExercise, on_delete=models.CASCADE,
                                                   related_name='athlete_overrides')
    target_percent = models.FloatField(null=True, blank=True)
    sets = models.PositiveIntegerField(null=True, blank=True)
    reps = models.PositiveIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['athlete', 'training_program_exercise'],
                                    name='athlete_override_unique_per_exercise'),
            models.CheckConstraint(
                check=(
                    models.Q(target_percent__isnull=False)
                    | models.Q(sets__isnull=False)
                    | models.Q(reps__isnull=False)
                ),
                name='athlete_override_at_least_one_field',
            ),
        ]

    def __str__(self):
        return f"Override for {self.athlete.name} on program exercise {self.training_program_exercise_id}"


class Session(models.Model):
    """One training session in the gym — a window of time containing many sets
    across the athletes who took part.

    NOTE (merge in progress): the canon renames this to TrainingSession and moves
    the group link to a SessionParticipation join row (a session becomes a SHARED
    timeslot many groups can be on). That rename touches every call site across
    views/serializers/tests, so it's deliberately deferred to its own phase — this
    model still reads/writes exactly as it always has for now."""
    label = models.CharField(max_length=255)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    athletes = models.ManyToManyField(Athlete, related_name='sessions')
    notes = models.TextField(blank=True)
    is_simulated = models.BooleanField(default=False)

    def __str__(self):
        return self.label


class SessionParticipation(models.Model):
    """The join between a shared session and one group's program — this is what
    lets many groups be on the same session at once instead of a session
    belonging to just one group.

    Deliberately carries NO snapshot blob: what was actually performed already
    lives in Set/Rep, and what was prescribed gets frozen for the whole session
    by DailyReport at end-of-day. Storing a third copy here would be two write
    paths for one guarantee (see merge canon D14)."""
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='participations')
    training_program = models.ForeignKey(TrainingProgram, on_delete=models.PROTECT,
                                         related_name='session_participations')
    training_program_workout = models.ForeignKey(TrainingProgramWorkout, on_delete=models.PROTECT, null=True,
                                                  blank=True, related_name='session_participations')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['session', 'training_program'], name='session_participation_unique'),
        ]

    def __str__(self):
        return f"{self.training_program} in session {self.session_id}"


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
    # True when a COACH wrote this row to adjust an athlete's carried-forward
    # working weight (the load the tablet defaults the next set to), not to log a
    # real lift. It must be a COMPLETED set (ended_at + weight_lbs) to move that
    # weight — but that same shape would otherwise count as a real set. So every
    # read over Set rows must consciously INCLUDE or EXCLUDE these: they feed
    # last_weight_lbs ONLY, and are excluded from set counts, "resting" status,
    # analytics, has_data/is_makeup, and reports. See merge canon D15 for the
    # exhaustive list — do not add a Set read without deciding this.
    is_coach_adjustment = models.BooleanField(default=False)
    is_makeup = models.BooleanField(default=False)  # True when this set is logged
    # retroactively for an athlete who missed the original run. The tablet sets it
    # from the roster's has_data flag (already has data this session => a makeup).
    is_simulated = models.BooleanField(default=False)

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


class RackCheckIn(models.Model):
    """A record that an athlete signed in ("checked in") at a rack during a session.

    ADD-ONLY, newest-wins — the same shape as AthleteReferenceMax. An athlete's
    CURRENT rack for a session is simply their newest row for that session. Because
    a newer check-in supersedes the older one, an athlete is only ever "owned" by
    one rack at a time: we assume they can't lift at two racks at once, so checking
    in somewhere new just moves them there. This is what a rack's HOT LIST (the
    fast re-pick shortcut on the check-in screen) reads from — the athletes whose
    newest check-in is that rack. Nothing here is meant to outlive the session.
    """
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='checkins')
    athlete = models.ForeignKey(Athlete, on_delete=models.CASCADE, related_name='checkins')
    rack_number = models.IntegerField()
    checked_in_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # newest-first, indexed on the lookup we always do: "this athlete's current
        # rack this session" == first row of this ordering for (session, athlete).
        ordering = ['-checked_in_at']
        indexes = [models.Index(fields=['session', 'athlete', '-checked_in_at'],
                                name='checkin_session_athlete_idx')]

    def __str__(self):
        return f"{self.athlete.name} → rack {self.rack_number} (session {self.session_id})"


class MonitoringEvent(models.Model):
    """A durable record that "something changed" — written the instant it
    happens; a separate publisher loop delivers it to the dashboard afterward and
    marks it published. Adopted from Braydon's realtime/ layer: sturdier than a
    fire-and-forget MQTT publish, because a dropped connection just leaves the
    row unpublished for the next attempt instead of losing the update outright."""
    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    reason = models.CharField(max_length=32)
    occurred_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    publish_attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=255, blank=True)
    is_simulated = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.reason} ({self.event_id})"
