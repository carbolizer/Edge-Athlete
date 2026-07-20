"""
*** IMPORTANT — how to regenerate migrations after editing this file ***
1. docker exec -it edgeathlete-django python manage.py makemigrations event_handler
2. docker exec -it edgeathlete-django python manage.py migrate
3. copy the generated migration file back into ./django/event_handler/migrations/
4. git add + commit the migration file

models.py — the thirteen Edge Athlete database tables.
------------------------------------------------------
Each class below is one table; each attribute is one column. This file is the
whole data model for the base station: the hardware (Node), the tablet screens
(RackScreen), reusable planning catalog (Workout → WorkoutExercise and
WorkoutProgram → WorkoutProgramItem), and training data (Athlete → Program, and
Session → Set → Rep).

Two things worth understanding before you read:
  • A RackScreen (the tablet at a rack) and a Node (the sensor on the bar) are
    SEPARATE identities. They are NOT linked by a foreign key — they only share
    a `rack_number`, and a coach assigns each one to a rack independently.
  • Rep rows are created ONLY by the batch set-complete endpoint, never one at a
    time and never from a live MQTT message.

See https://docs.djangoproject.com/en/5.1/topics/db/models/
"""
import uuid
import math

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import F, Q


POSITIVE_INTEGER_MAX = 2_147_483_647


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
    is_simulated = models.BooleanField(default=False)

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
    velocity_zone_min = models.FloatField(null=True, blank=True)
    velocity_zone_max = models.FloatField(null=True, blank=True)
    is_simulated = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(velocity_zone_min__isnull=True, velocity_zone_max__isnull=True)
                    | Q(
                        velocity_zone_min__isnull=False,
                        velocity_zone_max__isnull=False,
                        velocity_zone_min__gte=0,
                        velocity_zone_min__lte=10,
                        velocity_zone_max__gte=F("velocity_zone_min"),
                        velocity_zone_max__lte=10,
                    )
                ),
                name="program_velocity_zone_valid",
            ),
        ]

    def clean(self):
        super().clean()
        minimum = self.velocity_zone_min
        maximum = self.velocity_zone_max
        if (minimum is None) != (maximum is None):
            raise ValidationError("Velocity zone bounds must both be null or both be set.")
        if minimum is not None and minimum < 0:
            raise ValidationError({"velocity_zone_min": "Velocity zone minimum must be nonnegative."})
        if minimum is not None and (not math.isfinite(minimum) or not math.isfinite(maximum)):
            raise ValidationError("Velocity zone bounds must be finite numbers.")
        if minimum is not None and maximum < minimum:
            raise ValidationError({"velocity_zone_max": "Velocity zone maximum must be at least the minimum."})
        if maximum is not None and maximum > 10:
            raise ValidationError({"velocity_zone_max": "Velocity zone maximum must be at most 10 m/s."})

    def __str__(self):
        return f"{self.exercise} for {self.athlete.name}"


