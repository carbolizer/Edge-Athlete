import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wt901_gui import RepData, WorkoutSession, WorkoutSet, create_gui_app


class WorkoutSessionTests(unittest.TestCase):
    def setUp(self):
        self.session = WorkoutSession()

    def test_start_set_creates_active_set(self):
        s = self.session.start_set(exercise="Back Squat", weight="225 lbs")
        self.assertTrue(self.session.is_set_active)
        self.assertEqual(s.set_number, 1)
        self.assertEqual(s.exercise, "Back Squat")
        self.assertEqual(s.weight, "225 lbs")
        self.assertEqual(s.rep_count, 0)

    def test_add_rep_computes_velocity_metrics_and_loss(self):
        self.session.start_set(exercise="Bench Press", weight="185 lbs")
        # Rep 1: 0.80 m/s
        self.session.add_rep(mean_velocity=0.80, peak_velocity=1.25, duration_ms=1100, peak_excursion_m=0.42)
        # Rep 2: 0.72 m/s
        self.session.add_rep(mean_velocity=0.72, peak_velocity=1.18, duration_ms=1200, peak_excursion_m=0.43)
        # Rep 3: 0.64 m/s
        self.session.add_rep(mean_velocity=0.64, peak_velocity=1.05, duration_ms=1350, peak_excursion_m=0.41)

        active = self.session.active_set
        self.assertEqual(active.rep_count, 3)
        self.assertAlmostEqual(active.avg_mean_velocity, 0.72, places=2)
        self.assertAlmostEqual(active.best_velocity, 0.80, places=2)
        # Velocity loss: (0.80 - 0.64) / 0.80 * 100 = 20.0%
        self.assertEqual(active.velocity_loss_pct, 20.0)

    def test_end_set_archives_and_increments_set_counter(self):
        self.session.start_set(exercise="Deadlift", weight="315 lbs")
        self.session.add_rep(0.60, 0.95, 1500, 0.50)
        self.session.add_rep(0.55, 0.90, 1600, 0.50)

        finished = self.session.end_set()
        self.assertFalse(self.session.is_set_active)
        self.assertEqual(len(self.session.sets), 1)
        self.assertEqual(finished.set_number, 1)
        self.assertEqual(finished.rep_count, 2)

        # Next set should be Set 2
        next_set = self.session.start_set(exercise="Deadlift", weight="315 lbs")
        self.assertEqual(next_set.set_number, 2)

    def test_clear_set_discards_active_without_saving(self):
        self.session.start_set(exercise="Back Squat", weight="135 lbs")
        self.session.add_rep(0.85, 1.30, 1000)
        cleared = self.session.clear_set()
        self.assertTrue(cleared)
        self.assertFalse(self.session.is_set_active)
        self.assertEqual(len(self.session.sets), 0)

    def test_export_csv_and_json(self):
        self.session.start_set(exercise="Back Squat", weight="225 lbs")
        self.session.add_rep(0.75, 1.20, 1250, 0.45)
        self.session.add_rep(0.70, 1.15, 1300, 0.46)
        self.session.end_set()

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "workout.csv"
            json_path = Path(tmpdir) / "workout.json"

            count = self.session.export_csv(csv_path)
            self.assertEqual(count, 2)
            self.assertTrue(csv_path.is_file())

            with open(csv_path, encoding="utf-8") as f:
                reader = list(csv.DictReader(f))
                self.assertEqual(len(reader), 2)
                self.assertEqual(reader[0]["exercise"], "Back Squat")
                self.assertEqual(reader[0]["rep_number"], "1")
                self.assertEqual(reader[0]["mean_velocity_mps"], "0.75")

            self.session.export_json(json_path)
            self.assertTrue(json_path.is_file())
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
                self.assertEqual(data["sets_count"], 1)
                self.assertEqual(len(data["sets"][0]["reps"]), 2)


class GuiWidgetTests(unittest.TestCase):
    def test_gui_initialization_and_button_actions(self):
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
        except Exception as exc:
            self.skipTest(f"Tkinter display not available: {exc}")

        try:
            session = WorkoutSession()
            app = create_gui_app(root=root, session=session)

            # Test Start Set button action
            app.on_start_set()
            self.assertTrue(session.is_set_active)
            self.assertEqual(app.start_btn["state"], tk.DISABLED)
            self.assertEqual(app.end_btn["state"], tk.NORMAL)

            # Test Ingesting Reps
            app._ingest_rep({
                "mean_velocity": 0.72,
                "peak_velocity": 1.15,
                "duration_ms": 1300,
                "peak_excursion_m": 0.45,
            })
            self.assertEqual(session.active_set.rep_count, 1)
            self.assertEqual(app.rep_count_label["text"], "1")
            self.assertIn("0.72", app.mean_vel_val["text"])

            # Test End Set button action
            app.on_end_set()
            self.assertFalse(session.is_set_active)
            self.assertEqual(len(session.sets), 1)
            self.assertEqual(app.start_btn["state"], tk.NORMAL)
            self.assertEqual(app.end_btn["state"], tk.DISABLED)

            # Test Clear Set
            app.on_start_set()
            app.on_clear_set()
            self.assertFalse(session.is_set_active)

            # Test Simulation
            app.on_simulate_rep()
            self.assertTrue(session.is_set_active)
            self.assertEqual(session.active_set.rep_count, 1)

            # Clean close
            app.on_closing()
        finally:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
