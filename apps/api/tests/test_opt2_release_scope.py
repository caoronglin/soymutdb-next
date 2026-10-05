"""OPT2-02: release scope must be explicit, not best-effort-shared.

The pre-OPT2 concern: when release resolution fell back to the active release,
a request that *named* a different (unpublished) release silently shared the
active release's cache entry and response.  These tests decide the question
with a real ASGI request over a real PostgreSQL session and concrete evidence:
the exact cache keys handed to Redis and the exact response bodies.

Verdict pinned here: ASSUMED LEAK, NOW FIXED -- a request that *named* a
different release must never silently fall back to the active release's
response.

Superseded scope of that verdict (2026-10-05).  It originally read
"published or not": an explicit ``release_id`` was the request's release
scope whatever its status, so this file pinned draft releases being
retrievable through ``/api/v1/search``.  That predates the external-site
boundary being enforced through ``get_release_context``, and it contradicts
the repository's standing invariant that an external-site API "may search
and return only released public records".  ``/api/v1/search`` hardcodes
``site_variant=SiteVariant.EXTERNAL`` (``app/api/v1/search.py``), so pinning a
draft release there is a draft leak, not a scope feature.  The 404 it now
returns is the intended behaviour and is asserted below.

What survives unchanged is the reason the file exists: distinct releases must
not share a response, and an unknown or draft pin must not quietly resolve to
the active release.  The isolation assertions are therefore re-expressed over
two *published* releases, with the draft case turned into the negative
leakage assertion it should have been.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

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
async def test_explicit_draft_release_is_refused_by_the_public_endpoint(
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

    # The public endpoint refuses a draft pin instead of honouring it.
    assert response.status_code == 404
    assert "OPT2DRAFT" not in response.text

    # Control: without an explicit pin the active (published) release is used,
    # and the draft release's gene stays out of the response entirely.
    active = await client.get(
        "/api/v1/search", params={"query": "OPT2DRAFT", "format": "json"}
    )
    assert [item["id"] for item in active.json()["results"]] == []

    scoped = await client.get(
        "/api/v1/search", params={"query": "OPT2ACTIVE", "format": "json"}
    )
    assert [item["id"] for item in scoped.json()["results"]] == ["OPT2ACTIVE"]


@pytest.mark.asyncio
async def test_two_published_releases_do_not_share_a_response(
    client, db_session, monkeypatch
) -> None:
    published = await _seed_release_with_gene(
        db_session, version="opt2-r0", accession="OPT2R0", published=True
    )
    other = await _seed_release_with_gene(
        db_session, version="opt2-rb", accession="OPT2RB", published=True
    )
    db_session.add(ActiveRelease(id=1, release_id=published.id))
    await db_session.flush()

    # Both pins are published but different, so the isolation invariant is
    # exercised without reaching for a draft release the public endpoint
    # refuses to serve.
    first = await client.get(
        "/api/v1/search", params={"query": "OPT2R0", "release_id": published.id}
    )
    second = await client.get(
        "/api/v1/search", params={"query": "OPT2RB", "release_id": other.id}
    )

    assert first.status_code == second.status_code == 200
    body_a, body_b = first.json(), second.json()
    assert body_a != body_b
    assert [item["id"] for item in body_a["results"]] == ["OPT2R0"]
    assert [item["id"] for item in body_b["results"]] == ["OPT2RB"]
    assert body_a["results"][0]["release_id"] == published.id
    assert body_b["results"][0]["release_id"] == other.id

    # A draft pin answers 404 for each of them rather than resolving to the
    # active release, which is the leak this file was written to prevent.
    draft = await _seed_release_with_gene(
        db_session, version="opt2-ra", accession="OPT2RA", published=False
    )
    await db_session.flush()
    pinned = await client.get(
        "/api/v1/search", params={"query": "OPT2RA", "release_id": draft.id}
    )
    assert pinned.status_code == 404
    assert "OPT2RA" not in pinned.text


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
