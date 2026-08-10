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
(RackScreen), the athlete training data (TrainingSession → Set → Rep), and the Training*
planning hierarchy.

That hierarchy, biggest idea to smallest — this is CONCEPTUAL WEIGHT, not
ownership and not the foreign-key direction (see the canon §4):

    TrainingBlock  →  TrainingProgram  →  TrainingGroup  →  TrainingSession
    the template      an instance of      the athletes      the event where
    (timeless)        it, placed in       who train it      lifting is logged
                      time                (many per         (a manifestation
                                          athlete)           of the others)

The legacy per-athlete `Program` table is GONE as of migration 0011. A plan now
belongs to a TrainingGroup and stores a PERCENT; the pounds an athlete sees are
resolved at read time from their own reference max (services/plan_resolution.py).

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
from django.contrib.postgres.indexes import GinIndex
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
    ACQUISITION_MQTT = "mqtt"
    ACQUISITION_WT901_BLE = "wt901_ble"
    ACQUISITION_CHOICES = [
        (ACQUISITION_MQTT, "MQTT"),
        (ACQUISITION_WT901_BLE, "WT901 BLE"),
    ]

    node_id = models.CharField(max_length=255, unique=True)
    rack_number = models.IntegerField(null=True, blank=True)
    assignment_revision = models.PositiveBigIntegerField(default=1)
    mount_type = models.CharField(max_length=10, choices=MOUNT_CHOICES, default=MOUNT_BAR)
    firmware_version = models.CharField(max_length=50, null=True, blank=True)
    acquisition_kind = models.CharField(
        max_length=16, choices=ACQUISITION_CHOICES, default=ACQUISITION_MQTT,
    )
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

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rack_number__isnull=True) | models.Q(node_id__regex=r'^[A-Za-z0-9_-]{1,64}$'),
                name='assigned_node_id_is_mqtt_safe',
            ),
            models.UniqueConstraint(
                fields=['rack_number'],
                condition=models.Q(rack_number__isnull=False),
                name='node_one_per_assigned_rack',
            ),
        ]

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


class RackRuntime(models.Model):
    """The server-owned controller lease and transient presentation state for one rack.
    Completed training history remains in Set and Rep; no raw sensor data lives here."""
    PHASE_IDLE = "idle"
    PHASE_COUNTDOWN = "countdown"
    PHASE_ACTIVE = "active"
    PHASE_SUMMARY = "summary"
    PHASE_REST = "rest"
    PHASE_RECOVERY_REQUIRED = "recovery_required"
    PHASE_CHOICES = [
        (PHASE_IDLE, "Idle"),
        (PHASE_COUNTDOWN, "Countdown"),
        (PHASE_ACTIVE, "Active"),
        (PHASE_SUMMARY, "Summary"),
        (PHASE_REST, "Rest"),
        (PHASE_RECOVERY_REQUIRED, "Recovery required"),
    ]

    rack_number = models.IntegerField(unique=True)
    controller_screen = models.ForeignKey(
        RackScreen, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="controlled_runtimes",
    )
    client_instance_id = models.CharField(max_length=255, blank=True)
    controller_token_digest = models.CharField(max_length=64, blank=True)
    controller_epoch = models.PositiveBigIntegerField(default=0)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    state_version = models.PositiveBigIntegerField(default=0)
    phase = models.CharField(max_length=24, choices=PHASE_CHOICES, default=PHASE_IDLE)
    selected_athlete = models.ForeignKey(
        "Athlete", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="selected_at_runtimes",
    )
    selected_exercise = models.ForeignKey(
        "Exercise", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="selected_at_runtimes",
    )
    current_set = models.ForeignKey(
        "Set", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="runtime_states",
    )
    rep_count = models.PositiveIntegerField(default=0)
    latest_mean_velocity = models.FloatField(null=True, blank=True)
    latest_peak_velocity = models.FloatField(null=True, blank=True)
    latest_color = models.CharField(max_length=16, blank=True)
    phase_started_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Rack {self.rack_number} runtime ({self.phase}, v{self.state_version})"


class HostedGym(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=64, unique=True)
    display_name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)


