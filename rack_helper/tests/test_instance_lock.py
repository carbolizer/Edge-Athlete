import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from edgeathlete_rack_helper.instance_lock import (
    AlreadyRunningError,
    SingleInstanceLock,
    default_lock_path,
)


class InstanceLockTests(unittest.TestCase):
    def test_platform_paths_are_user_local_and_development_labeled(self):
        home = Path("/users/tester")
        linux = default_lock_path(platform="linux", environ={}, home=home)
        windows = default_lock_path(platform="win32", environ={}, home=home)
        self.assertEqual(linux, home / ".local/state/EdgeAthlete/RackHelperDevelopment/instance.lock")
        self.assertEqual(windows, home / "AppData/Local/EdgeAthlete/RackHelperDevelopment/instance.lock")

    @unittest.skipUnless(sys.platform == "linux", "Linux flock test")
    def test_second_owner_is_rejected_then_lock_is_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instance.lock"
            first = SingleInstanceLock(path)
            second = SingleInstanceLock(path)
            first.acquire()
            with self.assertRaisesRegex(AlreadyRunningError, "^single_instance_active$"):
                second.acquire()
            first.release()
            second.acquire()
            second.release()

    @unittest.skipUnless(sys.platform == "linux", "Linux safe-file test")
    def test_symlink_cannot_be_used_as_the_lock_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.write_text("unchanged")
            path = Path(directory) / "instance.lock"
            path.symlink_to(target)
            with self.assertRaises(OSError):
                SingleInstanceLock(path).acquire()
            self.assertEqual(target.read_text(), "unchanged")

    @unittest.skipUnless(sys.platform == "linux", "Linux two-process flock test")
    def test_two_processes_cannot_own_the_same_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instance.lock"
            source = (
                "import sys,time; from edgeathlete_rack_helper.instance_lock import SingleInstanceLock; "
                "lock=SingleInstanceLock(sys.argv[1]); lock.acquire(); print('locked', flush=True); time.sleep(10)"
            )
            environment = dict(os.environ)
            source_path = str(Path(__file__).resolve().parents[1] / "src")
            environment["PYTHONPATH"] = os.pathsep.join(filter(None, (source_path, environment.get("PYTHONPATH"))))
            owner = subprocess.Popen(
                [sys.executable, "-c", source, str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            try:
                self.assertEqual(owner.stdout.readline().strip(), "locked")
                contender = subprocess.run(
                    [sys.executable, "-c", source, str(path)],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    env=environment,
                )
                self.assertNotEqual(contender.returncode, 0)
                self.assertIn("single_instance_active", contender.stderr)
            finally:
                owner.terminate()
                owner.wait(timeout=3)
                owner.stdout.close()
                owner.stderr.close()
