"""

If you change backend code:
check top comment in models.py

views.py — Request Handlers and Business Logic
------------------------------------------------
Views are functions that receive an HTTP request and return an HTTP response.
This is where the actual work happens in the event_handler app.

What it does:
  - Receives motion events via POST from ESP32 nodes through MQTT -> Django
  - Saves each event to PostgreSQL
  - Sends a push notification to Ntfy when motion is detected
  - Serves stored event history to the React dashboard via GET

Works with:
  - event_handler/urls.py — routes incoming requests to these functions
  - event_handler/models.py — MotionEvent model for saving to database
  - basestation_config/settings.py — reads NTFY_URL and NTFY_TOPIC
  - ntfy container — receives HTTP POST notifications from here
  - React dashboard — fetches event history from get_events endpoint

URL endpoints defined in event_handler/urls.py:
  POST /api/motion/  -> motion_detected()
  GET  /api/events/  -> get_events()
"""
import json
import requests
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .models import MotionEvent, Device
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.authentication import JWTAuthentication



ONLINE_WINDOW_SECONDS = 120


def parse_sensor_timestamp(value):
    if not value:
        return None
    return parse_datetime(str(value))


def device_last_seen(device):
    if device.last_seen:
        return device.last_seen

    last_event = MotionEvent.objects.filter(device=device).order_by('-detected_at').first()
    return last_event.detected_at if last_event else device.registered_at


def device_to_dict(device):
    last_seen = device_last_seen(device)
    is_online = device.status == Device.STATUS_ACTIVE and device.last_seen is not None and (
        timezone.now() - last_seen
    ).total_seconds() <= ONLINE_WINDOW_SECONDS

    return {
        'node_id': device.node_id,
        'name': device.name,
        'location': device.location,
        'is_active': device.is_active,
        'status': device.status,
        'is_online': is_online,
        'last_seen': last_seen.isoformat(),
        'registered_at': device.registered_at.isoformat(),
        'battery': device.battery,
        'firmware_version': device.firmware_version,
        'signal_strength': device.signal_strength,
        'connection_interrupted': device.connection_interrupted,
    }

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny]) #Public endpoint
@csrf_exempt
def motion_detected(request):
    """
    Receives a motion event POST request from an ESP32 node.
    Extracts nested telemetry, updates the device status, and saves the event history.
    """
    if request.method == 'POST':
        try:
            # Parse the JSON body from the incoming request
            data = json.loads(request.body)
            
            # 1. Extract Top-Level Fields
            event_id = data.get('event_id')
            node_id = data.get('node_id')
            device_name = data.get('device_name', f"Sensor {node_id}")
            location = data.get('location', 'Unknown')
            event_type = data.get('event_type', 'motion')
            motion = data.get('motion', True)
            sensor_timestamp = parse_sensor_timestamp(data.get('timestamp'))
            event_timezone = data.get('timezone', 'UTC')
            
            # 2. Extract Nested Dictionaries safely (defaults to empty dict if missing)
            connection = data.get('connection', {})
            device_status = data.get('device_status', {})
            
            # Extract values from the nested dictionaries
            interrupted = connection.get('interrupted', False)
            signal_strength = connection.get('signal_strength')
            battery = device_status.get('battery')
            firmware = device_status.get('firmware_version')

            # 3. AUTOMATIC REGISTRATION & TELEMETRY UPDATE
            # Uses update_or_create so the Device table always holds the LATEST battery/signal info
            device, created = Device.objects.update_or_create(
                node_id=node_id,
                defaults={
                    'name': device_name,
                    'location': location,
                    'battery': battery,
                    'firmware_version': firmware,
                    'signal_strength': signal_strength,
                    'connection_interrupted': interrupted,
                    'last_seen': timezone.now(),
                    'status': Device.STATUS_ACTIVE,
                    'is_active': True
                }
            )

            # 4. Save the motion event with point-in-time data
            event = MotionEvent.objects.filter(event_id=event_id).first() if event_id else None
            duplicate_event = event is not None
            if event is None:
                event = MotionEvent.objects.create(
                    event_id=event_id,
                    device=device,
                    node_id=node_id,
                    location=location,
                    event_type=event_type,
                    motion=motion,
                    sensor_timestamp=sensor_timestamp,
                    timezone=event_timezone,
                    battery_at_event=battery,
                    signal_strength_at_event=signal_strength
                )

            # 5. Send push notification to Ntfy for new events only
            if not duplicate_event:
                requests.post(
                    f"{settings.NTFY_URL}/{settings.NTFY_TOPIC}",
                    headers={"Title": "Motion Detected"},
                    data=f"Motion detected at {location} (Node: {node_id})",
                    timeout=5
                )

            return JsonResponse({
                'status': 'success', 
                'db_id': event.id,
                'sensor_event_id': event.event_id,
                'device_registered': created,
                'duplicate': duplicate_event
            }, status=200)

        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON payload'}, status=400)
        except Exception as e:
            # Catch database integrity errors (like duplicate event_ids)
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Only POST requests allowed'}, status=405)


