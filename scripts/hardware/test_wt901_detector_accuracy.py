"""Deterministic robustness checks, not a measured real-world accuracy claim."""
import math
import unittest

from wt901_rack_agent import ImuSample, MovementEstimator, ProvisionalRepDetector


def sample(a=0.0, direction=(1.0, 0.0, 0.0)):
    return ImuSample(tuple(a * d + (1.0 if i == 2 else 0.0)
                           for i, d in enumerate(direction)), (0.0,) * 3, (0.0,) * 3)


class DetectorAccuracyTests(unittest.TestCase):
    def run_cycle(self, hz=50, direction=(1.0, 0.0, 0.0), pickup=False,
                  pause=0.16, accel_s=0.2):
        detector = ProvisionalRepDetector(sample_interval_seconds=1 / hz)
        phases = [(0, 1), (.2, accel_s), (-.2, accel_s), (0, pause)]
        if not pickup:
            phases += [(-.2, accel_s), (.2, accel_s)]
        phases += [(0, .6)]
        reps = []
        for a, seconds in phases:
            for _ in range(round(hz * seconds)):
                rep = detector.update(0.0, sample(a, direction))
                if rep:
                    reps.append(rep)
        return detector, reps

    def test_same_cycle_counts_once_across_sample_rates(self):
        durations = []
        for hz in (25, 50, 100, 200):
            with self.subTest(hz=hz):
                _, reps = self.run_cycle(hz)
                self.assertEqual(len(reps), 1)
                durations.append(reps[0]['duration_ms'])
                _, pickup = self.run_cycle(hz, pickup=True)
                self.assertEqual(pickup, [])
        self.assertLessEqual(max(durations) - min(durations), 80)

    def test_diagonal_translation_has_same_count_and_velocity(self):
        _, aligned_reps = self.run_cycle()
        aligned = aligned_reps[0]
        _, diagonal_reps = self.run_cycle(direction=(1 / math.sqrt(3),) * 3)
        self.assertEqual(len(diagonal_reps), 1)
        self.assertAlmostEqual(aligned['peak_velocity'], diagonal_reps[0]['peak_velocity'], delta=.005)

    def test_pause_at_turnaround_still_counts_one_rep(self):
        _, reps = self.run_cycle(pause=1.2)
        self.assertEqual(len(reps), 1)
        self.assertGreaterEqual(reps[0]['duration_ms'], 1800)

    def test_slow_translation_beyond_previous_four_second_cap_counts(self):
        detector = ProvisionalRepDetector()
        reps = []
        # Low acceleration for a long time, not a long pulse of 0.2g that
        # overshoots and looks like two cycles.
        phases = [(0.0, 1.0), (0.08, 1.4), (-0.08, 1.4), (0.0, 0.2),
                  (-0.08, 1.4), (0.08, 1.4), (0.0, 0.8)]
        for accel, seconds in phases:
            for _ in range(round(50 * seconds)):
                rep = detector.update(0.0, sample(accel))
                if rep:
                    reps.append(rep)
        self.assertEqual(len(reps), 1)

    def test_abandoned_hold_at_extent_rejects_without_counting(self):
        detector, reps = self.run_cycle(pickup=True, pause=7.0)
        self.assertEqual(reps, [])
        self.assertEqual(detector.diagnostics()['state'], 'idle')
        self.assertGreaterEqual(detector.diagnostics()['rejected_cycles'], 1)

    def test_mid_barbell_translation_with_incidental_roll_counts_once(self):
        detector = ProvisionalRepDetector()
        reps = []
        phases = [(0.0, 1.0), (0.2, 0.2), (-0.2, 0.2), (0.0, 1.0),
                  (-0.2, 0.2), (0.2, 0.2), (0.0, 0.6)]
        roll = 0.0
        for accel, seconds in phases:
            for _ in range(round(50 * seconds)):
                if accel:
                    roll = (roll + 2.0) % 20.0
                radians = math.radians(roll)
                imu = ImuSample(
                    (accel, math.sin(radians), math.cos(radians)),
                    (40.0 if accel else 0.0, 0.0, 0.0),
                    (roll, 0.0, 0.0),
                )
                rep = detector.update(0.0, imu)
                if rep:
                    reps.append(rep)
        self.assertEqual(len(reps), 1)

    def test_stream_gap_discards_unfinished_cycle(self):
        now = [0.0]
        detector = ProvisionalRepDetector(clock=lambda: now[0])
        for a in [0.0] * 50 + [0.2] * 10:
            now[0] += .02
            detector.update(0, sample(a))
        self.assertEqual(detector.diagnostics()['state'], 'active')
        now[0] += 1
        self.assertIsNone(detector.update(0, sample(-.2)))
        self.assertEqual(detector.diagnostics()['state'], 'idle')
        self.assertEqual(detector.diagnostics()['rejected_cycles'], 1)

    def test_nonfinite_sample_does_not_poison_next_cycle(self):
        detector = ProvisionalRepDetector()
        for value in (float('nan'), float('inf')):
            bad = sample(value)
            score = detector.activity_score(0, bad)
            self.assertIsNone(detector.update(0, bad, activity_score=score))
        for _ in range(50):
            detector.update(0, sample())
        self.assertTrue(all(math.isfinite(v) for v in detector._filtered_linear))

    def test_rotation_only_does_not_start_translation_cycle(self):
        detector = ProvisionalRepDetector()
        detector.update(0, sample())
        for roll in range(90):
            radians = math.radians(roll)
            rotated = ImuSample((0, math.sin(radians), math.cos(radians)),
                                (50, 0, 0), (roll, 0, 0))
            self.assertIsNone(detector.update(0, rotated))
        self.assertEqual(detector.diagnostics()['state'], 'idle')

    def test_varying_near_gravity_motion_does_not_reanchor_baseline(self):
        estimator = MovementEstimator(calibration_samples=1, rest_anchor_window=10)
        estimator.update(ImuSample((0, 0, .85), (0, 0, 0), (0, 0, 0)))
        for magnitude in [.94, 1.06] * 10:
            estimator.update(ImuSample((0, 0, magnitude), (0, 0, 0), (0, 0, 0)))
        self.assertAlmostEqual(estimator._baseline, .85)
        for _ in range(20):
            estimator.update(sample())
        self.assertAlmostEqual(estimator._baseline, 1.0)

    def test_invalid_sample_interval_rejected(self):
        for interval in (0, -.1, float('nan'), float('inf')):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                ProvisionalRepDetector(sample_interval_seconds=interval)

    def test_deadlift_concentric_first_cycle_counts_once(self):
        detector = ProvisionalRepDetector()
        vertical = (0.0, 0.0, 1.0)
        phases = [
            (0.0, 1.0),
            (0.25, 0.4), (-0.25, 0.4),
            (0.0, 0.6),
            (-0.25, 0.4), (0.25, 0.4),
            (0.0, 1.0),
        ]
        reps = []
        for a, sec in phases:
            for _ in range(round(50 * sec)):
                rep = detector.update(0.0, sample(a, direction=vertical))
                if rep:
                    reps.append(rep)
        self.assertEqual(len(reps), 1)
        self.assertGreaterEqual(reps[0]["duration_ms"], 2000)

    def test_bench_press_competition_chest_pause_counts_once(self):
        detector = ProvisionalRepDetector()
        vertical = (0.0, 0.0, 1.0)
        phases = [
            (0.0, 1.0),
            (-0.20, 0.3), (0.20, 0.3),
            (0.0, 2.0),
            (0.20, 0.3), (-0.20, 0.3),
            (0.0, 1.0),
        ]
        reps = []
        for a, sec in phases:
            for _ in range(round(50 * sec)):
                rep = detector.update(0.0, sample(a, direction=vertical))
                if rep:
                    reps.append(rep)
        self.assertEqual(len(reps), 1)
        self.assertGreaterEqual(reps[0]["duration_ms"], 3000)

    def test_unrack_and_walkout_does_not_count_as_rep(self):
        detector = ProvisionalRepDetector()
        unrack = [
            (0.0, 1.0),
            (0.10, 0.15), (-0.10, 0.15),
            (0.04, 0.2), (-0.04, 0.2),
            (0.04, 0.2), (-0.04, 0.2),
            (0.0, 2.0),
        ]
        reps = []
        for a, sec in unrack:
            for _ in range(round(50 * sec)):
                rep = detector.update(0.0, sample(a))
                if rep:
                    reps.append(rep)
        self.assertEqual(reps, [])
        self.assertEqual(detector.diagnostics()["state"], "idle")

    def test_imperfect_lockout_return_tolerance_counts(self):
        detector = ProvisionalRepDetector()
        vertical = (0.0, 0.0, 1.0)
        phases = [
            (0.0, 1.0),
            (-0.25, 0.4), (0.25, 0.4),
            (0.0, 0.2),
            (0.20, 0.32), (-0.20, 0.32),
            (0.0, 1.0),
        ]
        reps = []
        for a, sec in phases:
            for _ in range(round(50 * sec)):
                rep = detector.update(0.0, sample(a, direction=vertical))
                if rep:
                    reps.append(rep)
        self.assertEqual(len(reps), 1)
        self.assertEqual(detector.diagnostics()["rejected_cycles"], 0)
        self.assertGreaterEqual(reps[0]["duration_ms"], 1200)

    def test_one_way_translation_without_turnaround_does_not_count(self):
        detector = ProvisionalRepDetector()
        vertical = (0.0, 0.0, 1.0)
        phases = [
            (0.0, 1.0),
            (0.20, 0.4), (-0.20, 0.4),
            (0.0, 7.0),
        ]
        reps = []
        for a, sec in phases:
            for _ in range(round(50 * sec)):
                rep = detector.update(0.0, sample(a, direction=vertical))
                if rep:
                    reps.append(rep)
        self.assertEqual(reps, [])
        self.assertEqual(detector.diagnostics()["state"], "idle")
        self.assertGreaterEqual(detector.diagnostics()["rejected_cycles"], 1)

    def test_barbell_lockout_tremor_speed_qualifies(self):
        detector = ProvisionalRepDetector()
        vertical = (0.0, 0.0, 1.0)
        phases = [
            (0.0, 1.0),
            (-0.20, 0.3), (0.20, 0.3),
            (0.0, 0.2),
            (0.20, 0.3), (-0.20, 0.3),
            (0.0, 0.5),
        ]
        reps = []
        for a, sec in phases:
            for _ in range(round(50 * sec)):
                rep = detector.update(0.0, sample(a, direction=vertical))
                if rep:
                    reps.append(rep)
        self.assertEqual(len(reps), 1)
        self.assertGreaterEqual(reps[0]["duration_ms"], 1200)


if __name__ == '__main__':
    unittest.main()
