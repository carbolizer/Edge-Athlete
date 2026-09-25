from .test_factories import create_room_coach, ensure_test_room
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from .coach_auth import issue_setup_code
from .models import (Athlete, InstallationSetup, TrainingSession, Set, Exercise,
                     TrainingGroup, Rep, DailyReport, CoachProfile)

User = get_user_model()


def open_installation():
    ensure_test_room()
    InstallationSetup.objects.update_or_create(pk=1, defaults={'completed_at': None})
    return issue_setup_code()[0]


class CoachSetupTests(APITestCase):
    password = 'Unique-coach-2026!safe'

    def setUp(self):
        self.setup_code = open_installation()

    def enroll(self, **overrides):
        data = {'username': 'firstcoach', 'password': self.password}
        data.update(overrides)
        return self.client.post('/api/auth/setup/', data, format='json')

    def test_setup_requires_a_valid_code(self):
        self.assertTrue(self.client.get('/api/auth/setup/').data['setup_required'])
        self.assertTrue(self.client.get('/api/auth/setup/').data['setup_code_pending'])
        self.assertEqual(self.enroll(setup_code='WRONGCOD').status_code, 400)
        self.assertEqual(self.enroll().status_code, 400)  # no code at all
        self.assertFalse(User.objects.exists())
        self.assertTrue(self.client.get('/api/auth/setup/').data['setup_required'])

    def test_expired_code_is_refused_and_reissuing_revokes_the_old_one(self):
        first = self.setup_code
        InstallationSetup.objects.filter(pk=1).update(
            setup_code_expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.enroll(setup_code=first).status_code, 400)
        second = issue_setup_code()[0]
        self.assertEqual(self.enroll(setup_code=first).status_code, 400)
        self.assertEqual(self.enroll(setup_code=second).status_code, 201)

    def test_setup_login_and_protected_roster(self):
        response = self.enroll(setup_code=self.setup_code)
        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(username='firstcoach')
        self.assertTrue(user.is_staff and user.is_superuser)
        self.assertNotEqual(user.password, self.password)
        self.assertTrue(user.check_password(self.password))
        # The code is consumed: setup closes and no code remains stored.
        self.assertFalse(self.client.get('/api/auth/setup/').data['setup_required'])
        self.assertEqual(InstallationSetup.objects.get(pk=1).setup_code_hash, '')
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + response.data['access'])
        self.assertEqual(self.client.get('/api/auth/me/').data['username'], 'firstcoach')
        self.assertEqual(self.client.get('/api/athletes/').status_code, 200)
        self.assertFalse(self.client.get('/api/auth/me/').data['must_change_password'])
        self.client.credentials()
        login = self.client.post('/api/auth/login/', {'username': 'firstcoach', 'password': self.password})
        self.assertEqual(login.status_code, 200)
        self.assertFalse(login.data['must_change_password'])
        self.assertEqual(self.client.post('/api/auth/login/', {'username': 'firstcoach', 'password': 'incorrect'}).status_code, 401)
        user.is_active = False
        user.save()
        self.assertEqual(self.client.post('/api/auth/login/', {'username': 'firstcoach', 'password': self.password}).status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + response.data['access'])
        self.assertEqual(self.client.get('/api/athletes/').status_code, 401)

    def test_weak_password_and_invalid_username_leave_setup_available(self):
        for overrides in [{'password': 'password'}, {'username': 'bad name'}]:
            response = self.enroll(setup_code=self.setup_code, **overrides)
            self.assertEqual(response.status_code, 400, response.data)
            self.assertFalse(User.objects.exists())
            self.assertTrue(self.client.get('/api/auth/setup/').data['setup_required'])

    def test_setup_does_not_reopen_after_account_deletion(self):
        self.assertEqual(self.enroll(setup_code=self.setup_code).status_code, 201)
        User.objects.all().delete()
        self.assertFalse(self.client.get('/api/auth/setup/').data['setup_required'])
        self.assertEqual(self.enroll(setup_code=self.setup_code).status_code, 409)

    def test_existing_installation_is_not_claimable(self):
        create_room_coach(username='existing', password='existing-safe-password')
        self.assertFalse(self.client.get('/api/auth/setup/').data['setup_required'])
        self.assertEqual(self.enroll(setup_code=self.setup_code).status_code, 409)


class ConcurrentSetupTests(TransactionTestCase):
    def test_only_one_initial_admin_can_be_created(self):
        code = open_installation()
        barrier = Barrier(2)

        def enroll(username):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return APIClient().post('/api/auth/setup/', {
                    'username': username, 'password': 'Unique-coach-2026!safe',
                    'setup_code': code,
                }, format='json').status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(enroll, ['coachone', 'coachtwo']))
        self.assertEqual(sorted(statuses), [201, 409])
        self.assertEqual(User.objects.count(), 1)


