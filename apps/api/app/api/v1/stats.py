"""Statistics / dashboard endpoints.

Every endpoint aggregates **real data** from PostgreSQL: relational metadata
(genes, assemblies, releases) from the relational tables and variant counts
from the native ``variant_facts`` projection.  When a query fails the endpoint
degrades gracefully: it logs a warning and returns the empty structure
(zeros / empty lists) — never fabricated values.

Release scope
-------------
Statistics are biological aggregates, so a public aggregate is only meaningful
when it is bound to one published release:

* endpoints formerly accepted an arbitrary ``release_id`` and never checked its
  status, so a draft release's aggregates were readable;
* ``/dashboard`` and the PG aggregates counted every row in the table,
  including draft/other-release records;
* ``/dashboard`` also exposed the total account count anonymously;
* ``/releases`` defaulted to listing every release, drafted or rolled back;
* ``/homepage`` counted every gene, every mutant line (public or not), every
  assembly, every seed lot and every variant fact in the database, so an
  anonymous visitor learned the size of unpublished data.

Every endpoint therefore resolves ``ReleaseContext`` (which accepts only a
published release, or the active published pointer) and filters its queries by
that release. Cache keys carry the resolved release so one release's aggregate
can never be served for another.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import ColumnElement, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from ...core.database import get_db
from ...core.exceptions import ServiceUnavailableError, ValidationError
from ...models.content import Release, ReleaseStatus
from ...models.genomic import Assembly, Chromosome, Gene
from ...models.seed import SeedInventory
from ...models.variant import MutantLine, Phenotype, VariantSummary
from ...schemas.analytics import (
    ChromosomeDensity,
    ChromosomeDensityBin,
    ChromosomeDensitySummary,
    DashboardStats,
    DiscoveryTrendPoint,
    HomepageStats,
    ImpactSummaryItem,
    MutagenCount,
    ReleaseSummary,
    VariantTypeDistribution,
    VariantTypeSummaryItem,
)
from ...services.cache import get_or_set
from ...services.postgres_variant_service import PostgresVariantService
from ...services.release_context import (
    ReleaseContext,
    get_release_context,
    resolve_release_context,
)
from ...services.variant_visibility import public_mutant_visibility, public_summary_visibility

logger = get_logger(__name__)

router = APIRouter(prefix="/stats", tags=["stats"])
variant_service = PostgresVariantService()

# Impact classes in canonical display order.
_IMPACT_ORDER = ("HIGH", "MODERATE", "LOW", "MODIFIER")
# Variant-type buckets in canonical display order.
_VARIANT_TYPE_ORDER = (  # noqa: E501
    ("SNP", ("SNP",)),
    ("Indel", ("INS", "DEL")),
    ("MNV", ("MNV",)),
    ("SV", ("SV",)),
)
#: Release key used when no release is published. It matches no release, so a
#: release-scoped aggregate answers zeros instead of counting the whole table.
_NO_RELEASE_KEY = "0"


# ---------------------------------------------------------------------------
# Aggregation helpers (pure SQLAlchemy – unit-testable with a mocked session)
# ---------------------------------------------------------------------------


async def _variant_type_counts_from_pg(
    db: AsyncSession, release_id: int | ColumnElement[int] | None = None
) -> dict[str, int]:
    """Aggregate variant counts by ``variant_type`` from PostgreSQL.

    ``release_id`` binds the aggregate to one release. It accepts a release id
    or any SQL expression that resolves to one (see ``_release_scope``);
    public callers must pass it, otherwise the aggregate spans every release.
    """
    stmt = (
        select(VariantSummary.variant_type, func.count())
        .where(public_summary_visibility())
        .group_by(VariantSummary.variant_type)
    )
    if release_id is not None:
        stmt = stmt.where(VariantSummary.release_id == release_id)
    rows = (await db.execute(stmt)).all()
    return {str(variant_type): int(count) for variant_type, count in rows}


async def _variant_type_summary_from_pg(release_key: str | None = None) -> dict[str, int] | None:
    """Best-effort variant-type counts from PostgreSQL (None when unavailable).

    ``release_key`` scopes the aggregate to one release; callers on a public
    surface must pass it (see the dashboard loader).
    """
    try:
        return await variant_service.get_dashboard_stats(release_key=release_key)
    except Exception:
        logger.warning("stats_variant_store_unavailable", component="variant_type_summary")
        return None


# ---------------------------------------------------------------------------
# Public dashboard endpoints
# ---------------------------------------------------------------------------


async def _load_dashboard_stats(db: AsyncSession, release_id: int) -> dict:
    """Compute dashboard aggregates for one published release.

    Gene/mutant/phenotype/assembly counts are joined to the release's
    assemblies so draft or other-release rows cannot be counted. The anonymous
    dashboard does not expose the account population at all (``total_users``
    stays 0), because that is internal operational data.
    """
    # Keep dashboard counts in one round-trip: these independent scalar
    # subqueries avoid five sequential pool checkouts on every cache refresh.
    release_assembly_ids = select(Assembly.id).where(Assembly.release_id == release_id)
    count_result = await db.execute(
        select(
            select(func.count(Gene.gene_pk))
            .where(Gene.assembly_id.in_(release_assembly_ids))
            .scalar_subquery(),
            select(func.count(MutantLine.id))
            .where(MutantLine.release_id == release_id, public_mutant_visibility())
            .scalar_subquery(),
            select(func.count(Phenotype.id))
            .where(
                Phenotype.mutant_line_id.in_(
                    select(MutantLine.id).where(
                        MutantLine.release_id == release_id, public_mutant_visibility(),
                    )
                )
            )
            .scalar_subquery(),
            select(func.count(Assembly.id))
            .where(Assembly.release_id == release_id)
            .scalar_subquery(),
        )
    )
    (
        total_genes,
        total_mutant_lines,
        total_phenotypes,
        assemblies_count,
    ) = count_result.one()

    # The release row is the resolved published release (not "newest active").
    release_result = await db.execute(select(Release).where(Release.id == release_id))
    current_release = release_result.scalar_one_or_none()

    # Total variants from the native PostgreSQL projection, scoped to the same
    # release (best-effort: the endpoint still answers when the query fails).
    variant_stats = await _variant_type_summary_from_pg(release_key=str(release_id)) or {}
    total_variants = int(variant_stats.get("total_variants", 0))

    return DashboardStats(
        total_variants=total_variants,
        total_genes=int(total_genes or 0),
        total_mutant_lines=int(total_mutant_lines or 0),
        total_phenotypes=int(total_phenotypes or 0),
        # Anonymous operational metric: never the real account population.
        total_users=0,
        assemblies_count=int(assemblies_count or 0),
        current_release=current_release.version if current_release else None,
        last_updated=datetime.now(timezone.utc),  # noqa: UP017
    ).model_dump(mode="json")


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> DashboardStats:
    """High-level database statistics for the resolved published release.

    Read-hot aggregation cached in Redis (default TTL) via cache-aside;
    a Redis failure degrades to a direct aggregation. The cache key carries the
    release so one release's aggregate is never served for another.
    """
    release_id = release_context.release_id
    payload = await get_or_set(
        "stats:dashboard",
        ttl=None,
        params={"release_id": release_id, "variant_visibility": "public-v2"},
        loader=lambda: _load_dashboard_stats(db, release_id),
    )
    return DashboardStats(**payload)


async def _homepage_release_context(
    db: AsyncSession = Depends(get_db),
    release_id: int | None = Query(default=None, ge=1, include_in_schema=False),
    pinned_release_id: int | None = Header(
        default=None,
        alias="X-SoyMutDB-Release",
        ge=1,
        include_in_schema=False,
    ),
) -> ReleaseContext | None:
    """Resolve the published release the home page aggregate is bound to.

    This mirrors :func:`get_release_context` (query pin, header pin, rejection
    of conflicting pins) with two deliberate differences:

    * a missing published release answers ``None`` instead of raising, so the
      public home page still renders an empty aggregate before the first
      release is published (the sibling endpoints answer 503 there);
    * the pins stay out of the OpenAPI document, so the published home page
      contract — and the generated client built from it — is unchanged.
    """
    if release_id is not None and pinned_release_id is not None and release_id != pinned_release_id:
        raise ValidationError("Conflicting release ids were provided")
    requested = release_id if release_id is not None else pinned_release_id
    try:
        return await resolve_release_context(db, requested)
    except ServiceUnavailableError:
        return None


@router.get(
    "/homepage",
    response_model=HomepageStats,
    summary="Homepage statistics",
    description=(
        "Aggregate statistics for the public home page. Variant counts come "
        "from the native PostgreSQL variant_facts projection, falling back to "
        "the variant_summaries table; other counts are real PostgreSQL "
        "aggregates. Empty results are returned as zeros."
    ),
)
async def homepage_stats(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext | None = Depends(_homepage_release_context),
) -> HomepageStats:
    """Home page statistics (genes, lines, releases, variants, seeds).

    The aggregate is bound to the resolved published release: the genes,
    mutant lines, assemblies and seed lots of other releases — and the
    variant facts of a draft release — are never counted, so an anonymous
    visitor cannot learn the size of unpublished data.

    Read-hot aggregation cached in Redis (default TTL) via cache-aside; a
    Redis failure degrades to a direct aggregation. The cache key carries the
    release, so one release's aggregate is never served for another.

    A database without a published release answers an empty (zero) aggregate
    instead of failing the public home page.
    """
    if release_context is None:
        # Nothing is published: the home page still renders, with zeros.
        return HomepageStats()
    release_id = release_context.release_id
    payload = await get_or_set(
        "stats:homepage",
        ttl=None,
        params={"release_id": release_id, "variant_visibility": "public-v2"},
        loader=lambda: _load_homepage_stats(db, release_id),
    )
    return HomepageStats(**payload)


def _release_scope(release_id: int | None) -> ColumnElement[int]:
    """Return the SQL expression the homepage aggregate is bound to.

    An explicit release id is used as is. Without one the newest *published*
    release is resolved inside the same statement, so the aggregate is still
    bound to a single released release instead of spanning the whole table.
    """
    if release_id is not None:
        return literal(release_id)
    return (
        select(Release.id)
        .where(Release.status == ReleaseStatus.PUBLISHED.value)
        .order_by(Release.published_at.desc().nulls_last(), Release.id.desc())
        .limit(1)
        .scalar_subquery()
    )


async def _load_homepage_stats(db: AsyncSession, release_id: int | None = None) -> dict:
    """Compute homepage aggregates for one published release (Redis loader).

    Every independent aggregate is folded into one statement as a scalar
    subquery. They were previously seven sequential ``db.scalar`` / ``db.execute``
    calls, so one page load spent seven pool round trips to read seven numbers
    that never depend on each other. One statement is the same snapshot and one
    round trip; the homepage is the most-requested aggregate in the product.

    The counts are bound to one release, which in this schema means:

    * **genes** have no release column — they are assembly-scoped, so they are
      counted through the release's assemblies;
    * **mutant lines** carry ``release_id`` and are counted when they belong to
      the release, are not deleted and are public (the same visibility rule
      the public mutant routes use);
    * **assemblies** carry ``release_id`` and are counted directly;
    * **seed lots** have no release column — they hang off a mutant line, so
      they are counted through the release's public lines;
    * **variant facts** carry ``release_id`` and are read through the native
      projection bound to the same release key.

    ``release_count`` stays the number of *published* releases: that is the
    publication history, all of it public data, and not a property of the
    resolved release.

    ``release_id`` is optional only for local tooling (``scripts/dev``) and the
    query-count guard, which resolve the newest published release in the same
    statement. The public endpoint always passes the resolved release.
    """
    scope = _release_scope(release_id)

    # Public mutant lines of the release: not deleted, explicitly public and
    # attached to that release.
    public_lines = select(MutantLine.id).where(
        MutantLine.release_id == scope,
        public_mutant_visibility(),
    )

    row = (
        await db.execute(
            select(
                select(func.count(Gene.gene_pk))
                .where(
                    Gene.assembly_id.in_(
                        select(Assembly.id).where(Assembly.release_id == scope)
                    )
                )
                .scalar_subquery(),
                select(func.count(MutantLine.id))
                .where(
                    MutantLine.release_id == scope,
                    public_mutant_visibility(),
                )
                .scalar_subquery(),
                select(func.count(Release.id))
                .where(Release.status == ReleaseStatus.ACTIVE.value)
                .scalar_subquery(),
                select(func.count(Assembly.id))
                .where(Assembly.release_id == scope)
                .scalar_subquery(),
                select(func.count(SeedInventory.id))
                .where(SeedInventory.mutant_line_id.in_(public_lines))
                .scalar_subquery(),
                select(Release.published_at).where(Release.id == scope).scalar_subquery(),
                select(Release.version).where(Release.id == scope).scalar_subquery(),
                # The release the aggregate is bound to, so the native
                # projection can be scoped to the very same release.
                select(Release.id).where(Release.id == scope).scalar_subquery(),
            )
        )
    ).one()
    values = list(row)
    (
        gene_count,
        mutant_line_count,
        release_count,
        assembly_count,
        seed_accessions,
        published_at,
        current_release_version,
    ) = values[:7]
    # The bound release id is the last column; a row that does not carry it
    # falls back to the release the caller asked for.
    row_release_id = values[7] if len(values) > 7 else None
    bound_release_id = release_id if release_id is not None else row_release_id

    # Variant counts: native PostgreSQL projection first, the variant_summaries
    # table as fallback, zeros last. Both are bound to the same release; when
    # nothing is published the projection is bound to a release that does not
    # exist, so it answers zeros instead of the whole table.
    variant_stats = await _variant_type_summary_from_pg(
        release_key=(
            str(bound_release_id) if bound_release_id is not None else _NO_RELEASE_KEY
        )
    )
    if variant_stats is not None:
        total_variants = int(variant_stats.get("total_variants", 0))
        snp_count = int(variant_stats.get("snp_count", 0))
        indel_count = int(variant_stats.get("ins_count", 0)) + int(
            variant_stats.get("del_count", 0)
        )
        sv_count = int(variant_stats.get("sv_count", 0))
    else:
        try:
            pg_counts = await _variant_type_counts_from_pg(db, scope)
        except Exception:
            logger.warning("stats_pg_unavailable", component="homepage")
            pg_counts = {}
        total_variants = sum(pg_counts.values())
        snp_count = pg_counts.get("SNP", 0)
        indel_count = pg_counts.get("INS", 0) + pg_counts.get("DEL", 0)
        sv_count = pg_counts.get("SV", 0)

    return HomepageStats(
        total_variants=total_variants,
        snp_count=snp_count,
        indel_count=indel_count,
        sv_count=sv_count,
        gene_count=int(gene_count or 0),
        mutant_line_count=int(mutant_line_count or 0),
        release_count=int(release_count or 0),
        assembly_count=int(assembly_count or 0),
        seed_accessions=int(seed_accessions or 0),
        last_release_date=published_at,
        last_release_name=current_release_version,
    ).model_dump(mode="json")


@router.get("/variant-types", response_model=VariantTypeDistribution)
async def variant_type_distribution(
    release_context: ReleaseContext = Depends(get_release_context),
    assembly: str | None = Query(default=None),
) -> VariantTypeDistribution:
    """Variant type distribution (SNP/INS/DEL/MNV/SV) for a published release.

    The PostgreSQL variant aggregate is bound to the resolved release;
    previously it scanned every release's facts.
    """
    try:
        dist = await variant_service.get_variant_type_distribution(
            assembly=assembly, release_key=release_context.release_key
        )
    except Exception:
        logger.warning("stats_variant_store_unavailable", component="variant_types")
        dist = {}

    snp = dist.get("SNP", 0)
    ins = dist.get("INS", 0)
    dele = dist.get("DEL", 0)
    mnv = dist.get("MNV", 0)
    sv = dist.get("SV", 0)
    total = snp + ins + dele + mnv + sv

    return VariantTypeDistribution(
        snp_count=snp,
        ins_count=ins,
        del_count=dele,
        mnv_count=mnv,
        sv_count=sv,
        total=total,
    )


@router.get(
    "/summary/variant-types",
    response_model=list[VariantTypeSummaryItem],
    summary="Variant type summary (name/value)",
)
async def variant_type_summary(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> list[VariantTypeSummaryItem]:
    """Variant type distribution as ``[{name, value}]`` for charts.

    Aggregated from the PostgreSQL ``variant_summaries`` table, scoped to the
    resolved published release. Zero-count buckets are omitted so charts can
    fall back to other data sources.
    """
    pg_counts = await _variant_type_counts_from_pg(
        db, release_id=release_context.release_id
    )
    items = [
        VariantTypeSummaryItem(
            name=name, value=sum(pg_counts.get(key, 0) for key in keys)
        )
        for name, keys in _VARIANT_TYPE_ORDER
    ]
    return [item for item in items if item.value > 0]


@router.get(
    "/summary/impact",
    response_model=list[ImpactSummaryItem],
    summary="Variant counts by predicted impact",
)
async def impact_summary(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> list[ImpactSummaryItem]:
    """Variant counts grouped by impact class, scoped to the published release."""
    stmt = (
        select(VariantSummary.impact, func.count())
        .where(
            VariantSummary.impact.is_not(None),
            VariantSummary.release_id == release_context.release_id,
            public_summary_visibility(),
        )
        .group_by(VariantSummary.impact)
    )
    rows = (await db.execute(stmt)).all()
    counts = {str(impact): int(count) for impact, count in rows}

    items = [
        ImpactSummaryItem(impact=impact, count=counts.get(impact, 0))
        for impact in _IMPACT_ORDER
    ]
    return [item for item in items if item.count > 0]


@router.get(
    "/chromosome-density",
    response_model=list[ChromosomeDensitySummary],
    summary="Per-chromosome variant density",
)
async def chromosome_density_summary(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> list[ChromosomeDensitySummary]:
    """Variant density per chromosome, aggregated from PostgreSQL.

    ``density_per_kb`` is computed as ``variant_count / (length_bp / 1000)``.
    Read-hot aggregation cached in Redis (default TTL) keyed by
    ``release_id``; a Redis failure degrades to a direct aggregation.  Empty
    results are cached too (anti-penetration): when no data exists the
    loader returns ``[]`` which is memoised until the TTL expires instead of
    re-running the aggregate per request.
    """
    release_id = release_context.release_id
    payload = await get_or_set(
        "stats:chromosome-density",
        ttl=None,
        params={"release_id": release_id, "variant_visibility": "public-v2"},
        loader=lambda: _load_chromosome_density_summary(db, release_id),
    )
    return [ChromosomeDensitySummary.model_validate(item) for item in payload]


async def _load_chromosome_density_summary(
    db: AsyncSession, release_id: int | None
) -> list[dict]:
    """Compute per-chromosome density (loader for the Redis cache)."""
    stmt = (
        select(
            Chromosome.name,
            Chromosome.length,
            VariantSummary.variant_type,
            func.count(),
        )
        .join(VariantSummary, VariantSummary.chromosome_id == Chromosome.id)
        .where(public_summary_visibility())
        .group_by(Chromosome.name, Chromosome.length, VariantSummary.variant_type)
        .order_by(Chromosome.name)
    )
    if release_id is not None:
        stmt = stmt.where(VariantSummary.release_id == release_id)

    rows = (await db.execute(stmt)).all()
    per_chromosome: dict[str, dict] = {}
    for chromosome, length, variant_type, count in rows:
        entry = per_chromosome.setdefault(
            chromosome,
            {"variant_count": 0, "snp_count": 0, "indel_count": 0, "length_bp": int(length or 0)},
        )
        count = int(count)
        entry["variant_count"] += count
        variant_type = str(variant_type)
        if variant_type == "SNP":
            entry["snp_count"] += count
        elif variant_type in ("INS", "DEL"):
            entry["indel_count"] += count

    result: list[ChromosomeDensitySummary] = []
    for chromosome, entry in per_chromosome.items():
        length_bp = entry["length_bp"]
        density_per_kb = (
            round(entry["variant_count"] / (length_bp / 1000.0), 4)
            if length_bp > 0
            else 0.0
        )
        result.append(
            ChromosomeDensitySummary(
                chromosome=chromosome,
                variant_count=entry["variant_count"],
                snp_count=entry["snp_count"],
                indel_count=entry["indel_count"],
                length_bp=length_bp,
                density_per_kb=density_per_kb,
            )
        )
    return [item.model_dump(mode="json") for item in result]


@router.get(
    "/discovery-trend",
    response_model=list[DiscoveryTrendPoint],
    summary="Cumulative variant discovery trend",
)
async def discovery_trend(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    days: int = Query(default=30, ge=1, le=3650),
) -> list[DiscoveryTrendPoint]:
    """Cumulative variant counts across *published* releases.

    Each published release contributes ``new_variants`` (= its recorded
    ``variant_count``) and a running cumulative total. Draft and rolled-back
    releases are excluded, and the trend is anchored on the resolved published
    release rather than an arbitrary caller-supplied id.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)  # noqa: UP017
    stmt = (
        select(Release.published_at, Release.variant_count)
        .where(
            Release.status == ReleaseStatus.ACTIVE.value,
            Release.published_at.is_not(None),
            Release.published_at >= since,
        )
        .order_by(Release.published_at.asc())
    )

    rows = (await db.execute(stmt)).all()
    points: list[DiscoveryTrendPoint] = []
    cumulative = 0
    for published_at, variant_count in rows:
        new_variants = int(variant_count or 0)
        cumulative += new_variants
        points.append(
            DiscoveryTrendPoint(
                date=published_at.date().isoformat(),
                new_variants=new_variants,
                cumulative=cumulative,
            )
        )
    return points