class EdgeGateway(models.Model):
    QUEUE_UNKNOWN = "unknown"
    QUEUE_HEALTHY = "healthy"
    QUEUE_UNHEALTHY = "unhealthy"
    QUEUE_FULL = "full"
    QUEUE_CORRUPT = "corrupt"
    QUEUE_READ_ONLY = "read_only"
    QUEUE_STATE_CHOICES = [
        (QUEUE_UNKNOWN, "Unknown"),
        (QUEUE_HEALTHY, "Healthy"),
        (QUEUE_UNHEALTHY, "Unhealthy"),
        (QUEUE_FULL, "Full"),
        (QUEUE_CORRUPT, "Corrupt"),
        (QUEUE_READ_ONLY, "Read only"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(HostedGym, on_delete=models.PROTECT, related_name="gateways")
    label = models.CharField(max_length=120)
    revoked_at = models.DateTimeField(null=True, blank=True)
    current_boot = models.ForeignKey(
        "GatewayBoot", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="current_for_gateways",
    )
    last_contact_at = models.DateTimeField(null=True, blank=True)
    last_event_at = models.DateTimeField(null=True, blank=True)
    queue_state = models.CharField(
        max_length=16, choices=QUEUE_STATE_CHOICES, default=QUEUE_UNKNOWN,
    )
    queue_depth = models.PositiveIntegerField(null=True, blank=True)
    oldest_queued_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(queue_depth__isnull=True) | models.Q(queue_depth__lte=50000),
                name="gateway_queue_depth_bounded",
            ),
        ]


class GatewayCredential(models.Model):
    gateway = models.ForeignKey(EdgeGateway, on_delete=models.CASCADE, related_name="credentials")
    version = models.PositiveIntegerField()
    secret_digest = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    not_before = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sponsored_gateway_credentials",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["gateway", "version"], name="gateway_credential_version_unique",
            ),
        ]


class GatewayNodeGrant(models.Model):
    gateway = models.ForeignKey(EdgeGateway, on_delete=models.PROTECT, related_name="node_grants")
    node = models.OneToOneField(Node, on_delete=models.PROTECT, related_name="gateway_grant")
    assignment_revision = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class GatewayBoot(models.Model):
    gateway = models.ForeignKey(EdgeGateway, on_delete=models.CASCADE, related_name="boots")
    boot_id = models.UUIDField()
    server_epoch = models.PositiveBigIntegerField()
    acknowledged_through = models.PositiveBigIntegerField(default=0)
    first_received_at = models.DateTimeField(auto_now_add=True)
    last_received_at = models.DateTimeField(auto_now=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["gateway", "boot_id"], name="gateway_boot_id_unique"),
            models.UniqueConstraint(fields=["gateway", "server_epoch"], name="gateway_boot_epoch_unique"),
        ]


class GatewayEventReceipt(models.Model):
    EVENT_SENSOR_HEALTH = "sensor_health"
    RESULT_ACCEPTED = "accepted"
    RESULT_REJECTED = "rejected"
    RESULT_CHOICES = [
        (RESULT_ACCEPTED, "Accepted"),
        (RESULT_REJECTED, "Rejected"),
    ]

    gateway = models.ForeignKey(EdgeGateway, on_delete=models.CASCADE, related_name="event_receipts")
    boot = models.ForeignKey(GatewayBoot, on_delete=models.CASCADE, related_name="event_receipts")
    event_id = models.UUIDField()
    sequence = models.PositiveBigIntegerField()
    event_type = models.CharField(
        max_length=24, choices=[(EVENT_SENSOR_HEALTH, "Sensor health")],
        default=EVENT_SENSOR_HEALTH,
    )
    result = models.CharField(max_length=16, choices=RESULT_CHOICES)
    result_code = models.CharField(max_length=48)
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["gateway", "event_id"], name="gateway_event_id_unique"),
            models.UniqueConstraint(fields=["boot", "sequence"], name="gateway_boot_sequence_unique"),
        ]


