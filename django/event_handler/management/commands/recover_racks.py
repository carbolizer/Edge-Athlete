# recover_racks.py — clear wedged rack state at every boot.
#
# A power cycle leaves the previous session's state behind: an open set nobody
# can finish, a controller lease that expired with a screen still attached, a
# rack runtime stuck in recovery_required. The rack screen cannot claim a rack
# in that state, so after every reboot the first thing an athlete meets is
# "check-in did not complete" — until someone SSHes in and clears it by hand.
#
# The base station is meant to be boot-and-go. This command runs on every
# container boot (Dockerfile CMD, after migrate), and does exactly what a
# human would otherwise do with a shell:
#
#   - every open set is ended as a FALSE set (the honest label for work that
#     was abandoned mid-reboot; it never happened),
#   - every rack runtime is reset to idle with no athlete/exercise/set and no
#     controller capability, and its epoch is bumped so stale controller
#     commands from the previous boot are fenced out,
#   - command receipts from the old epoch are dropped.
#
# It is deliberately idempotent and unconditional: on a clean rack it changes
# nothing, and on a wedged one it un-wedges it. Nothing here deletes history —
# ended sets remain in the database, reports still render them (as false sets).
from django.core.management.base import BaseCommand
from django.utils import timezone

from event_handler.models import RackRuntime, Set


class Command(BaseCommand):
    help = "End open sets and reset rack runtimes to idle (boot recovery)."

    def handle(self, *args, **options):
        ended = Set.objects.filter(ended_at=None).update(
            ended_at=timezone.now(),
            is_false_set=True,
            reps_completed=0,
            avg_velocity=None,
            peak_velocity=None,
        )
        self.stdout.write(f"ended {ended} open set(s) left by the previous boot")

        for runtime in RackRuntime.objects.all():
            runtime.controller_screen = None
            runtime.client_instance_id = ""
            runtime.controller_token_digest = ""
            runtime.controller_epoch += 1
            runtime.lease_expires_at = None
            runtime.phase = RackRuntime.PHASE_IDLE
            runtime.selected_athlete = None
            runtime.selected_exercise = None
            runtime.current_set = None
            runtime.rep_count = 0
            runtime.latest_mean_velocity = None
            runtime.latest_peak_velocity = None
            runtime.latest_color = ""
            runtime.phase_started_at = None
            runtime.state_version += 1
            runtime.save()
            runtime.command_receipts.all().delete()
        self.stdout.write(f"reset {RackRuntime.objects.count()} rack runtime(s) to idle")
