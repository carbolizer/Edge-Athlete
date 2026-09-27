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
    if not math.isfinite(hz) or hz <= 0:
        raise ValueError("hz must be finite and positive")
    estimator = MovementEstimator(calibration_samples=calibration_samples)
    replay_time = [0.0]
    detector = ProvisionalRepDetector(
        sample_interval_seconds=1.0 / hz, clock=lambda: replay_time[0],
    )
    accepted = []
    manual = []

    for line_number, record in load_records(path):
        kind = record.get("kind")
        if kind == "manual_rep":
            manual.append(record.get("t_ms"))
            continue
        if kind in ("manual_set_start", "manual_set_end"):
            continue
        if kind != "sample":
            print(f"[!] line {line_number}: unknown kind {kind!r}; skipped", file=sys.stderr)
            continue

        replay_time[0] = record["t_ms"] / 1000.0
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


def match_reps(accepted, manual, tolerance_ms=1000):
    """One-to-one chronological matching, allowing markers before or after reps.

    Counts alone hide a missed rep offset by a false positive. The tolerance is
    explicit because keyboard labels include human reaction time.
    """
    if not math.isfinite(tolerance_ms) or tolerance_ms < 0:
        raise ValueError("tolerance_ms must be finite and nonnegative")
    detected = sorted((t, i) for i, (t, _) in enumerate(accepted))
    marked = sorted((t, i) for i, t in enumerate(manual))
    matches = {}
    d = m = 0
    while d < len(detected) and m < len(marked):
        dt, di = detected[d]
        mt, mi = marked[m]
        if dt < mt - tolerance_ms:
            d += 1
        elif mt < dt - tolerance_ms:
            m += 1
        else:
            matches[di] = mi
            d += 1
            m += 1
    return matches


def format_mismatch(accepted, manual, tolerance_ms=1000):
    matches = match_reps(accepted, manual, tolerance_ms)
    lines = []
    for index, (t_ms, rep) in enumerate(accepted):
        label = "ok" if index in matches else "UNMATCHED"
        lines.append(f"  [{label}] t={t_ms}ms  mean={rep['mean_velocity']:.3f} "
                     f"peak={rep['peak_velocity']:.3f} dur={rep['duration_ms']}ms")
    return lines


def labeled_sets(path):
    """Read explicit set boundaries; reject ambiguous or unfinished labels."""
    intervals = []
    start = None
    for line_number, record in load_records(path):
        kind = record.get("kind")
        if kind == "manual_set_start":
            if start is not None:
                raise ValueError(f"line {line_number}: set already started")
            start = record["t_ms"]
        elif kind == "manual_set_end":
            end = record["t_ms"]
            if start is None or end < start:
                raise ValueError(f"line {line_number}: set end without a valid start")
            intervals.append((start, end))
            start = None
    if start is not None:
        raise ValueError("capture has an unfinished labeled set")
    return intervals


def accuracy_summary(accepted, manual, tolerance_ms):
    matched = len(match_reps(accepted, manual, tolerance_ms))
    false_positives = len(accepted) - matched
    missed = len(manual) - matched
    precision = f"{matched / len(accepted):.1%}" if accepted else "n/a"
    recall = f"{matched / len(manual):.1%}" if manual else "n/a"
    return (f"matched={matched} false positives={false_positives} missed={missed} "
            f"precision={precision} recall={recall}")


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
    parser.add_argument("--match-tolerance-ms", type=float, default=1000,
                        help="maximum manual/detected timestamp difference (default 1000)")
    options = parser.parse_args(argv)
    if not math.isfinite(options.hz) or options.hz <= 0:
        parser.error("--hz must be finite and positive")
    if not math.isfinite(options.match_tolerance_ms) or options.match_tolerance_ms < 0:
        parser.error("--match-tolerance-ms must be finite and nonnegative")

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
        for line in format_mismatch(accepted, manual, options.match_tolerance_ms):
            print(line)

    if manual:
        print("\n" + accuracy_summary(accepted, manual, options.match_tolerance_ms))
        matches = match_reps(accepted, manual, options.match_tolerance_ms)
        agrees = len(matches) == len(accepted) == len(manual)
        print(f"verdict: detector {'AGREES' if agrees else 'DISAGREES'} "
              "with the timestamped labels in this capture")
    else:
        print("No manual rep labels: accuracy cannot be evaluated.")
    try:
        intervals = labeled_sets(options.capture_path)
    except ValueError as error:
        print(f"[!] {error}", file=sys.stderr)
        return 1
    for index, (start, end) in enumerate(intervals, 1):
        reps = [(t, rep) for t, rep in accepted if start <= t < end]
        markers = [t for t in manual if start <= t < end]
        print(f"set {index}: " + accuracy_summary(reps, markers, options.match_tolerance_ms))
    if intervals:
        outside = sum(not any(start <= t < end for start, end in intervals) for t, _ in accepted)
        print(f"detections outside labeled sets: {outside}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
