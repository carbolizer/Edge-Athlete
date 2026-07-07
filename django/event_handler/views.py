"""
views.py — the base station's HTTP endpoints (the handlers screens talk to).

Each function below sits at a web address and does one job when a screen calls it:
  - rack_register / rack_racknumber: a tablet says "here I am" and later asks
    "which rack am I?" (open to any tablet).
  - racks_unassigned / rack_assign: coach-only — see which tablets are waiting,
    and give one its rack number.
  - set_create: a tablet says "an athlete is starting a set" -> we make an empty
    set record to fill in later.
  - set_complete: a tablet says "the set is finished, here are all the reps" ->
    we save the whole thing to the database in one all-or-nothing step. This is
    the ONLY place rep records are ever created.

Open vs coach-only follows SPEC.md; shapes live in MESSAGE_CONTRACT.md.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import RackScreen, Set, Rep
from .permissions import IsCoach
from .serializers import SetSerializer, SetCompleteSerializer, RackScreenSerializer


@api_view(["POST"])
@permission_classes([AllowAny])
def rack_register(request):
    """A rack tablet announces itself. Make (or find) its RackScreen row by
    device_id; rack_number stays empty until a coach assigns it. Body: { device_id }."""
    device_id = request.data.get("device_id")
    if not device_id:
        return Response({"error": "device_id is required"}, status=400)
    screen, _ = RackScreen.objects.get_or_create(device_id=device_id)
    return Response({"device_id": screen.device_id, "rack_number": screen.rack_number})


@api_view(["GET"])
@permission_classes([AllowAny])
def rack_racknumber(request):
    """A waiting tablet asks "which rack am I?" Returns its rack_number (empty
    until a coach assigns it). Query: ?device_id=..."""
    device_id = request.query_params.get("device_id")
    if not device_id:
        return Response({"error": "device_id is required"}, status=400)
    screen = RackScreen.objects.filter(device_id=device_id).first()
    return Response({"rack_number": screen.rack_number if screen else None})


@api_view(["GET"])
@permission_classes([IsCoach])
def racks_unassigned(request):
    """Coach-only: list every tablet still waiting for a rack (rack_number empty),
    so a coach can see who needs assigning."""
    waiting = RackScreen.objects.filter(rack_number__isnull=True)
    return Response(RackScreenSerializer(waiting, many=True).data)


@api_view(["PATCH"])
@permission_classes([IsCoach])
def rack_assign(request, device_id):
    """Coach-only: give a waiting tablet its rack number. Body: { rack_number }."""
    screen = RackScreen.objects.filter(device_id=device_id).first()
    if screen is None:
        return Response({"error": "rack screen not found"}, status=404)
    rack_number = request.data.get("rack_number")
    if rack_number is None:
        return Response({"error": "rack_number is required"}, status=400)
    screen.rack_number = rack_number
    screen.save()
    return Response(RackScreenSerializer(screen).data)


@api_view(["POST"])
@permission_classes([AllowAny])
def set_create(request):
    """Start a set: create the empty set record when an athlete begins, so the
    finish endpoint has something to fill in. Body: session, athlete, exercise,
    set_number, and optionally node + weight_lbs."""
    form = SetSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    new_set = form.save()
    return Response(SetSerializer(new_set).data, status=201)


@api_view(["POST"])
@permission_classes([AllowAny])
def set_complete(request, set_id):
    """Save a finished set. Take all its reps + totals and write them to the
    database in ONE all-or-nothing step (if anything fails, nothing saves). This
    is the only code path that creates Rep rows. A false set saves zero reps.
    We also flag whether it was the athlete's best-ever velocity or weight."""
    target_set = Set.objects.filter(id=set_id).first()
    if target_set is None:
        return Response({"error": "set not found"}, status=404)

    form = SetCompleteSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    data = form.validated_data

    # all-or-nothing: either the whole set saves, or none of it does
    with transaction.atomic():
        if data["is_false_set"]:
            # false start — record it as false, save no reps
            target_set.is_false_set = True
            target_set.reps_completed = 0
            target_set.avg_velocity = None
            target_set.peak_velocity = None
            target_set.ended_at = timezone.now()
            target_set.save()
            is_velocity_pr = is_weight_pr = False
        else:
            # save every rep in one batch, all tied to this set
            Rep.objects.bulk_create([
                Rep(set=target_set, **rep) for rep in data["reps"]
            ])
            target_set.reps_completed = data["reps_completed"]
            target_set.avg_velocity = data.get("avg_velocity")
            target_set.peak_velocity = data.get("peak_velocity")
            target_set.is_false_set = False
            target_set.ended_at = timezone.now()
            target_set.save()
            is_velocity_pr, is_weight_pr = _personal_records(target_set)

    # Phase 5: publish rack/dashboard/coach state here (Derrilon hooks the broadcast in)

    body = SetSerializer(target_set).data
    body["is_velocity_pr"] = is_velocity_pr
    body["is_weight_pr"] = is_weight_pr
    return Response(body)


def _personal_records(finished_set):
    """Was this set the athlete's best-ever for this exercise? Compare it to their
    earlier real (non-false) sets of the same exercise. "Best" means fastest peak
    velocity, or heaviest weight. A first-ever set has nothing to beat, so it is
    not flagged as a new record."""
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
