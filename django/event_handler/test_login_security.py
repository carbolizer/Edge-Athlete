from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import identify_hasher
from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings, RequestFactory
from django.utils import timezone
from django.views.debug import ExceptionReporter
from rest_framework.test import APIClient, APITestCase

from .credential_privacy import CredentialPrivacyMiddleware
from .models import LoginAttemptWindow
from .test_factories import create_room_coach


class LoginLimitTests(APITestCase):
    def setUp(self):
        self.user = create_room_coach(username='coach', password='Correct-password-42!')

    def login(self, password='wrong', username='coach', **extra):
        return self.client.post('/api/auth/login/',
                                {'username': username, 'password': password}, format='json', **extra)

    def test_five_failures_then_429_even_with_correct_password_and_new_ip(self):
        for i in range(5):
            self.assertEqual(self.login(REMOTE_ADDR=f'192.0.2.{i}').status_code, 401)
        response = self.login('Correct-password-42!', REMOTE_ADDR='192.0.2.99')
        self.assertEqual(response.status_code, 429)
        self.assertTrue(1 <= int(response['Retry-After']) <= 600)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(len(LoginAttemptWindow.objects.get().failures), 5)

    def test_expiry_is_rolling_and_blocked_requests_do_not_extend_it(self):
        start = timezone.now()
        with patch('event_handler.login_limits.timezone.now', return_value=start):
            self.assertEqual(self.login().status_code, 401)
        with patch('event_handler.login_limits.timezone.now', return_value=start + timedelta(seconds=60)):
            for _ in range(4):
                self.assertEqual(self.login().status_code, 401)
        with patch('event_handler.login_limits.timezone.now', return_value=start + timedelta(seconds=599)):
            response = self.login('Correct-password-42!')
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response['Retry-After'], '1')
        with patch('event_handler.login_limits.timezone.now', return_value=start + timedelta(seconds=600)):
            self.assertEqual(self.login('Correct-password-42!').status_code, 200)
            self.assertEqual(len(LoginAttemptWindow.objects.get().failures), 4)

    def test_success_does_not_consume_or_erase_budget(self):
        for _ in range(6):
            self.assertEqual(self.login('Correct-password-42!').status_code, 200)
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login('Correct-password-42!').status_code, 200)
        self.assertEqual(len(LoginAttemptWindow.objects.get().failures), 1)

    def test_unknown_and_inactive_accounts_are_limited_independently(self):
        self.user.is_active = False
        self.user.save()
        for username in ['missing', 'coach']:
            for _ in range(5):
                self.assertEqual(self.login(username=username).status_code, 401)
            self.assertEqual(self.login(username=username).status_code, 429)
        self.assertEqual(self.login(username='someone-else').status_code, 401)

    def test_whitespace_matches_login_identity_and_invalid_payload_is_not_recorded(self):
        for _ in range(5):
            self.assertEqual(self.login(username=' coach ').status_code, 401)
        self.assertEqual(self.login().status_code, 429)
        before = LoginAttemptWindow.objects.count()
        for data in [{}, {'username': []}, {'username': 'a' * 151, 'password': 'x'}]:
            self.assertEqual(self.client.post('/api/auth/login/', data, format='json').status_code, 400)
        self.assertEqual(LoginAttemptWindow.objects.count(), before)
        state = LoginAttemptWindow.objects.get()
        self.assertNotIn('coach', state.account_key)
        self.assertNotIn('wrong', str(state.failures))


class ConcurrentLoginLimitTests(TransactionTestCase):
    def test_simultaneous_first_failures_share_one_budget(self):
        create_room_coach(username='racecoach', password='Correct-password-42!')
        barrier = Barrier(8)

        def attempt(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return APIClient().post('/api/auth/login/',
                    {'username': 'racecoach', 'password': 'wrong'}, format='json').status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(attempt, range(8)))
        self.assertEqual(statuses.count(401), 5, statuses)
        self.assertEqual(statuses.count(429), 3, statuses)
        self.assertEqual(LoginAttemptWindow.objects.count(), 1)
        self.assertEqual(len(LoginAttemptWindow.objects.get().failures), 5)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.PBKDF2PasswordHasher'])
