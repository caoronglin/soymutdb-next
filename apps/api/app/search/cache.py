"""Redis cache for external search results (5-minute TTL)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

DEFAULT_TTL_SECONDS = 300  # 5 minutes


class SearchCache:
    """Thin wrapper around Redis for caching rendered/serialized search output."""

    def __init__(self, redis: Redis, ttl_seconds: int = DEFAULT_TTL_SECONDS, prefix: str = "search") -> None:
        self._redis = redis
        self._ttl = ttl_seconds
        self._prefix = prefix

    @staticmethod
    def make_key(query: str, sources: tuple[str, ...]) -> str:
        """Deterministic cache key: search:{sha256(query+sorted(sources))}."""
        h = hashlib.sha256()
        h.update(query.encode("utf-8"))
        h.update(b"|")
        for s in sorted(sources):
            h.update(s.encode("utf-8"))
            h.update(b",")
        return f"search:{h.hexdigest()}"

    async def get(self, key: str) -> str | None:
        try:
            return await self._redis.get(key)
        except Exception:  # pragma: no cover
            logger.warning("search_cache.redis_error", op="get", key=key)
            return None

    async def get_json(self, key: str) -> Any | None:
        raw = await self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        ttl = ttl if ttl is not None else self._ttl
        try:
            await self._redis.set(key, value, ex=ttl)
        except Exception:  # pragma: no cover
            logger.warning("search_cache.redis_error", op="set", key=key)

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self.set(key, json.dumps(value, default=str), ttl=ttl)

    async def invalidate(self, key: str) -> None:
        try:
            await self._redis.delete(key)
        except Exception:  # pragma: no cover
            logger.warning("search_cache.redis_error", op="delete", key=key)
