"""Scope-integrity regressions for search caching and cross-version links.

GAP-3 (federated cache key): the shared federated cache used to key on
(query, sources) only, so requests differing by site variant, release,
assembly or active filter collided on one entry.  The scoped key is pinned
here without a live Redis.

GAP-1 (cross-version producer): a gene hit carries an explicit
cross_version link only when a provenance-bearing gene_crosswalks row
exists.  The positive case needs the real PostgreSQL fixture, matching the
existing search integration convention.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.v1.search import _external_html_cache_key
from app.core.site_variant import SiteVariant
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.genomic import Assembly, Chromosome, Gene, GeneCrosswalk
from app.schemas.search import MatchType, SearchResultType
from app.search import ExternalSearchAggregator
from app.search.cache import SearchCache
from app.search.models import SearchSource, SourceResult, SourceStatus
from app.services.search_service import SearchService


class FakeRedis:
    """Minimal async Redis stand-in for the best-effort search cache."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gets: list[str] = []
        self.sets: list[str] = []

    async def get(self, key: str):
        self.gets.append(key)
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self.sets.append(key)
        self.store[key] = value

    async def delete(self, key: str):
        self.store.pop(key, None)


class _EmptyAdapter:
    """Adapter returning no hits and performing no HTTP."""

    def __init__(self, source: SearchSource) -> None:
        self.source = source
        self.timeout = 0.1

    async def search(self, query: str, limit: int, client: object) -> SourceResult:
        return SourceResult(source=self.source, status=SourceStatus.EMPTY, hits=[])


# --------------------------------------------------------------------------- GAP-3
def test_scoped_key_requires_explicit_site_variant() -> None:
    with pytest.raises(TypeError):
        SearchCache.make_key("Glyma", ("ncbi",))  # type: ignore[call-arg]


def test_scoped_key_separates_site_variant_namespaces() -> None:
    external = SearchCache.make_key("Glyma", ("ncbi",), site_variant=SiteVariant.EXTERNAL)
    internal = SearchCache.make_key("Glyma", ("ncbi",), site_variant=SiteVariant.INTERNAL)
    assert external != internal
    assert external.startswith("search:external:")
    assert internal.startswith("search:internal:")


def test_scoped_key_separates_release_assembly_and_filters() -> None:
    base = SearchCache.make_key(
        "Glyma",
        ("ncbi",),
        site_variant=SiteVariant.EXTERNAL,
        release_id=7,
        assembly_id=11,
        filters={"limit_per_source": 8},
    )
    other_release = SearchCache.make_key(
        "Glyma",
        ("ncbi",),
        site_variant=SiteVariant.EXTERNAL,
        release_id=8,
        assembly_id=11,
        filters={"limit_per_source": 8},
    )
    other_assembly = SearchCache.make_key(
        "Glyma",
        ("ncbi",),
        site_variant=SiteVariant.EXTERNAL,
        release_id=7,
        assembly_id=12,
        filters={"limit_per_source": 8},
    )
    other_filter = SearchCache.make_key(
        "Glyma",
        ("ncbi",),
        site_variant=SiteVariant.EXTERNAL,
        release_id=7,
        assembly_id=11,
        filters={"limit_per_source": 20},
    )
    missing_release = SearchCache.make_key(
        "Glyma",
        ("ncbi",),
        site_variant=SiteVariant.EXTERNAL,
        release_id=None,
        assembly_id=11,
        filters={"limit_per_source": 8},
    )
    assert len({base, other_release, other_assembly, other_filter, missing_release}) == 5


def test_scoped_key_is_stable_and_source_order_insensitive() -> None:
    first = SearchCache.make_key("Glyma", ("uniprot", "ncbi"), site_variant=SiteVariant.EXTERNAL)
    second = SearchCache.make_key("Glyma", ("ncbi", "uniprot"), site_variant=SiteVariant.EXTERNAL)
    assert first == second


def test_external_html_cache_key_separates_assembly_and_limit() -> None:
    v4 = _external_html_cache_key("Glyma", [SearchSource.NCBI], assembly_id=11, limit_per_source=8)
    v5 = _external_html_cache_key("Glyma", [SearchSource.NCBI], assembly_id=12, limit_per_source=8)
    unscoped = _external_html_cache_key(
        "Glyma", [SearchSource.NCBI], assembly_id=None, limit_per_source=8
    )
    other_limit = _external_html_cache_key(
        "Glyma", [SearchSource.NCBI], assembly_id=11, limit_per_source=20
    )
    assert len({v4, v5, unscoped, other_limit}) == 4
    assert v4.startswith("search:external:")


