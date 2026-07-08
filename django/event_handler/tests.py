from django.test import TestCase

from event_handler.models import Athlete, Node, Session, Set
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
