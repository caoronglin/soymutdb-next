"""W3 ablation experiments: search cache key/site isolation.

Scratch (not committed) ablation suite. Each test runs the REAL production
code path twice:

* 对照 (control): real ``SearchService.global_search`` + real
  ``app.services.cache.get_or_set`` + real ``make_cache_key`` against an
  in-memory FakeRedis.
* 消融 (ablation): exactly one protective factor is neutralised via
  ``monkeypatch`` and the observable behaviour is re-measured.

A test PASSES when it has demonstrated the expected flip (control isolated,
ablation collides) while asserting the control observation too.
"""

from __future__ import annotations

import inspect
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Response

from app.core.site_variant import SiteVariant
from app.schemas.search import SearchResultType
from app.services import cache as cache_mod
from app.services import search_service
from app.services.cache import make_cache_key
from app.services.release_context import ReleaseContext
from app.services.search_service import SearchService


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gets: list[str] = []

    async def get(self, key: str):
        self.gets.append(key)
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str):
        self.store[key] = value


def _service_with_real_cache(redis: FakeRedis, *, drop: tuple[str, ...] = ()):
    captured: list[dict[str, Any]] = []

    async def wrapper(name, ttl, loader, *, params=None):
        effective = {k: v for k, v in (params or {}).items() if k not in drop}
        captured.append(effective)
        return await cache_mod.get_or_set(name, ttl, loader, params=effective, redis=redis)

    return SearchService(), wrapper, captured


async def _run(
    redis: FakeRedis,
    context: ReleaseContext,
    variant: SiteVariant,
    *,
    drop: tuple[str, ...] = (),
    query: str = "Glyma",
):
    service, wrapper, captured = _service_with_real_cache(redis, drop=drop)
    loader_calls = {"n": 0}

    async def genes(*_a, **_k):
        loader_calls["n"] += 1
        return []

    with (
        patch("app.services.search_service.get_or_set", wrapper),
        patch(
            "app.services.search_service.resolve_release_context",
            AsyncMock(return_value=context),
        ),
        patch.object(service, "_search_genes", genes),
        patch.object(
            service, "_gene_assembly_distribution", AsyncMock(return_value={})
        ),
    ):
        await service.global_search(
            object(),
            query,
            types=[SearchResultType.GENE],
            assembly_id=context.assembly_id,
            site_variant=variant,
        )
    cache_awaited = bool(captured)
    keys = [make_cache_key("search:global", p) for p in captured] if captured else []
    return {
        "loader_calls": loader_calls["n"],
        "cache_awaited": cache_awaited,
        "store_size": len(redis.store),
        "params": captured,
        "keys": keys,
    }


def _emit(tag: str, **kw: Any) -> None:
    print(f"ABLATION-RESULT {tag} " + json.dumps(kw, default=str, sort_keys=True))


@pytest.mark.asyncio
async def test_key_scope_fields_present_in_real_params() -> None:
    """Every biological scope required by AGENTS.md is really in the key."""
    ctx = ReleaseContext(release_id=7, assembly_id=11)

    async def capture(**kwargs: Any):
        redis = FakeRedis()
        service, wrapper, captured = _service_with_real_cache(redis)
        with (
            patch("app.services.search_service.get_or_set", wrapper),
            patch(
                "app.services.search_service.resolve_release_context",
                AsyncMock(return_value=ctx),
            ),
            patch.object(service, "_search_genes", AsyncMock(return_value=[])),
            patch.object(service, "_search_mutant_lines", AsyncMock(return_value=[])),
            patch.object(
                service, "_gene_assembly_distribution", AsyncMock(return_value={})
            ),
        ):
            await service.global_search(
                object(),
                kwargs.pop("query", "Glyma"),
                assembly_id=ctx.assembly_id,
                site_variant=SiteVariant.EXTERNAL,
                **kwargs,
            )
        return make_cache_key("search:global", captured[-1]), captured[-1]

    base_key, base_params = await capture(types=[SearchResultType.GENE])
    variants = {
        "query": await capture(query="Gm01", types=[SearchResultType.GENE]),
        "limit": await capture(types=[SearchResultType.GENE], limit=50),
        "filters_types": await capture(
            types=[SearchResultType.GENE, SearchResultType.MUTANT_LINE]
        ),
        "pagination_cursor": await capture(
            types=[SearchResultType.GENE], cursor="0"
        ),
    }
    _emit(
        "key_scope.present",
        base_key=base_key,
        base_params=base_params,
        distinct={k: (v[0] != base_key) for k, v in variants.items()},
    )
    for name, (key, _params) in variants.items():
        assert key != base_key, f"{name} must change the real cache key"
    assert set(base_params) == {
        "query",
        "types",
        "cursor",
        "limit",
        "site_variant",
        "release_id",
        "assembly_id",
    }