@pytest.mark.asyncio
async def test_aggregator_cache_key_carries_scope_and_limit() -> None:
    async def key_for(limit: int = 8, **scope: object) -> str:
        redis = FakeRedis()
        aggregator = ExternalSearchAggregator(redis, shared_http_client=object(), **scope)
        aggregator._adapters = {SearchSource.NCBI: _EmptyAdapter(SearchSource.NCBI)}
        await aggregator.search("Glyma", sources=[SearchSource.NCBI], limit_per_source=limit)
        return redis.sets[0]

    base = await key_for(site_variant=SiteVariant.EXTERNAL, release_id=7, assembly_id=11)
    other_release = await key_for(site_variant=SiteVariant.EXTERNAL, release_id=8, assembly_id=11)
    other_assembly = await key_for(site_variant=SiteVariant.EXTERNAL, release_id=7, assembly_id=12)
    other_limit = await key_for(
        limit=20, site_variant=SiteVariant.EXTERNAL, release_id=7, assembly_id=11
    )
    internal = await key_for(site_variant=SiteVariant.INTERNAL, release_id=7, assembly_id=11)
    assert len({base, other_release, other_assembly, other_limit, internal}) == 5
    assert base.startswith("search:external:")
    assert internal.startswith("search:internal:")


# --------------------------------------------------------------------------- GAP-1
async def _seed_gene_pair(db_session):
    release = Release(
        version="scope-prov-release",
        name="scope prov release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(release)
    await db_session.flush()
    db_session.add(ActiveRelease(id=1, release_id=release.id))
    await db_session.flush()

    async def add_gene(assembly: Assembly, accession: str) -> Gene:
        chrom = (
            await db_session.execute(
                select(Chromosome).where(
                    Chromosome.assembly_id == assembly.id, Chromosome.name == "Gm01"
                )
            )
        ).scalar_one_or_none()
        if chrom is None:
            chrom = Chromosome(assembly_id=assembly.id, name="Gm01", length=100_000, order=1)
            db_session.add(chrom)
            await db_session.flush()
        gene = Gene(
            accession=accession,
            assembly_id=assembly.id,
            chromosome_id=chrom.id,
            name=f"gene {accession}",
            biotype="protein_coding",
            start=1,
            end=10,
            strand="+",
        )
        db_session.add(gene)
        await db_session.flush()
        return gene

    source_assembly = Assembly(
        name="scope-prov-a4", species="Glycine max", version="v4", release_id=release.id
    )
    target_assembly = Assembly(
        name="scope-prov-a5", species="Glycine max", version="v5", release_id=release.id
    )
    db_session.add_all([source_assembly, target_assembly])
    await db_session.flush()
    source = await add_gene(source_assembly, "SCPPROV01")
    target = await add_gene(target_assembly, "SCPPROV02")
    return source, target


@pytest.mark.asyncio
async def test_cross_version_link_exists_only_with_crosswalk_row(db_session):
    source, target = await _seed_gene_pair(db_session)
    service = SearchService()

    without = await service.global_search(
        db_session, source.accession, types=[SearchResultType.GENE]
    )
    assert [item.id for item in without.results] == [source.accession]
    assert without.results[0].cross_version == [], (
        "no crosswalk row must mean no cross-version link"
    )

    db_session.add(
        GeneCrosswalk(
            source_gene_id=source.gene_pk,
            target_gene_id=target.gene_pk,
            relation_type="one_to_one",
            provenance_source="scope-unit-fixture",
        )
    )
    await db_session.flush()

    with_row = await service.global_search(
        db_session, source.accession, types=[SearchResultType.GENE]
    )
    assert [item.id for item in with_row.results] == [source.accession]
    assert with_row.total_count == 1
    # The matched hit keeps its own type; the relation is attached, not a row.
    assert with_row.results[0].match_type == MatchType.EXACT
    links = with_row.results[0].cross_version
    assert len(links) == 1
    assert links[0].gene_accession == target.accession
    assert links[0].assembly_id == target.assembly_id
    assert links[0].match_type == MatchType.CROSS_VERSION
    assert links[0].relation_type == "one_to_one"
    assert links[0].provenance_source == "scope-unit-fixture"
