"""
views.py — HTTP endpoints for the event_handler app.

Phase 4 is in progress. These three endpoints unblock the rack tablet's full
flow before the real batch-write logic lands:
  - racks/register and racks/racknumber are REAL, backed by the RackScreen model
    (simple enough to just do properly now).
  - sets/<id>/complete is a STUB: it accepts the MESSAGE_CONTRACT.md body and
    returns a spec-shaped Set, but does NOT create Rep rows yet. The real
    transactional bulk write + PR computation is the Phase 4 centerpiece.

All three are open (AllowAny) per SPEC.md. The project's default DRF permission
is IsAuthenticated, so each one explicitly opts out. See MESSAGE_CONTRACT.md for
the exact request/response shapes.
"""
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import RackScreen


@api_view(["POST"])
@permission_classes([AllowAny])
def rack_register(request):
    """A rack tablet announces itself. Upsert a RackScreen by device_id;
    rack_number stays null until a coach assigns it. Body: { device_id }."""
    device_id = request.data.get("device_id")
    if not device_id:
        return Response({"error": "device_id is required"}, status=400)
    screen, _ = RackScreen.objects.get_or_create(device_id=device_id)
    return Response({"device_id": screen.device_id, "rack_number": screen.rack_number})


@api_view(["GET"])
@permission_classes([AllowAny])
def rack_racknumber(request):
    """Poll target while a tablet waits for assignment. Returns this screen's
    rack_number (null until a coach assigns it). Query: ?device_id=..."""
    device_id = request.query_params.get("device_id")
    if not device_id:
        return Response({"error": "device_id is required"}, status=400)
    screen = RackScreen.objects.filter(device_id=device_id).first()
    return Response({"rack_number": screen.rack_number if screen else None})


@api_view(["POST"])
@permission_classes([AllowAny])
def set_complete(request, set_id):
    """STUB — Phase 4 turns this into the real transactional batch write (the ONLY
    path that creates Rep rows, plus is_velocity_pr / is_weight_pr). For now it
    accepts the contract body and echoes a spec-shaped Set so the tablet's
    finish-a-set flow works end to end. It does NOT persist reps yet."""
    data = request.data
    reps = data.get("reps", [])
    return Response({
        "id": set_id,
        "reps_completed": data.get("reps_completed", len(reps)),
        "avg_velocity": data.get("avg_velocity"),
        "peak_velocity": data.get("peak_velocity"),
        "is_false_set": data.get("is_false_set", False),
        "ended_at": timezone.now().isoformat(),
        "reps_received": len(reps),
        "stub": True,  # remove when the Phase 4 batch write replaces this
    })
