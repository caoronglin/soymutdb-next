"""Redis cache for external search results (5-minute TTL)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

DEFAULT_TTL_SECONDS = 300  # 5 minutes

#: Fixed, code-owned key namespace. Every biological search key is suffixed
#: with the explicit site variant so an internal (private) response can never
#: be read from, or written into, the shared external namespace even if a
#: future caller forgets to bypass the cache.
KEY_NAMESPACE = "search"


class SearchCache:
    """Thin wrapper around Redis for caching rendered/serialized search output."""

    def __init__(
        self,
        redis: Redis,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        prefix: str = KEY_NAMESPACE,
    ) -> None:
        self._redis = redis
        self._ttl = ttl_seconds
        self._prefix = prefix

    @staticmethod
    def make_key(
        query: str,
        sources: tuple[str, ...],
        *,
        site_variant: str,
        release_id: int | None = None,
        assembly_id: int | None = None,
        filters: Mapping[str, Any] | None = None,
    ) -> str:
        """Deterministic, scope-bound key: search:{site_variant}:{digest}.

        The digest covers the full biological scope the repository requires
        for search results: site variant, release, assembly, query, and any
        active filters.  site_variant is required and keyword-only so a
        caller cannot silently fall back to an unscoped external key; an
        omitted release/assembly is hashed as null and therefore never
        collides with a concrete value.
        """
        variant = str(getattr(site_variant, "value", site_variant))
        payload = {
            "query": query,
            "sources": sorted(sources),
            "release_id": release_id,
            "assembly_id": assembly_id,
            "filters": dict(filters) if filters else {},
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        return f"{KEY_NAMESPACE}:{variant}:{digest}"

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