class GatewayNodeHealth(models.Model):
    SENSOR_STARTING = "starting"
    SENSOR_LIVE = "live"
    SENSOR_STALE = "stale"
    SENSOR_RECONNECTING = "reconnecting"
    SENSOR_STATE_CHOICES = [
        (SENSOR_STARTING, "Starting"),
        (SENSOR_LIVE, "Live"),
        (SENSOR_STALE, "Stale"),
        (SENSOR_RECONNECTING, "Reconnecting"),
    ]

    grant = models.OneToOneField(GatewayNodeGrant, on_delete=models.CASCADE, related_name="health")
    sensor_state = models.CharField(max_length=16, choices=SENSOR_STATE_CHOICES)
    sample_age_ms = models.PositiveIntegerField(null=True, blank=True)
    agent_schema_version = models.PositiveSmallIntegerField()
    gateway_occurred_at = models.DateTimeField()
    server_received_at = models.DateTimeField()
    boot = models.ForeignKey(GatewayBoot, on_delete=models.CASCADE, related_name="node_health_rows")
    sequence = models.PositiveBigIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(sample_age_ms__isnull=True) | models.Q(sample_age_ms__lte=600000),
                name="gateway_sample_age_bounded",
            ),
            models.CheckConstraint(
                condition=models.Q(agent_schema_version__gte=1),
                name="gateway_agent_schema_positive",
            ),
        ]


class RackCommandReceipt(models.Model):
    """A durable accepted controller-command result, preventing retry duplication."""
    runtime = models.ForeignKey(RackRuntime, on_delete=models.CASCADE, related_name="command_receipts")
    command_id = models.UUIDField()
    controller_epoch = models.PositiveBigIntegerField()
    controller_device_id = models.CharField(max_length=255)
    client_instance_id = models.CharField(max_length=255)
    controller_token_digest = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField()
    response_body = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["runtime", "created_at"], name="rack_receipt_runtime_time_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["runtime", "command_id"], name="rack_command_once_per_runtime",
            ),
        ]


class Athlete(models.Model):
    """A lifter. Optionally carries an NFC tag id for tap-to-identify at a rack."""
    name = models.CharField(max_length=255)
    nfc_tag_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    is_simulated = models.BooleanField(default=False)
    # Every group this athlete CURRENTLY trains with. Many-to-many on purpose: a
    # football player can also sit in a speed TrainingGroup, and each group runs its own
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


# The per-athlete `Program` table lived here until the group hierarchy replaced
# it. A coach typed one weight per person per movement; now a plan belongs to a
# TrainingGroup, stores a PERCENT, and the pounds are resolved per athlete from
# their own reference max — so one plan serves a whole group and the weights
# follow people as they get stronger. See TrainingBlock / TrainingProgram below.


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
    it's "who trains together," not a schedule.

    ⚠️ The staff who run a group live in TrainingGroupCoach, not in a field here.
    This used to be a single `coach` FK, which could not say what a real weight
    room does every day: "Sarah and Mike both run Varsity"."""
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def head_coach(self):
        """The one coach who answers for the group, or None.

        A convenience for display and for anything that needs a single name.
        It is NOT a permission check and NOT the only coach — read `coaches`
        when the question is "who may run this"."""
        link = self.coach_links.filter(role=TrainingGroupCoach.HEAD).first()
        return link.coach if link else None

    def __str__(self):
        return self.name


class TrainingGroupCoach(models.Model):
    """Which staff run a TrainingGroup, and in what capacity.

    A join table rather than a field on TrainingGroup because a real weight room
    puts several people on one group — a head coach plus assistants — and a
    single FK can only ever name one of them. That FK is what this replaced; its
    value was carried over as the head coach of each group it named.

    ⚠️ Being listed here is currently a STATEMENT, not a permission. Nothing in
    the API asks this table whether a write is allowed — `IsCoach` still means
    "is authenticated", same as before. The canon calls this filter-not-fence,
    and it is deliberate: recording who runs what is useful on its own, and a
    real boundary can be added on top later without undoing any of this. Do not
    read a row here as authorization until something actually enforces it."""
    HEAD = "head"
    ASSISTANT = "assistant"
    ROLE_CHOICES = [(HEAD, "Head coach"), (ASSISTANT, "Assistant coach")]

    training_group = models.ForeignKey(TrainingGroup, on_delete=models.CASCADE,
                                       related_name='coach_links')
    # PROTECT, matching the FK this replaced: deleting a user who still runs a
    # group should fail loudly rather than quietly orphaning the group's staff.
    coach = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name='training_group_links')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ASSISTANT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # One row per person per group. Without this, adding the same coach
            # twice would silently double them in every staff list.
            models.UniqueConstraint(fields=["training_group", "coach"],
                                    name="one_row_per_coach_per_group"),
        ]

    def __str__(self):
        return f"{self.coach} — {self.training_group} ({self.role})"


class BlockCategory(models.Model):
    """A label for finding things in the shared block catalog — "Off-season",
    "Football", "Freshman".

    ⚠️ This is deliberately NOT the existing `Tag` model, even though both are
    "a name you hang on something". `Tag`'s vocabulary is movement labels for
    Exercises ("lower", "push") and its `name` is globally unique, so reusing it
    would put two unrelated vocabularies in one namespace and make a word like
    "Upper" mean a body region or a grade level depending on what it hangs off.
    Two small tables are cheaper than one ambiguous one.

    A block has MANY of these, not one, because real categories sit on different
    axes: a block is honestly both "Off-season" AND "Football", and those are not
    competing answers to the same question. Forcing one would mean inventing
    combination rows ("Off-season Football"), which multiplies badly."""
    name = models.CharField(max_length=60, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "block categories"

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
    # Several, not one — a block sits on more than one axis at a time. See
    # BlockCategory. Filtering is any-of, so a block tagged both "Off-season" and
    # "Football" turns up under either.
    categories = models.ManyToManyField(BlockCategory, related_name='blocks', blank=True)
    duration_weeks = models.IntegerField(null=True, blank=True)
    cadence_days_of_week = models.CharField(max_length=100, blank=True)  # e.g. "Mon,Wed,Fri"
    created_at = models.DateTimeField(auto_now_add=True)
    # "Last edited", so a coach can sort a growing catalog by what they touched
    # recently. ⚠️ auto_now only fires when THIS row is saved, and most edits are
    # to a day or a prescription row inside the block — those are still edits to
    # the template, so every write that touches a descendant must call
    # touch_block() (services/planning.py) or this goes stale and the sort lies.
    updated_at = models.DateTimeField(auto_now=True)

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
    are permanent, first-class paths, not a migration shim.

    ⚠️ This docstring used to claim that promoting a one-off into a reusable
    template was "just adding a TrainingBlock row and pointing this FK at it".
    **That was false**, and it was repeated in several places before anyone
    checked. Setting `training_block` records where a program CAME FROM; it
    copies nothing. Pointing it at a fresh block would produce a block claiming
    to be the source of this program while containing zero days — and deploying
    that block would hand a group an empty plan.

    Promotion is `instantiate_block()` run backwards: create the block, copy
    every day and prescription row UP into it, and only then point the FK. That
    is `promote_program_to_block()` in services/planning.py (P15)."""
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


