"""Statistics / dashboard endpoints.

Every endpoint aggregates **real data** from PostgreSQL and/or ClickHouse.
When a data source is unavailable (e.g. ClickHouse not provisioned) the
endpoint degrades gracefully: it logs a warning and returns the empty
structure (zeros / empty lists) — never fabricated values.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from ...core.database import get_db
from ...models.auth import User
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
from ...services.clickhouse_service import ClickHouseService

logger = get_logger(__name__)

router = APIRouter(prefix="/stats", tags=["stats"])
ch_service = ClickHouseService()

# Impact classes in canonical display order.
_IMPACT_ORDER = ("HIGH", "MODERATE", "LOW", "MODIFIER")
# Variant-type buckets in canonical display order.
_VARIANT_TYPE_ORDER = (  # noqa: E501
    ("SNP", ("SNP",)),
    ("Indel", ("INS", "DEL")),
    ("MNV", ("MNV",)),
    ("SV", ("SV",)),
)


# ---------------------------------------------------------------------------
# Aggregation helpers (pure SQLAlchemy – unit-testable with a mocked session)
# ---------------------------------------------------------------------------


async def _variant_type_counts_from_pg(
    db: AsyncSession, release_id: int | None = None
) -> dict[str, int]:
    """Aggregate variant counts by ``variant_type`` from PostgreSQL."""
    stmt = (
        select(VariantSummary.variant_type, func.count())
        .group_by(VariantSummary.variant_type)
    )
    if release_id is not None:
        stmt = stmt.where(VariantSummary.release_id == release_id)
    rows = (await db.execute(stmt)).all()
    return {str(variant_type): int(count) for variant_type, count in rows}


async def _variant_type_summary_from_ch() -> dict[str, int] | None:
    """Best-effort variant-type counts from ClickHouse (None when unavailable)."""
    try:
        return await ch_service.get_dashboard_stats()
    except Exception:
        logger.warning("stats_clickhouse_unavailable", component="variant_type_summary")
        return None


# ---------------------------------------------------------------------------
# Public dashboard endpoints
# ---------------------------------------------------------------------------


async def _load_dashboard_stats(db: AsyncSession) -> dict:
    """Compute dashboard aggregates (loader for the Redis cache)."""
    # Keep dashboard counts in one round-trip: these independent scalar
    # subqueries avoid five sequential pool checkouts on every cache refresh.
    count_result = await db.execute(
        select(
            select(func.count(Gene.gene_pk)).scalar_subquery(),
            select(func.count(MutantLine.id)).scalar_subquery(),
            select(func.count(Phenotype.id)).scalar_subquery(),
            select(func.count(Assembly.id)).scalar_subquery(),
            select(func.count(User.id))
            .where(User.is_deleted.is_(False))
            .scalar_subquery(),
        )
    )
    (
        total_genes,
        total_mutant_lines,
        total_phenotypes,
        assemblies_count,
        total_users,
    ) = count_result.one()

    # Current release version.
    release_result = await db.execute(
        select(Release)
        .where(Release.status == ReleaseStatus.ACTIVE)
        .order_by(Release.published_at.desc())
        .limit(1)
    )
    current_release = release_result.scalar_one_or_none()

    # Total variants from ClickHouse (best-effort).
    ch_stats = await _variant_type_summary_from_ch() or {}
    total_variants = int(ch_stats.get("total_variants", 0))

    return DashboardStats(
        total_variants=total_variants,
        total_genes=int(total_genes or 0),
        total_mutant_lines=int(total_mutant_lines or 0),
        total_phenotypes=int(total_phenotypes or 0),
        total_users=int(total_users or 0),
        assemblies_count=int(assemblies_count or 0),
        current_release=current_release.version if current_release else None,
        last_updated=datetime.now(timezone.utc),  # noqa: UP017
    ).model_dump(mode="json")


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
) -> DashboardStats:
    """High-level database statistics for the dashboard.

    Read-hot aggregation cached in Redis (default TTL) via cache-aside;
    a Redis failure degrades to a direct aggregation.
    """
    payload = await get_or_set(
        "stats:dashboard",
        ttl=None,
        loader=lambda: _load_dashboard_stats(db),
    )
    return DashboardStats(**payload)


@router.get(
    "/homepage",
    response_model=HomepageStats,
    summary="Homepage statistics",
    description=(
        "Aggregate statistics for the public home page. Variant counts come "
        "from ClickHouse when available, falling back to the PostgreSQL "
        "variant_summaries table; other counts are real PostgreSQL aggregates. "
        "Empty results are returned as zeros."
    ),
)
async def homepage_stats(
    db: AsyncSession = Depends(get_db),
) -> HomepageStats:
    """Home page statistics (genes, lines, releases, variants, seeds).

    Read-hot aggregation cached in Redis (default TTL) via cache-aside;
    a Redis failure degrades to a direct aggregation.
    """
    payload = await get_or_set(
        "stats:homepage",
        ttl=None,
        loader=lambda: _load_homepage_stats(db),
    )
    return HomepageStats(**payload)


async def _load_homepage_stats(db: AsyncSession) -> dict:
    """Compute homepage aggregates (loader for the Redis cache)."""
    gene_count = await db.scalar(select(func.count(Gene.gene_pk))) or 0
    mutant_line_count = (
        await db.scalar(
            select(func.count(MutantLine.id)).where(MutantLine.is_deleted.is_(False))
        )
        or 0
    )
    release_count = (
        await db.scalar(
            select(func.count(Release.id)).where(
                Release.status == ReleaseStatus.ACTIVE.value
            )
        )
        or 0
    )
    assembly_count = await db.scalar(select(func.count(Assembly.id))) or 0
    seed_accessions = await db.scalar(select(func.count(SeedInventory.id))) or 0

    release_result = await db.execute(
        select(Release)
        .where(Release.status == ReleaseStatus.ACTIVE.value)
        .order_by(Release.published_at.desc())
        .limit(1)
    )
    current_release = release_result.scalar_one_or_none()

    # Variant counts: ClickHouse first, PostgreSQL as fallback, zeros last.
    ch_stats = await _variant_type_summary_from_ch()
    if ch_stats is not None:
        total_variants = int(ch_stats.get("total_variants", 0))
        snp_count = int(ch_stats.get("snp_count", 0))
        indel_count = int(ch_stats.get("ins_count", 0)) + int(
            ch_stats.get("del_count", 0)
        )
        sv_count = int(ch_stats.get("sv_count", 0))
    else:
        try:
            pg_counts = await _variant_type_counts_from_pg(db)
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
        gene_count=int(gene_count),
        mutant_line_count=int(mutant_line_count),
        release_count=int(release_count),
        assembly_count=int(assembly_count),
        seed_accessions=int(seed_accessions),
        last_release_date=current_release.published_at if current_release else None,
        last_release_name=current_release.version if current_release else None,
    ).model_dump(mode="json")


@router.get("/variant-types", response_model=VariantTypeDistribution)
async def variant_type_distribution(
    assembly: str | None = Query(default=None),
) -> VariantTypeDistribution:
    """Variant type distribution (SNP/INS/DEL/MNV/SV)."""
    try:
        dist = await ch_service.get_variant_type_distribution(assembly=assembly)
    except Exception:
        logger.warning("stats_clickhouse_unavailable", component="variant_types")
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
    release_id: int | None = Query(default=None),
) -> list[VariantTypeSummaryItem]:
    """Variant type distribution as ``[{name, value}]`` for charts.

    Aggregated from the PostgreSQL ``variant_summaries`` table.  Zero-count
    buckets are omitted so charts can fall back to other data sources.
    """
    pg_counts = await _variant_type_counts_from_pg(db, release_id=release_id)
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
    release_id: int | None = Query(default=None),
) -> list[ImpactSummaryItem]:
    """Variant counts grouped by impact class (HIGH/MODERATE/LOW/MODIFIER)."""
    stmt = (
        select(VariantSummary.impact, func.count())
        .where(VariantSummary.impact.is_not(None))
        .group_by(VariantSummary.impact)
    )
    if release_id is not None:
        stmt = stmt.where(VariantSummary.release_id == release_id)
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
    release_id: int | None = Query(default=None),
) -> list[ChromosomeDensitySummary]:
    """Variant density per chromosome, aggregated from PostgreSQL.

    ``density_per_kb`` is computed as ``variant_count / (length_bp / 1000)``.
    Read-hot aggregation cached in Redis (default TTL) keyed by
    ``release_id``; a Redis failure degrades to a direct aggregation.  Empty
    results are cached too (anti-penetration): when no data exists the
    loader returns ``[]`` which is memoised until the TTL expires instead of
    re-running the aggregate per request.
    """
    payload = await get_or_set(
        "stats:chromosome-density",
        ttl=None,
        params={"release_id": release_id},
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
    days: int = Query(default=30, ge=1, le=3650),
    release_id: int | None = Query(default=None),
) -> list[DiscoveryTrendPoint]:
    """Cumulative variant counts across published releases.

    Each published release contributes ``new_variants`` (= its recorded
    ``variant_count``) and a running cumulative total.
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
    if release_id is not None:
        stmt = stmt.where(Release.id == release_id)

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
    only_active: bool = Query(default=False),
) -> list[ReleaseSummary]:
    """Statistics per release (version, date, variant/gene/line counts).

    Read-hot query cached in Redis (default TTL) keyed by ``only_active``;
    a Redis failure degrades to a direct query.  An empty release list is
    cached as well (anti-penetration) so a freshly seeded database does not
    re-run the query on every request.
    """
    payload = await get_or_set(
        "stats:releases",
        ttl=None,
        params={"only_active": only_active},
        loader=lambda: _load_release_statistics(db, only_active),
    )
    return [ReleaseSummary.model_validate(item) for item in payload]


