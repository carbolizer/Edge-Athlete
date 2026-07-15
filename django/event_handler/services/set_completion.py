"""Atomically persist a validated set completion from a rack or simulator."""

from django.db import transaction
from django.utils import timezone

from event_handler.models import MonitoringEvent, Rep, Set


class SetNotFound(Exception):
    pass


class SetAlreadyComplete(Exception):
    pass


def complete_set(set_id, data):
    with transaction.atomic():
        target_set = Set.objects.select_for_update().filter(id=set_id).first()
        if target_set is None:
            raise SetNotFound
        if target_set.ended_at is not None or target_set.reps.exists():
            raise SetAlreadyComplete
        if data["is_false_set"]:
            target_set.is_false_set = True
            target_set.reps_completed = 0
            target_set.avg_velocity = None
            target_set.peak_velocity = None
            is_velocity_pr = is_weight_pr = False
        else:
            Rep.objects.bulk_create([Rep(set=target_set, **rep) for rep in data["reps"]])
            target_set.reps_completed = data["reps_completed"]
            target_set.avg_velocity = data.get("avg_velocity")
            target_set.peak_velocity = data.get("peak_velocity")
            target_set.is_false_set = False
            is_velocity_pr, is_weight_pr = _personal_records(target_set)
        target_set.ended_at = timezone.now()
        target_set.save()
        MonitoringEvent.objects.create(reason="set_completed", is_simulated=target_set.is_simulated)
    return target_set, is_velocity_pr, is_weight_pr


def _personal_records(finished_set):
    prior_sets = Set.objects.filter(
        athlete=finished_set.athlete,
        exercise=finished_set.exercise,
        is_false_set=False,
    ).exclude(id=finished_set.id)

    is_velocity_pr = False
    if finished_set.peak_velocity is not None:
        best = prior_sets.exclude(peak_velocity=None).order_by("-peak_velocity").first()
        is_velocity_pr = best is not None and finished_set.peak_velocity > best.peak_velocity

    is_weight_pr = False
    if finished_set.weight_lbs is not None:
        best = prior_sets.exclude(weight_lbs=None).order_by("-weight_lbs").first()
        is_weight_pr = best is not None and finished_set.weight_lbs > best.weight_lbs

    return is_velocity_pr, is_weight_pr