# --------------------------------------------------------------------------- CTX-02
@pytest.mark.asyncio
async def test_ABL_ctx02_release_id_isolation(monkeypatch) -> None:
    a = ReleaseContext(release_id=7, assembly_id=11)
    b = ReleaseContext(release_id=8, assembly_id=11)

    control = FakeRedis()
    ra = await _run(control, a, SiteVariant.EXTERNAL)
    rb = await _run(control, b, SiteVariant.EXTERNAL)
    control_distinct = ra["keys"][0] != rb["keys"][0]
    _emit(
        "CTX-02.control",
        keys=[ra["keys"][0], rb["keys"][0]],
        store_size=control.store,
        second_loader_calls=rb["loader_calls"],
    )
    assert control_distinct and control.store.__len__() == 2 and rb["loader_calls"] == 1

    ablated = FakeRedis()
    ra2 = await _run(ablated, a, SiteVariant.EXTERNAL, drop=("release_id",))
    rb2 = await _run(ablated, b, SiteVariant.EXTERNAL, drop=("release_id",))
    _emit(
        "CTX-02.ablation_drop_release_id",
        keys=[ra2["keys"][0], rb2["keys"][0]],
        store_size=ablated.store,
        second_loader_calls=rb2["loader_calls"],
    )
    assert ra2["keys"][0] == rb2["keys"][0]
    assert len(ablated.store) == 1 and rb2["loader_calls"] == 0


# --------------------------------------------------------------------------- CTX-03
@pytest.mark.asyncio
async def test_ABL_ctx03_assembly_id_isolation() -> None:
    a = ReleaseContext(release_id=7, assembly_id=11)
    b = ReleaseContext(release_id=7, assembly_id=12)

    control = FakeRedis()
    ra = await _run(control, a, SiteVariant.EXTERNAL)
    rb = await _run(control, b, SiteVariant.EXTERNAL)
    _emit(
        "CTX-03.control",
        keys=[ra["keys"][0], rb["keys"][0]],
        store_size=control.store,
        second_loader_calls=rb["loader_calls"],
    )
    assert ra["keys"][0] != rb["keys"][0]
    assert len(control.store) == 2 and rb["loader_calls"] == 1

    ablated = FakeRedis()
    ra2 = await _run(ablated, a, SiteVariant.EXTERNAL, drop=("assembly_id",))
    rb2 = await _run(ablated, b, SiteVariant.EXTERNAL, drop=("assembly_id",))
    _emit(
        "CTX-03.ablation_drop_assembly_id",
        keys=[ra2["keys"][0], rb2["keys"][0]],
        store_size=ablated.store,
        second_loader_calls=rb2["loader_calls"],
    )
    assert ra2["keys"][0] == rb2["keys"][0]
    assert len(ablated.store) == 1 and rb2["loader_calls"] == 0


# --------------------------------------------------------------------------- CTX-01
class _AblatedSiteVariantNS:
    """Namespace where ``INTERNAL`` no longer equals the real enum member."""

    EXTERNAL = SiteVariant.EXTERNAL
    INTERNAL = object()


