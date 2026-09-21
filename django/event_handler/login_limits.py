"""A rolling failed-login budget serialized across PostgreSQL workers."""
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from rest_framework.exceptions import AuthenticationFailed, Throttled

from .models import LoginAttemptWindow

FAILURE_LIMIT = 5
WINDOW_SECONDS = 10 * 60


def authenticate_with_limit(username, authenticate):
    # Match Django's case-sensitive username identity. Serializer whitespace
    # trimming happens before this function, just as it does for authentication.
    key = salted_hmac('coach-login-budget', username, algorithm='sha256').hexdigest()
    error = None
    with transaction.atomic():
        state, _ = LoginAttemptWindow.objects.select_for_update().get_or_create(account_key=key)
        now = timezone.now().timestamp()
        failures = [stamp for stamp in state.failures if stamp > now - WINDOW_SECONDS]
        if len(failures) >= FAILURE_LIMIT:
            raise Throttled(wait=failures[0] + WINDOW_SECONDS - now,
                            detail='Too many failed login attempts. Try again later.')
        try:
            result = authenticate()
        except AuthenticationFailed as exc:
            error = exc
            failures.append(timezone.now().timestamp())
        state.failures = failures
        state.save(update_fields=['failures', 'updated_at'])
    # Raise AFTER committing, otherwise the failed-attempt record rolls back.
    if error is not None:
        raise error
    return result
