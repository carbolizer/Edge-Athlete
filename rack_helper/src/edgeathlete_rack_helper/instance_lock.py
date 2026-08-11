"""Cross-process ownership without a listener or handoff channel."""

import errno
import os
from pathlib import Path
import stat
import sys


ERROR_CODE = "single_instance_active"
EXIT_CODE = 4


class AlreadyRunningError(RuntimeError):
    pass


def default_lock_path(*, platform=None, environ=None, home=None):
    platform = platform or sys.platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    if platform == "linux":
        state_home = environ.get("XDG_STATE_HOME")
        base = Path(state_home) if state_home and Path(state_home).is_absolute() else home / ".local" / "state"
    elif platform == "win32":
        local_app_data = environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data and Path(local_app_data).is_absolute() else home / "AppData" / "Local"
    else:
        raise RuntimeError("unsupported_platform")
    return base / "EdgeAthlete" / "RackHelperDevelopment" / "instance.lock"


class SingleInstanceLock:
    def __init__(self, path=None, *, platform=None):
        self.platform = platform or sys.platform
        self.path = Path(path) if path is not None else default_lock_path(platform=self.platform)
        self.fd = None

    def acquire(self):
        if self.fd is not None:
            return
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_RDWR
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOINHERIT", 0)
        if self.platform == "linux":
            flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags, 0o600)
            self._validate_file(fd)
            self._lock(fd)
        except Exception:
            if "fd" in locals():
                os.close(fd)
            raise
        self.fd = fd

    def _validate_file(self, fd):
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise RuntimeError("unsafe_instance_lock")
        if self.platform == "linux":
            if details.st_uid != os.getuid():
                raise RuntimeError("unsafe_instance_lock")
            os.fchmod(fd, 0o600)

    def _lock(self, fd):
        if self.platform == "linux":
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    raise AlreadyRunningError(ERROR_CODE) from None
                raise
            return
        if self.platform == "win32":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise AlreadyRunningError(ERROR_CODE) from None
                raise
            return
        raise RuntimeError("unsupported_platform")

    def release(self):
        if self.fd is None:
            return
        fd, self.fd = self.fd, None
        try:
            if self.platform == "linux":
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
            elif self.platform == "win32":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_args):
        self.release()