class Workout(models.Model):
    """A reusable, coach-authored collection of ordered exercise targets."""
    name = models.CharField(max_length=255)
    normalized_name = models.TextField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["normalized_name"],
                name="workout_normalized_name_unique",
            ),
            models.CheckConstraint(
                condition=~Q(normalized_name=""),
                name="workout_normalized_name_not_empty",
            ),
        ]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.normalized_name = self.name.casefold()
        if kwargs.get("update_fields") and "name" in kwargs["update_fields"]:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"normalized_name"}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class WorkoutExercise(models.Model):
    """One ordered prescription within a reusable workout."""
    workout = models.ForeignKey(Workout, on_delete=models.CASCADE, related_name="exercises")
    exercise = models.CharField(max_length=255)
    position = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(POSITIVE_INTEGER_MAX)])
    sets = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(POSITIVE_INTEGER_MAX)])
    reps = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(POSITIVE_INTEGER_MAX)])
    default_weight_lbs = models.FloatField(validators=[MinValueValidator(0)])
    velocity_min = models.FloatField(null=True, blank=True)
    velocity_max = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["workout", "position"],
                name="workout_exercise_unique_position",
            ),
            models.CheckConstraint(
                condition=Q(exercise__regex=r"\S"),
                name="workout_exercise_nonempty_exercise",
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1),
                name="workout_exercise_positive_position",
            ),
            models.CheckConstraint(
                condition=Q(sets__gte=1),
                name="workout_exercise_positive_sets",
            ),
            models.CheckConstraint(
                condition=Q(reps__gte=1),
                name="workout_exercise_positive_reps",
            ),
            models.CheckConstraint(
                condition=Q(default_weight_lbs__gte=0, default_weight_lbs__lt=float("inf")),
                name="workout_exercise_finite_nonnegative_weight",
            ),
            models.CheckConstraint(
                condition=(
                    Q(velocity_min__isnull=True, velocity_max__isnull=True)
                    | Q(
                        velocity_min__isnull=False,
                        velocity_max__isnull=False,
                        velocity_min__gte=0,
                        velocity_min__lte=10,
                        velocity_max__gte=F("velocity_min"),
                        velocity_max__lte=10,
                    )
                ),
                name="workout_exercise_velocity_valid",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.exercise.strip():
            raise ValidationError({"exercise": "Exercise is required."})
        if not math.isfinite(self.default_weight_lbs) or self.default_weight_lbs < 0:
            raise ValidationError({"default_weight_lbs": "Weight must be a finite nonnegative number."})
        minimum = self.velocity_min
        maximum = self.velocity_max
        if (minimum is None) != (maximum is None):
            raise ValidationError("Velocity bounds must both be blank or both be set.")
        if minimum is not None and (
            not math.isfinite(minimum)
            or not math.isfinite(maximum)
            or minimum < 0
            or maximum > 10
            or maximum < minimum
        ):
            raise ValidationError("Velocity bounds must be finite, ordered, and between 0 and 10 m/s.")

    def save(self, *args, **kwargs):
        self.exercise = self.exercise.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.position}. {self.exercise} ({self.workout.name})"


class WorkoutProgram(models.Model):
    """A reusable, ordered collection of workout templates."""
    name = models.CharField(max_length=255)
    normalized_name = models.TextField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["normalized_name"],
                name="workout_program_normalized_name_unique",
            ),
            models.CheckConstraint(
                condition=~Q(normalized_name=""),
                name="workout_program_normalized_name_not_empty",
            ),
        ]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.normalized_name = self.name.casefold()
        if kwargs.get("update_fields") and "name" in kwargs["update_fields"]:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"normalized_name"}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class WorkoutProgramItem(models.Model):
    """One workout's position within a reusable workout program."""
    workout_program = models.ForeignKey(
        WorkoutProgram,
        on_delete=models.CASCADE,
        related_name="items",
    )
    workout = models.ForeignKey(
        Workout,
        on_delete=models.PROTECT,
        related_name="workout_program_items",
    )
    position = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(POSITIVE_INTEGER_MAX)],
    )

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["workout_program", "position"],
                name="workout_program_item_unique_position",
            ),
            models.UniqueConstraint(
                fields=["workout_program", "workout"],
                name="workout_program_item_unique_workout",
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1),
                name="workout_program_item_positive_position",
            ),
        ]

    def __str__(self):
        return f"{self.position}. {self.workout.name} ({self.workout_program.name})"


class AthleteWorkoutAssignment(models.Model):
    """An athlete-specific workout choice that takes precedence at any rack."""
    athlete = models.OneToOneField(
        Athlete,
        on_delete=models.CASCADE,
        related_name="workout_assignment",
    )
    assigned_workout = models.ForeignKey(
        Workout,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="athlete_assignments",
    )
    assigned_program_item = models.ForeignKey(
        WorkoutProgramItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="athlete_assignments",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(assigned_workout__isnull=False, assigned_program_item__isnull=True)
                    | Q(assigned_workout__isnull=True, assigned_program_item__isnull=False)
                ),
                name="athlete_workout_assignment_exactly_one",
            ),
        ]

    def __str__(self):
        return f"Workout assignment for {self.athlete.name}"