class CoachManagementTests(APITestCase):
    password = 'Unique-coach-2026!safe'

    def setUp(self):
        self.admin = create_room_coach(username='head', password=self.password, is_staff=True)
        self.coach = create_room_coach(username='assistant', password=self.password)
        CoachProfile.objects.filter(user=self.coach).update(must_change_password=True)

    def as_admin(self):
        self.client.force_authenticate(self.admin)

    def test_management_is_administrator_only(self):
        self.assertEqual(self.client.get('/api/coaches/').status_code, 401)
        self.client.force_authenticate(self.coach)
        self.assertEqual(self.client.get('/api/coaches/').status_code, 403)
        self.assertEqual(self.client.post('/api/coaches/', {'username': 'sneaky'}).status_code, 403)
        self.assertEqual(self.client.patch(f'/api/coaches/{self.admin.pk}/', {'is_active': False}).status_code, 403)
        self.assertEqual(self.client.post(f'/api/coaches/{self.admin.pk}/reset/').status_code, 403)

    def test_admin_creates_a_coach_with_a_temporary_password(self):
        self.as_admin()
        created = self.client.post('/api/coaches/', {'username': 'newcoach'}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertFalse(created.data['is_staff'])
        self.assertTrue(created.data['must_change_password'])
        temp = created.data['temporary_password']
        user = User.objects.get(username='newcoach')
        self.assertTrue(user.check_password(temp))
        # The new coach can sign in, is told to change the password, and cannot
        # reach account management.
        # A fresh client so the admin's forced authentication does not linger.
        self.client.force_authenticate(None)
        login = self.client.post('/api/auth/login/', {'username': 'newcoach', 'password': temp})
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.data['must_change_password'])
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + login.data['access'])
        self.assertEqual(self.client.get('/api/coaches/').status_code, 403)
        self.assertEqual(self.client.get('/api/auth/me/').data['must_change_password'], True)
        self.client.credentials()

    def test_duplicate_and_invalid_usernames_are_refused(self):
        self.as_admin()
        self.assertEqual(self.client.post('/api/coaches/', {'username': 'assistant'}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/coaches/', {'username': 'bad name'}, format='json').status_code, 400)

    def test_deactivate_reactivate_promote_and_self_guard(self):
        self.as_admin()
        url = f'/api/coaches/{self.coach.pk}/'
        self.assertEqual(self.client.patch(url, {'is_active': False}, format='json').status_code, 200)
        self.assertFalse(User.objects.get(pk=self.coach.pk).is_active)
        self.assertEqual(self.client.post('/api/auth/login/', {'username': 'assistant', 'password': self.password}).status_code, 401)
        self.assertEqual(self.client.patch(url, {'is_active': True, 'is_staff': True}, format='json').status_code, 200)
        self.coach.refresh_from_db()
        self.assertTrue(self.coach.is_active and self.coach.is_staff)
        self.assertEqual(self.client.patch(f'/api/coaches/{self.admin.pk}/', {'is_active': False}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(f'/api/coaches/{self.admin.pk}/', {'is_staff': False}, format='json').status_code, 400)

    def test_reset_issues_a_fresh_temporary_password(self):
        self.as_admin()
        response = self.client.post(f'/api/coaches/{self.coach.pk}/reset/')
        self.assertEqual(response.status_code, 200, response.data)
        temp = response.data['temporary_password']
        self.assertTrue(response.data['must_change_password'])
        self.coach.refresh_from_db()
        self.assertFalse(self.coach.check_password(self.password))
        self.assertTrue(self.coach.check_password(temp))

    def test_missing_coach_is_not_found(self):
        self.as_admin()
        self.assertEqual(self.client.patch('/api/coaches/999999/', {'is_active': False}, format='json').status_code, 404)
        self.assertEqual(self.client.post('/api/coaches/999999/reset/').status_code, 404)


class PasswordChangeTests(APITestCase):
    def setUp(self):
        self.user = create_room_coach(username='coach', password='Temp-pass-2026!x')
        CoachProfile.objects.filter(user=self.user).update(must_change_password=True)
        self.client.force_authenticate(self.user)

    def test_change_password_requires_the_current_one(self):
        url = '/api/auth/password/'
        self.assertEqual(self.client.post(url, {'current_password': 'wrong', 'new_password': 'Brand-new-pass-2026!'}, format='json').status_code, 400)
        self.assertEqual(self.client.post(url, {'current_password': 'Temp-pass-2026!x', 'new_password': 'short'}, format='json').status_code, 400)
        self.assertEqual(self.client.post(url, {'current_password': 'Temp-pass-2026!x', 'new_password': 'Temp-pass-2026!x'}, format='json').status_code, 400)

    def test_successful_change_clears_the_forced_flag_and_swaps_the_login(self):
        url = '/api/auth/password/'
        response = self.client.post(url, {'current_password': 'Temp-pass-2026!x', 'new_password': 'Brand-new-pass-2026!'}, format='json')
        self.assertEqual(response.status_code, 204, response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Brand-new-pass-2026!'))
        self.assertFalse(CoachProfile.objects.get(user=self.user).must_change_password)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post('/api/auth/login/', {'username': 'coach', 'password': 'Temp-pass-2026!x'}).status_code, 401)
        login = self.client.post('/api/auth/login/', {'username': 'coach', 'password': 'Brand-new-pass-2026!'})
        self.assertEqual(login.status_code, 200)
        self.assertFalse(login.data['must_change_password'])


class DemoCoachGuardTests(APITestCase):
    """The published coach/coachpass login must never reach a real box by accident."""

    def test_refused_when_debug_is_off(self):
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                call_command('ensure_demo_coach', stdout=StringIO())
        self.assertFalse(User.objects.filter(username='coach').exists())

    def test_explicit_override_creates_it_even_when_debug_is_off(self):
        with override_settings(DEBUG=False):
            call_command('ensure_demo_coach', '--i-know-this-is-a-demo-box', stdout=StringIO())
        user = User.objects.get(username='coach')
        self.assertTrue(user.check_password('coachpass'))

    def test_allowed_on_a_debug_laptop(self):
        with override_settings(DEBUG=True):
            call_command('ensure_demo_coach', stdout=StringIO())
        self.assertTrue(User.objects.get(username='coach').check_password('coachpass'))


class RosterManagementTests(APITestCase):
    def setUp(self):
        self.user = create_room_coach(username='coach', password='Unique-coach-2026!safe')
        self.client.force_authenticate(self.user)

    def test_create_edit_archive_preserves_history_and_releases_tag(self):
        response = self.client.post('/api/athletes/', {'name': 'Jordan', 'nfc_tag_id': 'tag-one'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        athlete = Athlete.objects.get(pk=response.data['id'])
        url = f'/api/athletes/{athlete.pk}/'
        self.assertEqual(self.client.patch(url, {'name': 'Jordan Smith'}, format='json').status_code, 200)
        athlete.refresh_from_db()
        self.assertEqual(athlete.nfc_tag_id, 'tag-one')
        session = TrainingSession.objects.create(label='Past workout', ended_at=timezone.now())
        session.athletes.add(athlete)
        exercise = Exercise.objects.create(name='Test squat')
        workout_set = Set.objects.create(session=session, athlete=athlete, exercise=exercise, set_number=1)
        rep = Rep.objects.create(set=workout_set, rep_number=1, timestamp=timezone.now(), mean_velocity=.6, peak_velocity=.8, duration_ms=500, velocity_color='green')
        report = DailyReport.objects.create(session=session, snapshot={'athletes': [{'athlete': {'id': athlete.pk, 'name': athlete.name}}]})
        snapshot = report.snapshot
        planned = TrainingSession.objects.create(label='Future workout')
        planned.athletes.add(athlete)
        group = TrainingGroup.objects.create(name='Varsity')
        athlete.training_groups.add(group)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.delete(url).status_code, 204)
        athlete.refresh_from_db()
        self.assertFalse(athlete.is_active)
        self.assertIsNone(athlete.nfc_tag_id)
        self.assertFalse(athlete.training_groups.exists())
        self.assertTrue(Set.objects.filter(pk=workout_set.pk, athlete=athlete).exists())
        self.assertTrue(session.athletes.filter(pk=athlete.pk).exists())
        self.assertFalse(planned.athletes.filter(pk=athlete.pk).exists())
        self.assertTrue(Rep.objects.filter(pk=rep.pk).exists())
        report.refresh_from_db()
        self.assertEqual(report.snapshot, snapshot)
        self.assertEqual(self.client.get('/api/athletes/').data, [])
        self.assertEqual(len(self.client.get('/api/athletes/?include_archived=true').data), 1)
        self.assertEqual(self.client.get(url).data['name'], 'Jordan Smith')
        self.assertEqual(self.client.post('/api/athletes/', {'name': 'New lifter', 'nfc_tag_id': 'tag-one'}).status_code, 201)
        self.assertEqual(self.client.post(f'/api/training-groups/{group.pk}/athletes/', {'athletes': [athlete.pk]}, format='json').status_code, 404)

    def test_cannot_archive_active_session_participant(self):
        athlete = Athlete.objects.create(name='Active lifter')
        session = TrainingSession.objects.create(label='Today', started_at=timezone.now())
        session.athletes.add(athlete)
        self.assertEqual(self.client.delete(f'/api/athletes/{athlete.pk}/').status_code, 409)
        athlete.refresh_from_db()
        self.assertTrue(athlete.is_active)

    def test_validation_and_permissions(self):
        athlete = Athlete.objects.create(name='Existing', nfc_tag_id='unique-tag')
        for body in [{'name': ' '}, {'name': 'Duplicate', 'nfc_tag_id': 'unique-tag'}]:
            self.assertEqual(self.client.post('/api/athletes/', body, format='json').status_code, 400)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post('/api/athletes/', {'name': 'No access'}).status_code, 401)
        self.assertEqual(self.client.patch(f'/api/athletes/{athlete.pk}/', {'name': 'No access'}).status_code, 401)
        self.assertEqual(self.client.delete(f'/api/athletes/{athlete.pk}/').status_code, 401)
