#!/usr/bin/env python3
"""Replay a capture file through the provisional rep detector.

The laptop agent writes decoded IMU samples (and ENTER-key manual rep markers)
to a JSONL file with --capture-path. This tool replays that file through the
exact same ProvisionalRepDetector the live agent uses, prints the reps it
accepts, and compares them against the manually marked reps so you can tell
whether the detector's thresholds are agreeing with reality.

Usage:
    python3 replay_capture.py <capture.jsonl>

Each accepted rep is printed with its mean/peak velocity and duration, then a
one-line summary: detected vs manually marked counts, and a per-rep timing
comparison when manual markers are present.
"""

import argparse
import json
import math
import sys
from pathlib import Path

from wt901_rack_agent import ImuSample, MovementEstimator, ProvisionalRepDetector


def load_records(path):
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield line_number, json.loads(line)
            except json.JSONDecodeError as error:
                print(f"[!] line {line_number}: not JSON ({error}); skipped", file=sys.stderr)


def replay(path, calibration_samples=50, recompute_movement=False, hz=50.0):
    estimator = MovementEstimator(calibration_samples=calibration_samples)
    detector = ProvisionalRepDetector(sample_interval_seconds=1.0 / hz)
    accepted = []
    manual = []

    for line_number, record in load_records(path):
        kind = record.get("kind")
        if kind == "manual_rep":
            manual.append(record.get("t_ms"))
            continue
        if kind != "sample":
            print(f"[!] line {line_number}: unknown kind {kind!r}; skipped", file=sys.stderr)
            continue

        sample = ImuSample(
            (record["ax"], record["ay"], record["az"]),
            (record["gx"], record["gy"], record["gz"]),
            (record["rx"], record["ry"], record["rz"]),
        )
        if recompute_movement:
            movement_g = estimator.update(sample)
            if movement_g is None:
                continue
        else:
            movement_g = record.get("movement_g")
            if movement_g is None:
                movement_g = estimator.update(sample)
                if movement_g is None:
                    continue
            else:
                estimator.update(sample)
        # Mirror the live agent loop exactly: activity_score() advances the
        # detector's internal linear filter, and update() must receive a score
        # computed this way — feeding a stored score straight into update()
        # skips the filter step and zeroes the displacement integration.
        activity_score = detector.activity_score(movement_g, sample)
        rep = detector.update(movement_g, sample, activity_score=activity_score)
        if rep is not None:
            accepted.append((record.get("t_ms"), rep))

    return accepted, manual


def format_mismatch(accepted, manual):
    lines = []
    manual_index = 0
    for t_ms, rep in accepted:
        matched = None
        while manual_index < len(manual) and manual[manual_index] < t_ms:
            manual_index += 1
        if manual_index < len(manual) and abs(manual[manual_index] - t_ms) < 5000:
            matched = manual[manual_index]
            manual_index += 1
        label = "ok" if matched is not None else "UNMATCHED"
        lines.append(f"  [{label}] t={t_ms}ms  mean={rep['mean_velocity']:.3f} "
                     f"peak={rep['peak_velocity']:.3f} dur={rep['duration_ms']}ms")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_path", help="JSONL capture file written by --capture-path")
    parser.add_argument("--calibration-samples", type=int, default=50)
    parser.add_argument(
        "--hz", type=float, default=50.0,
        help="sample rate the capture was taken at (default 50); the detector "
             "integrates velocity with a 1/Hz step",
    )
    parser.add_argument(
        "--recompute-movement", action="store_true",
        help="re-run the movement estimator instead of trusting the recorded movement_g "
             "(use after an estimator fix, to validate against an old capture)",
    )
    options = parser.parse_args(argv)

    if not Path(options.capture_path).is_file():
        print(f"[!] no such file: {options.capture_path}", file=sys.stderr)
        return 1

    accepted, manual = replay(
        options.capture_path, options.calibration_samples,
        recompute_movement=options.recompute_movement, hz=options.hz,
    )

    print(f"manual reps marked:   {len(manual)}")
    print(f"detected reps:        {len(accepted)}")

    if accepted:
        print("accepted reps:")
        for line in format_mismatch(accepted, manual):
            print(line)

    if manual:
        print(f"\nverdict: detector {'AGREES' if len(accepted) == len(manual) else 'DISAGREES'} "
              f"with your manual count")
        if len(accepted) != len(manual):
            print("  this is expected while thresholds are provisional; tune the "
                  "detector constants in wt901_rack_agent.py and re-run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
