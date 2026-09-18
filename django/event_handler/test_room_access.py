from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from .models import CoachProfile, School, WeightRoom, InstallationSetup
from .test_factories import create_room_coach, ensure_test_room

User = get_user_model()


class RoomAccessTests(APITestCase):
    def setUp(self):
        self.room = ensure_test_room()
        self.coach = create_room_coach(username='assigned', password='test-pass')
        self.admin = create_room_coach(username='admin', password='test-pass', is_staff=True)
        self.other_room = WeightRoom.objects.create(name='Other room', school=School.objects.create(name='Other school'))
        self.outsider = User.objects.create_user(username='outsider', password='test-pass')

    def authenticate(self, user):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + str(RefreshToken.for_user(user).access_token))

    def test_session_and_login_return_canonical_room(self):
        login = self.client.post('/api/auth/login/', {'username': 'assigned', 'password': 'test-pass'})
        self.assertEqual(login.status_code, 200)
        room = login.data['weight_room']
        self.assertEqual(room['id'], self.room.pk)
        self.assertEqual(room['school']['id'], self.room.school_id)
        self.assertEqual(room['dashboard_path'], f'/coach/rooms/{self.room.pk}')
        self.authenticate(self.coach)
        session = self.client.get('/api/auth/me/')
        self.assertEqual(session.data['weight_room'], room)
        self.assertEqual(session['Cache-Control'], 'private, no-store')
        self.assertEqual(self.client.get('/api/athletes/').status_code, 200)
        self.assertEqual(self.client.get('/api/room-state/?details=true').status_code, 200)

    def test_unassigned_can_inspect_account_but_cannot_read_or_write_room(self):
        self.authenticate(self.outsider)
        self.assertIsNone(self.client.get('/api/auth/me/').data['weight_room'])
        for path in ['/api/athletes/', '/api/nodes/', '/api/room-state/?details=true', '/api/training-groups/', '/api/coaches/']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.post('/api/athletes/', {'name': 'Forbidden'}).status_code, 403)

    def test_wrong_room_including_staff_has_no_access(self):
        CoachProfile.objects.create(user=self.outsider, weight_room=self.other_room)
        self.outsider.is_staff = True
        self.outsider.save()
        self.authenticate(self.outsider)
        self.assertIsNone(self.client.get('/api/auth/me/').data['weight_room'])
        self.assertEqual(self.client.get('/api/athletes/').status_code, 403)
        self.assertEqual(self.client.get('/api/coaches/').status_code, 403)

    def test_revocation_blocks_existing_token_immediately(self):
        self.authenticate(self.coach)
        self.assertEqual(self.client.get('/api/athletes/').status_code, 200)
        CoachProfile.objects.filter(user=self.coach).update(weight_room=None)
        self.assertEqual(self.client.get('/api/athletes/').status_code, 403)
        self.assertEqual(self.client.get('/api/room-state/?details=true').status_code, 403)
        self.assertIsNone(self.client.get('/api/auth/me/').data['weight_room'])

    def test_forced_authentication_also_checks_membership(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get('/api/athletes/').status_code, 403)
        self.assertNotEqual(self.client.get('/api/room-state/?details=true').status_code, 200)

    def test_admin_assigns_and_revokes_only_local_room(self):
        self.authenticate(self.admin)
        url = f'/api/coaches/{self.outsider.pk}/'
        for room_id in [self.other_room.pk, True, '1', 0, []]:
            with self.subTest(room_id=room_id):
                self.assertEqual(self.client.patch(url, {'weight_room_id': room_id}, format='json').status_code, 400)
        assigned = self.client.patch(url, {'weight_room_id': self.room.pk}, format='json')
        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(assigned.data['weight_room']['id'], self.room.pk)
        revoked = self.client.patch(url, {'weight_room_id': None}, format='json')
        self.assertEqual(revoked.status_code, 200)
        self.assertIsNone(revoked.data['weight_room'])

    def test_coach_cannot_assign_themselves_or_others(self):
        self.authenticate(self.coach)
        self.assertEqual(self.client.patch(f'/api/coaches/{self.outsider.pk}/',
                         {'weight_room_id': self.room.pk}, format='json').status_code, 403)

    def test_admin_cannot_revoke_own_assignment(self):
        self.authenticate(self.admin)
        self.assertEqual(self.client.patch(f'/api/coaches/{self.admin.pk}/',
                         {'weight_room_id': None}, format='json').status_code, 400)

    def test_created_coach_gets_room_and_reset_preserves_assignment(self):
        self.authenticate(self.admin)
        created = self.client.post('/api/coaches/', {'username': 'newcoach'})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data['weight_room']['id'], self.room.pk)
        reset = self.client.post(f"/api/coaches/{created.data['id']}/reset/")
        self.assertEqual(reset.data['weight_room'], created.data['weight_room'])

    def test_missing_installation_fails_closed(self):
        InstallationSetup.objects.filter(pk=1).update(weight_room=None)
        self.authenticate(self.admin)
        self.assertEqual(self.client.get('/api/athletes/').status_code, 403)

    def test_public_wall_remains_public_but_private_details_do_not(self):
        self.assertEqual(self.client.get('/api/room-state/').status_code, 200)
        self.assertEqual(self.client.get('/api/room-state/?details=true').status_code, 401)

    def test_inactive_account_existing_token_is_rejected(self):
        self.authenticate(self.coach)
        self.coach.is_active = False
        self.coach.save()
        self.assertEqual(self.client.get('/api/athletes/').status_code, 401)


class RoomMigrationTests(TransactionTestCase):
    def test_existing_users_are_backfilled_without_resetting_password_state(self):
        old = [('event_handler', '0024_setup_code_and_coach_profiles')]
        new = [('event_handler', '0026_assign_existing_coaches')]
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        apps = executor.loader.project_state(old).apps
        user = apps.get_model('auth', 'User').objects.create(username='legacy', password='unchanged-hash')
        apps.get_model('event_handler', 'CoachProfile').objects.create(user_id=user.pk, must_change_password=True)
        no_profile = apps.get_model('auth', 'User').objects.create(username='no-profile')
        executor = MigrationExecutor(connection)
        executor.migrate(new)
        apps = executor.loader.project_state(new).apps
        room_id = apps.get_model('event_handler', 'InstallationSetup').objects.get(pk=1).weight_room_id
        profiles = apps.get_model('event_handler', 'CoachProfile')
        self.assertEqual(profiles.objects.get(user_id=user.pk).weight_room_id, room_id)
        self.assertTrue(profiles.objects.get(user_id=user.pk).must_change_password)
        self.assertEqual(profiles.objects.get(user_id=no_profile.pk).weight_room_id, room_id)
        self.assertEqual(apps.get_model('auth', 'User').objects.get(pk=user.pk).password, 'unchanged-hash')

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()
