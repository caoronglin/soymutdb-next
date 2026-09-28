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


def _canonical_scope_value(value: object) -> str | None:
    """Normalise one scope value so equal logical scopes share one key.

    ``None`` stays ``None``, an enum collapses to its ``.value``, and every
    other value becomes its string form, so ``7``/``"7"`` and
    ``SiteVariant.EXTERNAL``/``"external"`` can never split a scope in two.
    """
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _canonical_filters(filters: Mapping[str, Any] | None) -> dict[str, Any]:
    """Recursively string-normalise filter values before hashing."""
    if not filters:
        return {}
    return {str(key): _canonical_json_value(value) for key, value in filters.items()}


def _canonical_json_value(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    return _canonical_scope_value(value)


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
        site_variant: object | None = None,
        release_id: int | str | None = None,
        assembly_id: int | str | None = None,
        filters: Mapping[str, Any] | None = None,
    ) -> str:
        """Deterministic, scope-bound key.

        Two shapes, selected by whether any biological scope is present:

        * fully unscoped (every scope keyword omitted or ``None``, no filters):
          ``search:{sha256(query|sorted(sources))}`` -- byte-identical to the
          pre-scope key, so existing callers/cached entries keep working.
        * scoped: ``search:{site_variant}:{digest}`` -- the digest covers
          query, sources, release, assembly and filters, while the explicit
          site variant stays a separate colon segment so a private internal
          entry can never be read from the shared external namespace.

        Scope values are string-normalised and ``None``/omitted hash
        identically, so one logical scope can never split across two keys; a
        concrete value never collides with a missing one. The ``search:``
        prefix and sha256 hex format are unchanged.
        """
        ordered_sources = tuple(sorted(sources))
        scope = {
            "release_id": _canonical_scope_value(release_id),
            "assembly_id": _canonical_scope_value(assembly_id),
            "filters": _canonical_filters(filters),
        }
        variant = _canonical_scope_value(site_variant)
        if variant is None and all(not value for value in scope.values()):
            h = hashlib.sha256()
            h.update(query.encode("utf-8"))
            h.update(b"|")
            for source in ordered_sources:
                h.update(source.encode("utf-8"))
                h.update(b",")
            return f"{KEY_NAMESPACE}:{h.hexdigest()}"

        payload = {"query": query, "sources": list(ordered_sources), **scope}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"{KEY_NAMESPACE}:{variant or '_'}:{digest}"

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