async def _load_release_statistics(
    db: AsyncSession, only_active: bool
) -> list[dict]:
    """Compute per-release statistics (loader for the Redis cache)."""
    stmt = select(Release).where(Release.published_at.is_not(None))
    if only_active:
        stmt = stmt.where(Release.status == ReleaseStatus.ACTIVE.value)
    stmt = stmt.order_by(Release.published_at.desc())

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
    release_id: int | None = Query(default=None),
) -> list[MutagenCount]:
    """Number of mutant lines per mutagen (real PostgreSQL aggregation)."""
    stmt = (
        select(MutantLine.mutagen, func.count())
        .where(MutantLine.mutagen.is_not(None), MutantLine.is_deleted.is_(False))
        .group_by(MutantLine.mutagen)
        .order_by(func.count().desc())
    )
    if release_id is not None:
        stmt = stmt.where(MutantLine.release_id == release_id)

    rows = (await db.execute(stmt)).all()
    return [
        MutagenCount(mutagen=str(mutagen), count=int(count))
        for mutagen, count in rows
        if mutagen
    ]


@router.get("/density", response_model=ChromosomeDensity)
async def chromosome_density(
    assembly: str = Query(..., description="Assembly name (required)"),
    chromosome: str = Query(...),
    bin_size: int = Query(default=1_000_000, ge=1000),
) -> ChromosomeDensity:
    """Variant density across a chromosome.

    Density is computed entirely from the ClickHouse projection, so an
    unavailable projection is reported as capability-unavailable (503). The
    response model also requires a concrete ``chromosome_length``: fabricating
    ``0`` here would both violate the contract and present an empty chromosome
    as a real result.
    """
    bins = await ch_service.get_chromosome_density(
        assembly=assembly,
        chromosome=chromosome,
        bin_size=bin_size,
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
