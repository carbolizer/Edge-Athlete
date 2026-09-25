"""Coach authentication: local first-run enrollment and password changes.

The base station is self-hosted, so there is no public registration. The FIRST
administrator is claimed with a short code that only someone standing at the
machine can obtain (`manage.py setup_code` prints it to the local terminal).
Every later account is created by an administrator (see coach_accounts.py).
"""
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import CoachProfile, InstallationSetup
from .room_access import coach_room_payload
from .login_limits import authenticate_with_limit

# How long a locally-issued setup code stays valid. Long enough to walk a
# head coach through booting the box, short enough that a code left on a
# whiteboard overnight is not a standing key.
SETUP_CODE_TTL = timedelta(hours=24)

# No 0/O/1/I/L: the code is read off a terminal and typed on a phone or tablet.
SETUP_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def must_change_password(user) -> bool:
    profile = getattr(user, 'coach_profile', None)
    return bool(profile and profile.must_change_password)


def issue_setup_code(ttl=SETUP_CODE_TTL):
    """Create a fresh one-time code, store only its hash, and return the code.

    Returns (code, expires_at). Any previously issued code stops working, so a
    re-run is also a safe way to revoke a code that leaked.
    """
    code = ''.join(secrets.choice(SETUP_CODE_ALPHABET) for _ in range(8))
    now = timezone.now()
    setup, _ = InstallationSetup.objects.get_or_create(pk=1)
    setup.setup_code_hash = make_password(normalize_setup_code(code))
    setup.setup_code_created_at = now
    setup.setup_code_expires_at = now + ttl
    setup.save(update_fields=['setup_code_hash', 'setup_code_created_at', 'setup_code_expires_at'])
    return code, setup.setup_code_expires_at


def normalize_setup_code(raw) -> str:
    """Accept the code however someone types it: case, spaces, and dashes drop."""
    return ''.join(ch for ch in str(raw or '').upper() if ch in SETUP_CODE_ALPHABET)


def setup_code_is_valid(raw):
    """True only for the current, unexpired code. False for expired or absent."""
    setup = InstallationSetup.objects.filter(pk=1).first()
    if setup is None or not setup.setup_code_hash:
        return False
    if setup.setup_code_expires_at is None or setup.setup_code_expires_at <= timezone.now():
        return False
    return check_password(normalize_setup_code(raw), setup.setup_code_hash)


def setup_is_required() -> bool:
    """Enrollment is open only before the marker is set AND before any user exists."""
    if get_user_model().objects.exists():
        return False
    return not InstallationSetup.objects.filter(
        pk=1, completed_at__isnull=False).exists()


class SetupSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(trim_whitespace=False, write_only=True, max_length=1024)
    setup_code = serializers.CharField(trim_whitespace=False, write_only=True, max_length=64)

    def validate(self, attrs):
        if not setup_code_is_valid(attrs['setup_code']):
            raise serializers.ValidationError(
                {'setup_code': 'That setup code is not valid or has expired. '
                               'Run `python manage.py setup_code` on the base station.'})
        user = get_user_model()(username=attrs['username'])
        try:
            user.full_clean(exclude=['password', 'last_login', 'date_joined'])
            validate_password(attrs['password'], user)
        except ValidationError as error:
            raise serializers.ValidationError(error.messages)
        return attrs


class SetupView(APIView):
    """First-run enrollment. Open only while the installation is unclaimed."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        required = setup_is_required()
        setup = InstallationSetup.objects.filter(pk=1).first()
        pending = bool(
            setup
            and setup.setup_code_hash
            and setup.setup_code_expires_at
            and setup.setup_code_expires_at > timezone.now()
        )
        response = Response({
            'setup_required': required,
            'setup_code_pending': required and pending,
        })
        response['Cache-Control'] = 'no-store'
        return response

    def post(self, request):
        try:
            with transaction.atomic():
                # The migration creates the singleton before requests arrive; the
                # row lock serializes enrollment across gunicorn workers.
                setup = InstallationSetup.objects.select_for_update().get(pk=1)
                if setup.completed_at or get_user_model().objects.exists():
                    return Response(
                        {'detail': 'Setup is complete. Sign in with an existing account.'},
                        status=409)
                form = SetupSerializer(data=request.data)
                form.is_valid(raise_exception=True)
                user = get_user_model().objects.create_superuser(
                    username=form.validated_data['username'],
                    password=form.validated_data['password'])
                if setup.weight_room_id is None:
                    raise serializers.ValidationError('Configure the installation weight room before enrollment.')
                CoachProfile.objects.get_or_create(user=user, defaults={'weight_room_id': setup.weight_room_id})
                setup.completed_at = timezone.now()
                setup.setup_code_hash = ''
                setup.setup_code_expires_at = None
                setup.save(update_fields=['completed_at', 'setup_code_hash', 'setup_code_expires_at'])
        except IntegrityError:
            # A racing worker won the unique-username insert.
            return Response({'detail': 'That username was just taken. Try another.'}, status=400)
        refresh = RefreshToken.for_user(user)
        response = Response({'access': str(refresh.access_token), 'refresh': str(refresh)}, status=201)
        response['Cache-Control'] = 'no-store'
        return response


class CoachTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Adds the first-login password-change requirement to the login response."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[self.username_field] = serializers.CharField(max_length=150)
        self.fields['password'] = serializers.CharField(
            write_only=True, trim_whitespace=False, max_length=1024)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['must_change_password'] = must_change_password(user)
        return token

    def validate(self, attrs):
        validate_credentials = super().validate
        data = authenticate_with_limit(
            attrs[self.username_field], lambda: validate_credentials(attrs))
        data['must_change_password'] = must_change_password(self.user)
        data['weight_room'] = coach_room_payload(self.user)
        return data


class CoachTokenObtainPairView(TokenObtainPairView):
    serializer_class = CoachTokenObtainPairSerializer


class CoachSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        response = Response({
            'weight_room': coach_room_payload(request.user),
            'username': request.user.username,
            'is_staff': request.user.is_staff,
            'must_change_password': must_change_password(request.user),
        })

        response['Cache-Control'] = 'private, no-store'
        return response


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False, write_only=True, max_length=1024)
    new_password = serializers.CharField(trim_whitespace=False, write_only=True, max_length=1024)

    def validate(self, attrs):
        user = self.context['user']
        if not user.check_password(attrs['current_password']):
            raise serializers.ValidationError({'current_password': 'That password is incorrect.'})
        if attrs['current_password'] == attrs['new_password']:
            raise serializers.ValidationError({'new_password': 'Choose a different password.'})
        try:
            validate_password(attrs['new_password'], user)
        except ValidationError as error:
            raise serializers.ValidationError({'new_password': error.messages})
        return attrs


class PasswordChangeView(APIView):
    """Let a signed-in coach replace their own password."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        form = PasswordChangeSerializer(data=request.data, context={'user': request.user})
        form.is_valid(raise_exception=True)
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            user.set_password(form.validated_data['new_password'])
            user.save(update_fields=['password'])
            CoachProfile.objects.update_or_create(
                user=user, defaults={'must_change_password': False})
        return Response(status=204)
