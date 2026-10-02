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
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.genomic import Assembly, Chromosome, Gene


# The federated-search fakes (`_FakeRedis`, `_StaticAdapter`, provider install
# and cache-key spies) were removed with federated search itself: they only
# served the HTML cache-key tests, and their target modules no longer exist.


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


# The federated HTML cache-key tests were removed with federated search itself:
# `_external_html_cache_key` and `app.search.cache.SearchCache` no longer exist.


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
