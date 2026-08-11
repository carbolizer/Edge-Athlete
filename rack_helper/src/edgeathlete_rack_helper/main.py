"""Rack Helper process entry point."""

import logging
import sys
import threading

from .instance_lock import AlreadyRunningError, ERROR_CODE, EXIT_CODE, SingleInstanceLock
from .protocol import ProtocolArgumentError, parse_arguments


def main(argv=None, *, instance_lock=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        mode = parse_arguments(arguments)
    except ProtocolArgumentError:
        logging.getLogger("edgeathlete_rack_helper").warning("protocol_result=rejected")
        return 2
    ownership = instance_lock or SingleInstanceLock()
    try:
        ownership.acquire()
    except AlreadyRunningError:
        logging.getLogger("edgeathlete_rack_helper").warning("startup_result=%s", ERROR_CODE)
        _show_single_instance_error()
        return EXIT_CODE
    try:
        import keyring
        import tkinter as tk

        from .http_client import JsonTransport
        from .keyring_store import KeychainUnavailable, KeyringStore
        from .runtime import RackHelperRuntime
        from .ui import RackHelperWindow

        root = tk.Tk()
        try:
            store = KeyringStore(keyring)
            runtime = RackHelperRuntime(store, JsonTransport())
        except KeychainUnavailable:
            runtime = _BlockedRuntime()
        except (RuntimeError, ValueError):
            root.destroy()
            return 3
        RackHelperWindow(root, runtime)
        threading.Thread(target=runtime.start, args=(mode,), daemon=True).start()
        root.mainloop()
        return 0
    finally:
        ownership.release()


def _show_single_instance_error():
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Edge Athlete Rack Helper - Development Only",
            "Rack Helper is already running. Close it before starting another instance.\n\n"
            f"Error: {ERROR_CODE}",
            parent=root,
        )
        root.destroy()
    except ImportError:
        pass
    except tk.TclError:
        pass


class _BlockedRuntime:
    def __init__(self):
        self.on_state = lambda state, detail=None: None

    def start(self, _mode):
        self.on_state("keychain_unavailable", None)

    def pair(self, _code):
        self.on_state("keychain_unavailable", None)
        return False

    def poll_and_activate(self):
        self.on_state("keychain_unavailable", None)
        return False

    def quit(self):
        self.on_state("disconnected", None)


if __name__ == "__main__":
    raise SystemExit(main())
