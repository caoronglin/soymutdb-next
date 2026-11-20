"""OPT-01 focused regressions: provenance-bearing cross-version links.

Companion to ``test_ablation_assembly_scope_and_crossversion.py``: that file
proves the red->green flip, this one pins the contract details so a future
change cannot quietly weaken them:

- only ``gene_crosswalks`` rows produce ``cross_version`` entries (ASM-05:
  string similarity alone must stay unrelated);
- both directions (source->target and target->source) are honoured;
- a ``NULL`` crosswalk release is generic, a foreign release is filtered out;
- the link never becomes an extra row and never retypes the matched hit.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.site_variant import SiteVariant
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.genomic import Assembly, Chromosome, Gene, GeneCrosswalk
from app.schemas.search import MatchType, SearchResultType
from app.services.release_context import ReleaseContext
from app.services.search_service import SearchService


async def _release(db_session, slug) -> Release:
    release = Release(
        version=f"{slug}-release",
        name=f"{slug} release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(release)
    await db_session.flush()
    return release


async def _active_release(db_session, slug) -> Release:
    release = await _release(db_session, slug)
    db_session.add(ActiveRelease(id=1, release_id=release.id))
    await db_session.flush()
    return release


async def _assembly(db_session, release, slug, *, version) -> Assembly:
    assembly = Assembly(
        name=slug, species="Glycine max", version=version, release_id=release.id
    )
    db_session.add(assembly)
    await db_session.flush()
    return assembly


async def _gene(db_session, assembly, accession, *, name=None) -> Gene:
    chrom = (
        await db_session.execute(
            select(Chromosome).where(
                Chromosome.assembly_id == assembly.id, Chromosome.name == "Gm01"
            )
        )
    ).scalar_one_or_none()
    if chrom is None:
        chrom = Chromosome(
            assembly_id=assembly.id, name="Gm01", length=100_000, order=1
        )
        db_session.add(chrom)
        await db_session.flush()
    gene = Gene(
        accession=accession,
        assembly_id=assembly.id,
        chromosome_id=chrom.id,
        name=name,
        biotype="protein_coding",
        start=1,
        end=10,
        strand="+",
    )
    db_session.add(gene)
    await db_session.flush()
    return gene


def _links(response):
    return [link for item in response.results for link in item.cross_version]


# ---------------------------------------------------------------------------
# Negative: similarity without a crosswalk row stays unrelated (ASM-05).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_opt01_similarity_only_genes_have_empty_cross_version(db_session):
    release = await _active_release(db_session, "opt-cw-sim")
    v4 = await _assembly(db_session, release, "opt-cw-sim-a4", version="v4")
    v5 = await _assembly(db_session, release, "opt-cw-sim-a5", version="v5")
    await _gene(db_session, v4, "Glyma.01G000100", name="similar locus")
    await _gene(db_session, v5, "Glyma.01G000101", name="similar locus")

    response = await SearchService().global_search(
        db_session, "similar locus", types=[SearchResultType.GENE]
    )
    print(f"[OPT01 NEG] results={len(response.results)} "
          f"match_types={[str(r.match_type) for r in response.results]} "
          f"links={_links(response)}")
    assert len(response.results) == 2
    assert all(item.match_type == MatchType.TEXT for item in response.results)
    assert all(item.cross_version == [] for item in response.results), (
        "string similarity alone must not create a cross-version link"
    )


# ---------------------------------------------------------------------------
# Positive: one row is consumed in BOTH directions, without extra rows.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_opt01_crosswalk_is_resolved_in_both_directions(db_session):
    release = await _active_release(db_session, "opt-cw-both")
    v4 = await _assembly(db_session, release, "opt-cw-both-a4", version="v4")
    v5 = await _assembly(db_session, release, "opt-cw-both-a5", version="v5")
    gene_v4 = await _gene(db_session, v4, "Glyma.01G000100")
    gene_v5 = await _gene(db_session, v5, "Glyma.05G000100")
    db_session.add(
        GeneCrosswalk(
            source_gene_id=gene_v4.gene_pk,
            target_gene_id=gene_v5.gene_pk,
            relation_type="one_to_one",
            provenance_source="opt-fixture",
        )
    )
    await db_session.flush()

    service = SearchService()
    forward = await service.global_search(
        db_session, "Glyma.01G000100", types=[SearchResultType.GENE]
    )
    reverse = await service.global_search(
        db_session, "Glyma.05G000100", types=[SearchResultType.GENE]
    )
    forward_links = {
        i.id: [link.gene_accession for link in i.cross_version] for i in forward.results
    }
    reverse_links = {
        i.id: [link.gene_accession for link in i.cross_version] for i in reverse.results
    }
    print(f"[OPT01 BOTH] forward={forward_links} reverse={reverse_links}")

    # source -> target
    assert [i.id for i in forward.results] == ["Glyma.01G000100"]
    assert forward.total_count == 1
    assert {link.gene_accession for link in _links(forward)} == {"Glyma.05G000100"}
    assert all(link.match_type == MatchType.CROSS_VERSION for link in _links(forward))
    assert forward.results[0].match_type == MatchType.EXACT

    # target -> source (same row, other direction)
    assert [i.id for i in reverse.results] == ["Glyma.05G000100"]
    assert reverse.total_count == 1
    assert {link.gene_accession for link in _links(reverse)} == {"Glyma.01G000100"}
    assert all(link.match_type == MatchType.CROSS_VERSION for link in _links(reverse))
    assert reverse.results[0].match_type == MatchType.EXACT


# ---------------------------------------------------------------------------
# Scoping: NULL crosswalk release is generic; a foreign release is filtered.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_opt01_null_release_is_generic_and_foreign_release_is_skipped(db_session):
    release = await _active_release(db_session, "opt-cw-scope")
    foreign = await _release(db_session, "opt-cw-foreign")

    a4 = await _assembly(db_session, release, "opt-cw-scope-a4", version="v4")
    a5 = await _assembly(db_session, release, "opt-cw-scope-a5", version="v5")
    generic_v4 = await _gene(db_session, a4, "Glyma.01G000100")
    generic_v5 = await _gene(db_session, a5, "Glyma.05G000100")
    db_session.add(
        GeneCrosswalk(
            source_gene_id=generic_v4.gene_pk,
            target_gene_id=generic_v5.gene_pk,
            relation_type="one_to_one",
            provenance_source="generic",
            release_id=None,  # NULL => applies to every release
        )
    )

    b4 = await _assembly(db_session, release, "opt-cw-scope-b4", version="v4")
    b5 = await _assembly(db_session, release, "opt-cw-scope-b5", version="v5")
    foreign_v4 = await _gene(db_session, b4, "Glyma.02G000200")
    foreign_v5 = await _gene(db_session, b5, "Glyma.06G000600")
    db_session.add(
        GeneCrosswalk(
            source_gene_id=foreign_v4.gene_pk,
            target_gene_id=foreign_v5.gene_pk,
            relation_type="one_to_one",
            provenance_source="foreign",
            release_id=foreign.id,  # non-null, not the active release
        )
    )

    # A generic row is not enough: a linked gene whose assembly exists only in
    # an *unpublished* release is not part of any catalogue yet, so the row must
    # not publish its accession and assembly.
    draft = Release(
        version="opt-cw-draft-release",
        name="draft release",
        status=ReleaseStatus.DRAFT,
    )
    db_session.add(draft)
    await db_session.flush()
    foreign_only = await _assembly(db_session, draft, "opt-cw-fscope-a5", version="v5")
    foreign_target = await _gene(db_session, foreign_only, "Glyma.09G000900")
    db_session.add(
        GeneCrosswalk(
            source_gene_id=generic_v4.gene_pk,
            target_gene_id=foreign_target.gene_pk,
            relation_type="one_to_many",
            provenance_source="generic-foreign-assembly",
            release_id=None,
        )
    )
    await db_session.flush()

    service = SearchService()
    generic = await service.global_search(
        db_session, "Glyma.01G000100", types=[SearchResultType.GENE]
    )
    scoped_away = await service.global_search(
        db_session, "Glyma.02G000200", types=[SearchResultType.GENE]
    )
    print(f"[OPT01 SCOPE] generic={[link.gene_accession for link in _links(generic)]} "
          f"foreign={[link.gene_accession for link in _links(scoped_away)]}")

    assert {link.gene_accession for link in _links(generic)} == {"Glyma.05G000100"}
    assert "Glyma.09G000900" not in {
        link.gene_accession for link in _links(generic)
    }, "a generic row must not disclose a link into another release's assembly"
    assert _links(scoped_away) == [], (
        "a crosswalk scoped to another release must not appear here"
    )


# ---------------------------------------------------------------------------
# OPT-02: the cache param `site_variant` is deliberate defence in depth.
#
# cache-site.md I2: while the internal bypass is active this field is
# unreachable for internal callers, so deleting it changes nothing observable
# today. It must still be present: the moment the bypass goes away, two site
# variants would otherwise share one cache entry. This test is the pin.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_opt02_site_variant_is_pinned_in_global_search_cache_params():
    context = ReleaseContext(release_id=7, assembly_id=11, assembly="Wm82.v5")
    captured: dict = {}

    async def fake_get_or_set(name, ttl, loader, *, params=None):
        del loader
        captured.update({"name": name, "params": params})
        return {
            "query": "Glyma",
            "results": [],
            "by_type": {"gene": 0},
            "cursor": None,
            "next_cursor": None,
            "has_more": False,
            "total_count": 0,
        }

    with (
        patch(
            "app.services.search_service.resolve_release_context",
            AsyncMock(return_value=context),
        ),
        patch("app.services.search_service.get_or_set", fake_get_or_set),
    ):
        await SearchService().global_search(
            object(),
            "Glyma",
            types=[SearchResultType.GENE],
            site_variant=SiteVariant.EXTERNAL,
        )

    print(f"[OPT02] cache_params={captured['params']}")
    assert "site_variant" in captured["params"], (
        "site_variant dropped from the shared cache key; site variants would "
        "cross-contaminate once the internal bypass is removed"
    )
    assert captured["params"]["site_variant"] == SiteVariant.EXTERNAL.value
    assert captured["params"]["release_id"] == 7