class AthleteWorkoutProgramAssignment(models.Model):
    """The complete ordered workout program assigned to one athlete."""
    athlete = models.OneToOneField(
        Athlete,
        on_delete=models.CASCADE,
        related_name="workout_program_assignment",
    )
    workout_program = models.ForeignKey(
        WorkoutProgram,
        on_delete=models.PROTECT,
        related_name="athlete_program_assignments",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Program assignment for {self.athlete.name}"


class AthleteWorkoutExerciseOverride(models.Model):
    """Sparse athlete target overrides for one reusable workout exercise."""
    athlete = models.ForeignKey(
        Athlete,
        on_delete=models.CASCADE,
        related_name="workout_exercise_overrides",
    )
    workout_exercise = models.ForeignKey(
        WorkoutExercise,
        on_delete=models.CASCADE,
        related_name="athlete_overrides",
    )
    sets = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(POSITIVE_INTEGER_MAX)],
    )
    reps = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(POSITIVE_INTEGER_MAX)],
    )
    weight_lbs = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["athlete", "workout_exercise"],
                name="athlete_workout_exercise_override_unique",
            ),
            models.CheckConstraint(
                condition=(
                    Q(sets__isnull=False) | Q(reps__isnull=False) | Q(weight_lbs__isnull=False)
                ),
                name="athlete_workout_override_not_empty",
            ),
            models.CheckConstraint(
                condition=Q(sets__isnull=True) | Q(sets__gte=1),
                name="athlete_workout_override_positive_sets",
            ),
            models.CheckConstraint(
                condition=Q(reps__isnull=True) | Q(reps__gte=1),
                name="athlete_workout_override_positive_reps",
            ),
            models.CheckConstraint(
                condition=(
                    Q(weight_lbs__isnull=True)
                    | Q(weight_lbs__gte=0, weight_lbs__lt=float("inf"))
                ),
                name="athlete_workout_override_finite_weight",
            ),
        ]

    def __str__(self):
        return f"Override for {self.athlete.name}: {self.workout_exercise.exercise}"


class Session(models.Model):
    """One training session in the gym — a window of time containing many sets
    across the athletes who took part."""
    label = models.CharField(max_length=255)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    athletes = models.ManyToManyField(Athlete, related_name='sessions')
    notes = models.TextField(blank=True)
    is_simulated = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                models.Value(1),
                condition=Q(ended_at__isnull=True),
                name="session_one_active_training_day",
            ),
        ]

    def __str__(self):
        return self.label


class AthleteDayProgress(models.Model):
    READY = "ready"
    IN_SET = "in_set"
    COMPLETE = "complete"
    STATUS_CHOICES = [
        (READY, "Ready"),
        (IN_SET, "In set"),
        (COMPLETE, "Complete"),
    ]

    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="athlete_progress",
    )
    athlete = models.ForeignKey(
        Athlete,
        on_delete=models.CASCADE,
        related_name="day_progress",
    )
    workout_program = models.ForeignKey(
        WorkoutProgram,
        on_delete=models.PROTECT,
        related_name="athlete_progress",
    )
    current_program_item = models.ForeignKey(
        WorkoutProgramItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_athlete_progress",
    )
    current_workout_exercise = models.ForeignKey(
        WorkoutExercise,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_athlete_progress",
    )
    expected_set_number = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(POSITIVE_INTEGER_MAX)],
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=READY)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "athlete"],
                name="athlete_day_progress_unique_session_athlete",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="complete",
                        current_program_item__isnull=True,
                        current_workout_exercise__isnull=True,
                        expected_set_number__isnull=True,
                    )
                    | Q(
                        status__in=["ready", "in_set"],
                        current_program_item__isnull=False,
                        current_workout_exercise__isnull=False,
                        expected_set_number__gte=1,
                    )
                ),
                name="athlete_day_progress_status_fields",
            ),
        ]

    def __str__(self):
        return f"{self.athlete.name} progress for {self.session.label}"


class DailyReport(models.Model):
    """Immutable end-of-day snapshot for one completed real session."""
    session = models.OneToOneField(
        Session,
        on_delete=models.PROTECT,
        related_name="daily_report",
    )
    schema_version = models.PositiveIntegerField(default=1)
    generated_at = models.DateTimeField(auto_now_add=True)
    snapshot = models.JSONField()

    class Meta:
        ordering = ["-generated_at", "-id"]
        indexes = [
            models.Index(
                fields=["-generated_at", "-id"],
                name="daily_report_newest_idx",
            ),
            GinIndex(
                models.Func(
                    models.F("snapshot"),
                    models.Value("$.athletes[*].athlete.id"),
                    function="jsonb_path_query_array",
                ),
                name="daily_report_athlete_ids_gin",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(schema_version__gte=1),
                name="daily_report_positive_schema_version",
            ),
        ]

    def __str__(self):
        return f"Daily report for {self.session.label}"