class ScheduledSession(models.Model):
    """One planned training slot: this program's day N, on this date.

    WHAT THIS IS FOR, plainly: a coach deploys an 8-week block that trains
    Mon/Wed/Fri and wants to see it on a calendar. Before this, nothing turned
    `start_date` + cadence into actual dates — `cadence_days_of_week` and
    `duration_weeks` were written and never read by anything.

    ⚠️ THE SLOT IS A PLAN; THE SESSION IS THE REAL THING. `session` is nullable
    and stays null until a coach actually creates that day. This separation is
    why the change is small: no model is asked to mean two things, and a
    `TrainingSession` still only exists when someone means to run it.

    ⚠️ SLOTS ARE FROZEN ONCE GENERATED. Editing the block's cadence afterwards
    moves no existing slot — the same independence rule as a deployed program.
    Once a program is an instance it is its own thing; a coach who wants the new
    cadence deploys the block again. Moving a single slot is one `date` write and
    regenerates nothing.
    """
    training_program = models.ForeignKey(TrainingProgram, on_delete=models.CASCADE,
                                         related_name='scheduled_sessions')
    # Which day of the program runs in this slot.
    #
    # CASCADE, not PROTECT. PROTECT was the first instinct — "don't let a day the
    # calendar points at disappear" — but it protected nothing and broke
    # something: no route deletes a program day directly, while PROTECT here made
    # the whole PROGRAM undeletable, because deleting it cascades to its days and
    # the slots then blocked their own parent's cleanup. A slot for a day that no
    # longer exists is meaningless, so it should go with it.
    training_program_workout = models.ForeignKey(TrainingProgramWorkout, on_delete=models.CASCADE,
                                                 related_name='scheduled_sessions')
    date = models.DateField()
    # Null until a coach creates the day. SET_NULL rather than CASCADE: deleting a
    # session should leave its slot on the calendar as an unrun plan, not erase
    # the fact that training was scheduled.
    # Quoted because TrainingSession is defined further down this file.
    session = models.ForeignKey('TrainingSession', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='scheduled_slots')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'id']
        constraints = [
            # One slot per program per day. Stops a double-run of the generator
            # from quietly doubling a coach's calendar. ⚠️ It also means moving a
            # slot ONTO an occupied date is refused rather than stacking two
            # days on one date — which is the intended answer, but it makes
            # SWAPPING two slots' dates a two-step operation.
            models.UniqueConstraint(fields=['training_program', 'date'],
                                    name='one_slot_per_program_per_day'),
        ]

    def __str__(self):
        return f"{self.training_program.name} · {self.date}"


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


