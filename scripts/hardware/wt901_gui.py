#!/usr/bin/env python3
"""Edge Athlete WT901 Barbell Rep & Velocity Tracking GUI.

Provides an interactive dashboard for strength athletes and coaches:
- Set lifecycle controls: Start Set, End Set, Clear Set, Manual Rep.
- Real-time barbell velocity tracking (Mean Vel, Peak Vel, Duration, Excursion).
- Velocity loss and fatigue monitoring across sets.
- Full set history logging and CSV / JSON export.
- BLE and USB Serial hardware connection management with live status.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import urllib.request

HERE = Path(__file__).resolve().parent
DEFAULT_BLE_ADDRESS = "606A5A24-9A43-D631-61E5-7BBB9E495F05"
DEFAULT_NODE_ID = "barbell_local"
DEFAULT_HZ = 50

# Modern gym dashboard color palette
THEME = {
    "bg_dark": "#11141c",
    "surface": "#1b202c",
    "surface_alt": "#242b3b",
    "border": "#2f384c",
    "text_main": "#f9fafb",
    "text_muted": "#9ca3af",
    "green": "#10b981",
    "green_hover": "#059669",
    "red": "#ef4444",
    "red_hover": "#dc2626",
    "amber": "#f59e0b",
    "amber_hover": "#d97706",
    "blue": "#3b82f6",
    "blue_hover": "#2563eb",
    "purple": "#8b5cf6",
}


@dataclass
class RepData:
    rep_number: int
    mean_velocity: float
    peak_velocity: float
    duration_ms: int
    peak_excursion_m: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))


@dataclass
class WorkoutSet:
    set_number: int
    exercise: str
    weight: str = ""
    target_reps: Optional[int] = None
    start_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    end_time: Optional[str] = None
    duration_seconds: float = 0.0
    reps: List[RepData] = field(default_factory=list)

    @property
    def rep_count(self) -> int:
        return len(self.reps)

    @property
    def avg_mean_velocity(self) -> float:
        if not self.reps:
            return 0.0
        return round(sum(r.mean_velocity for r in self.reps) / len(self.reps), 3)

    @property
    def best_velocity(self) -> float:
        if not self.reps:
            return 0.0
        return max(r.mean_velocity for r in self.reps)

    @property
    def peak_velocity_max(self) -> float:
        if not self.reps:
            return 0.0
        return max(r.peak_velocity for r in self.reps)

    @property
    def velocity_loss_pct(self) -> float:
        """Percentage velocity decline from first rep to slowest/last rep."""
        if len(self.reps) < 2 or self.reps[0].mean_velocity <= 0:
            return 0.0
        first_vel = self.reps[0].mean_velocity
        last_vel = self.reps[-1].mean_velocity
        loss = max(0.0, (first_vel - last_vel) / first_vel * 100.0)
        return round(loss, 1)


class WorkoutSession:
    """Session state machine tracking sets, reps, and workout statistics."""

    def __init__(self):
        self.sets: List[WorkoutSet] = []
        self.active_set: Optional[WorkoutSet] = None
        self._next_set_number = 1
        self._active_start_monotonic = 0.0

    @property
    def is_set_active(self) -> bool:
        return self.active_set is not None

    def start_set(self, exercise: str, weight: str = "", target_reps: Optional[int] = None) -> WorkoutSet:
        if self.active_set is not None:
            self.end_set()
        new_set = WorkoutSet(
            set_number=self._next_set_number,
            exercise=exercise or "Barbell Exercise",
            weight=weight,
            target_reps=target_reps,
        )
        self.active_set = new_set
        self._active_start_monotonic = time.monotonic()
        return new_set

    def add_rep(self, mean_velocity: float, peak_velocity: float, duration_ms: int,
                peak_excursion_m: float = 0.0, timestamp: Optional[str] = None) -> Optional[RepData]:
        if self.active_set is None:
            # Auto-start an open set if sensor emits a rep outside an explicit set
            self.start_set(exercise="General Set")
        rep_num = len(self.active_set.reps) + 1
        rep = RepData(
            rep_number=rep_num,
            mean_velocity=round(mean_velocity, 3),
            peak_velocity=round(peak_velocity, 3),
            duration_ms=int(duration_ms),
            peak_excursion_m=round(peak_excursion_m, 4),
            timestamp=timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        self.active_set.reps.append(rep)
        return rep

    def end_set(self) -> Optional[WorkoutSet]:
        if self.active_set is None:
            return None
        finished_set = self.active_set
        finished_set.end_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        finished_set.duration_seconds = round(time.monotonic() - self._active_start_monotonic, 1)
        self.sets.append(finished_set)
        self._next_set_number += 1
        self.active_set = None
        return finished_set

    def clear_set(self) -> bool:
        if self.active_set is None:
            return False
        self.active_set = None
        return True

    def export_csv(self, filepath: Path) -> int:
        """Export all completed sets and reps to a flat CSV."""
        rows = []
        for s in self.sets:
            if not s.reps:
                rows.append({
                    "set_number": s.set_number,
                    "exercise": s.exercise,
                    "weight": s.weight,
                    "set_duration_s": s.duration_seconds,
                    "rep_number": "",
                    "mean_velocity_mps": "",
                    "peak_velocity_mps": "",
                    "duration_ms": "",
                    "peak_excursion_m": "",
                    "timestamp": s.start_time,
                })
            for r in s.reps:
                rows.append({
                    "set_number": s.set_number,
                    "exercise": s.exercise,
                    "weight": s.weight,
                    "set_duration_s": s.duration_seconds,
                    "rep_number": r.rep_number,
                    "mean_velocity_mps": r.mean_velocity,
                    "peak_velocity_mps": r.peak_velocity,
                    "duration_ms": r.duration_ms,
                    "peak_excursion_m": r.peak_excursion_m,
                    "timestamp": r.timestamp,
                })
        if not rows:
            return 0
        fieldnames = [
            "set_number", "exercise", "weight", "set_duration_s",
            "rep_number", "mean_velocity_mps", "peak_velocity_mps",
            "duration_ms", "peak_excursion_m", "timestamp",
        ]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)

    def export_json(self, filepath: Path) -> None:
        """Export session data hierarchy to JSON."""
        data = {
            "session_exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "sets_count": len(self.sets),
            "sets": [
                {
                    "set_number": s.set_number,
                    "exercise": s.exercise,
                    "weight": s.weight,
                    "target_reps": s.target_reps,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "duration_seconds": s.duration_seconds,
                    "rep_count": s.rep_count,
                    "avg_mean_velocity": s.avg_mean_velocity,
                    "best_velocity": s.best_velocity,
                    "velocity_loss_pct": s.velocity_loss_pct,
                    "reps": [asdict(r) for r in s.reps],
                }
                for s in self.sets
            ],
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


class SensorProcessManager:
    """Manages the background wt901_rack_agent subprocess and streams events."""

    def __init__(self, event_queue: queue.Queue):
        self.queue = event_queue
        self.process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False

    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, mode: str = "ble", address: str = DEFAULT_BLE_ADDRESS,
              serial_port: str = "", baud: int = 115200, node_id: str = DEFAULT_NODE_ID,
              hz: int = DEFAULT_HZ, capture_path: str = "") -> bool:
        if self.is_alive():
            self.stop()

        python_bin = sys.executable
        venv_py = HERE.parent.parent / "venv" / "wt901" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        if venv_py.is_file():
            python_bin = str(venv_py)

        agent_script = HERE / "wt901_rack_agent.py"
        cmd = [python_bin, str(agent_script), "--node-id", node_id, "--hz", str(hz)]
        if mode == "ble":
            cmd.extend(["--address", address.strip()])
        else:
            cmd.extend(["--serial-port", serial_port.strip(), "--baud", str(baud)])
        if capture_path:
            cmd.extend(["--capture-path", capture_path.strip()])

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._running = True
            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()
            self.queue.put(("connection_state", "connecting"))
            return True
        except Exception as exc:
            self.queue.put(("error", str(exc)))
            return False

    def stop(self):
        self._running = False
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=1.5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        self.queue.put(("connection_state", "disconnected"))

    def _reader_loop(self):
        if self.process is None or self.process.stdout is None:
            return
        for raw_line in iter(self.process.stdout.readline, ""):
            if not self._running:
                break
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("[REP_JSON] "):
                try:
                    payload = json.loads(line[11:])
                    self.queue.put(("rep", payload))
                except Exception:
                    pass
            elif line.startswith("[STATUS_JSON] "):
                try:
                    payload = json.loads(line[14:])
                    self.queue.put(("status", payload))
                except Exception:
                    pass
            else:
                # Forward all other output to the debug log
                self.queue.put(("log", line))
                if "WT901BLE unavailable" in line or "retrying" in line:
                    self.queue.put(("connection_state", "retrying"))

        self.queue.put(("connection_state", "disconnected"))


# ---------------------------------------------------------------------------
# Tkinter GUI Implementation
# ---------------------------------------------------------------------------

def create_gui_app(root: Optional[Any] = None, session: Optional[WorkoutSession] = None):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    if root is None:
        root = tk.Tk()

    class EdgeAthleteBarbellApp:
        def __init__(self, root: tk.Tk):
            self.root = root
            self.root.title("Edge Athlete — Barbell Rep & Velocity Tracker")
            self.root.geometry("1100x740")
            self.root.minsize(960, 680)
            self.root.configure(bg=THEME["bg_dark"])

            self.session = session or WorkoutSession()
            self.event_queue = queue.Queue()
            self.sensor_mgr = SensorProcessManager(self.event_queue)
            self._set_timer_running = False

            self._configure_styles()
            self._build_ui()
            self._schedule_updates()

        def _configure_styles(self):
            style = ttk.Style(self.root)
            try:
                style.theme_use("clam")
            except Exception:
                pass
            style.configure(".", background=THEME["bg_dark"], foreground=THEME["text_main"])
            style.configure("TFrame", background=THEME["bg_dark"])
            style.configure("Surface.TFrame", background=THEME["surface"])
            style.configure("TLabel", background=THEME["bg_dark"], foreground=THEME["text_main"], font=("Helvetica", 11))
            style.configure("Surface.TLabel", background=THEME["surface"], foreground=THEME["text_main"])
            style.configure("Muted.TLabel", background=THEME["surface"], foreground=THEME["text_muted"], font=("Helvetica", 10))
            style.configure("Header.TLabel", background=THEME["bg_dark"], foreground=THEME["text_main"], font=("Helvetica", 15, "bold"))
            style.configure("Treeview", background=THEME["surface_alt"], foreground=THEME["text_main"], fieldbackground=THEME["surface_alt"], rowheight=28)
            style.configure("Treeview.Heading", background=THEME["surface"], foreground=THEME["text_main"], font=("Helvetica", 10, "bold"))
            style.map("Treeview", background=[("selected", THEME["blue"])])

        def _build_ui(self):
            # 1. Header & Connection Bar
            top_bar = tk.Frame(self.root, bg=THEME["surface"], highlightbackground=THEME["border"], highlightthickness=1, height=64)
            top_bar.pack(fill=tk.X, padx=12, pady=(10, 8))

            title_box = tk.Frame(top_bar, bg=THEME["surface"])
            title_box.pack(side=tk.LEFT, padx=14, pady=8)
            tk.Label(title_box, text="EDGE ATHLETE", font=("Helvetica", 15, "bold"), fg=THEME["green"], bg=THEME["surface"]).pack(anchor=tk.W)
            tk.Label(title_box, text="Barbell Velocity & Rep Tracker", font=("Helvetica", 10), fg=THEME["text_muted"], bg=THEME["surface"]).pack(anchor=tk.W)

            conn_box = tk.Frame(top_bar, bg=THEME["surface"])
            conn_box.pack(side=tk.RIGHT, padx=14, pady=10)

            tk.Label(conn_box, text="BLE Address:", font=("Helvetica", 10), fg=THEME["text_muted"], bg=THEME["surface"]).pack(side=tk.LEFT, padx=(0, 4))
            self.addr_var = tk.StringVar(value=DEFAULT_BLE_ADDRESS)
            self.addr_entry = tk.Entry(conn_box, textvariable=self.addr_var, width=32, bg=THEME["surface_alt"], fg=THEME["text_main"], insertbackground=THEME["text_main"], highlightthickness=1, highlightbackground=THEME["border"])
            self.addr_entry.pack(side=tk.LEFT, padx=(0, 10))

            self.status_pill = tk.Label(conn_box, text="● Disconnected", font=("Helvetica", 10, "bold"), fg=THEME["text_muted"], bg=THEME["surface_alt"], padx=10, pady=4)
            self.status_pill.pack(side=tk.LEFT, padx=(0, 10))

            self.connect_btn = tk.Button(conn_box, text="Connect", font=("Helvetica", 10, "bold"), bg=THEME["blue"], fg="white", activebackground=THEME["blue_hover"], padx=12, pady=4, relief=tk.FLAT, cursor="hand2", command=self._toggle_connection)
            self.connect_btn.pack(side=tk.LEFT)

            # 2. Main Content Split (Left: Set Controls & Live Cards, Right: Tables)
            main_split = tk.Frame(self.root, bg=THEME["bg_dark"])
            main_split.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

            left_panel = tk.Frame(main_split, bg=THEME["bg_dark"], width=460)
            left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 8))

            right_panel = tk.Frame(main_split, bg=THEME["bg_dark"])
            right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(8, 0))

            self._build_set_controller(left_panel)
            self._build_live_display(left_panel)
            self._build_history_tables(right_panel)

        def _build_set_controller(self, parent):
            card = tk.LabelFrame(parent, text="  Workout Set Controls  ", bg=THEME["surface"], fg=THEME["text_main"], font=("Helvetica", 11, "bold"), highlightbackground=THEME["border"], highlightthickness=1, padx=12, pady=12)
            card.pack(fill=tk.X, pady=(0, 10))

            # Row 1: Exercise & Weight
            row1 = tk.Frame(card, bg=THEME["surface"])
            row1.pack(fill=tk.X, pady=(0, 8))

            tk.Label(row1, text="Exercise:", font=("Helvetica", 10, "bold"), fg=THEME["text_muted"], bg=THEME["surface"]).grid(row=0, column=0, sticky=tk.W, padx=(0, 6))
            self.exercise_var = tk.StringVar(value="Back Squat")
            self.exercise_combo = ttk.Combobox(row1, textvariable=self.exercise_var, values=["Back Squat", "Bench Press", "Deadlift", "Overhead Press", "Barbell Row", "Custom Exercise"], width=16)
            self.exercise_combo.grid(row=0, column=1, sticky=tk.W, padx=(0, 14))

            tk.Label(row1, text="Weight:", font=("Helvetica", 10, "bold"), fg=THEME["text_muted"], bg=THEME["surface"]).grid(row=0, column=2, sticky=tk.W, padx=(0, 6))
            self.weight_var = tk.StringVar(value="225 lbs")
            self.weight_entry = tk.Entry(row1, textvariable=self.weight_var, width=10, bg=THEME["surface_alt"], fg=THEME["text_main"], insertbackground=THEME["text_main"], highlightthickness=1, highlightbackground=THEME["border"])
            self.weight_entry.grid(row=0, column=3, sticky=tk.W)

            # Row 2: Set Info & Live Duration Timer
            row2 = tk.Frame(card, bg=THEME["surface"])
            row2.pack(fill=tk.X, pady=(0, 12))

            self.set_badge = tk.Label(row2, text="Set 1 (Ready)", font=("Helvetica", 11, "bold"), fg=THEME["text_main"], bg=THEME["surface_alt"], padx=8, pady=3)
            self.set_badge.pack(side=tk.LEFT)

            self.timer_label = tk.Label(row2, text="⏱  00:00", font=("Helvetica", 11, "bold"), fg=THEME["text_muted"], bg=THEME["surface"], padx=10)
            self.timer_label.pack(side=tk.RIGHT)

            # Row 3: Action Buttons (Start Set, End Set, Clear Set)
            btn_row = tk.Frame(card, bg=THEME["surface"])
            btn_row.pack(fill=tk.X, pady=(4, 0))

            self.start_btn = tk.Button(btn_row, text="▶ START SET", font=("Helvetica", 11, "bold"), bg=THEME["green"], fg="white", activebackground=THEME["green_hover"], padx=12, pady=8, relief=tk.FLAT, cursor="hand2", command=self.on_start_set)
            self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

            self.end_btn = tk.Button(btn_row, text="■ END SET", font=("Helvetica", 11, "bold"), bg=THEME["red"], fg="white", activebackground=THEME["red_hover"], padx=12, pady=8, relief=tk.FLAT, cursor="hand2", state=tk.DISABLED, command=self.on_end_set)
            self.end_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

            self.clear_btn = tk.Button(btn_row, text="✕ CLEAR", font=("Helvetica", 10, "bold"), bg=THEME["surface_alt"], fg=THEME["amber"], activebackground=THEME["amber_hover"], padx=8, pady=8, relief=tk.FLAT, cursor="hand2", command=self.on_clear_set)
            self.clear_btn.pack(side=tk.LEFT, padx=(4, 0))

        def _build_live_display(self, parent):
            card = tk.LabelFrame(parent, text="  Live Barbell Kinematics  ", bg=THEME["surface"], fg=THEME["text_main"], font=("Helvetica", 11, "bold"), highlightbackground=THEME["border"], highlightthickness=1, padx=12, pady=10)
            card.pack(fill=tk.BOTH, expand=True)

            # Big Rep Counter Banner
            counter_box = tk.Frame(card, bg=THEME["surface_alt"], pady=8)
            counter_box.pack(fill=tk.X, pady=(0, 10))

            tk.Label(counter_box, text="CURRENT SET REPS", font=("Helvetica", 10, "bold"), fg=THEME["text_muted"], bg=THEME["surface_alt"]).pack()
            self.rep_count_label = tk.Label(counter_box, text="0", font=("Helvetica", 54, "bold"), fg=THEME["green"], bg=THEME["surface_alt"])
            self.rep_count_label.pack()

            self.motion_pill = tk.Label(counter_box, text="● REST / IDLE", font=("Helvetica", 9, "bold"), fg=THEME["text_muted"], bg=THEME["surface"], padx=8, pady=2)
            self.motion_pill.pack()

            # 4 Metric Cards Grid (Mean Vel, Peak Vel, Duration, Velocity Loss)
            grid = tk.Frame(card, bg=THEME["surface"])
            grid.pack(fill=tk.BOTH, expand=True)

            def make_tile(parent_frame, title, default_val, col, row, color):
                f = tk.Frame(parent_frame, bg=THEME["surface_alt"], padx=8, pady=8, highlightbackground=THEME["border"], highlightthickness=1)
                f.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
                tk.Label(f, text=title, font=("Helvetica", 9, "bold"), fg=THEME["text_muted"], bg=THEME["surface_alt"]).pack(anchor=tk.W)
                val_lbl = tk.Label(f, text=default_val, font=("Helvetica", 20, "bold"), fg=color, bg=THEME["surface_alt"])
                val_lbl.pack(anchor=tk.W, pady=(2, 0))
                return val_lbl

            grid.columnconfigure(0, weight=1)
            grid.columnconfigure(1, weight=1)
            grid.rowconfigure(0, weight=1)
            grid.rowconfigure(1, weight=1)

            self.mean_vel_val = make_tile(grid, "MEAN VELOCITY", "0.00 m/s", 0, 0, THEME["green"])
            self.peak_vel_val = make_tile(grid, "PEAK VELOCITY", "0.00 m/s", 1, 0, THEME["blue"])
            self.duration_val = make_tile(grid, "REP DURATION", "0.00 s", 0, 1, THEME["purple"])
            self.vel_loss_val = make_tile(grid, "VELOCITY LOSS", "0.0 %", 1, 1, THEME["amber"])

            # Manual / Sim buttons row
            sim_row = tk.Frame(card, bg=THEME["surface"])
            sim_row.pack(fill=tk.X, pady=(10, 0))
            tk.Button(sim_row, text="+ Add Manual Rep", font=("Helvetica", 9), bg=THEME["surface_alt"], fg=THEME["text_main"], relief=tk.FLAT, cursor="hand2", command=self.on_manual_rep).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
            tk.Button(sim_row, text="⚡ Simulate Rep", font=("Helvetica", 9), bg=THEME["surface_alt"], fg=THEME["text_main"], relief=tk.FLAT, cursor="hand2", command=self.on_simulate_rep).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        def _build_history_tables(self, parent):
            # Notebook tabs for Current Set Breakdown vs Completed Sets
            notebook = ttk.Notebook(parent)
            notebook.pack(fill=tk.BOTH, expand=True)

            # Tab 1: Current Set Rep Breakdown
            tab1 = tk.Frame(notebook, bg=THEME["bg_dark"])
            notebook.add(tab1, text="  Current Set Reps  ")

            cols1 = ("rep", "mean_vel", "peak_vel", "duration", "depth", "time")
            self.rep_tree = ttk.Treeview(tab1, columns=cols1, show="headings", height=12)
            self.rep_tree.heading("rep", text="Rep #")
            self.rep_tree.heading("mean_vel", text="Mean Vel (m/s)")
            self.rep_tree.heading("peak_vel", text="Peak Vel (m/s)")
            self.rep_tree.heading("duration", text="Duration (s)")
            self.rep_tree.heading("depth", text="Depth (m)")
            self.rep_tree.heading("time", text="Timestamp")

            self.rep_tree.column("rep", width=55, anchor=tk.CENTER)
            self.rep_tree.column("mean_vel", width=105, anchor=tk.CENTER)
            self.rep_tree.column("peak_vel", width=105, anchor=tk.CENTER)
            self.rep_tree.column("duration", width=95, anchor=tk.CENTER)
            self.rep_tree.column("depth", width=90, anchor=tk.CENTER)
            self.rep_tree.column("time", width=150, anchor=tk.W)
            self.rep_tree.pack(fill=tk.BOTH, expand=True, pady=6)

            # Tab 2: Completed Sets History
            tab2 = tk.Frame(notebook, bg=THEME["bg_dark"])
            notebook.add(tab2, text="  Completed Sets History  ")

            cols2 = ("set", "exercise", "weight", "reps", "avg_vel", "best_vel", "vel_loss", "duration")
            self.set_tree = ttk.Treeview(tab2, columns=cols2, show="headings", height=12)
            self.set_tree.heading("set", text="Set #")
            self.set_tree.heading("exercise", text="Exercise")
            self.set_tree.heading("weight", text="Weight")
            self.set_tree.heading("reps", text="Reps")
            self.set_tree.heading("avg_vel", text="Avg Vel")
            self.set_tree.heading("best_vel", text="Best Vel")
            self.set_tree.heading("vel_loss", text="Loss %")
            self.set_tree.heading("duration", text="Set Time")

            self.set_tree.column("set", width=55, anchor=tk.CENTER)
            self.set_tree.column("exercise", width=120, anchor=tk.W)
            self.set_tree.column("weight", width=80, anchor=tk.CENTER)
            self.set_tree.column("reps", width=55, anchor=tk.CENTER)
            self.set_tree.column("avg_vel", width=85, anchor=tk.CENTER)
            self.set_tree.column("best_vel", width=85, anchor=tk.CENTER)
            self.set_tree.column("vel_loss", width=75, anchor=tk.CENTER)
            self.set_tree.column("duration", width=80, anchor=tk.CENTER)
            self.set_tree.pack(fill=tk.BOTH, expand=True, pady=6)

            # Tab 3: Sensor Log (debug console)
            tab3 = tk.Frame(notebook, bg=THEME["bg_dark"])
            notebook.add(tab3, text="  Sensor Log  ")

            import tkinter.scrolledtext as st
            self.log_text = st.ScrolledText(tab3, bg=THEME["surface_alt"], fg=THEME["text_main"],
                                            insertbackground=THEME["text_main"], font=("Courier", 10),
                                            state=tk.DISABLED, wrap=tk.WORD, height=12)
            self.log_text.pack(fill=tk.BOTH, expand=True, pady=6)

            # Export toolbar
            export_bar = tk.Frame(parent, bg=THEME["bg_dark"])
            export_bar.pack(fill=tk.X, pady=(6, 2))

            tk.Button(export_bar, text="Export CSV", font=("Helvetica", 10, "bold"), bg=THEME["surface_alt"], fg=THEME["text_main"], relief=tk.FLAT, cursor="hand2", padx=10, pady=4, command=self.on_export_csv).pack(side=tk.RIGHT, padx=(4, 0))
            tk.Button(export_bar, text="Export JSON", font=("Helvetica", 10), bg=THEME["surface_alt"], fg=THEME["text_main"], relief=tk.FLAT, cursor="hand2", padx=10, pady=4, command=self.on_export_json).pack(side=tk.RIGHT)

        def _toggle_connection(self):
            if self.sensor_mgr.is_alive():
                self.sensor_mgr.stop()
                self._set_connection_badge("disconnected")
                self.connect_btn.configure(text="Connect", bg=THEME["blue"])
            else:
                addr = self.addr_var.get().strip()
                if not addr:
                    messagebox.showerror("Error", "Please provide a BLE address or port.")
                    return
                self._set_connection_badge("connecting")
                self.connect_btn.configure(text="Disconnect", bg=THEME["red"])
                self.sensor_mgr.start(mode="ble", address=addr)

        def _set_connection_badge(self, state: str):
            if state == "live":
                self.status_pill.configure(text="● Streaming (50Hz)", fg=THEME["green"])
            elif state == "connecting":
                self.status_pill.configure(text="● Connecting...", fg=THEME["amber"])
            elif state == "calibrating":
                self.status_pill.configure(text="● Calibrating...", fg=THEME["amber"])
            elif state == "starting":
                self.status_pill.configure(text="● Starting...", fg=THEME["amber"])
            elif state == "retrying":
                self.status_pill.configure(text="● Retrying...", fg=THEME["red"])
            elif state == "stale":
                self.status_pill.configure(text="● Stale Data", fg=THEME["red"])
            else:
                self.status_pill.configure(text="● Disconnected", fg=THEME["text_muted"])

        def on_start_set(self):
            exercise = self.exercise_var.get().strip() or "Barbell Exercise"
            weight = self.weight_var.get().strip()
            new_set = self.session.start_set(exercise=exercise, weight=weight)

            self.start_btn.configure(state=tk.DISABLED)
            self.end_btn.configure(state=tk.NORMAL)
            self.exercise_combo.configure(state=tk.DISABLED)
            self.weight_entry.configure(state=tk.DISABLED)

            self.set_badge.configure(text=f"Set {new_set.set_number} (Active)", fg=THEME["green"])
            self.rep_count_label.configure(text="0", fg=THEME["green"])
            self.mean_vel_val.configure(text="0.00 m/s")
            self.peak_vel_val.configure(text="0.00 m/s")
            self.duration_val.configure(text="0.00 s")
            self.vel_loss_val.configure(text="0.0 %")

            # Clear current set tree
            for item in self.rep_tree.get_children():
                self.rep_tree.delete(item)

            self._set_timer_running = True

        def on_end_set(self):
            if not self.session.is_set_active:
                return
            finished_set = self.session.end_set()
            self._set_timer_running = False

            self.start_btn.configure(state=tk.NORMAL)
            self.end_btn.configure(state=tk.DISABLED)
            self.exercise_combo.configure(state=tk.NORMAL)
            self.weight_entry.configure(state=tk.NORMAL)

            next_num = self.session._next_set_number
            self.set_badge.configure(text=f"Set {next_num} (Ready)", fg=THEME["text_main"])

            if finished_set is not None:
                # Add to completed sets tree
                self.set_tree.insert(
                    "",
                    tk.END,
                    values=(
                        finished_set.set_number,
                        finished_set.exercise,
                        finished_set.weight,
                        finished_set.rep_count,
                        f"{finished_set.avg_mean_velocity:.2f} m/s",
                        f"{finished_set.best_velocity:.2f} m/s",
                        f"{finished_set.velocity_loss_pct:.1f} %",
                        f"{finished_set.duration_seconds:.1f} s",
                    ),
                )

        def on_clear_set(self):
            if self.session.is_set_active:
                if self.session.active_set and self.session.active_set.rep_count > 0:
                    if not messagebox.askyesno("Clear Set", "Discard current active set?"):
                        return
                self.session.clear_set()

            self._set_timer_running = False
            self.start_btn.configure(state=tk.NORMAL)
            self.end_btn.configure(state=tk.DISABLED)
            self.exercise_combo.configure(state=tk.NORMAL)
            self.weight_entry.configure(state=tk.NORMAL)

            cur_num = self.session._next_set_number
            self.set_badge.configure(text=f"Set {cur_num} (Ready)", fg=THEME["text_main"])
            self.timer_label.configure(text="⏱  00:00")
            self.rep_count_label.configure(text="0", fg=THEME["green"])

            for item in self.rep_tree.get_children():
                self.rep_tree.delete(item)

        def on_manual_rep(self):
            self._ingest_rep({
                "mean_velocity": 0.65,
                "peak_velocity": 1.10,
                "duration_ms": 1320,
                "peak_excursion_m": 0.45,
            })

        def on_simulate_rep(self):
            import random
            rep_idx = len(self.session.active_set.reps) + 1 if self.session.active_set else 1
            decay = max(0.40, 0.78 - (rep_idx - 1) * 0.04 + random.uniform(-0.02, 0.02))
            self._ingest_rep({
                "mean_velocity": round(decay, 2),
                "peak_velocity": round(decay * 1.6, 2),
                "duration_ms": random.randint(1100, 1600),
                "peak_excursion_m": round(random.uniform(0.42, 0.54), 2),
            })

        def _ingest_rep(self, payload: Dict[str, Any]):
            if not self.session.is_set_active:
                self.on_start_set()

            mean_v = float(payload.get("mean_velocity", 0.0))
            peak_v = float(payload.get("peak_velocity", 0.0))
            dur_ms = int(payload.get("duration_ms", 0))
            exc_m = float(payload.get("peak_excursion_m", 0.0))
            ts = payload.get("timestamp")

            rep = self.session.add_rep(
                mean_velocity=mean_v,
                peak_velocity=peak_v,
                duration_ms=dur_ms,
                peak_excursion_m=exc_m,
                timestamp=ts,
            )
            if rep is None:
                return

            # Update live displays
            self.rep_count_label.configure(text=str(self.session.active_set.rep_count))
            self.mean_vel_val.configure(text=f"{rep.mean_velocity:.2f} m/s")
            self.peak_vel_val.configure(text=f"{rep.peak_velocity:.2f} m/s")
            self.duration_val.configure(text=f"{rep.duration_ms / 1000.0:.2f} s")
            self.vel_loss_val.configure(text=f"{self.session.active_set.velocity_loss_pct:.1f} %")

            # Add to table
            time_display = rep.timestamp.split("T")[-1][:8] if "T" in rep.timestamp else rep.timestamp
            self.rep_tree.insert(
                "",
                tk.END,
                values=(
                    rep.rep_number,
                    f"{rep.mean_velocity:.3f}",
                    f"{rep.peak_velocity:.3f}",
                    f"{rep.duration_ms / 1000.0:.2f}",
                    f"{rep.peak_excursion_m:.2f}",
                    time_display,
                ),
            )

        def _handle_status_update(self, payload: Dict[str, Any]):
            state = payload.get("state", "disconnected")
            self._set_connection_badge(state)

            detector = payload.get("detector") or {}
            det_state = detector.get("state", "idle")
            turned_around = detector.get("turned_around", False)
            returned = detector.get("returned", False)
            excursion = detector.get("peak_excursion_m", 0.0)
            rejected = detector.get("rejected_cycles", 0)
            noise_floor = detector.get("noise_floor", 0.0)

            if det_state == "active":
                extra = f"  exc={excursion:.3f}m"
                if turned_around:
                    label = f"▲ CONCENTRIC / RETURN{extra}"
                    self.motion_pill.configure(text=label, fg=THEME["green"])
                else:
                    label = f"▼ ECCENTRIC / DESCENT{extra}"
                    self.motion_pill.configure(text=label, fg=THEME["blue"])
            else:
                rej_info = f"  rej={rejected}" if rejected else ""
                self.motion_pill.configure(text=f"● REST / IDLE{rej_info}", fg=THEME["text_muted"])

        def _append_log(self, text: str):
            """Append a line to the Sensor Log tab."""
            try:
                self.log_text.configure(state=tk.NORMAL)
                self.log_text.insert(tk.END, text + "\n")
                self.log_text.see(tk.END)
                # Keep only last 500 lines
                line_count = int(self.log_text.index("end-1c").split(".")[0])
                if line_count > 500:
                    self.log_text.delete("1.0", f"{line_count - 500}.0")
                self.log_text.configure(state=tk.DISABLED)
            except Exception:
                pass

        def on_export_csv(self):
            if not self.session.sets:
                messagebox.showinfo("Export CSV", "No completed sets to export yet.")
                return
            default_name = f"workout_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            filepath = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=default_name, filetypes=[("CSV Files", "*.csv")])
            if filepath:
                count = self.session.export_csv(Path(filepath))
                messagebox.showinfo("Export Successful", f"Exported {count} rep records to:\n{filepath}")

        def on_export_json(self):
            if not self.session.sets:
                messagebox.showinfo("Export JSON", "No completed sets to export yet.")
                return
            default_name = f"workout_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = filedialog.asksaveasfilename(defaultextension=".json", initialfile=default_name, filetypes=[("JSON Files", "*.json")])
            if filepath:
                self.session.export_json(Path(filepath))
                messagebox.showinfo("Export Successful", f"Exported {len(self.session.sets)} sets to:\n{filepath}")

        def _schedule_updates(self):
            # Process incoming events from background sensor runner
            try:
                while True:
                    event_type, data = self.event_queue.get_nowait()
                    if event_type == "rep":
                        self._ingest_rep(data)
                    elif event_type == "status":
                        self._handle_status_update(data)
                    elif event_type == "connection_state":
                        self._set_connection_badge(data)
                    elif event_type == "log":
                        self._append_log(str(data))
            except queue.Empty:
                pass

            # Update active set timer
            if self._set_timer_running and self.session.is_set_active:
                elapsed = max(0, int(time.monotonic() - self.session._active_start_monotonic))
                mins, secs = divmod(elapsed, 60)
                self.timer_label.configure(text=f"⏱  {mins:02d}:{secs:02d}")

            self.root.after(50, self._schedule_updates)

        def on_closing(self):
            self.sensor_mgr.stop()
            self.root.destroy()

    app = EdgeAthleteBarbellApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default=DEFAULT_BLE_ADDRESS, help="Preloaded BLE MAC address / UUID")
    parser.add_argument("--node-id", default=DEFAULT_NODE_ID, help="Node identifier")
    args = parser.parse_args()

    import tkinter as tk
    root = tk.Tk()
    app = create_gui_app(root=root)
    if args.address:
        app.addr_var.set(args.address)
    root.mainloop()


if __name__ == "__main__":
    main()
