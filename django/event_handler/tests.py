from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from event_handler.models import Athlete, Node, RackScreen, Session, Set
from event_handler.notification_flow.mqtt_broadcaster import (
    build_leaderboard_update_message,
    rack_number_for_set,
)


class DashboardBroadcastTests(TestCase):
    def setUp(self):
        self.athlete = Athlete.objects.create(name="Jordan Lee")
        self.session = Session.objects.create(label="Test session")
        self.node = Node.objects.create(node_id="rack_1", rack_number=3)
        self.set = Set.objects.create(
            session=self.session,
            athlete=self.athlete,
            node=self.node,
            exercise="Back Squat",
            set_number=1,
            weight_lbs=225,
            reps_completed=5,
            avg_velocity=0.82,
            peak_velocity=0.95,
            is_false_set=False,
        )

    def test_build_leaderboard_update_message(self):
        msg = build_leaderboard_update_message(self.set, True, False)
        self.assertEqual(msg["type"], "leaderboard_update")
        self.assertEqual(msg["athlete"], {"id": self.athlete.id, "name": "Jordan Lee"})
        self.assertEqual(msg["rack_number"], 3)
        self.assertEqual(msg["avg_velocity"], 0.82)
        self.assertEqual(msg["peak_velocity"], 0.95)
        self.assertEqual(msg["reps_completed"], 5)
        self.assertFalse(msg["is_false_set"])
        self.assertTrue(msg["is_velocity_pr"])
        self.assertFalse(msg["is_weight_pr"])

    def test_rack_number_defaults_when_node_unassigned(self):
        self.set.node = None
        self.set.save(update_fields=["node"])
        self.assertEqual(rack_number_for_set(self.set), 0)


class CoachAssignApiTests(TestCase):
    """Room Layout assign path used by /coach: unassigned → PATCH → poll."""

    def setUp(self):
        self.client = APIClient()
        self.coach = User.objects.create_user(username="coach", password="coachpass")
        token = RefreshToken.for_user(self.coach).access_token
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.screen = RackScreen.objects.create(device_id="tablet_demo_abc")
        self.node = Node.objects.create(node_id="node_demo_1", rack_number=None)

    def test_unassigned_requires_coach(self):
        res = self.client.get("/api/racks/unassigned/")
        self.assertIn(res.status_code, (401, 403))

    def test_assign_screen_then_poll_reflects_rack(self):
        waiting = self.client.get("/api/racks/unassigned/", **self.auth)
        self.assertEqual(waiting.status_code, 200)
        device_ids = [row["device_id"] for row in waiting.json()]
        self.assertIn("tablet_demo_abc", device_ids)

        assign = self.client.patch(
            "/api/racks/tablet_demo_abc/",
            {"rack_number": 3},
            format="json",
            **self.auth,
        )
        self.assertEqual(assign.status_code, 200)
        self.assertEqual(assign.json()["rack_number"], 3)

        poll = self.client.get("/api/racks/racknumber/?device_id=tablet_demo_abc")
        self.assertEqual(poll.status_code, 200)
        self.assertEqual(poll.json()["rack_number"], 3)

        waiting_after = self.client.get("/api/racks/unassigned/", **self.auth)
        self.assertNotIn(
            "tablet_demo_abc",
            [row["device_id"] for row in waiting_after.json()],
        )

    def test_assign_node_to_rack_slot(self):
        assign = self.client.patch(
            "/api/nodes/node_demo_1/",
            {"rack_number": 2},
            format="json",
            **self.auth,
        )
        self.assertEqual(assign.status_code, 200)
        self.assertEqual(assign.json()["rack_number"], 2)
        self.node.refresh_from_db()
        self.assertEqual(self.node.rack_number, 2)