class TrainingSession(models.Model):
    """One training session in the gym — a window of time containing many sets
    across the athletes who took part.

    A session is SHARED: several TrainingGroups can be on the same one, each via
    its own SessionParticipation row pointing at that group's program and the day
    they are running. The session itself belongs to nobody.

    ⚠️ `started_at` IS NULLABLE, and that is the whole of P14's schema change:
    **a session can exist before it runs.** Null means "created, not started yet"
    — Thursday's session, set up on Tuesday. It is set when a coach actually
    starts the day.

    Because of that, "the active session" means STARTED and not ended, never
    merely existing — see services/active_session.py. A future session that could
    capture check-ins is exactly the D18 failure, and nullable `started_at` is
    what makes it structurally impossible rather than merely guarded against.

    ⚠️ Never order sessions by `-started_at` without excluding nulls: Postgres
    sorts NULLs FIRST descending, so an unstarted future session would come back
    as the newest thing in the room."""
    label = models.CharField(max_length=255)
    # Not auto_now_add — see above. Creating a session no longer starts it.
    started_at = models.DateTimeField(null=True, blank=True)
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
    session = models.ForeignKey(TrainingSession, on_delete=models.CASCADE, related_name='participations')
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
    # PROTECT, not CASCADE. A Set is the only permanent record that an athlete
    # actually did something — deleting the session it happened in used to take
    # every set and rep inside it with no warning and no way back. Now the delete
    # is refused while any lifting exists, which turns a silent, unrecoverable
    # loss into an error message. Ending a day is `ended_at`, not a delete; a
    # session with real work in it is not supposed to be removable.
    session = models.ForeignKey(TrainingSession, on_delete=models.PROTECT, related_name='sets')
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
    source_session = models.ForeignKey(TrainingSession, on_delete=models.SET_NULL, null=True, blank=True,
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
    session = models.ForeignKey(TrainingSession, on_delete=models.CASCADE, related_name='checkins')
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


class DailyReport(models.Model):
    """The permanent record of one finished training day — written once, never
    edited.

    WHY THIS IS STORED RATHER THAN DERIVED (the one deliberate exception to this
    codebase's derive-don't-store rule): a report has to keep saying what was
    true on the day it was generated. If we recomputed it on demand, a coach
    editing next week's program — or an athlete's max drifting — would silently
    rewrite last month's history. Immutability IS the feature here, so the whole
    day gets frozen into `snapshot` at the moment the session ends.

    `snapshot` holds the entire report as JSON (roster, each athlete's sets and
    reps, which racks they used, room totals) so reading a report never depends
    on the live tables it came from. `schema_version` lets an older stored
    snapshot still be read correctly after the shape evolves.
    """
    session = models.OneToOneField(TrainingSession, on_delete=models.PROTECT, related_name='daily_report')
    schema_version = models.PositiveIntegerField(default=1)
    generated_at = models.DateTimeField(auto_now_add=True)
    snapshot = models.JSONField()

    class Meta:
        ordering = ['-generated_at', '-id']
        indexes = [
            models.Index(fields=['-generated_at', '-id'], name='daily_report_newest_idx'),
            # "Which reports mention this athlete?" is the main way reports get
            # browsed, and the answer lives inside the JSON rather than in a
            # column. This indexes just the athlete ids out of the snapshot so
            # that lookup stays fast instead of re-reading every report.
            # POSTGRES-ONLY (jsonb) — fine here, the base station always runs
            # Postgres. The query works without it, just slower.
            GinIndex(
                models.Func(
                    models.F('snapshot'),
                    models.Value('$.athletes[*].athlete.id'),
                    function='jsonb_path_query_array',
                ),
                name='daily_report_athlete_ids_gin',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(schema_version__gte=1),
                name='daily_report_positive_schema_version',
            ),
        ]

    def __str__(self):
        return f"Daily report for {self.session.label}"


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
