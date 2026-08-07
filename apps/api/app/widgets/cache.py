"""Redis caching layer for rendered widget HTML fragments.

Cache key pattern: ``widget:{name}:{sha256(params_json)}``

Cache stampede protection uses a short-lived Redis SET NX lock.  If a
request cannot acquire the lock it waits briefly for the holder to populate
the cache; if the lock holder fails the request falls through to render.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Lock timeout in seconds – must be long enough for a slow render but short
# enough that a crashed holder doesn't block everyone forever.
_LOCK_TTL = 10
_LOCK_POLL_INTERVAL = 0.05
_LOCK_POLL_TIMEOUT = 8


def _cache_key(name: str, params: dict[str, Any]) -> str:
    """Compute the Redis cache key for a widget+params combination."""
    params_json = json.dumps(params, sort_keys=True, default=str)
    digest = hashlib.sha256(params_json.encode("utf-8")).hexdigest()
    return f"widget:{name}:{digest}"


def _lock_key(name: str, params: dict[str, Any]) -> str:
    return _cache_key(name, params) + ":lock"


class WidgetCache:
    """Async Redis-backed cache for rendered widget HTML."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    async def get(self, name: str, params: dict[str, Any]) -> str | None:
        """Return cached HTML or ``None`` on miss."""
        key = _cache_key(name, params)
        try:
            value = await self._redis.get(key)
            return value
        except Exception as exc:
            logger.warning("widget_cache_get_error", widget=name, error=str(exc))
            return None

    async def set(self, name: str, params: dict[str, Any], html: str, ttl: int) -> None:
        """Store rendered HTML in cache with given TTL."""
        key = _cache_key(name, params)
        try:
            await self._redis.setex(key, ttl, html)
        except Exception as exc:
            logger.warning("widget_cache_set_error", widget=name, error=str(exc))

    async def invalidate(self, name: str) -> int:
        """Invalidate all cached variants of a widget.

        Uses SCAN to find matching keys because we don't track individual
        param digests.  Returns the number of keys deleted.
        """
        pattern = f"widget:{name}:*"
        deleted = 0
        try:
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    # Don't delete lock keys as part of invalidation
                    html_keys = [k for k in keys if not k.endswith(":lock")]
                    if html_keys:
                        deleted += await self._redis.delete(*html_keys)
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning("widget_cache_invalidate_error", widget=name, error=str(exc))
        return deleted

    async def acquire_lock(self, name: str, params: dict[str, Any]) -> bool:
        """Attempt to acquire the stampede-prevention lock.

        Returns ``True`` if the caller is the lock holder and should render
        the widget.  Returns ``False`` if another request holds the lock.
        """
        key = _lock_key(name, params)
        try:
            acquired = await self._redis.set(key, "1", nx=True, ex=_LOCK_TTL)
            return bool(acquired)
        except Exception:
            # If Redis is failing, let the request through rather than blocking.
            return True

    async def release_lock(self, name: str, params: dict[str, Any]) -> None:
        """Release the stampede-prevention lock."""
        key = _lock_key(name, params)
        try:
            await self._redis.delete(key)
        except Exception:
            pass

    async def wait_for_cache(self, name: str, params: dict[str, Any]) -> str | None:
        """Poll waiting for another request to populate the cache.

        Returns the cached value if it appears within the poll timeout, else
        ``None`` (caller should render).
        """
        deadline = asyncio.get_running_loop().time() + _LOCK_POLL_TIMEOUT
        while asyncio.get_running_loop().time() < deadline:
            value = await self.get(name, params)
            if value is not None:
                return value
            await asyncio.sleep(_LOCK_POLL_INTERVAL)
        return None

    async def get_or_render(
        self,
        name: str,
        params: dict[str, Any],
        ttl: int,
        render_fn,
    ) -> str:
        """High-level cache-aside with stampede protection.

        *render_fn* is an async callable ``() -> str`` that produces the
        HTML on a cache miss.  The rendered HTML is NOT sanitized here;
        callers must sanitize before caching or within *render_fn*.
        """
        # 1. Fast path: cache hit
        cached = await self.get(name, params)
        if cached is not None:
            return cached

        # 2. Try to acquire the stampede lock
        lock_held = await self.acquire_lock(name, params)
        if not lock_held:
            # Another request is rendering – wait for it
            waited = await self.wait_for_cache(name, params)
            if waited is not None:
                return waited
            # Wait timed out – fall through and render ourselves
            lock_held = await self.acquire_lock(name, params)

        try:
            # Double-check after acquiring lock
            cached = await self.get(name, params)
            if cached is not None:
                return cached

            html = await render_fn()
            if ttl > 0:
                await self.set(name, params, html, ttl)
            return html
        finally:
            if lock_held:
                await self.release_lock(name, params)