@pytest.mark.asyncio
async def test_ABL_ctx01_site_variant_isolation_and_internal_bypass() -> None:
    ctx = ReleaseContext(release_id=7, assembly_id=11)

    # control: internal never touches the shared cache at all.
    control = FakeRedis()
    ext = await _run(control, ctx, SiteVariant.EXTERNAL)
    internal = await _run(control, ctx, SiteVariant.INTERNAL)
    _emit(
        "CTX-01.control_internal_bypass",
        external_cache_awaited=ext["cache_awaited"],
        internal_cache_awaited=internal["cache_awaited"],
        store_size=control.store,
    )
    assert ext["cache_awaited"] is True
    assert internal["cache_awaited"] is False
    assert len(control.store) == 1

    # ablation A: remove the bypass (internal goes through shared get_or_set)
    # but keep site_variant in the params -> still two distinct entries.
    with patch.object(search_service, "SiteVariant", _AblatedSiteVariantNS):
        no_bypass = FakeRedis()
        ext2 = await _run(no_bypass, ctx, SiteVariant.EXTERNAL)
        internal2 = await _run(no_bypass, ctx, SiteVariant.INTERNAL)
    _emit(
        "CTX-01.ablation_remove_bypass_keep_site_variant",
        external_key=ext2["keys"][0],
        internal_key=internal2["keys"][0],
        store_size=no_bypass.store,
        internal_loader_calls=internal2["loader_calls"],
    )
    assert internal2["cache_awaited"] is True
    assert ext2["keys"][0] != internal2["keys"][0]
    assert len(no_bypass.store) == 2 and internal2["loader_calls"] == 1

    # ablation B: remove the bypass AND drop site_variant -> internal reuses
    # the external entry (CTX-01 collision).
    with patch.object(search_service, "SiteVariant", _AblatedSiteVariantNS):
        collide = FakeRedis()
        ext3 = await _run(collide, ctx, SiteVariant.EXTERNAL, drop=("site_variant",))
        internal3 = await _run(
            collide, ctx, SiteVariant.INTERNAL, drop=("site_variant",)
        )
    _emit(
        "CTX-01.ablation_remove_bypass_drop_site_variant",
        external_key=ext3["keys"][0],
        internal_key=internal3["keys"][0],
        store_size=collide.store,
        internal_loader_calls=internal3["loader_calls"],
    )
    assert ext3["keys"][0] == internal3["keys"][0]
    assert len(collide.store) == 1 and internal3["loader_calls"] == 0


# --------------------------------------------------------------- cache key material
@pytest.mark.asyncio
async def test_ABL_params_are_part_of_the_key() -> None:
    loaders = AsyncMock(side_effect=[{"a": 1}, {"b": 2}])

    control = FakeRedis()
    await cache_mod.get_or_set(
        "k", 60, AsyncMock(return_value={"a": 1}), params={"s": "a"}, redis=control
    )
    await cache_mod.get_or_set(
        "k", 60, AsyncMock(return_value={"b": 2}), params={"s": "b"}, redis=control
    )
    _emit("params_in_key.control", store_size=len(control.store), keys=list(control.store))

    ablated = FakeRedis()

    def _key_no_params(name, params=None):
        return f"cache:{name}"

    with patch.object(cache_mod, "make_cache_key", _key_no_params):
        await cache_mod.get_or_set("k", 60, loaders, params={"s": "a"}, redis=ablated)
        await cache_mod.get_or_set("k", 60, loaders, params={"s": "b"}, redis=ablated)
    _emit("params_in_key.ablation_drop_hash", store_size=len(ablated.store))
    assert len(control.store) == 2
    assert len(ablated.store) == 1


