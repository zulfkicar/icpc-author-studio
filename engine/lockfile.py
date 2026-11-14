"""Local OS ownership lock.

One controller per workspace/run.  On Windows ``msvcrt.locking`` provides the
exclusion; on POSIX ``fcntl.flock``.  Loopback-only, single-author scope.
"""
from __future__ import annotations

import os
import pathlib
import sys


class FileLock:
    def __init__(self, path: str | pathlib.Path):
        self.path = str(path)
        self._handle = None
        self._held = False

    def acquire(self) -> bool:
        if self._held:
            return True
        pathlib.Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                if os.path.getsize(self.path) == 0:
                    self._handle.write(b"0")
                    self._handle.flush()
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._held = True
            return True
        except (OSError, PermissionError):
            try:
                self._handle.close()
            except Exception:  # noqa: BLE001
                pass
            self._handle = None
            return False

    def release(self) -> None:
        if not self._held or self._handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                try:
                    self._handle.seek(0)
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    # Closing the descriptor below releases the region anyway.
                    pass
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            try:
                self._handle.close()
            except Exception:  # noqa: BLE001
                pass
            self._handle = None
            self._held = False

    @property
    def held(self) -> bool:
        return self._held

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("lock is held by another owner")
        return self

    def __exit__(self, *exc):
        self.release()
        return False
