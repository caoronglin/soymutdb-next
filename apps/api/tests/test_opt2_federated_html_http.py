"""OPT2-01: the ``format=html`` federated branch must traverse the real HTTP stack.

The pre-OPT2 regression called ``global_search`` directly and patched the
endpoint's own dependencies, so nothing proved that a real ASGI request
negotiates HTML, reaches the renderer, and returns a fragment rather than
JSON.  These tests boot the real FastAPI app on ``httpx.ASGITransport`` with a
real PostgreSQL session and only replace genuinely external services:

* Redis is an in-process fake (no ``redis-server`` on this host);
* the federated providers' outbound HTTP is a deterministic static adapter,
  while the real aggregator, cache and renderer all run untouched.

The negative half seeds an ``internal-only`` mutant line and asserts its
private persistence key never appears in the external HTML fragment.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.api.v1 import search as search_api
from app.core.exceptions import ServiceUnavailableError
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.variant import MutantLine
from app.search import SearchSource, SourceResult, SourceStatus
from app.search import aggregator as aggregator_module
from app.search.models import SearchHit


class _FakeRedis:
    """In-process stand-in for Redis (this host has no redis-server)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gets: list[str] = []
        self.sets: list[str] = []

    async def get(self, key: str):
        self.gets.append(key)
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.sets.append(key)
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


class _StaticAdapter:
    """Provider adapter with canned hits: no outbound network."""

    def __init__(self, source: SearchSource, hits: list[SearchHit]) -> None:
        self.source = source
        self.timeout = 0.5
        self._hits = hits

    async def search(self, query: str, limit: int, client: object) -> SourceResult:
        return SourceResult(
            source=self.source,
            status=SourceStatus.OK if self._hits else SourceStatus.EMPTY,
            hits=self._hits[:limit],
        )


_ADAPTER_NAMES = {
    SearchSource.NCBI: "NCBIAdapter",
    SearchSource.UNIPROT: "UniProtAdapter",
    SearchSource.ENSEMBL: "EnsemblAdapter",
    SearchSource.EBI: "EBIAdapter",
}


def _install_providers(monkeypatch, hits: list[SearchHit]) -> None:
    """Replace only the outbound provider adapters.

    The real ``ExternalSearchAggregator``, ``SearchCache`` and
    ``render_search_html`` all still run; the route constructs them itself.
    """
    for source, name in _ADAPTER_NAMES.items():
        monkeypatch.setattr(
            aggregator_module,
            name,
            lambda redis, _source=source: _StaticAdapter(_source, hits),
        )
    monkeypatch.setattr(search_api, "get_redis", lambda: _FakeRedis())


async def _seed_internal_only_mutant(db_session) -> MutantLine:
    """Seed a published release plus a private mutant invisible to the external site."""
    release = Release(
        version="opt2-html-release",
        name="opt2 html release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(release)
    await db_session.flush()
    db_session.add(ActiveRelease(id=1, release_id=release.id))
    mutant = MutantLine(
        id=987650,
        name="ghost-internal-only-html",
        public_id=None,
        is_public=False,
        release_id=release.id,
    )
    db_session.add(mutant)
    await db_session.flush()
    return mutant


@pytest.mark.asyncio
async def test_format_html_traverses_real_http_and_renders_html(
    client, db_session, monkeypatch
) -> None:
    await _seed_internal_only_mutant(db_session)
    _install_providers(
        monkeypatch,
        [
            SearchHit(
                source=SearchSource.NCBI,
                title="external gene hit",
                url="https://www.ncbi.nlm.nih.gov/gene/1",
                id="EXT-NCBI-1",
                snippet="an external snippet",
            )
        ],
    )

    response = await client.get(
        "/api/v1/search",
        params={"query": "ghost", "format": "html", "sources": "ncbi"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"

    body = response.text
    # Rendered fragment, not a JSON document.
    assert body.lstrip().startswith("<div")
    assert not body.lstrip().startswith("{")
    assert '"sources"' not in body
    # The real renderer actually produced the external hit.
    assert 'class="ext-search"' in body
    assert "EXT-NCBI-1" in body
    assert "external gene hit" in body
    # Negative: the internal-only record's private persistence key is absent.
    assert "987650" not in body


@pytest.mark.asyncio
async def test_accept_header_also_negotiates_html_over_real_http(
    client, db_session, monkeypatch
) -> None:
    _install_providers(
        monkeypatch,
        [
            SearchHit(
                source=SearchSource.NCBI,
                title="accept-negotiated hit",
                url="https://www.ncbi.nlm.nih.gov/gene/2",
                id="EXT-NCBI-2",
            )
        ],
    )

    response = await client.get(
        "/api/v1/search",
        params={"query": "accept", "sources": "ncbi"},
        headers={"Accept": "text/html"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "EXT-NCBI-2" in response.text


@pytest.mark.asyncio
async def test_html_fragment_is_cached_under_an_html_suffixed_key(
    client, db_session, monkeypatch
) -> None:
    await _seed_internal_only_mutant(db_session)
    redis = _FakeRedis()
    _install_providers(
        monkeypatch,
        [
            SearchHit(
                source=SearchSource.NCBI,
                title="cached hit",
                url="https://www.ncbi.nlm.nih.gov/gene/3",
                id="EXT-NCBI-3",
            )
        ],
    )
    monkeypatch.setattr(search_api, "get_redis", lambda: redis)

    first = await client.get(
        "/api/v1/search",
        params={"query": "ghost", "format": "html", "sources": "ncbi"},
    )
    second = await client.get(
        "/api/v1/search",
        params={"query": "ghost", "format": "html", "sources": "ncbi"},
    )

    assert first.status_code == second.status_code == 200
    assert first.text == second.text
    html_keys = [key for key in redis.sets if key.endswith(":html")]
    assert len(html_keys) == 1
    assert html_keys[0].startswith("search:external:")


@pytest.mark.asyncio
async def test_html_route_survives_without_a_published_release(
    client, db_session, monkeypatch
) -> None:
    """No active release still serves a fragment (best-effort federated scope)."""
    _install_providers(
        monkeypatch,
        [
            SearchHit(
                source=SearchSource.NCBI,
                title="no release hit",
                url="https://www.ncbi.nlm.nih.gov/gene/4",
                id="EXT-NCBI-4",
            )
        ],
    )
    # Force the active-release lookup to miss for this request only.
    monkeypatch.setattr(
        search_api,
        "resolve_release_context",
        AsyncMock(side_effect=ServiceUnavailableError("no active release")),
    )

    response = await client.get(
        "/api/v1/search",
        params={"query": "ghost", "format": "html", "sources": "ncbi"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "EXT-NCBI-4" in response.text
