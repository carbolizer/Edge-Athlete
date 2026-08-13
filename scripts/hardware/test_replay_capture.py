import importlib.util
import json
import tempfile
from pathlib import Path
import unittest


REPLAY_PATH = Path(__file__).with_name("replay_capture.py")
SPEC = importlib.util.spec_from_file_location("replay_capture", REPLAY_PATH)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


def rest_to_rest_cycle(step_t_ms=20):
    acceleration_x = (
        [0.0] * 50 + [0.20] * 10 + [-0.20] * 10 + [0.0] * 8
        + [-0.20] * 10 + [0.20] * 10 + [0.0] * 25
    )
    return [
        {
            "kind": "sample",
            "t_ms": index * step_t_ms,
            "movement_g": 0.0,
            "ax": acceleration_x,
            "ay": 0.0,
            "az": 1.0,
            "gx": 0.0,
            "gy": 0.0,
            "gz": 0.0,
            "rx": 0.0,
            "ry": 0.0,
            "rz": 0.0,
        }
        for index, acceleration_x in enumerate(acceleration_x)
    ]


class ReplayCaptureTests(unittest.TestCase):
    def write_capture(self, records):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8",
        )
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        handle.close()
        return handle.name

    def test_replays_one_detected_rep_from_rest_to_rest_cycle(self):
        path = self.write_capture(rest_to_rest_cycle())
        accepted, manual = replay.replay(path)
        self.assertEqual(len(accepted), 1)
        _, rep = accepted[0]
        self.assertGreater(rep["peak_velocity"], rep["mean_velocity"])
        self.assertGreaterEqual(rep["duration_ms"], 600)

    def test_manual_marker_counts_alongside_detected(self):
        records = rest_to_rest_cycle()
        records.append({"kind": "manual_rep", "n": 1, "t_ms": 3000})
        path = self.write_capture(records)
        accepted, manual = replay.replay(path)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(manual), 1)

    def test_skips_malformed_lines(self):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8",
        )
        handle.write("this is not json\n")
        handle.close()
        accepted, manual = replay.replay(handle.name)
        self.assertEqual((accepted, manual), ([], []))

    def test_main_returns_zero_for_valid_capture(self):
        path = self.write_capture(rest_to_rest_cycle())
        self.assertEqual(replay.main([path]), 0)

    def test_main_missing_file_returns_nonzero(self):
        self.assertNotEqual(replay.main(["/nonexistent/capture.jsonl"]), 0)


if __name__ == "__main__":
    unittest.main()