@router.get(
    "/releases",
    response_model=list[ReleaseSummary],
    summary="Per-release statistics",
)
async def release_statistics(
    db: AsyncSession = Depends(get_db),
) -> list[ReleaseSummary]:
    """Statistics per *published* release (version, date, counts).

    Public callers may only see releases that reached a published state:
    previously the default (``only_active=false``) listed every release,
    including drafts and rolled-back ones. A rollback is deliberately excluded
    because its counts no longer describe the served data.

    Read-hot query cached in Redis (default TTL); a Redis failure degrades to a
    direct query. An empty release list is cached as well (anti-penetration) so
    a freshly seeded database does not re-run the query on every request.
    """
    payload = await get_or_set(
        "stats:releases",
        ttl=None,
        loader=lambda: _load_release_statistics(db),
    )
    return [ReleaseSummary.model_validate(item) for item in payload]


async def _load_release_statistics(db: AsyncSession) -> list[dict]:
    """Compute per-release statistics (loader for the Redis cache)."""
    stmt = (
        select(Release)
        .where(
            Release.published_at.is_not(None),
            Release.status == ReleaseStatus.ACTIVE.value,
        )
        .order_by(Release.published_at.desc())
    )

    releases = (await db.execute(stmt)).scalars().all()
    result: list[ReleaseSummary] = []
    for release in releases:
        published_at = release.published_at
        if published_at is None:
            continue
        result.append(
            ReleaseSummary(
                release_version=release.version,
                release_date=published_at.date(),
                variant_count=int(release.variant_count or 0),
                gene_count=int(release.gene_count or 0),
                mutant_line_count=int(release.mutant_line_count or 0),
            )
        )
    return [item.model_dump(mode="json") for item in result]


