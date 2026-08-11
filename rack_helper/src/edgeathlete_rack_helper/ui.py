"""Tkinter surface for inert pairing and development status."""

import queue
import threading
import tkinter as tk
from tkinter import ttk


DISPLAY = {
    "inert": "Inert. Open this helper from the Rack page to launch.",
    "unpaired": "Unpaired. Enter the code displayed by the Rack.",
    "pairing_code_invalid": "Enter the exact eight-character pairing code.",
    "confirmation_required": "Compare these words with the Rack, then ask a coach to confirm.",
    "awaiting_coach_confirmation": "Waiting for coach confirmation.",
    "paired_inert": "Paired. Return to the Rack and select Launch Helper.",
    "no_sensor": "Development status: no_sensor. Sensor support is not enabled.",
    "cloud_unavailable": "Cloud unavailable. No launch or sensor action was taken.",
    "pairing_rejected": "Pairing was rejected or expired. Request a new code.",
    "authentication_blocked": "Credential rejected. Pair this helper again.",
    "keychain_unavailable": "Approved OS keychain unavailable. Helper is blocked.",
    "disconnected": "Disconnected.",
}


class RackHelperWindow:
    def __init__(self, root, runtime):
        self.root = root
        self.runtime = runtime
        self.events = queue.Queue()
        self.confirmation_polling = False
        runtime.on_state = lambda state, detail=None: self.events.put((state, detail))
        root.title("Edge Athlete Rack Helper - Development Only")
        root.resizable(False, False)
        frame = ttk.Frame(root, padding=24)
        frame.grid()
        ttk.Label(frame, text="Rack Helper", font=("TkDefaultFont", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text="UNSIGNED DEVELOPMENT BUILD").grid(row=1, column=0, sticky="w", pady=(0, 16))
        self.status = tk.StringVar(value=DISPLAY["inert"])
        ttk.Label(frame, textvariable=self.status, wraplength=430).grid(row=2, column=0, sticky="w", pady=(0, 16))
        self.code = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=self.code, width=16)
        entry.grid(row=3, column=0, sticky="w")
        entry.bind("<Return>", lambda _event: self.pair())
        ttk.Button(frame, text="Pair with code", command=self.pair).grid(row=4, column=0, sticky="w", pady=(8, 16))
        self.phrase = tk.StringVar()
        ttk.Label(frame, textvariable=self.phrase, wraplength=430, font=("TkDefaultFont", 12, "bold")).grid(row=5, column=0, sticky="w")
        ttk.Button(frame, text="Check coach confirmation", command=self.check_confirmation).grid(row=6, column=0, sticky="w", pady=(8, 20))
        ttk.Button(frame, text="Disconnect and quit", command=self.close).grid(row=7, column=0, sticky="w")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(50, self.drain_events)

    def pair(self):
        code = self.code.get()
        self.code.set("")
        threading.Thread(target=self.runtime.pair, args=(code,), daemon=True).start()

    def check_confirmation(self):
        threading.Thread(target=self.runtime.poll_and_activate, daemon=True).start()

    def drain_events(self):
        while True:
            try:
                state, detail = self.events.get_nowait()
            except queue.Empty:
                break
            self.status.set(DISPLAY.get(state, "Helper is inert."))
            if state == "confirmation_required" and detail:
                self.phrase.set(detail)
                self.confirmation_polling = True
                self.root.after(2000, self.poll_confirmation)
            elif state == "awaiting_coach_confirmation" and self.confirmation_polling:
                self.root.after(2000, self.poll_confirmation)
            elif state in {"paired_inert", "no_sensor", "pairing_rejected"}:
                self.phrase.set("")
                self.confirmation_polling = False
        self.root.after(50, self.drain_events)

    def close(self):
        self.confirmation_polling = False
        self.runtime.quit()
        self.root.destroy()

    def poll_confirmation(self):
        if not self.confirmation_polling:
            return
        threading.Thread(target=self.runtime.poll_and_activate, daemon=True).start()
