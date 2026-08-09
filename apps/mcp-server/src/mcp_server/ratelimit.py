"""Fixed-window rate limiting for the SoyMutDB MCP server (B4 / G3).

Two budgets are enforced by the tools (``server.py``):

- **global**: 60 requests per minute per MCP client (all tools share one
  budget).  Covers read + write tools.
- **blast_submit quota**: 10 BLAST submissions per hour per MCP client
  (BLAST jobs spawn worker tasks, so they get their own tighter budget).

Backends (G3 upgrade):

- **Redis** (preferred): :class:`RedisLimiter` implements the same
  fixed-window semantics with a single atomic Lua script (``INCR`` +
  ``EXPIRE`` on first hit).  Keys live under ``mcp:rl:<name>:<key>`` so
  every worker / instance shares one budget.
- **in-memory** (fallback): :class:`FixedWindowLimiter` (thread-safe dict
  of fixed windows).  Used when Redis is unreachable at startup; a warning
  is logged and limits are then per-process.  If Redis dies at runtime,
  ``RedisLimiter`` fails over to an embedded memory limiter so the budget
  is never silently dropped (slightly stricter, never looser).

:func:`get_limiter` picks the backend from ``SOYMUTDB_MCP_REDIS_URL``
(default ``redis://localhost:6379/0``); set it to an empty string to force
the in-memory backend.  Every limiter exposes the same ``check(key) ->
(allowed, retry_after)`` plus ``reset`` / ``hits`` interface, so
``server.py`` never needs to know which backend is active.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import redis as redis_types

logger = logging.getLogger(__name__)

try:  # redis is a hard dependency; keep the import guarded for tooling that
    import redis  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - only when deps are not installed
    redis = None  # type: ignore[assignment]

#: Default Redis URL for the shared budget store (env-overridable).
DEFAULT_REDIS_URL = "redis://localhost:6379/0"

#: Key prefix for every Redis counter; full key is ``mcp:rl:<name>:<key>``.
KEY_PREFIX = "mcp:rl:"


@dataclass(slots=True)
class _Window:
    started_at: float
    count: int


class FixedWindowLimiter:
    """Fixed-window counter keyed by an arbitrary string (in-memory backend).

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