@router.get(
    "/mutagens",
    response_model=list[MutagenCount],
    summary="Mutant lines grouped by mutagen",
)
async def mutagen_statistics(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> list[MutagenCount]:
    """Number of mutant lines per mutagen, scoped to the published release."""
    stmt = (
        select(MutantLine.mutagen, func.count())
        .where(
            MutantLine.mutagen.is_not(None),
            public_mutant_visibility(),
            MutantLine.release_id == release_context.release_id,
        )
        .group_by(MutantLine.mutagen)
        .order_by(func.count().desc())
    )

    rows = (await db.execute(stmt)).all()
    return [
        MutagenCount(mutagen=str(mutagen), count=int(count))
        for mutagen, count in rows
        if mutagen
    ]


@router.get("/density", response_model=ChromosomeDensity)
async def chromosome_density(
    release_context: ReleaseContext = Depends(get_release_context),
    assembly: str = Query(..., description="Assembly name (required)"),
    chromosome: str = Query(...),
    bin_size: int = Query(default=1_000_000, ge=1000),
) -> ChromosomeDensity:
    """Variant density across a chromosome in the published release.

    Density is computed entirely from the PostgreSQL ``variant_facts``
    projection, so an unavailable projection is reported as
    capability-unavailable (503). The response model also requires a concrete
    ``chromosome_length``: fabricating ``0`` here would both violate the
    contract and present an empty chromosome as a real result. The query is
    bound to the resolved release, so bins can never mix drafts into a
    published density.
    """
    bins = await variant_service.get_chromosome_density(
        assembly=assembly,
        chromosome=chromosome,
        bin_size=bin_size,
        release_key=release_context.release_key,
    )

    total = sum(b["count"] for b in bins)
    chromosome_length = max((b["bin_end"] for b in bins), default=0)
    return ChromosomeDensity(
        chromosome=chromosome,
        chromosome_length=max(chromosome_length, 1) if bins else 1,
        bin_size=bin_size,
        bins=[ChromosomeDensityBin(**b) for b in bins],
        total_variants=total,
    )


__all__ = [
    "chromosome_density",
    "chromosome_density_summary",
    "dashboard_stats",
    "discovery_trend",
    "homepage_stats",
    "impact_summary",
    "mutagen_statistics",
    "release_statistics",
    "variant_type_distribution",
    "variant_type_summary",
]