class AthleteRackParticipation(models.Model):
    """A durable record that an athlete used a rack during a training day."""
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="athlete_rack_participation",
    )
    athlete = models.ForeignKey(
        Athlete,
        on_delete=models.CASCADE,
        related_name="rack_participation",
    )
    rack_number = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "athlete", "rack_number"],
                name="athlete_rack_participation_unique",
            ),
            models.CheckConstraint(
                condition=Q(rack_number__gt=0),
                name="athlete_rack_participation_positive_rack",
            ),
        ]


class RackWorkoutState(models.Model):
    """The coach-selected program for a physical rack in a specific session."""
    rack_number = models.PositiveIntegerField(
        primary_key=True,
        validators=[MinValueValidator(1)],
    )
    active_session = models.ForeignKey(
        Session,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rack_workout_states",
    )
    active_program = models.ForeignKey(
        Program,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rack_workout_states",
    )
    assigned_workout = models.ForeignKey(
        Workout,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rack_assignments",
    )
    assigned_program_item = models.ForeignKey(
        WorkoutProgramItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rack_assignments",
    )
    selected_athlete = models.ForeignKey(
        Athlete,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="selected_rack_states",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(rack_number__gt=0),
                name="rack_workout_state_positive_rack",
            ),
            models.CheckConstraint(
                condition=(
                    Q(active_program__isnull=True) | Q(assigned_workout__isnull=True)
                ) & (
                    Q(active_program__isnull=True) | Q(assigned_program_item__isnull=True)
                ) & (
                    Q(assigned_workout__isnull=True) | Q(assigned_program_item__isnull=True)
                ),
                name="rack_workout_state_one_assignment",
            ),
            models.CheckConstraint(
                condition=(
                    Q(selected_athlete__isnull=True)
                    | Q(active_session__isnull=False, active_program__isnull=True)
                ),
                name="rack_selected_athlete_requires_active_context",
            ),
            models.UniqueConstraint(
                fields=["selected_athlete"],
                condition=Q(selected_athlete__isnull=False),
                name="rack_selected_athlete_unique",
            ),
        ]

    def __str__(self):
        return f"Rack {self.rack_number} workout state"


class Set(models.Model):
    """One set an athlete performed. Created when the set starts; its summary
    fields (reps_completed, velocities, is_false_set) are filled in by the batch
    set-complete write when the set ends."""
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='sets')
    athlete = models.ForeignKey(Athlete, on_delete=models.CASCADE, related_name='sets')
    node = models.ForeignKey(Node, on_delete=models.SET_NULL, null=True, blank=True, related_name='sets')
    rack_number = models.IntegerField(null=True, blank=True)
    exercise = models.CharField(max_length=255)
    set_number = models.IntegerField()
    weight_lbs = models.FloatField(null=True, blank=True)  # actual load lifted; enables weight PRs + load-velocity analytics
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    reps_completed = models.IntegerField(default=0)
    avg_velocity = models.FloatField(null=True, blank=True)
    peak_velocity = models.FloatField(null=True, blank=True)
    is_false_set = models.BooleanField(default=False)
    is_simulated = models.BooleanField(default=False)
    athlete_day_progress = models.ForeignKey(
        AthleteDayProgress,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sets",
    )
    workout_program_item = models.ForeignKey(
        WorkoutProgramItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sets",
    )
    workout_exercise = models.ForeignKey(
        WorkoutExercise,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="performed_sets",
    )

    class Meta:
        ordering = ['set_number']
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        athlete_day_progress__isnull=True,
                        workout_program_item__isnull=True,
                        workout_exercise__isnull=True,
                    )
                    | Q(
                        athlete_day_progress__isnull=False,
                        workout_program_item__isnull=False,
                        workout_exercise__isnull=False,
                    )
                ),
                name="set_athlete_progress_binding_complete",
            ),
            models.UniqueConstraint(
                fields=["athlete_day_progress"],
                condition=Q(athlete_day_progress__isnull=False, ended_at__isnull=True),
                name="set_one_unfinished_per_athlete_progress",
            ),
        ]

    def save(self, *args, **kwargs):
        if self._state.adding and self.rack_number is None and self.node_id:
            self.rack_number = self.node.rack_number
        super().save(*args, **kwargs)

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


class MonitoringEvent(models.Model):
    """Durable room-change notification published to MQTT after commit."""
    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    reason = models.CharField(max_length=32)
    occurred_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    publish_attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=255, blank=True)
    is_simulated = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"Monitoring revision {self.id}: {self.reason}"
