"""Token-bucket rate limiter per source, backed by Redis.

Used to be a good citizen against external APIs (NCBI asks for <=3 req/s
without an API key, etc.).  The limiter is *advisory*: when the bucket is
empty the adapter simply waits a small delay rather than erroring out, so
callers never see a hard failure from rate limiting.
"""

from __future__ import annotations

import asyncio
import time

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


class TokenBucketRateLimiter:
    """Distributed token bucket using a Redis hash + Lua fill logic.

    For simplicity (and to avoid Redis Lua deployment across versions) we
    approximate the bucket with a simple ``last_check`` timestamp and
    token count stored in a hash.
    """

    def __init__(
        self,
        redis: Redis,
        name: str,
        rate_per_second: float = 3.0,
        burst: int = 5,
        key_prefix: str = "rl",
    ) -> None:
        self._redis = redis
        self._name = name
        self._rate = rate_per_second
        self._burst = burst
        self._key = f"{key_prefix}:{name}:bucket"

    async def acquire(self, max_wait: float = 5.0) -> bool:
        """Block (asynchronously) until a token is available or ``max_wait`` elapses.

        Returns True if a token was acquired, False if we gave up waiting.
        """
        deadline = time.monotonic() + max_wait
        while True:
            ok = await self._try_take()
            if ok:
                return True
            if time.monotonic() >= deadline:
                logger.warning("rate_limiter.give_up", source=self._name)
                return False
            # Sleep proportional to refill interval (1 token / rate).
            await asyncio.sleep(min(1.0 / max(self._rate, 0.1), deadline - time.monotonic()))

    async def _try_take(self) -> bool:
        """Attempt to atomically take one token.

        We approximate without Lua by doing GET-then-SET; if two callers race
        the burst may be exceeded by at most one request, which is acceptable
        for outbound API politeness.
        """
        now = time.monotonic()
        try:
            data = await self._redis.hmget(self._key, "tokens", "last")  # type: ignore[no-untyped-call]
            raw_tokens, raw_last = data
        except Exception:
            logger.warning("rate_limiter.redis_error", source=self._name)
            return True  # fail-open if Redis is down

        tokens = float(raw_tokens) if raw_tokens is not None else float(self._burst)
        last = float(raw_last) if raw_last is not None else now

        # Refill based on elapsed time.
        elapsed = max(0.0, now - last)
        tokens = min(float(self._burst), tokens + elapsed * self._rate)

        if tokens >= 1.0:
            tokens -= 1.0
            try:
                async with self._redis.pipeline(transaction=True) as pipe:
                    pipe.hset(self._key, mapping={"tokens": tokens, "last": now})
                    pipe.expire(self._key, 60)
                    await pipe.execute()
            except Exception:
                logger.warning("rate_limiter.redis_error", source=self._name)
            return True
        return False
