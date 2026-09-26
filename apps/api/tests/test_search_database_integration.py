"""PostgreSQL-backed search service contracts.

Contract mapping (database-core-contract):
- ID-01: published public_id hits on the external surface, without the
  internal persistence key.
- ASM-01/02/03: v4/v5 namespaces coexist; assembly-scoped queries return
  only their namespace; unscoped queries label hits per assembly and
  report ambiguity instead of defaulting.
- CTX-02/03: the external cache key separates release and assembly
  contexts (internal searches bypass the cache entirely).
"""

from __future__ import annotations

import pytest

from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from sqlalchemy import select
from app.core.site_variant import SiteVariant
from app.models.genomic import Assembly, Chromosome, Gene, GeneAlias, GeneCrosswalk
from app.models.variant import MutantLine
from app.schemas.search import MatchType, SearchResultType
from app.services.search_service import SearchService


async def _create_active_assembly(
    db_session, slug: str, *, version: str = "v1", make_active: bool = True
) -> tuple[Assembly, Release]:
    release = Release(
        version=f"{slug}-release",
        name=f"{slug} release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(release)
    await db_session.flush()

    assembly = Assembly(
        name=slug,
        species="Glycine max",
        version=version,
        release_id=release.id,
    )
    db_session.add(assembly)
    await db_session.flush()

    assembly.release_id = release.id
    assembly.release = release
    if make_active:
        db_session.add(ActiveRelease(id=1, release_id=release.id))
    await db_session.flush()
    return assembly, release


async def _add_gene(
    db_session,
    assembly: Assembly,
    accession: str,
    *,
    name: str | None = None,
    order: int = 1,
) -> Gene:
    chromosome = (
        await db_session.execute(
            select(Chromosome).where(
                Chromosome.assembly_id == assembly.id,
                Chromosome.name == "Gm01",
            )
        )
    ).scalar_one_or_none()
    if chromosome is None:
        chromosome = Chromosome(
            assembly_id=assembly.id, name="Gm01", length=100_000, order=order
        )
        db_session.add(chromosome)
        await db_session.flush()
    gene = Gene(
        accession=accession,
        assembly_id=assembly.id,
        chromosome_id=chromosome.id,
        name=name,
        biotype="protein_coding",
        start=1,
        end=10,
        strand="+",
    )
    db_session.add(gene)
    await db_session.flush()
    return gene


@pytest.mark.asyncio
async def test_global_search_uses_literal_substring_matching_in_postgresql(db_session):
    assembly, _release = await _create_active_assembly(db_session, "search-db")
    await _add_gene(
        db_session,
        assembly,
        "SEARCH_MATCH",
        name="Target gene contains literal 100% marker",
    )
    await _add_gene(db_session, assembly, "SEARCH_OTHER", name="Other gene")

    service = SearchService()
    matched = await service.global_search(
        db_session,
        "100% marker",
        types=[SearchResultType.GENE],
    )
    assert [item.id for item in matched.results] == ["SEARCH_MATCH"]

    literal_wildcard = await service.global_search(
        db_session,
        "%",
        types=[SearchResultType.GENE],
    )
    assert [item.id for item in literal_wildcard.results] == ["SEARCH_MATCH"]


@pytest.mark.asyncio
async def test_global_search_returns_a_continuation_cursor_for_truncated_results(db_session):
    assembly, _release = await _create_active_assembly(db_session, "search-cursor-db")
    for number in range(3):
        await _add_gene(
            db_session,
            assembly,
            f"CURSOR_MATCH_{number}",
            name=f"Cursor gene {number} cursor integration match",
            order=number + 1,
        )

    service = SearchService()
    first = await service.global_search(
        db_session, "cursor integration match", types=[SearchResultType.GENE], limit=1
    )
    assert first.has_more is True
    # New pages emit a sealed per-source cursor rather than a shared offset.
    assert first.next_cursor is not None
    assert first.next_cursor != "1"

    second = await service.global_search(
        db_session,
        "cursor integration match",
        types=[SearchResultType.GENE],
        cursor=first.next_cursor,
        limit=1,
    )
    assert second.results[0].id != first.results[0].id
    assert second.next_cursor is not None
    assert second.next_cursor != "2"

    # Decimal cursors remain accepted for mixed-version clients and retain
    # their original offset semantics.
    legacy_second = await service.global_search(
        db_session,
        "cursor integration match",
        types=[SearchResultType.GENE],
        cursor="1",
        limit=1,
    )
    assert legacy_second.results[0].id == second.results[0].id


@pytest.mark.asyncio
async def test_v4_v5_same_accession_coexist_and_are_labelled(db_session):
    """H04/ASM-01/02/03: same accession in two assemblies, no silent default."""
    v4, shared_release = await _create_active_assembly(
        db_session, "coexist-a4", version="v4"
    )
    # v4 and v5 can also live in one release; they remain distinct namespaces.
    v5 = Assembly(
        name="coexist-a5",
        species="Glycine max",
        version="v5",
        release_id=shared_release.id,
    )
    db_session.add(v5)
    await db_session.flush()
    await _add_gene(db_session, v4, "Glyma.01G000100", name="v4 gene")
    await _add_gene(db_session, v5, "Glyma.01G000100", name="v5 gene")

    service = SearchService()

    # ASM-01: v4-scoped query returns only the v4 namespace.
    scoped_v4 = await service.global_search(
        db_session,
        "Glyma.01G000100",
        types=[SearchResultType.GENE],
        assembly_id=v4.id,
    )
    assert [item.id for item in scoped_v4.results] == ["Glyma.01G000100"]
    assert scoped_v4.results[0].assembly_id == v4.id

    # ASM-02: v5-scoped query returns only the v5 namespace.
    scoped_v5 = await service.global_search(
        db_session,
        "Glyma.01G000100",
        types=[SearchResultType.GENE],
        assembly_id=v5.id,
    )
    assert [item.id for item in scoped_v5.results] == ["Glyma.01G000100"]
    assert scoped_v5.results[0].assembly_id == v5.id

    # ASM-03: unscoped query labels both assemblies and flags ambiguity.
    unscoped = await service.global_search(
        db_session,
        "Glyma.01G000100",
        types=[SearchResultType.GENE],
    )
    assert {item.assembly_id for item in unscoped.results} == {v4.id, v5.id}
    assert unscoped.ambiguous is True
    assert unscoped.by_assembly == {str(v4.id): 1, str(v5.id): 1}


@pytest.mark.asyncio
async def test_gene_search_marks_exact_and_alias_matches(db_session):
    assembly, _ = await _create_active_assembly(db_session, "match-db")
    await _add_gene(db_session, assembly, "GmFT2a", name="Flowering locus")
    await _add_gene(db_session, assembly, "GmFT2b", name="Flowering locus b")
    from app.models.genomic import GeneAlias

    gene = (await db_session.execute(
        select(Gene).where(Gene.accession == "GmFT2b")
    )).scalar_one()
    db_session.add(GeneAlias(gene_id=gene.gene_pk, alias="FLOWER-B"))
    await db_session.flush()

    service = SearchService()
    exact = await service.global_search(
        db_session, "GmFT2a", types=[SearchResultType.GENE]
    )
    assert exact.results[0].id == "GmFT2a"
    assert exact.results[0].match_type == "exact"

    alias = await service.global_search(
        db_session, "FLOWER-B", types=[SearchResultType.GENE]
    )
    assert alias.results[0].id == "GmFT2b"
    assert alias.results[0].match_type == "alias"


@pytest.mark.asyncio
async def test_similar_genes_without_crosswalk_stay_unrelated(db_session):
    """ASM-05: string similarity must never create cross-version claims."""
    v4, sim_release = await _create_active_assembly(
        db_session, "sim-a4", version="v4"
    )
    v5 = Assembly(
        name="sim-a5",
        species="Glycine max",
        version="v5",
        release_id=sim_release.id,
    )
    db_session.add(v5)
    await db_session.flush()
    await _add_gene(db_session, v4, "Glyma.01G000100", name="similar locus")
    await _add_gene(db_session, v5, "Glyma.01G000101", name="similar locus")

    service = SearchService()
    response = await service.global_search(
        db_session, "similar locus", types=[SearchResultType.GENE]
    )
    assert len(response.results) == 2
    assert all(item.match_type == "text" for item in response.results)
    assert response.ambiguous is True


@pytest.mark.asyncio
async def test_crosswalk_data_is_explicit_and_linked(db_session):
    """H08: cross-version relations come from provenance-bearing rows."""
    v4, _ = await _create_active_assembly(db_session, "cw-a4", version="v4")
    v5, _ = await _create_active_assembly(
        db_session, "cw-a5", version="v5", make_active=False
    )
    gene_v4 = await _add_gene(db_session, v4, "Glyma.01G000100")
    gene_v5 = await _add_gene(db_session, v5, "Glyma.05G000100")

    db_session.add(
        GeneCrosswalk(
            source_gene_id=gene_v4.gene_pk,
            target_gene_id=gene_v5.gene_pk,
            relation_type="one_to_one",
            provenance_source="unit-fixture",
        )
    )
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(GeneCrosswalk)
            .where(GeneCrosswalk.source_gene_id == gene_v4.gene_pk)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].target_gene_id == gene_v5.gene_pk
    assert rows[0].provenance_source == "unit-fixture"

    # Unique pair/type constraint: the same mapping cannot be re-asserted.
    db_session.add(
        GeneCrosswalk(
            source_gene_id=gene_v4.gene_pk,
            target_gene_id=gene_v5.gene_pk,
            relation_type="one_to_one",
            provenance_source="duplicate",
        )
    )
    with pytest.raises(Exception):
        await db_session.flush()


