"""Remove expired throttle records, including attempts for nonexistent users."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from event_handler.login_limits import WINDOW_SECONDS
from event_handler.models import LoginAttemptWindow


class Command(BaseCommand):
    help = 'Remove login throttle records whose failures have all expired.'

    def handle(self, *args, **options):
        count, _ = LoginAttemptWindow.objects.filter(
            updated_at__lte=timezone.now() - timedelta(seconds=WINDOW_SECONDS)
        ).delete()
        self.stdout.write(f'Removed {count} expired login throttle records.')
