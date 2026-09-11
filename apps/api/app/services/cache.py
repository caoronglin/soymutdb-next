"""Lightweight Redis cache-aside helper for read-hot database queries.

Usage::

    from ..services.cache import get_or_set, make_cache_key

    payload = await get_or_set(
        "stats:homepage",
        ttl=settings.redis_cache_default_ttl,
        loader=lambda: _load_homepage_stats(db),   # returns JSON-serialisable data
    )

Contract:
- Key layout ``cache:{name}[:{hash}]`` — ``name`` is a short endpoint/service
  label, the optional ``hash`` segment covers cache-relevant parameters.
- Values are JSON strings (``datetime``/``UUID``/pydantic models auto-encode).
- Redis failures (connection, timeout, decode) are swallowed and logged at
  debug level: the caller transparently falls back to a direct query.  The
  cache is therefore a best-effort accelerator, never a correctness
  dependency.
- **Anti-penetration**: whatever ``loader()`` returns is cached, including
  empty structures (``[]`` / ``{}``) that loaders return when their data
  source is temporarily unavailable or a table is empty.  Once memoised, the
  empty result short-circuits repeated requests for the whole TTL instead of
  letting them all penetrate to the source.  Call sites that expect frequent
  content churn (e.g. news featured) pass a shorter ``ttl``.
- Only read paths are cached — write paths must not go through here.

NOTE: external reference (geekblogs) was unavailable; this follows the
standard cache-aside + TTL + graceful-degradation pattern for Redis-backed
read caching.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from structlog import get_logger

from ..core.database import get_redis
from ..core.metrics import CACHE_LOOKUPS_TOTAL, CACHE_WRITE_FAILURES_TOTAL

logger = get_logger(__name__)

_CACHE_PREFIX = "cache"
_HASH_LENGTH = 12


def make_cache_key(name: str, params: Mapping[str, Any] | None = None) -> str:
    """Build a cache key: ``cache:{name}`` or ``cache:{name}:{hash}``.

    ``params`` are the cache-relevant request parameters (sorted + JSON
    encoded before hashing) so distinct parameter sets never collide.
    """
    if not params:
        return f"{_CACHE_PREFIX}:{name}"
    digest = hashlib.sha256(
        json.dumps(params, sort_keys=True, default=_json_default).encode("utf-8")
    ).hexdigest()[:_HASH_LENGTH]
    return f"{_CACHE_PREFIX}:{name}:{digest}"


def _json_default(value: Any) -> Any:
    """Encode non-JSON-native values (datetimes, UUIDs, pydantic models)."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


async def get_or_set[T](
    name: str,
    ttl: int | None,
    loader: Callable[[], Awaitable[T]],
    *,
    params: Mapping[str, Any] | None = None,
    redis: Any = None,
) -> T:
    """Return ``loader()``, memoising it in Redis for ``ttl`` seconds.

    ``loader`` must return a JSON-serialisable value (dict / list / scalar;
    datetimes and pydantic models are auto-encoded).  When ``ttl`` is None
    the configured ``redis_cache_default_ttl`` is used.  ``redis`` is
    injectable for tests; it defaults to the global client.
    """
    from ..core.config import get_settings

    client = redis if redis is not None else get_redis()
    key = make_cache_key(name, params)
    effective_ttl = ttl if ttl is not None else get_settings().redis_cache_default_ttl

    # 1. Cache lookup. The label is a stable call-site name, never a full key.
    outcome = "miss"
    try:
        cached = await client.get(key)
        if cached is not None:
            try:
                value = json.loads(cached)
            except (json.JSONDecodeError, TypeError):
                outcome = "decode_error"
                logger.debug("cache_decode_failed", key=key)
            else:
                CACHE_LOOKUPS_TOTAL.labels(cache=name, outcome="hit").inc()
                return value
    except Exception:
        outcome = "read_error"
        logger.debug("cache_read_failed_fallback_to_db", key=key)
    CACHE_LOOKUPS_TOTAL.labels(cache=name, outcome=outcome).inc()

    # 2. Cache miss (or Redis unavailable) — load from the source of truth.
    value = await loader()

    # 3. Best-effort write-through; never fail the request on cache errors.
    try:
        await client.setex(key, effective_ttl, json.dumps(value, default=_json_default))
    except Exception:
        CACHE_WRITE_FAILURES_TOTAL.labels(cache=name).inc()
        logger.debug("cache_write_failed", key=key)

    return value


async def delete_prefix(prefix: str, *, redis: Any = None) -> int:
    """Delete cache entries whose logical name starts with the prefix.

    Redis SCAN keeps invalidation incremental and non-blocking; UNLINK moves
    deletion off the Redis event loop when supported. Cache failures are
    deliberately swallowed because invalidation is an optimization, not a
    source-of-truth operation.
    """
    if not prefix:
        return 0
    client = redis if redis is not None else get_redis()
    pattern = f"{_CACHE_PREFIX}:{prefix}*"
    deleted = 0
    try:
        batch: list[str] = []
        async for key in client.scan_iter(match=pattern, count=100):
            batch.append(key)
            if len(batch) < 100:
                continue
            deleted += await _delete_keys(client, batch)
            batch.clear()
        if batch:
            deleted += await _delete_keys(client, batch)
    except Exception:
        logger.debug("cache_prefix_delete_failed", prefix=prefix)
    return deleted


async def _delete_keys(client: Any, keys: list[str]) -> int:
    """Delete one bounded batch, falling back for older Redis servers."""
    unlink = getattr(client, "unlink", None)
    try:
        if unlink is not None:
            return int(await unlink(*keys))
        return int(await client.delete(*keys))
    except Exception:
        return int(await client.delete(*keys))


__all__ = ["delete_prefix", "get_or_set", "make_cache_key"]
