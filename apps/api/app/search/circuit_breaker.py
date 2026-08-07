"""Redis-backed circuit breaker.

States:
    CLOSED      — requests flow normally; failures are counted.
    OPEN        — failures exceeded the threshold; fast-fail for recovery_timeout.
    HALF_OPEN   — recovery_timeout elapsed; allow one probe request.

State is stored in Redis so it survives across worker processes / restarts
and is shared across a horizontally scaled API fleet.
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(Exception):
    """Raised when a call is rejected because the circuit is open."""


class CircuitBreaker:
    """Per-source circuit breaker with Redis-backed state.

    Keys used (prefixed with ``cb:{name}:``):
        state         — "closed" | "open" | "half_open"
        failures      — integer counter (reset on success)
        opened_at     — unix timestamp (float) when circuit tripped open
    """

    def __init__(
        self,
        redis: Redis,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        key_prefix: str = "cb",
    ) -> None:
        self._redis = redis
        self._name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._prefix = f"{key_prefix}:{name}"

    # ------------------------------------------------------------------ keys
    @property
    def state_key(self) -> str:
        return f"{self._prefix}:state"

    @property
    def failures_key(self) -> str:
        return f"{self._prefix}:failures"

    @property
    def opened_at_key(self) -> str:
        return f"{self._prefix}:opened_at"

    # ----------------------------------------------------------------- state
    async def get_state(self) -> CircuitState:
        """Return the current circuit state, handling TTL expiry of OPEN."""
        try:
            raw = await self._redis.get(self.state_key)
        except Exception:  # pragma: no cover - Redis connectivity blip
            logger.warning("circuit_breaker.redis_error", source=self._name)
            return CircuitState.CLOSED

        if raw is None:
            return CircuitState.CLOSED

        state = CircuitState(raw)
        if state is CircuitState.OPEN:
            opened_raw = await self._redis.get(self.opened_at_key)
            if opened_raw is not None:
                try:
                    opened_at = float(opened_raw)
                except ValueError:
                    opened_at = 0.0
                if time.monotonic() - opened_at >= self._recovery_timeout:
                    # Transition to HALF_OPEN so the next caller can probe.
                    await self._redis.set(self.state_key, CircuitState.HALF_OPEN.value)
                    return CircuitState.HALF_OPEN
        return state

    async def allow_request(self) -> bool:
        """Return True if a request may proceed; False means short-circuit."""
        state = await self.get_state()
        if state is CircuitState.CLOSED:
            return True
        if state is CircuitState.HALF_OPEN:
            # Allow exactly one probe.  We leave state as HALF_OPEN; the caller
            # will call record_success / record_failure to finalize.
            return True
        # OPEN
        return False

    async def record_success(self) -> None:
        """Reset failure count after a successful call."""
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                await pipe.delete(self.failures_key)
                await pipe.set(self.state_key, CircuitState.CLOSED.value)
                await pipe.delete(self.opened_at_key)
                await pipe.execute()
        except Exception:  # pragma: no cover
            logger.warning("circuit_breaker.redis_error", source=self._name)

    async def record_failure(self) -> None:
        """Record a failure and trip the circuit if threshold is exceeded."""
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(self.failures_key)
                pipe.get(self.failures_key)
                results = await pipe.execute()
            failures = int(results[1] or 0)
            if failures >= self._failure_threshold:
                async with self._redis.pipeline(transaction=True) as pipe:
                    pipe.set(self.state_key, CircuitState.OPEN.value)
                    pipe.set(self.opened_at_key, str(time.monotonic()))
                    # Auto-expire state after recovery_timeout plus a small
                    # buffer so Redis cleans up even if we never re-check.
                    pipe.expire(self.state_key, int(self._recovery_timeout) + 5)
                    pipe.expire(self.opened_at_key, int(self._recovery_timeout) + 5)
                    await pipe.execute()
                logger.warning(
                    "circuit_breaker.tripped",
                    source=self._name,
                    failures=failures,
                    recovery_s=self._recovery_timeout,
                )
        except Exception:  # pragma: no cover
            logger.warning("circuit_breaker.redis_error", source=self._name)

    async def reset(self) -> None:
        """Manually reset the circuit to CLOSED."""
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                await pipe.delete(self.state_key, self.failures_key, self.opened_at_key)
                await pipe.execute()
        except Exception:  # pragma: no cover
            logger.warning("circuit_breaker.redis_error", source=self._name)

    # ---------------------------------------------------------------- context
    async def __aenter__(self) -> "CircuitBreaker":
        if not await self.allow_request():
            raise CircuitBreakerOpen(f"circuit open for {self._name}")
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any) -> bool:
        if exc is None:
            await self.record_success()
        else:
            # Only count "real" failures (transport / 5xx); skip cancellations.
            if not isinstance(exc, asyncio.CancelledError):
                await self.record_failure()
        return False  # do not suppress
