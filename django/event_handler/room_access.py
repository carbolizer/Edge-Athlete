"""The base station/database is one room; membership is checked live, not in JWT claims."""
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import CoachProfile, InstallationSetup


def installation_room():
    setup = InstallationSetup.objects.select_related('weight_room__school').filter(pk=1).first()
    return setup.weight_room if setup else None


def has_room_access(user):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    room = installation_room()
    return bool(room and CoachProfile.objects.filter(user_id=user.pk, weight_room=room).exists())


def room_payload(room):
    if room is None:
        return None
    return {'id': room.pk, 'name': room.name,
            'school': {'id': room.school_id, 'name': room.school.name},
            'dashboard_path': f'/coach/rooms/{room.pk}'}


def coach_room_payload(user):
    room = installation_room()
    return room_payload(room) if room and has_room_access(user) else None


class RoomJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        # These account-only endpoints let an unassigned coach inspect their
        # session and change their password without exposing any room data.
        if result and request.path.rstrip('/') not in {'/api/auth/me', '/api/auth/password'}:
            if not has_room_access(result[0]):
                raise PermissionDenied('Your account is not assigned to this weight room.',
                                       code='room_access_denied')
        return result
