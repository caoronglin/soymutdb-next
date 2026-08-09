"""In-memory fixed-window rate limiter for the SoyMutDB MCP server (B4).

Two budgets are enforced by the tools (``server.py``):

- **global**: 60 requests per minute per MCP client (all tools share one
  budget).  Covers read + write tools.
- **blast_submit quota**: 10 BLAST submissions per hour per MCP client
  (BLAST jobs spawn worker tasks, so they get their own tighter budget).

Windows are *fixed* (aligned to the first hit in each window), stored in a
plain dict with wall/monotonic timestamps, and pruned lazily on access.  A
single-process deployment is assumed; when the server is scaled out, swap
this class for a Redis-backed implementation with the same ``check``
interface (see ``README.md`` / G3 gate).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class _Window:
    started_at: float
    count: int


class FixedWindowLimiter:
    """Fixed-window counter keyed by an arbitrary string.

    ``check(key)`` records one hit for *key* and returns
    ``(allowed: bool, retry_after: int)``; when the limit is already
    exhausted ``retry_after`` is the number of seconds until the window
    resets (never < 1).  Thread-safe (server is async, but guards against
    concurrent task interleaving).
    """

    def __init__(self, limit: int, window_seconds: float, *, name: str = "") -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.limit = limit
        self.window = window_seconds
        self.name = name
        self._lock = threading.Lock()
        self._counters: dict[str, _Window] = {}

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Record one hit for *key*; return ``(allowed, retry_after)``."""
        if not key:
            key = "anonymous"
        now = time.monotonic() if now is None else now
        with self._lock:
            window = self._counters.get(key)
            if window is None or now - window.started_at >= self.window:
                window = _Window(started_at=now, count=0)
                self._counters[key] = window
            if window.count >= self.limit:
                retry_after = max(
                    1, int(self.window - (now - window.started_at)) + 1
                )
                return False, retry_after
            window.count += 1
            return True, 0

    def reset(self, key: str | None = None) -> None:
        """Clear one key (or all counters when *key* is None).  Tests only."""
        with self._lock:
            if key is None:
                self._counters.clear()
            else:
                self._counters.pop(key, None)

    def hits(self, key: str) -> int:
        """Current recorded hit count for *key* (0 when absent/expired)."""
        with self._lock:
            window = self._counters.get(key)
            return window.count if window is not None else 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._counters)


#: Server-wide budget shared by every tool: 60 calls/minute/client.
GLOBAL_LIMITER = FixedWindowLimiter(limit=60, window_seconds=60.0, name="global")

#: blast_submit spawns worker jobs; give it a separate 10/hour/client quota.
SUBMIT_LIMITER = FixedWindowLimiter(
    limit=10, window_seconds=3600.0, name="blast_submit"
)

__all__ = ["FixedWindowLimiter", "GLOBAL_LIMITER", "SUBMIT_LIMITER"]