@api_view(['GET'])
@authentication_classes([]) #Requires valid JWT token
@permission_classes([AllowAny]) #Blocks unauthenticated responses
def get_events(request):
    """
    Returns the 50 most recent motion events as JSON.
    Supports filtering by node_id via query parameter.
    """
    if request.method == 'GET':
        node_id = request.GET.get('node_id')
        events = MotionEvent.objects.all()

        if node_id:
            events = events.filter(node_id=node_id)

        events = events.order_by('-detected_at')[:50]

        data = [
            {
                'id': e.id,
                'event_id': e.event_id,
                'node_id': e.node_id,
                'location': e.location,
                'event_type': e.event_type,
                'motion': e.motion,
                'detected_at': e.detected_at.isoformat(),
                'device_name': e.device.name if e.device else "Unregistered",
                'signal_strength': e.signal_strength_at_event,
                'battery': e.battery_at_event,
            }
            for e in events
        ]
        return JsonResponse({'events': data}, status=200)

    return JsonResponse({'status': 'error', 'message': 'Only GET requests allowed'}, status=405)

@api_view(['GET', 'POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@csrf_exempt
def get_devices(request):
    """
    Returns a list of all registered sensors and their current status.
    Used for the device status dashboard.
    """
    if request.method == 'GET':
        devices = Device.objects.all().order_by('node_id')
        data = [device_to_dict(d) for d in devices]
        return JsonResponse({'devices': data}, status=200)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            node_id = str(data.get('node_id', '')).strip()
            if not node_id:
                return JsonResponse({'status': 'error', 'message': 'node_id is required'}, status=400)

            device, created = Device.objects.update_or_create(
                node_id=node_id,
                defaults={
                    'name': data.get('name') or node_id,
                    'location': data.get('location') or 'unassigned',
                    'last_seen': None,
                    'status': Device.STATUS_PENDING,
                    'is_active': True,
                }
            )
            return JsonResponse({
                'status': 'success',
                'created': created,
                'device': device_to_dict(device),
            }, status=201 if created else 200)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON payload'}, status=400)

    return JsonResponse({'status': 'error', 'message': 'Only GET and POST requests allowed'}, status=405)

@api_view(['DELETE', 'PATCH'])
@authentication_classes([])
@permission_classes([AllowAny])
@csrf_exempt
def device_detail(request, node_id):
    if request.method == 'DELETE':
        updated = Device.objects.filter(node_id=node_id).update(
            is_active=False,
            status=Device.STATUS_REMOVED,
        )
        if not updated:
            return JsonResponse({'status': 'error', 'message': 'Device not found'}, status=404)
        return JsonResponse({'status': 'success'}, status=200)

    if request.method == 'PATCH':
        try:
            data = json.loads(request.body)
            status = data.get('status')
            allowed_statuses = {
                Device.STATUS_PENDING,
                Device.STATUS_ACTIVE,
                Device.STATUS_DISABLED,
                Device.STATUS_REMOVED,
            }
            if status not in allowed_statuses:
                return JsonResponse({'status': 'error', 'message': 'Invalid device status'}, status=400)

            device = Device.objects.filter(node_id=node_id).first()
            if not device:
                return JsonResponse({'status': 'error', 'message': 'Device not found'}, status=404)

            device.status = status
            device.is_active = status not in {Device.STATUS_DISABLED, Device.STATUS_REMOVED}
            device.save(update_fields=['status', 'is_active'])
            return JsonResponse({'status': 'success', 'device': device_to_dict(device)}, status=200)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON payload'}, status=400)

    return JsonResponse({'status': 'error', 'message': 'Only DELETE and PATCH requests allowed'}, status=405)