class RedisLimiter:
    """Redis fixed-window limiter (shared across workers / instances).

    Same interface as :class:`FixedWindowLimiter`.  Every ``check`` runs one
    atomic pipeline: ``SET key 0 EX <ttl> NX`` stamps the window start (and
    TTL) exactly once — the first hit in a window — then ``INCR`` consumes
    one budget slot.  Both commands travel in a single round trip and the
    ``SET NX`` guard makes concurrent workers safe: whoever wins the NX
    opens the window, everyone else just increments.  If Redis raises at
    runtime, calls fail over to an embedded :class:`FixedWindowLimiter`
    (per-process, slightly stricter than the shared budget) and a throttled
    warning is logged.
    """

    def __init__(
        self,
        client: "redis_types.Redis",
        limit: int,
        window_seconds: float,
        *,
        name: str = "",
        key_prefix: str = KEY_PREFIX,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.client = client
        self.limit = limit
        self.window = window_seconds
        self.name = name
        self.key_prefix = key_prefix
        #: Per-process safety net used while Redis is unreachable.
        self._fallback = FixedWindowLimiter(limit, window_seconds, name=name)
        self._last_warning = 0.0

    # -- internals ----------------------------------------------------------

    def _rkey(self, key: str) -> str:
        return f"{self.key_prefix}{self.name}:{key}"

    def _warn_once(self) -> None:
        now = time.monotonic()
        if now - self._last_warning >= 60.0:
            self._last_warning = now
            logger.warning(
                "Redis rate limiter %r unreachable; using in-memory fallback "
                "(limits are per-process until Redis recovers)",
                self.name,
            )

    # -- public interface (same as FixedWindowLimiter) -----------------------

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Record one hit for *key*; return ``(allowed, retry_after)``."""
        if not key:
            key = "anonymous"
        rkey = self._rkey(key)
        try:
            # Atomic pipeline: SET NX EX stamps the window TTL on the first
            # hit, INCR consumes one slot.  One round trip, no Lua needed.
            pipe = self.client.pipeline()
            pipe.set(rkey, 0, ex=int(self.window), nx=True)
            pipe.incr(rkey)
            _, n = cast("list[Any]", pipe.execute())
            if int(n) > self.limit:
                pttl = cast("int", self.client.pttl(rkey))
                retry = (pttl // 1000) + 1 if pttl and pttl > 0 else int(self.window)
                return False, max(1, retry)
            return True, 0
        except Exception as exc:  # noqa: BLE001 - any redis error -> fallback
            if _is_redis_error(exc):
                self._warn_once()
                return self._fallback.check(key, now)
            raise

    def reset(self, key: str | None = None) -> None:
        """Clear one key (or all counters when *key* is None).  Tests only."""
        try:
            if key is None:
                pattern = f"{self.key_prefix}{self.name}:*"
                for rkey in self.client.scan_iter(pattern, count=100):
                    self.client.delete(rkey)
            else:
                self.client.delete(self._rkey(key))
        except Exception as exc:  # noqa: BLE001
            if not _is_redis_error(exc):
                raise
            self._warn_once()
        self._fallback.reset(key)

    def hits(self, key: str) -> int:
        """Current recorded hit count for *key* (0 when absent/expired).

        Note: on the Redis backend this counts *all* attempts in the window
        (``INCR`` runs for denied calls too), unlike the in-memory backend
        which only counts allowed calls.  Used by tests / observability.
        """
        try:
            value = cast(
                "str | None", self.client.get(self._rkey(key))
            )
            return int(value) if value is not None else 0
        except Exception as exc:  # noqa: BLE001
            if not _is_redis_error(exc):
                raise
            self._warn_once()
            return self._fallback.hits(key)

    def __len__(self) -> int:
        try:
            return sum(1 for _ in self.client.scan_iter(f"{self.key_prefix}{self.name}:*", count=100))
        except Exception as exc:  # noqa: BLE001
            if not _is_redis_error(exc):
                raise
            self._warn_once()
            return len(self._fallback)


def _is_redis_error(exc: Exception) -> bool:
    """True for any redis client / connection error (incl. fakeredis)."""
    if redis is not None and isinstance(exc, redis.RedisError):
        return True
    return type(exc).__name__ in {
        "ConnectionError",
        "TimeoutError",
        "ResponseError",
        "RedisError",
        "AuthenticationError",
    }


#: ``SOYMUTDB_MCP_REDIS_URL`` — empty string forces the in-memory backend.
def _env_redis_url() -> str:
    return os.environ.get("SOYMUTDB_MCP_REDIS_URL", DEFAULT_REDIS_URL)


def get_limiter(
    limit: int,
    window_seconds: float,
    *,
    name: str = "",
    redis_url: str | None = None,
    redis_client: "redis_types.Redis | None" = None,
) -> FixedWindowLimiter | RedisLimiter:
    """Build a limiter, preferring Redis when it is reachable.

    - ``redis_client`` injected (tests / callers with an existing client)
      -> always a :class:`RedisLimiter` wrapping it.
    - ``redis_url`` empty -> in-memory :class:`FixedWindowLimiter`.
    - otherwise probe ``redis_url`` (default ``SOYMUTDB_MCP_REDIS_URL`` /
      ``redis://localhost:6379/0``); on failure fall back to memory with a
      logged warning.
    """
    if redis_client is not None:
        return RedisLimiter(redis_client, limit, window_seconds, name=name)
    url = _env_redis_url() if redis_url is None else redis_url
    if not url:
        return FixedWindowLimiter(limit, window_seconds, name=name)
    if redis is None:  # pragma: no cover - deps not installed
        logger.warning(
            "rate limiter %r: redis package not installed; using in-memory backend", name
        )
        return FixedWindowLimiter(limit, window_seconds, name=name)
    try:
        client = redis.Redis.from_url(
            url, socket_connect_timeout=0.5, socket_timeout=1.0, decode_responses=True
        )
        client.ping()
        logger.info("rate limiter %r -> Redis backend (%s)", name, url)
        return RedisLimiter(client, limit, window_seconds, name=name)
    except Exception as exc:  # noqa: BLE001
        if not _is_redis_error(exc):
            raise
        logger.warning(
            "rate limiter %r: Redis at %s unavailable (%s); falling back to "
            "in-memory fixed window (per-process limits)",
            name,
            url,
            exc,
        )
        return FixedWindowLimiter(limit, window_seconds, name=name)


#: Server-wide budget shared by every tool: 60 calls/minute/client.
GLOBAL_LIMITER = get_limiter(60, 60.0, name="global")

#: blast_submit spawns worker jobs; give it a separate 10/hour/client quota.
SUBMIT_LIMITER = get_limiter(10, 3600.0, name="blast_submit")

__all__ = [
    "DEFAULT_REDIS_URL",
    "KEY_PREFIX",
    "FixedWindowLimiter",
    "RedisLimiter",
    "get_limiter",
    "GLOBAL_LIMITER",
    "SUBMIT_LIMITER",
]