class ProductionPasswordTests(APITestCase):
    def test_create_change_reset_use_salted_hashes_and_reads_never_return_secrets(self):
        admin = create_room_coach(username='admin', password='Admin-password-42!', is_staff=True)
        self.client.force_authenticate(admin)
        password = 'New-coach-password-42!'
        created = self.client.post('/api/coaches/', {'username': 'new', 'password': password})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created['Cache-Control'], 'private, no-store')
        user = get_user_model().objects.get(pk=created.data['id'])
        self.assertEqual(identify_hasher(user.password).algorithm, 'pbkdf2_sha256')
        self.assertTrue(user.check_password(password))
        twin = get_user_model().objects.create_user(username='twin', password=password)
        self.assertNotEqual(user.password, twin.password)
        self.client.force_authenticate(user)
        changed = self.client.post('/api/auth/password/', {
            'current_password': password, 'new_password': 'Changed-coach-password-42!'}, format='json')
        self.assertEqual(changed.status_code, 204)
        user.refresh_from_db()
        self.assertTrue(user.check_password('Changed-coach-password-42!'))
        self.assertFalse(user.check_password(password))
        self.client.force_authenticate(admin)
        reset = self.client.post(f'/api/coaches/{user.pk}/reset/')
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset['Cache-Control'], 'private, no-store')
        user.refresh_from_db()
        self.assertEqual(identify_hasher(user.password).algorithm, 'pbkdf2_sha256')
        self.assertTrue(user.check_password(reset.data['temporary_password']))
        listing = self.client.get('/api/coaches/').content.decode()
        for secret in [password, user.password, reset.data['temporary_password']]:
            self.assertNotIn(secret, listing)
        self.client.force_authenticate(None)
        login = self.client.post('/api/auth/login/', {
            'username': 'new', 'password': reset.data['temporary_password']})
        self.assertEqual(login.status_code, 200)
        self.assertNotIn(reset.data['temporary_password'], login.content.decode())

    @override_settings(DEBUG=False)
    def test_exception_report_redacts_form_and_json_credentials(self):
        import sys
        from django.http import HttpResponse
        for content_type in ['application/json', 'multipart/form-data']:
            if content_type == 'application/json':
                request = RequestFactory().post('/api/auth/login/',
                    {'password': 'Unique-private-secret'}, content_type=content_type)
            else:
                request = RequestFactory().post('/api/coaches/', {'password': 'Unique-private-secret'})
            CredentialPrivacyMiddleware(lambda req: HttpResponse())(request)
            try:
                secret_in_a_local = 'Unique-private-secret'
                raise RuntimeError('Authentication service unavailable')
            except RuntimeError:
                report = ExceptionReporter(request, *sys.exc_info()).get_traceback_text()
            self.assertNotIn(secret_in_a_local, report)


class LoginMaintenanceTests(APITestCase):
    def test_cleanup_preserves_live_budget_and_does_not_print_identifiers(self):
        from io import StringIO
        from django.core.management import call_command
        expired = LoginAttemptWindow.objects.create(account_key='expired', failures=[])
        LoginAttemptWindow.objects.filter(pk=expired.pk).update(
            updated_at=timezone.now() - timedelta(minutes=11))
        LoginAttemptWindow.objects.create(account_key='live', failures=[timezone.now().timestamp()])
        output = StringIO()
        call_command('prune_login_attempts', stdout=output)
        self.assertEqual(list(LoginAttemptWindow.objects.values_list('account_key', flat=True)), ['live'])
        self.assertEqual(output.getvalue(), 'Removed 1 expired login throttle records.\n')

    @override_settings(DEBUG=True)
    def test_demo_command_does_not_print_password(self):
        from io import StringIO
        from django.core.management import call_command
        from .test_factories import ensure_test_room
        ensure_test_room()
        output = StringIO()
        call_command('ensure_demo_coach', stdout=output)
        self.assertNotIn('coachpass', output.getvalue())

    def test_wifi_reauthentication_is_also_private(self):
        from django.http import HttpResponse
        request = RequestFactory().post('/api/system/wifi-password/',
            {'coach_password': 'private-coach-secret'}, content_type='application/json')
        response = CredentialPrivacyMiddleware(lambda req: HttpResponse())(request)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(request.sensitive_post_parameters, '__ALL__')
        self.assertEqual(request.exception_reporter_filter.get_traceback_frame_variables(request, None),
                         [('locals', '[redacted credential request]')])
