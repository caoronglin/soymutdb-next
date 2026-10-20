"""Scratch ablation tests for workstream W2 (assembly / cross-version).

Each test establishes a control (real code path) and a single-factor ablation
(monkeypatch only), then asserts the *contrast*. A passing test therefore
proves the guard flipped; an unexpected non-flip shows up as a failure.

Anchors (apps/api/tests/test_search_database_integration.py):
- test_v4_v5_same_accession_coexist_and_are_labelled  (ASM-01/02)
- test_unscoped_ambiguity_is_judged_over_full_match_set (ASM-03)
- test_crosswalk_data_is_explicit_and_linked          (ASM-04)
- test_similar_genes_without_crosswalk_stay_unrelated (ASM-05)
- test_gene_search_marks_exact_and_alias_matches      (alias scope)
"""

from __future__ import annotations

import pytest

from app.core.site_variant import SiteVariant
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.genomic import Assembly, Chromosome, Gene, GeneAlias, GeneCrosswalk
from app.schemas.search import MatchType, SearchResultType
from app.services import search_service
from app.services.search_service import SearchService


async def _assembly(db_session, slug, *, version, make_active=True):
    release = Release(
        version=f"{slug}-release",
        name=f"{slug} release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(release)
    await db_session.flush()
    assembly = Assembly(
        name=slug, species="Glycine max", version=version, release_id=release.id
    )
    db_session.add(assembly)
    await db_session.flush()
    if make_active:
        db_session.add(ActiveRelease(id=1, release_id=release.id))
    await db_session.flush()
    return assembly, release


async def _gene(db_session, assembly, accession, *, name=None, alias=None):
    chrom = (
        await db_session.execute(
            search_service.select(Chromosome).where(
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
    if alias is not None:
        db_session.add(GeneAlias(gene_id=gene.gene_pk, alias=alias))
        await db_session.flush()
    return gene


# ---------------------------------------------------------------------------
# ASM-01/02: the assembly predicate on the gene SQL must be load bearing.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_asm01_ablation_assembly_predicate_is_load_bearing(db_session, monkeypatch):
    v4, shared = await _assembly(db_session, "abl-scope-a4", version="v4")
    v5 = Assembly(
        name="abl-scope-a5", species="Glycine max", version="v5", release_id=shared.id
    )
    db_session.add(v5)
    await db_session.flush()
    await _gene(db_session, v4, "Glyma.01G000100", name="v4 gene")
    await _gene(db_session, v5, "Glyma.01G000100", name="v5 gene")

    service = SearchService()
    control = await service.global_search(
        db_session, "Glyma.01G000100", types=[SearchResultType.GENE], assembly_id=v4.id
    )
    print(f"[ASM-01 CONTROL] scoped v4 hits={len(control.results)} "
          f"assemblies={[r.assembly_id for r in control.results]}")
    assert len(control.results) == 1
    assert control.results[0].assembly_id == v4.id

    original = search_service._gene_match_query

    def drop_assembly(query, pattern, *, release_id, assembly_id):
        return original(query, pattern, release_id=release_id, assembly_id=None)

    monkeypatch.setattr(search_service, "_gene_match_query", drop_assembly)
    ablated = await service.global_search(
        db_session, "Glyma.01G000100", types=[SearchResultType.GENE], assembly_id=v4.id
    )
    print(f"[ASM-01 ABLATED] scoped v4 hits={len(ablated.results)} "
          f"assemblies={[r.assembly_id for r in ablated.results]}")
    # Ablation collapses both namespaces into the "scoped" page.
    assert len(ablated.results) == 2
    assert {r.assembly_id for r in ablated.results} == {v4.id, v5.id}


# ---------------------------------------------------------------------------
# ASM-03: ambiguity must be aggregated over the full set, not the page.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_asm03_ablation_full_set_aggregate_is_load_bearing(db_session, monkeypatch):
    v4, shared = await _assembly(db_session, "abl-ambig-a4", version="v4")
    v5 = Assembly(
        name="abl-ambig-a5", species="Glycine max", version="v5", release_id=shared.id
    )
    db_session.add(v5)
    await db_session.flush()
    await _gene(db_session, v4, "Glyma.01G000100", name="shared locus")
    await _gene(db_session, v5, "Glyma.01G000100", name="shared locus")

    service = SearchService()
    control = await service.global_search(
        db_session, "Glyma.01G000100", types=[SearchResultType.GENE], limit=1
    )
    print(f"[ASM-03 CONTROL] len={len(control.results)} ambiguous={control.ambiguous} "
          f"by_assembly={control.by_assembly}")
    assert len(control.results) == 1
    assert control.ambiguous is True
    assert control.by_assembly == {str(v4.id): 1, str(v5.id): 1}

    async def page_only_distribution(self, db, query, pattern, *, release_id):
        # Neutralize the full-set aggregate: the service then relies on the
        # truncated-page fallback branch (``by_assembly`` from ``hits``).
        return {}

    monkeypatch.setattr(
        SearchService, "_gene_assembly_distribution", page_only_distribution
    )
    ablated = await service.global_search(
        db_session, "Glyma.01G000100", types=[SearchResultType.GENE], limit=1
    )
    print(f"[ASM-03 ABLATED] len={len(ablated.results)} ambiguous={ablated.ambiguous} "
          f"by_assembly={ablated.by_assembly}")
    assert ablated.ambiguous is False
    assert ablated.by_assembly == {}


# ---------------------------------------------------------------------------
# ASM-04: a v4 exact hit with a gene_crosswalks row must surface an explicit
# cross-version link. Establishes whether the audit GAP still exists.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_asm04_crosswalk_probe(db_session):
    """Always-passing probe that prints what search really exposes."""
    v4, _ = await _assembly(db_session, "abl-cw-a4", version="v4")
    v5, _ = await _assembly(db_session, "abl-cw-a5", version="v5", make_active=False)
    gene_v4 = await _gene(db_session, v4, "Glyma.01G000100")
    gene_v5 = await _gene(db_session, v5, "Glyma.05G000100")
    db_session.add(
        GeneCrosswalk(
            source_gene_id=gene_v4.gene_pk,
            target_gene_id=gene_v5.gene_pk,
            relation_type="one_to_one",
            provenance_source="ablation-fixture",
        )
    )
    await db_session.flush()

    service = SearchService()
    response = await service.global_search(
        db_session, "Glyma.01G000100", types=[SearchResultType.GENE]
    )
    payload = response.model_dump()
    print(f"[ASM-04 PROBE] results={len(response.results)}")
    for item in response.results:
        print(f"[ASM-04 PROBE] id={item.id} match_type={item.match_type} "
              f"assembly_id={item.assembly_id} "
              f"fields={sorted(item.model_dump(exclude_none=True))}")
    print(f"[ASM-04 PROBE] cross-version anywhere="
          f"{'cross-version' in str(payload)}")
    # The v5 target never appears as its own hit for this accession:
    assert {item.id for item in response.results} == {"Glyma.01G000100"}


@pytest.mark.asyncio
async def test_asm04_crosswalk_must_be_exposed_as_cross_version(db_session):
    """Desired contract; fails at HEAD => ASM-04 is a GAP."""
    v4, _ = await _assembly(db_session, "abl-cw2-a4", version="v4")
    v5, _ = await _assembly(db_session, "abl-cw2-a5", version="v5", make_active=False)
    gene_v4 = await _gene(db_session, v4, "Glyma.01G000100")
    gene_v5 = await _gene(db_session, v5, "Glyma.05G000100")
    db_session.add(
        GeneCrosswalk(
            source_gene_id=gene_v4.gene_pk,
            target_gene_id=gene_v5.gene_pk,
            relation_type="one_to_one",
            provenance_source="ablation-fixture",
        )
    )
    await db_session.flush()

    service = SearchService()
    response = await service.global_search(
        db_session, "Glyma.01G000100", types=[SearchResultType.GENE]
    )
    # The crosswalk row exists and is provenance-bearing (E1 row assertion).
    rows = (
        await db_session.execute(
            search_service.select(GeneCrosswalk).where(
                GeneCrosswalk.source_gene_id == gene_v4.gene_pk
            )
        )
    ).scalars().all()
    print(f"[ASM-04 ROWS] crosswalk_rows={len(rows)} "
          f"target={rows[0].target_gene_id if rows else None}")
    assert len(rows) == 1

    # Desired: the v5 target surfaces as an explicit cross-version link on the
    # v4 exact hit -- carrying its own CROSS_VERSION typing and the crosswalk
    # provenance -- WITHOUT becoming an extra result row.
    ids = {item.id for item in response.results}
    match_types = {item.match_type for item in response.results}
    links = [link for item in response.results for link in item.cross_version]
    print(f"[ASM-04 DESIRED] ids={ids} match_types={match_types} "
          f"links={[(link.gene_accession, str(link.match_type)) for link in links]}")
    assert response.total_count == 1, "linked gene must not add a result row"
    assert len(response.results) == 1
    assert ids == {"Glyma.01G000100"}
    # The exact hit keeps its own typing; CROSS_VERSION lives on the link.
    assert match_types == {MatchType.EXACT}
    assert "Glyma.05G000100" in {link.gene_accession for link in links}, (
        "crosswalk target not surfaced by search"
    )
    assert all(link.match_type == MatchType.CROSS_VERSION for link in links)
    assert {link.provenance_source for link in links} == {"ablation-fixture"}
    assert {link.assembly_version for link in links} == {"v5"}


@pytest.mark.asyncio
async def test_asm04_ablation_dropping_crosswalk_row_changes_nothing(db_session):
    """Ablation: remove the factor (the crosswalk row) and diff the search.

    If search consumed the provenance-bearing relation, deleting the row
    would change the response. Identical output => the factor never reaches
    the search path (the GAP quantified).
    """
    v4, _ = await _assembly(db_session, "abl-cw3-a4", version="v4")
    v5, _ = await _assembly(db_session, "abl-cw3-a5", version="v5", make_active=False)
    gene_v4 = await _gene(db_session, v4, "Glyma.01G000100")
    gene_v5 = await _gene(db_session, v5, "Glyma.05G000100")
    row = GeneCrosswalk(
        source_gene_id=gene_v4.gene_pk,
        target_gene_id=gene_v5.gene_pk,
        relation_type="one_to_one",
        provenance_source="ablation-fixture",
    )
    db_session.add(row)
    await db_session.flush()

    service = SearchService()

    async def snapshot():
        r = await service.global_search(
            db_session, "Glyma.01G000100", types=[SearchResultType.GENE]
        )
        return [
            (i.id, str(i.match_type), i.assembly_id, i.url) for i in r.results
        ]

    with_crosswalk = await snapshot()
    await db_session.delete(row)
    await db_session.flush()
    without_crosswalk = await snapshot()
    print(f"[ASM-04 ABLATION] with={with_crosswalk} without={without_crosswalk}")
    assert with_crosswalk == without_crosswalk


# ---------------------------------------------------------------------------
# ASM-05: similarity must not promote unmapped genes to cross-version.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_asm05_ablation_provenance_vs_similarity(db_session, monkeypatch):
    v4, shared = await _assembly(db_session, "abl-sim-a4", version="v4")
    v5 = Assembly(
        name="abl-sim-a5", species="Glycine max", version="v5", release_id=shared.id
    )
    db_session.add(v5)
    await db_session.flush()
    await _gene(db_session, v4, "Glyma.01G000100", name="similar locus")
    await _gene(db_session, v5, "Glyma.01G000101", name="similar locus")

    service = SearchService()
    control = await service.global_search(
        db_session, "similar locus", types=[SearchResultType.GENE]
    )
    print(f"[ASM-05 CONTROL] match_types={[r.match_type for r in control.results]} "
          f"ambiguous={control.ambiguous}")
    assert all(item.match_type == MatchType.TEXT for item in control.results)

    original = SearchService._search_genes

    async def promote_similarity(self, db, query, pattern, limit, offset=0, **kw):
        hits = await original(self, db, query, pattern, limit, offset, **kw)
        if len({h.metadata.get("assembly_id") for h in hits}) > 1:
            for hit in hits:
                hit.match_type = MatchType.CROSS_VERSION
        return hits

    monkeypatch.setattr(SearchService, "_search_genes", promote_similarity)
    ablated = await service.global_search(
        db_session, "similar locus", types=[SearchResultType.GENE]
    )
    print(f"[ASM-05 ABLATED] match_types={[r.match_type for r in ablated.results]}")
    # Dropping the provenance requirement (similarity promotion) flips the
    # labeling: the same two genes would read as cross-version relatives.
    assert all(item.match_type == MatchType.CROSS_VERSION for item in ablated.results)


# ---------------------------------------------------------------------------
# Alias matching must stay assembly-scoped.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_alias_ablation_alias_scope_is_load_bearing(db_session, monkeypatch):
    v4, shared = await _assembly(db_session, "abl-alias-a4", version="v4")
    v5 = Assembly(
        name="abl-alias-a5", species="Glycine max", version="v5", release_id=shared.id
    )
    db_session.add(v5)
    await db_session.flush()
    await _gene(db_session, v4, "GmFT2b", name="flowering v4", alias="FLOWER-B")
    await _gene(db_session, v5, "GmFT2c", name="flowering v5", alias="FLOWER-B")

    service = SearchService()
    control = await service.global_search(
        db_session, "FLOWER-B", types=[SearchResultType.GENE], assembly_id=v4.id
    )
    print(f"[ALIAS CONTROL] hits={[r.id for r in control.results]} "
          f"match_types={[r.match_type for r in control.results]}")
    assert [r.id for r in control.results] == ["GmFT2b"]
    assert control.results[0].match_type == MatchType.ALIAS

    original = search_service._gene_match_query

    def drop_assembly(query, pattern, *, release_id, assembly_id):
        return original(query, pattern, release_id=release_id, assembly_id=None)

    monkeypatch.setattr(search_service, "_gene_match_query", drop_assembly)
    ablated = await service.global_search(
        db_session, "FLOWER-B", types=[SearchResultType.GENE], assembly_id=v4.id
    )
    print(f"[ALIAS ABLATED] hits={[r.id for r in ablated.results]}")
    assert {r.id for r in ablated.results} == {"GmFT2b", "GmFT2c"}
