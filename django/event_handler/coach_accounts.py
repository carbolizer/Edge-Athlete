"""Administrator-only management of coach logins.

The head coach (a staff account) creates individual logins for the rest of the
staff, hands out a temporary password, and can deactivate an account. Everybody
shares ONE database — an account identifies a person, it does not partition the
data. Ordinary coaches may use the whole coach workspace but cannot create
accounts or grant themselves administrator access.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.crypto import get_random_string
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CoachProfile
from .permissions import IsInstallationAdmin


def _username_field():
    return get_user_model()._meta.get_field('username')


def _validate_username(value):
    if get_user_model().objects.filter(username__iexact=value).exists():
        raise serializers.ValidationError('That username is already taken.')
    for validator in _username_field().validators:
        validator(value)
    return value


def generate_temporary_password():
    """A strong random password that satisfies Django's validators."""
    return get_random_string(16, allowed_chars='abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#%^&*')


def _would_remove_last_admin(user, *, is_active=None, is_staff=None):
    """True if this change would leave the installation with no usable admin."""
    currently_admin = user.is_active and user.is_staff
    if not currently_admin:
        return False
    next_active = user.is_active if is_active is None else is_active
    next_staff = user.is_staff if is_staff is None else is_staff
    if next_active and next_staff:
        return False
    others = get_user_model().objects.filter(is_active=True, is_staff=True).exclude(pk=user.pk)
    return not others.exists()


def serialize_coach(user):
    profile = getattr(user, 'coach_profile', None)
    return {
        'id': user.id,
        'username': user.username,
        'is_active': user.is_active,
        'is_staff': user.is_staff,
        'must_change_password': bool(profile and profile.must_change_password),
        'date_joined': user.date_joined,
    }


class CoachCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=False, write_only=True, max_length=1024)

    def validate_username(self, value):
        return _validate_username(value)

    def validate(self, attrs):
        if attrs.get('password'):
            try:
                validate_password(attrs['password'])
            except ValidationError as error:
                raise serializers.ValidationError({'password': error.messages})
        return attrs


class CoachListView(APIView):
    permission_classes = [IsInstallationAdmin]

    def get(self, request):
        users = get_user_model().objects.select_related('coach_profile').order_by('username')
        return Response([serialize_coach(user) for user in users])

    def post(self, request):
        form = CoachCreateSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        username = form.validated_data['username']
        temporary_password = form.validated_data.get('password') or generate_temporary_password()
        try:
            with transaction.atomic():
                user = get_user_model().objects.create_user(username=username, password=temporary_password)
                user.is_staff = False
                user.save(update_fields=['is_staff'])
                CoachProfile.objects.update_or_create(
                    user=user, defaults={'must_change_password': True})
        except IntegrityError:
            return Response({'detail': 'That username is already taken.'}, status=400)
        body = serialize_coach(user)
        # The temporary password is returned exactly once, at creation. It is
        # never stored in plaintext and cannot be read back afterwards.
        body['temporary_password'] = temporary_password
        return Response(body, status=201)


class CoachDetailView(APIView):
    permission_classes = [IsInstallationAdmin]

    def patch(self, request, user_id):
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None:
            return Response({'detail': 'Coach not found.'}, status=404)
        is_active = request.data.get('is_active')
        is_staff = request.data.get('is_staff')
        if is_active is not None and not isinstance(is_active, bool):
            return Response({'detail': 'is_active must be true or false.'}, status=400)
        if is_staff is not None and not isinstance(is_staff, bool):
            return Response({'detail': 'is_staff must be true or false.'}, status=400)
        if user.pk == request.user.pk and (is_active is False or is_staff is False):
            return Response({'detail': 'You cannot deactivate or demote your own account.'}, status=400)
        if _would_remove_last_admin(user, is_active=is_active, is_staff=is_staff):
            return Response({'detail': 'At least one active administrator must remain.'}, status=400)
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=user_id)
            if is_active is not None:
                user.is_active = is_active
            if is_staff is not None:
                user.is_staff = is_staff
            user.save(update_fields=['is_active', 'is_staff'])
        return Response(serialize_coach(user))


class CoachResetPasswordView(APIView):
    permission_classes = [IsInstallationAdmin]

    def post(self, request, user_id):
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None:
            return Response({'detail': 'Coach not found.'}, status=404)
        temporary_password = generate_temporary_password()
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=user_id)
            user.set_password(temporary_password)
            user.save(update_fields=['password'])
            CoachProfile.objects.update_or_create(
                user=user, defaults={'must_change_password': True})
        body = serialize_coach(user)
        body['temporary_password'] = temporary_password
        return Response(body)
