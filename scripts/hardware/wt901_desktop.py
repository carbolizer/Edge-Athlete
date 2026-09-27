#!/usr/bin/env python3
"""Create an isolated BLE environment, or run the agent on macOS/Windows/Linux."""

import argparse
from pathlib import Path
import subprocess
import sys
import venv


HERE = Path(__file__).resolve().parent
ENVIRONMENT = HERE.parent.parent / "venv" / "wt901"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "run", "gui"))
    parser.add_argument("agent_args", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.error("Python 3.10 or newer is required; use Python 3.12 if installing Python now")
    python = ENVIRONMENT / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if options.command == "setup":
        if options.agent_args:
            parser.error("setup takes no agent arguments")
        venv.EnvBuilder(with_pip=True).create(ENVIRONMENT)
        return subprocess.call([
            str(python), "-m", "pip", "install", "-r", str(HERE / "requirements-ble.txt"),
        ])
    if not python.is_file():
        parser.error("BLE environment is missing; run this launcher with setup first")
    agent_args = options.agent_args
    if agent_args[:1] == ["--"]:
        agent_args = agent_args[1:]
    target_script = HERE / ("wt901_gui.py" if options.command == "gui" else "wt901_rack_agent.py")
    try:
        return subprocess.call([str(python), str(target_script), *agent_args])
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