def test_ABL_params_are_sorted_before_hashing() -> None:
    assert make_cache_key("x", {"a": 1, "b": 2}) == make_cache_key("x", {"b": 2, "a": 1})

    class _NoSortJson:
        def dumps(self, obj, **kw):
            kw.pop("sort_keys", None)
            return json.dumps(obj, **kw)

        def loads(self, *a, **k):
            return json.loads(*a, **k)

    with patch.object(cache_mod, "json", _NoSortJson()):
        _emit(
            "sorted_params.ablation_no_sort",
            forward=make_cache_key("x", {"a": 1, "b": 2}),
            reverse=make_cache_key("x", {"b": 2, "a": 1}),
        )
        assert make_cache_key("x", {"a": 1, "b": 2}) != make_cache_key(
            "x", {"b": 2, "a": 1}
        )


def test_ABL_rejects_unknown_cache_key_parameter(monkeypatch) -> None:
    from app.core import cache_decorator

    async def load(release_id: int) -> dict[str, int]:
        return {"release_id": release_id}

    with pytest.raises(ValueError, match="not function parameters"):
        cache_decorator.cached("release:context", key_params=("missing",))(load)

    real_sig = inspect.signature(load)

    class _PatchedSig:
        def __init__(self, real):
            params = dict(real.parameters)
            params["missing"] = inspect.Parameter(
                "missing", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None
            )
            self.parameters = params
            self._real = real

        def bind(self, *a, **k):
            return self._real.bind(*a, **k)

    monkeypatch.setattr(cache_decorator.inspect, "signature", lambda _f: _PatchedSig(real_sig))
    decorated = cache_decorator.cached("release:context", key_params=("missing",))(load)
    _emit("unknown_key_param.ablation_guard_removed", decorated=decorated.__name__)
    assert decorated is not None


# ------------------------------------------------------------ legacy federated key
def test_GAP_legacy_federated_searchcache_key_ignores_biological_scope() -> None:
    """Was: the federated key only covered (query, sources). OPT-03 closed it."""
    from app.search.cache import SearchCache

    params = list(inspect.signature(SearchCache.make_key).parameters)
    key = SearchCache.make_key("G1", ("ncbi", "uniprot"))
    other = SearchCache.make_key("G1", ("uniprot", "ncbi"))
    scoped = SearchCache.make_key(
        "G1", ("ncbi", "uniprot"), site_variant="external", release_id=7
    )
    _emit("legacy_federated_key", params=params, key=key, sorted_sources_same=key == other)
    assert params == [
        "query",
        "sources",
        "site_variant",
        "release_id",
        "assembly_id",
        "filters",
    ]
    # An unscoped call keeps the old shape; a scoped one forks the key.
    assert "release" not in key and "assembly" not in key
    assert key == other  # sources are sorted
    assert scoped != key


# ------------------------------------------------------------ Cache-Control header
@pytest.mark.asyncio
async def test_ABL_internal_search_private_no_store_header() -> None:
    from app.api.v1 import search as search_api

    db = AsyncMock()
    db.add = lambda *_a, **_k: None
    fake_result = type("FakeResult", (), {"total_count": 0})()

    async def _call(response: Response) -> Response:
        with (
            patch(
                "app.api.v1.search.resolve_release_context",
                AsyncMock(return_value=type("C", (), {"release_id": 7})()),
            ),
            patch("app.api.v1.search.AuditLog", autospec=True),
            patch(
                "app.services.search_service.SearchService.internal_search",
                AsyncMock(return_value=fake_result),
            ),
        ):
            await search_api.internal_search(
                response=response, db=db, current_user=object(), q="SMTEST0001", limit=20
            )
        return response

    control = await _call(Response())
    _emit(
        "cache_control.control",
        header=control.headers.get("Cache-Control"),
        vary=control.headers.get("Vary"),
    )
    assert control.headers.get("Cache-Control") == "private, no-store"

    class _MuteHeaders(dict):
        def __setitem__(self, key, value):  # neutralise the endpoint's write
            return None

    muted = type("MuteResponse", (), {})()
    muted.headers = _MuteHeaders()
    ablated = await _call(muted)
    _emit("cache_control.ablation_mute_write", header=ablated.headers.get("Cache-Control"))
    assert ablated.headers.get("Cache-Control") is None
