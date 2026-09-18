"""Explicit room membership for legacy endpoint fixtures."""
from django.contrib.auth import get_user_model
from .models import CoachProfile, InstallationSetup, School, WeightRoom


def ensure_test_room():
    setup, _ = InstallationSetup.objects.get_or_create(pk=1)
    if not setup.weight_room_id:
        school = School.objects.create(name='Test school')
        setup.weight_room = WeightRoom.objects.create(school=school, name='Test room')
        setup.save(update_fields=['weight_room'])
    return setup.weight_room


def create_room_coach(**kwargs):
    user = get_user_model().objects.create_user(**kwargs)
    CoachProfile.objects.create(user=user, weight_room=ensure_test_room())
    return user
