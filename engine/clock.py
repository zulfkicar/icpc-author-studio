"""Injectable clock and deterministic failpoint scheduler.

The engine never calls ``datetime.now`` directly for durable records.  Tests
can therefore advance time without sleeping, and absolute delegation expiry
survives restarts because the value is stored in SQLite as UTC text.
"""
from __future__ import annotations

import datetime as _dt
import threading


class CrashInjected(RuntimeError):
    """A deterministic failpoint fired; used to simulate process death."""

    def __init__(self, name: str):
        super().__init__(f"injected crash at {name}")
        self.name = name


class Clock:
    def now(self) -> _dt.datetime:
        return _dt.datetime.now(_dt.timezone.utc)

    def now_iso(self) -> str:
        return self.now().astimezone(_dt.timezone.utc).isoformat()

    def monotonic(self) -> float:
        import time

        return time.monotonic()


class ManualClock(Clock):
    """A clock whose UTC time only moves when a test moves it."""

    def __init__(self, start: _dt.datetime | None = None, monotonic: float = 1000.0):
        self._now = start or _dt.datetime(2026, 11, 14, 9, 0, 0, tzinfo=_dt.timezone.utc)
        self._mono = float(monotonic)
        self._lock = threading.Lock()

    def now(self) -> _dt.datetime:
        with self._lock:
            return self._now

    def monotonic(self) -> float:
        with self._lock:
            return self._mono

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now = self._now + _dt.timedelta(seconds=float(seconds))
            self._mono += float(seconds)

    def set(self, value: _dt.datetime) -> None:
        with self._lock:
            delta = (value - self._now).total_seconds()
            self._now = value
            self._mono += delta


class Failpoints:
    """Named injection points.  ``hit`` is a no-op until armed."""

    def __init__(self) -> None:
        self._armed: set[str] = set()
        self._hits: list[str] = []
        self._lock = threading.Lock()

    def arm(self, *names: str) -> None:
        with self._lock:
            self._armed.update(names)

    def disarm(self, *names: str) -> None:
        with self._lock:
            for name in names or tuple(self._armed):
                self._armed.discard(name)

    def clear(self) -> None:
        with self._lock:
            self._armed.clear()
            self._hits.clear()

    def armed(self) -> set[str]:
        with self._lock:
            return set(self._armed)

    def hits(self) -> list[str]:
        with self._lock:
            return list(self._hits)

    def hit(self, name: str) -> None:
        """Raise :class:`CrashInjected` exactly once per armed name."""
        with self._lock:
            if name not in self._armed:
                return
            self._armed.discard(name)
            self._hits.append(name)
        raise CrashInjected(name)
