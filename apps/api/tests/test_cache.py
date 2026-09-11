"""Unit tests for the cache-aside helper (``app.services.cache``).

The Redis client is injected explicitly (never the global one), covering:

- key layout ``cache:{name}`` / ``cache:{name}:{hash}``;
- cache hit: loader not invoked, cached JSON decoded;
- cache miss: loader invoked, value stored with the requested TTL;
- default TTL from settings when ``ttl=None``;
- Redis read/write failures degrade to the loader result (never raise);
- corrupt cache entries fall through to the loader;
- a cached payload is restored into the endpoint response model.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.metrics import CACHE_LOOKUPS_TOTAL, CACHE_WRITE_FAILURES_TOTAL
from app.services.cache import get_or_set, make_cache_key


class FakeRedis:
    """Minimal async Redis stand-in: dict-backed with programmable failure."""

    def __init__(self, store: dict | None = None, *, fail_get=False, fail_set=False):
        self.store = store if store is not None else {}
        self.fail_get = fail_get
        self.fail_set = fail_set
        self.setex_calls: list[tuple[str, int, str]] = []

    async def get(self, key: str):
        if self.fail_get:
            raise ConnectionError("redis down")
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str):
        if self.fail_set:
            raise ConnectionError("redis down")
        self.setex_calls.append((key, ttl, value))
        self.store[key] = value


class TestMakeCacheKey:
    def test_no_params_uses_name_only(self) -> None:
        assert make_cache_key("stats:homepage") == "cache:stats:homepage"

    def test_params_add_hash_segment(self) -> None:
        key = make_cache_key("releases:list", {"status": "active"})
        assert key.startswith("cache:releases:list:")
        assert len(key.split(":")[-1]) == 12

    def test_params_are_sorted_before_hashing(self) -> None:
        assert make_cache_key("x", {"a": 1, "b": 2}) == make_cache_key(
            "x", {"b": 2, "a": 1}
        )


class TestGetOrSet:
    async def test_cache_hit_skips_loader(self) -> None:
        redis = FakeRedis(store={"cache:demo": json.dumps({"ok": True})})
        loader = AsyncMock(side_effect=AssertionError("loader must not run"))

        value = await get_or_set("demo", ttl=60, loader=loader, redis=redis)

        assert value == {"ok": True}
        loader.assert_not_awaited()
        assert redis.setex_calls == []

    async def test_cache_miss_runs_loader_and_stores(self) -> None:
        redis = FakeRedis()
        loader = AsyncMock(return_value={"count": 42})

        value = await get_or_set("demo", ttl=60, loader=loader, redis=redis)

        assert value == {"count": 42}
        loader.assert_awaited_once()
        assert redis.setex_calls == [
            ("cache:demo", 60, json.dumps({"count": 42}))
        ]

    async def test_default_ttl_comes_from_settings(self, monkeypatch) -> None:
        from app.core.config import Settings

        monkeypatch.setattr(
            "app.core.config.get_settings",
            lambda: Settings(_env_file=None, app_env="dev", redis_cache_default_ttl=123),
        )
        redis = FakeRedis()
        loader = AsyncMock(return_value={"x": 1})

        await get_or_set("demo", ttl=None, loader=loader, redis=redis)

        assert redis.setex_calls[0][1] == 123

    async def test_redis_get_failure_falls_back_to_loader(self) -> None:
        redis = FakeRedis(fail_get=True)
        loader = AsyncMock(return_value={"fallback": True})

        value = await get_or_set("demo", ttl=60, loader=loader, redis=redis)

        assert value == {"fallback": True}
        loader.assert_awaited_once()

    async def test_redis_set_failure_still_returns_loader_value(self) -> None:
        redis = FakeRedis(fail_set=True)
        loader = AsyncMock(return_value={"fallback": True})

        value = await get_or_set("demo", ttl=60, loader=loader, redis=redis)

        assert value == {"fallback": True}

    async def test_cache_metrics_distinguish_hit_miss_and_degradation(self) -> None:
        hit = CACHE_LOOKUPS_TOTAL.labels(cache="metrics-hit", outcome="hit")
        miss = CACHE_LOOKUPS_TOTAL.labels(cache="metrics-miss", outcome="miss")
        read_error = CACHE_LOOKUPS_TOTAL.labels(
            cache="metrics-error", outcome="read_error"
        )
        write_error = CACHE_WRITE_FAILURES_TOTAL.labels(cache="metrics-error")
        before = tuple(metric._value.get() for metric in (hit, miss, read_error, write_error))

        await get_or_set(
            "metrics-hit",
            ttl=60,
            loader=AsyncMock(side_effect=AssertionError("must hit")),
            redis=FakeRedis(store={"cache:metrics-hit": "1"}),
        )
        await get_or_set(
            "metrics-miss",
            ttl=60,
            loader=AsyncMock(return_value=1),
            redis=FakeRedis(),
        )
        await get_or_set(
            "metrics-error",
            ttl=60,
            loader=AsyncMock(return_value=1),
            redis=FakeRedis(fail_get=True, fail_set=True),
        )

        after = tuple(metric._value.get() for metric in (hit, miss, read_error, write_error))
        assert after == tuple(value + 1 for value in before)

    async def test_corrupt_cache_entry_falls_through(self) -> None:
        redis = FakeRedis(store={"cache:demo": "{not-json"})
        loader = AsyncMock(return_value={"fresh": True})

        value = await get_or_set("demo", ttl=60, loader=loader, redis=redis)

        assert value == {"fresh": True}
        loader.assert_awaited_once()

    async def test_loader_datetime_value_is_serialised(self) -> None:
        redis = FakeRedis()
        loader = AsyncMock(
            return_value={"at": datetime(2026, 8, 1, tzinfo=timezone.utc)}  # noqa: UP017 — datetime.UTC unavailable in this env's conda shim
        )

        await get_or_set("demo", ttl=60, loader=loader, redis=redis)

        stored = json.loads(redis.setex_calls[0][2])
        assert stored["at"] == "2026-08-01T00:00:00+00:00"

    async def test_params_are_part_of_the_key(self) -> None:
        redis = FakeRedis()
        loader_a = AsyncMock(return_value={"status": "a"})
        loader_b = AsyncMock(return_value={"status": "b"})

        await get_or_set(
            "releases:list",
            ttl=60,
            params={"status": "active"},
            loader=loader_a,
            redis=redis,
        )
        await get_or_set(
            "releases:list",
            ttl=60,
            params={"status": "draft"},
            loader=loader_b,
            redis=redis,
        )

        assert len(redis.store) == 2
        assert all(k.startswith("cache:releases:list:") for k in redis.store)


@pytest.mark.asyncio
class TestEndpointCacheIntegration:
    """Endpoints restore cached JSON payloads into response models."""

    async def test_homepage_stats_cache_hit_skips_db(self, monkeypatch) -> None:
        from app.api.v1 import stats as stats_module
        from app.schemas.analytics import HomepageStats

        payload = {
            "total_variants": 10,
            "snp_count": 5,
            "indel_count": 3,
            "sv_count": 2,
            "gene_count": 100,
            "mutant_line_count": 10,
            "release_count": 1,
            "assembly_count": 2,
            "seed_accessions": 3,
            "last_release_date": "2026-08-01T00:00:00+00:00",
            "last_release_name": "v4.0",
        }
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=AssertionError("DB must not be queried on cache hit")
        )
        db.scalar = AsyncMock(
            side_effect=AssertionError("DB must not be queried on cache hit")
        )

        called: dict = {}

        async def _fake_get_or_set(name, ttl, loader, **kwargs):
            called["name"] = name
            called["ttl"] = ttl
            return payload

        monkeypatch.setattr(stats_module, "get_or_set", _fake_get_or_set)

        result = await stats_module.homepage_stats(db)

        assert isinstance(result, HomepageStats)
        assert result.total_variants == 10
        assert result.last_release_name == "v4.0"
        assert called["name"] == "stats:homepage"
        assert called["ttl"] is None  # default TTL

    async def test_list_releases_cache_hit_skips_db(self, monkeypatch) -> None:
        from app.api.v1 import releases as releases_module
        from app.schemas.content import ReleaseResponse

        payload = [
            {
                "id": "1",
                "version": "v4.0",
                "name": "Wm82 v4.0",
                "description": None,
                "variant_count": 10,
                "gene_count": 100,
                "mutant_line_count": 5,
                "status": "active",
                "published_at": "2026-08-01T00:00:00+00:00",
                "created_at": "2026-07-01T00:00:00+00:00",
                "updated_at": "2026-07-01T00:00:00+00:00",
            }
        ]
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=AssertionError("DB must not be queried on cache hit")
        )

        called: dict = {}

        async def _fake_get_or_set(name, ttl, loader, **kwargs):
            called["name"] = name
            called["params"] = kwargs.get("params")
            return payload

        monkeypatch.setattr(releases_module, "get_or_set", _fake_get_or_set)

        result = await releases_module.list_releases(db, status=None)

        assert isinstance(result, list)
        assert isinstance(result[0], ReleaseResponse)
        assert result[0].version == "v4.0"
        assert called["name"] == "releases:list"

    async def test_list_assemblies_cache_hit_skips_db(self, monkeypatch) -> None:
        from app.api.v1 import genes as genes_module
        from app.schemas.genomic import AssemblyResponse

        payload = [
            {
                "id": 1,
                "name": "Wm82.a4.v1",
                "species": "Glycine max",
                "version": "v4",
                "description": None,
                "is_default": True,
                "created_at": "2026-07-01T00:00:00+00:00",
                "updated_at": "2026-07-01T00:00:00+00:00",
            }
        ]
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=AssertionError("DB must not be queried on cache hit")
        )

        called: dict = {}

        async def _fake_get_or_set(name, ttl, loader, **kwargs):
            called["name"] = name
            called["ttl"] = ttl
            return payload

        monkeypatch.setattr(genes_module, "get_or_set", _fake_get_or_set)

        result = await genes_module.list_assemblies(db)

        assert isinstance(result, list)
        assert isinstance(result[0], AssemblyResponse)
        assert result[0].name == "Wm82.a4.v1"
        assert called["name"] == "genes:assemblies"
        assert called["ttl"] is None  # default TTL

    async def test_chromosome_density_cache_hit_skips_db(self, monkeypatch) -> None:
        from app.api.v1 import stats as stats_module
        from app.schemas.analytics import ChromosomeDensitySummary

        payload = [
            {
                "chromosome": "Gm01",
                "variant_count": 10,
                "snp_count": 8,
                "indel_count": 2,
                "length_bp": 55900000,
                "density_per_kb": 0.0002,
            }
        ]
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=AssertionError("DB must not be queried on cache hit")
        )

        called: dict = {}

        async def _fake_get_or_set(name, ttl, loader, **kwargs):
            called["name"] = name
            called["params"] = kwargs.get("params")
            return payload

        monkeypatch.setattr(stats_module, "get_or_set", _fake_get_or_set)

        result = await stats_module.chromosome_density_summary(
            db, release_id=None
        )

        assert isinstance(result, list)
        assert isinstance(result[0], ChromosomeDensitySummary)
        assert result[0].chromosome == "Gm01"
        assert called["name"] == "stats:chromosome-density"
        assert called["params"] == {"release_id": None}

    async def test_chromosome_density_cache_key_includes_release(self, monkeypatch) -> None:
        """Distinct ``release_id`` values must produce distinct cache keys."""
        from app.api.v1 import stats as stats_module

        seen: list[dict | None] = []

        async def _fake_get_or_set(name, ttl, loader, **kwargs):
            seen.append(kwargs.get("params"))
            return []

        monkeypatch.setattr(stats_module, "get_or_set", _fake_get_or_set)
        db = AsyncMock()

        await stats_module.chromosome_density_summary(db, release_id=None)
        await stats_module.chromosome_density_summary(db, release_id=7)

        assert seen == [{"release_id": None}, {"release_id": 7}]

    async def test_release_statistics_cache_hit_skips_db(self, monkeypatch) -> None:
        from app.api.v1 import stats as stats_module
        from app.schemas.analytics import ReleaseSummary

        payload = [
            {
                "release_version": "v4.0",
                "release_date": "2026-08-01",
                "variant_count": 10,
                "gene_count": 100,
                "mutant_line_count": 5,
            }
        ]
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=AssertionError("DB must not be queried on cache hit")
        )

        called: dict = {}

        async def _fake_get_or_set(name, ttl, loader, **kwargs):
            called["name"] = name
            called["params"] = kwargs.get("params")
            return payload

        monkeypatch.setattr(stats_module, "get_or_set", _fake_get_or_set)

        result = await stats_module.release_statistics(db, only_active=False)

        assert isinstance(result, list)
        assert isinstance(result[0], ReleaseSummary)
        assert result[0].release_version == "v4.0"
        assert called["name"] == "stats:releases"
        assert called["params"] == {"only_active": False}

    async def test_featured_news_cache_hit_skips_db(self, monkeypatch) -> None:
        from app.api.v1 import news as news_module
        from app.schemas.news import NewsFeaturedResponse

        payload = {"featured": [], "carousel": []}
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=AssertionError("DB must not be queried on cache hit")
        )

        called: dict = {}

        async def _fake_get_or_set(name, ttl, loader, **kwargs):
            called["name"] = name
            called["ttl"] = ttl
            return payload

        monkeypatch.setattr(news_module, "get_or_set", _fake_get_or_set)

        result = await news_module.featured_news(db)

        assert isinstance(result, NewsFeaturedResponse)
        assert result.featured == []
        assert called["name"] == "news:featured"
        assert called["ttl"] == news_module.FEATURED_CACHE_TTL_SECONDS == 60


class TestCachedDecorator:
    @pytest.mark.asyncio
    async def test_binds_selected_parameters_independent_of_call_style(self, monkeypatch) -> None:
        from app.core import cache_decorator

        called: dict[str, object] = {}

        async def fake_get_or_set(name, ttl, loader, *, params=None):
            called["name"] = name
            called["ttl"] = ttl
            called["params"] = params
            return await loader()

        monkeypatch.setattr(cache_decorator, "get_or_set", fake_get_or_set)

        @cache_decorator.cached("release:context", ttl=60, key_params=("release_id",))
        async def load(release_id: int, include_drafts: bool = False) -> dict[str, object]:
            return {"release_id": release_id, "include_drafts": include_drafts}

        result = await load(7, include_drafts=True)

        assert result == {"release_id": 7, "include_drafts": True}
        assert called == {
            "name": "release:context",
            "ttl": 60,
            "params": {"release_id": 7},
        }

    def test_rejects_unknown_cache_key_parameter(self) -> None:
        from app.core.cache_decorator import cached

        with pytest.raises(ValueError, match="not function parameters"):
            @cached("release:context", key_params=("missing",))
            async def load(release_id: int) -> dict[str, int]:
                return {"release_id": release_id}

    def test_rejects_blank_cache_name(self) -> None:
        from app.core.cache_decorator import cached

        with pytest.raises(ValueError, match="non-empty"):
            cached("   ")

    @pytest.mark.asyncio
    async def test_release_context_cache_hit_skips_database(self, monkeypatch) -> None:
        from app.core import cache_decorator
        from app.services import release_context

        called: dict[str, object] = {}

        async def fake_get_or_set(name, ttl, loader, *, params=None):
            called["name"] = name
            called["ttl"] = ttl
            called["params"] = params
            return {"release_id": 9, "assembly_id": 4, "assembly": "Wm82.v4"}

        monkeypatch.setattr(cache_decorator, "get_or_set", fake_get_or_set)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=AssertionError("database must not run on cache hit"))

        context = await release_context.resolve_release_context(db, requested_release_id=9)

        assert context.release_id == 9
        assert context.assembly_id == 4
        assert context.assembly == "Wm82.v4"
        assert called == {
            "name": "release-context",
            "ttl": 60,
            "params": {"request_id": 9},
        }