@pytest.mark.asyncio
async def test_external_mutant_search_uses_public_id_only(db_session):
    """ID-01/ID-02: public_id hits externally; internal keys stay hidden."""
    _assembly, release = await _create_active_assembly(db_session, "mutant-search-db")
    line = MutantLine(
        name="lab-1",
        public_id="SMPUB00001",
        is_public=True,
        release_id=release.id,
    )
    embargoed = MutantLine(
        name="lab-secret", public_id="SMSECRET01", is_public=False, release_id=release.id
    )
    other_release = Release(
        version="mutant-search-other",
        name="mutant search other",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(other_release)
    await db_session.flush()
    other_release_line = MutantLine(
        name="lab-other-release",
        public_id="SMOTHER01",
        is_public=True,
        release_id=other_release.id,
    )
    null_release_line = MutantLine(
        name="lab-null-release",
        public_id="SMNULL01",
        is_public=True,
        release_id=None,
    )
    db_session.add_all([line, embargoed, other_release_line, null_release_line])
    await db_session.commit()

    service = SearchService()
    response = await service.global_search(
        db_session,
        "SMPUB00001",
        types=[SearchResultType.MUTANT_LINE],
        site_variant=SiteVariant.EXTERNAL,
    )
    assert [item.id for item in response.results] == ["SMPUB00001"]
    dump = response.model_dump_json()
    assert '"internal_id"' not in dump
    assert all(item.id != str(line.id) for item in response.results)

    # Internal id lookups must not disclose that id as an identity: text
    # matches on public ids may legitimately appear, but no hit may carry
    # the internal key and unpublished rows stay hidden.
    internal_query = await service.global_search(
        db_session,
        str(line.id),
        types=[SearchResultType.MUTANT_LINE],
    )
    assert all(item.id != str(line.id) for item in internal_query.results)
    assert '"internal_id"' not in internal_query.model_dump_json()

    # Unpublished record: not searchable externally even by its public_id.
    unpublished_query = await service.global_search(
        db_session,
        "SMSECRET01",
        types=[SearchResultType.MUTANT_LINE],
    )
    assert unpublished_query.results == []

    # A public mutant is also release-scoped: rows from another release and
    # rows without a release must not leak into the active public surface.
    other_release_query = await service.global_search(
        db_session,
        "SMOTHER01",
        types=[SearchResultType.MUTANT_LINE],
        site_variant=SiteVariant.EXTERNAL,
    )
    null_release_query = await service.global_search(
        db_session,
        "SMNULL01",
        types=[SearchResultType.MUTANT_LINE],
        site_variant=SiteVariant.EXTERNAL,
    )
    assert other_release_query.results == []
    assert null_release_query.results == []


@pytest.mark.asyncio
async def test_internal_search_returns_both_identities_and_matched_field(db_session):
    """ID-04: authorized internal search locates one entity via either id."""
    line = MutantLine(name="lab-2", public_id="SMPUB00002")
    db_session.add(line)
    await db_session.flush()

    service = SearchService()
    by_public = await service.internal_search(
        db_session, "SMPUB00002", release_id=None
    )
    by_name = await service.internal_search(db_session, "lab-2", release_id=None)
    by_internal = await service.internal_search(
        db_session, str(line.id), release_id=None
    )

    assert [m.public_id for m in by_public.mutants] == ["SMPUB00002"]
    assert by_public.mutants[0].matched_field == "public_id"
    assert by_public.mutants[0].internal_id == str(line.id)

    assert [m.name for m in by_name.mutants] == ["lab-2"]
    assert by_name.mutants[0].matched_field == "name"
    assert by_name.mutants[0].public_id == "SMPUB00002"
    assert by_name.mutants[0].internal_id == str(line.id)

    assert [m.public_id for m in by_internal.mutants] == ["SMPUB00002"]
    assert by_internal.mutants[0].matched_field == "internal_id"
    assert by_internal.mutants[0].internal_id == str(line.id)
    assert by_internal.mutants[0].match_type == MatchType.EXACT


@pytest.mark.asyncio
async def test_unpublished_mutant_is_visible_internally_only(db_session):
    """Internal scope includes unpublished rows; external scope excludes them."""
    await _create_active_assembly(db_session, "internal-db")
    embargoed = MutantLine(name="lab-embargo", public_id=None, is_public=False)
    db_session.add(embargoed)
    await db_session.commit()

    service = SearchService()
    internal = await service.internal_search(db_session, "lab-embargo", release_id=None)
    assert len(internal.mutants) == 1
    assert internal.mutants[0].is_public is False

    external = await service.global_search(
        db_session, "lab-embargo", types=[SearchResultType.MUTANT_LINE]
    )
    assert external.results == []


@pytest.mark.asyncio
async def test_suggest_fails_closed_without_active_release(client, db_session):
    """P0-02: anonymous suggest never exposes data without a published release."""
    draft = Release(
        version="suggest-draft-only",
        name="suggest draft only",
        status=ReleaseStatus.DRAFT,
    )
    db_session.add(draft)
    await db_session.flush()
    assembly = Assembly(
        name="suggest-draft-asm",
        species="Glycine max",
        version="v1",
        release_id=draft.id,
    )
    db_session.add(assembly)
    await db_session.flush()
    await _add_gene(db_session, assembly, "SUGGDRAFTONLY", name="draft only gene")
    await db_session.commit()

    response = await client.get(
        "/api/v1/search/suggest", params={"q": "SUGGDRAFTONLY"}
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_suggest_is_scoped_to_the_active_release(client, db_session):
    """P0-02: a draft assembly accession is not suggested beside the active release."""
    active_assembly, _active_release = await _create_active_assembly(
        db_session, "suggest-active"
    )
    await _add_gene(db_session, active_assembly, "SUGGACTIVE01", name="active gene")

    draft = Release(
        version="suggest-draft-secondary",
        name="suggest draft secondary",
        status=ReleaseStatus.DRAFT,
    )
    db_session.add(draft)
    await db_session.flush()
    draft_assembly = Assembly(
        name="suggest-draft-secondary-asm",
        species="Glycine max",
        version="v1",
        release_id=draft.id,
    )
    db_session.add(draft_assembly)
    await db_session.flush()
    await _add_gene(db_session, draft_assembly, "SUGGDRAFT02", name="draft gene 2")
    await db_session.commit()

    response = await client.get("/api/v1/search/suggest", params={"q": "SUGG"})
    assert response.status_code == 200
    texts = {item["text"] for item in response.json()}
    assert "SUGGACTIVE01" in texts
    assert "SUGGDRAFT02" not in texts


@pytest.mark.asyncio
async def test_unscoped_ambiguity_is_judged_over_full_match_set(db_session):
    """P0-03/ASM-04: a truncated page must not hide cross-assembly ambiguity."""
    v4, shared_release = await _create_active_assembly(
        db_session, "ambig-a4", version="v4"
    )
    v5 = Assembly(
        name="ambig-a5",
        species="Glycine max",
        version="v5",
        release_id=shared_release.id,
    )
    db_session.add(v5)
    await db_session.flush()
    await _add_gene(db_session, v4, "Glyma.01G000100", name="shared locus")
    await _add_gene(db_session, v5, "Glyma.01G000100", name="shared locus")

    service = SearchService()
    response = await service.global_search(
        db_session, "Glyma.01G000100", types=[SearchResultType.GENE], limit=1
    )

    # Only one row fits the page, but ambiguity is a property of the whole set.
    assert len(response.results) == 1
    assert response.ambiguous is True
    assert response.by_assembly == {str(v4.id): 1, str(v5.id): 1}
    # The hit carries a human-readable assembly label alongside the numeric id.
    assert response.results[0].assembly_id in {v4.id, v5.id}
    assert response.results[0].assembly
