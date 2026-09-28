"""OPT2-02: release scope must be explicit, not best-effort-shared.

The pre-OPT2 concern: when release resolution fell back to the active release,
a request that *named* a different (unpublished) release silently shared the
active release's cache entry and response.  These tests decide the question
with a real ASGI request over a real PostgreSQL session and concrete evidence:
the exact cache keys handed to Redis and the exact response bodies.

Verdict pinned here: ASSUMED LEAK, NOW FIXED -- an explicit ``release_id``
query parameter is the request's release scope, published or not, for both
the federated (HTML) cache key and the DB-backed JSON response.  The reverse
invariant (distinct published releases never share a key) is also asserted.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.v1 import search as search_api
from app.api.v1.search import _external_html_cache_key
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.genomic import Assembly, Chromosome, Gene
from app.search import SearchSource, SourceResult, SourceStatus
from app.search import aggregator as aggregator_module
from app.search.cache import SearchCache
from app.search.models import SearchHit


class _FakeRedis:
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
    def __init__(self, source: SearchSource) -> None:
        self.source = source
        self.timeout = 0.5

    async def search(self, query: str, limit: int, client: object) -> SourceResult:
        return SourceResult(
            source=self.source,
            status=SourceStatus.OK,
            hits=[
                SearchHit(
                    source=self.source,
                    title=f"external {query}",
                    url=f"https://example.test/{query}",
                    id=f"EXT-{query}",
                )
            ],
        )


_ADAPTER_NAMES = {
    SearchSource.NCBI: "NCBIAdapter",
    SearchSource.UNIPROT: "UniProtAdapter",
    SearchSource.ENSEMBL: "EnsemblAdapter",
    SearchSource.EBI: "EBIAdapter",
}


def _install_providers(monkeypatch, redis: _FakeRedis) -> None:
    """Replace only the outbound provider adapters; keep the real aggregator."""
    for source, name in _ADAPTER_NAMES.items():
        monkeypatch.setattr(
            aggregator_module, name, lambda redis_client, _source=source: _StaticAdapter(_source)
        )
    monkeypatch.setattr(search_api, "get_redis", lambda: redis)


def _spy_make_key(monkeypatch) -> list[dict]:
    calls: list[dict] = []
    real = SearchCache.make_key

    def spy(query, sources, **scope):
        calls.append({"query": query, "sources": tuple(sources), **scope})
        return real(query, sources, **scope)

    monkeypatch.setattr(SearchCache, "make_key", staticmethod(spy))
    return calls


async def _seed_release_with_gene(
    db_session, *, version: str, accession: str, published: bool
) -> Release:
    release = Release(
        version=version,
        name=version,
        status=ReleaseStatus.PUBLISHED if published else ReleaseStatus.DRAFT,
    )
    db_session.add(release)
    await db_session.flush()
    assembly = Assembly(
        name=f"opt2-{version}", species="Glycine max", version="v5", release_id=release.id
    )
    db_session.add(assembly)
    await db_session.flush()
    chromosome = Chromosome(
        assembly_id=assembly.id, name="Gm01", length=100_000, order=1
    )
    db_session.add(chromosome)
    await db_session.flush()
    db_session.add(
        Gene(
            accession=accession,
            assembly_id=assembly.id,
            chromosome_id=chromosome.id,
            name=accession,
            biotype="protein_coding",
            start=1,
            end=10,
            strand="+",
        )
    )
    await db_session.flush()
    return release


# ------------------------------------------------------------------ direct key
def test_external_html_key_forks_on_each_explicit_release() -> None:
    base = _external_html_cache_key(
        "q", [SearchSource.NCBI], release_id=101, assembly_id=None, limit_per_source=10
    )
    other = _external_html_cache_key(
        "q", [SearchSource.NCBI], release_id=102, assembly_id=None, limit_per_source=10
    )
    missing = _external_html_cache_key(
        "q", [SearchSource.NCBI], release_id=None, assembly_id=None, limit_per_source=10
    )
    assert base.startswith("search:external:")
    assert len({base, other, missing}) == 3


# ------------------------------------------------------ HTTP: DB-backed JSON
@pytest.mark.asyncio
async def test_explicit_unpublished_release_scopes_the_json_response(
    client, db_session, monkeypatch
) -> None:
    published = await _seed_release_with_gene(
        db_session, version="opt2-active", accession="OPT2ACTIVE", published=True
    )
    unreleased = await _seed_release_with_gene(
        db_session, version="opt2-draft", accession="OPT2DRAFT", published=False
    )
    db_session.add(ActiveRelease(id=1, release_id=published.id))
    await db_session.flush()

    response = await client.get(
        "/api/v1/search",
        params={"query": "OPT2DRAFT", "format": "json", "release_id": unreleased.id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["results"]] == ["OPT2DRAFT"]
    assert payload["results"][0]["release_id"] == unreleased.id

    # Control: without an explicit pin the active (published) release is used.
    active = await client.get(
        "/api/v1/search", params={"query": "OPT2ACTIVE", "format": "json"}
    )
    assert [item["id"] for item in active.json()["results"]] == ["OPT2ACTIVE"]


@pytest.mark.asyncio
async def test_two_unpublished_releases_do_not_share_a_response(
    client, db_session, monkeypatch
) -> None:
    published = await _seed_release_with_gene(
        db_session, version="opt2-r0", accession="OPT2R0", published=True
    )
    draft_a = await _seed_release_with_gene(
        db_session, version="opt2-ra", accession="OPT2RA", published=False
    )
    draft_b = await _seed_release_with_gene(
        db_session, version="opt2-rb", accession="OPT2RB", published=False
    )
    db_session.add(ActiveRelease(id=1, release_id=published.id))
    await db_session.flush()

    first = await client.get(
        "/api/v1/search", params={"query": "OPT2RA", "release_id": draft_a.id}
    )
    second = await client.get(
        "/api/v1/search", params={"query": "OPT2RB", "release_id": draft_b.id}
    )

    assert first.status_code == second.status_code == 200
    body_a, body_b = first.json(), second.json()
    assert body_a != body_b
    assert [item["id"] for item in body_a["results"]] == ["OPT2RA"]
    assert [item["id"] for item in body_b["results"]] == ["OPT2RB"]
    assert body_a["results"][0]["release_id"] == draft_a.id
    assert body_b["results"][0]["release_id"] == draft_b.id


# ------------------------------------------------- HTTP: federated HTML keys
@pytest.mark.asyncio
async def test_unpublished_release_ids_do_not_share_the_html_cache_key(
    client, db_session, monkeypatch
) -> None:
    published = await _seed_release_with_gene(
        db_session, version="opt2-key-r0", accession="OPT2KEYR0", published=True
    )
    draft_a = await _seed_release_with_gene(
        db_session, version="opt2-key-ra", accession="OPT2KEYRA", published=False
    )
    draft_b = await _seed_release_with_gene(
        db_session, version="opt2-key-rb", accession="OPT2KEYRB", published=False
    )
    db_session.add(ActiveRelease(id=1, release_id=published.id))
    await db_session.flush()

    redis = _FakeRedis()
    calls = _spy_make_key(monkeypatch)
    _install_providers(monkeypatch, redis)

    await client.get(
        "/api/v1/search",
        params={"query": "glyma", "format": "html", "sources": "ncbi", "release_id": draft_a.id},
    )
    await client.get(
        "/api/v1/search",
        params={"query": "glyma", "format": "html", "sources": "ncbi", "release_id": draft_b.id},
    )

    html_keys = [key for key in redis.sets if key.endswith(":html")]
    assert len(html_keys) == 2
    assert len(set(html_keys)) == 2, f"two unpublished releases shared one entry: {html_keys}"
    assert {call["release_id"] for call in calls} == {draft_a.id, draft_b.id}
    expected_a = (
        _external_html_cache_key(
            "glyma", [SearchSource.NCBI], release_id=draft_a.id,
            assembly_id=None, limit_per_source=10,
        )
        + ":html"
    )
    assert expected_a in html_keys


@pytest.mark.asyncio
async def test_published_release_ids_also_fork_the_html_cache_key(
    client, db_session, monkeypatch
) -> None:
    """Reverse proof: with published releases, distinct ids still fork."""
    published_a = await _seed_release_with_gene(
        db_session, version="opt2-pub-a", accession="OPT2PUBA", published=True
    )
    published_b = await _seed_release_with_gene(
        db_session, version="opt2-pub-b", accession="OPT2PUBB", published=True
    )
    db_session.add(ActiveRelease(id=1, release_id=published_a.id))
    await db_session.flush()

    redis = _FakeRedis()
    calls = _spy_make_key(monkeypatch)
    _install_providers(monkeypatch, redis)

    await client.get(
        "/api/v1/search",
        params={
            "query": "glyma",
            "format": "html",
            "sources": "ncbi",
            "release_id": published_a.id,
        },
    )
    await client.get(
        "/api/v1/search",
        params={
            "query": "glyma",
            "format": "html",
            "sources": "ncbi",
            "release_id": published_b.id,
        },
    )

    html_keys = [key for key in redis.sets if key.endswith(":html")]
    assert len(set(html_keys)) == 2
    assert {call["release_id"] for call in calls} == {published_a.id, published_b.id}


@pytest.mark.asyncio
async def test_gene_rows_stay_in_their_own_release(db_session) -> None:
    """Sanity: the seeds really are release-disjoint at the SQL level."""
    from app.services.search_service import SearchService

    release = await _seed_release_with_gene(
        db_session, version="opt2-sql", accession="OPT2SQL", published=False
    )
    rows = (
        await db_session.execute(
            select(Gene.accession, Assembly.release_id)
            .join(Assembly, Assembly.id == Gene.assembly_id)
            .where(Assembly.release_id == release.id)
        )
    ).all()
    assert [(acc, rel) for acc, rel in rows] == [("OPT2SQL", release.id)]
    assert SearchService is not None
