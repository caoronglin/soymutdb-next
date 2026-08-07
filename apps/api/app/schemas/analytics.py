"""Pydantic v2 schemas for analytics, dashboard stats, and chart data."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class DashboardStats(BaseModel):
    total_variants: int = Field(..., ge=0)
    total_genes: int = Field(..., ge=0)
    total_mutant_lines: int = Field(..., ge=0)
    total_phenotypes: int = Field(..., ge=0)
    total_users: int = Field(..., ge=0)
    assemblies_count: int = Field(..., ge=0)
    current_release: str | None = None
    last_updated: datetime


class ChromosomeDensityBin(BaseModel):
    bin_start: int = Field(..., ge=0)
    bin_end: int = Field(..., ge=0)
    count: int = Field(..., ge=0)


class ChromosomeDensity(BaseModel):
    chromosome: str
    chromosome_length: int = Field(..., ge=1)
    bin_size: int = Field(..., ge=1)
    bins: list[ChromosomeDensityBin] = Field(default_factory=list)
    total_variants: int = Field(..., ge=0)


class GeneImpactSummary(BaseModel):
    gene_id: str
    gene_symbol: str | None = None
    high_impact: int = Field(default=0, ge=0)
    moderate_impact: int = Field(default=0, ge=0)
    low_impact: int = Field(default=0, ge=0)
    modifier_impact: int = Field(default=0, ge=0)
    total_variants: int = Field(default=0, ge=0)


class VariantTypeDistribution(BaseModel):
    snp_count: int = Field(default=0, ge=0)
    ins_count: int = Field(default=0, ge=0)
    del_count: int = Field(default=0, ge=0)
    mnv_count: int = Field(default=0, ge=0)
    sv_count: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)


class SubstitutionCount(BaseModel):
    substitution: str = Field(..., pattern=r"^[ACGT]>[ACGT]$")
    count: int = Field(..., ge=0)
    percentage: float = Field(default=0.0, ge=0.0, le=100.0)


class SubstitutionSpectrum(BaseModel):
    substitutions: list[SubstitutionCount] = Field(default_factory=list)
    total_snps: int = Field(default=0, ge=0)
    ti_tv_ratio: float = Field(default=0.0, ge=0.0)


class MutantLineComparison(BaseModel):
    mutant_line_id: str
    mutant_line_name: str
    mutagen: str | None = None
    total_variants: int = Field(default=0, ge=0)
    snp_count: int = Field(default=0, ge=0)
    indel_count: int = Field(default=0, ge=0)
    high_impact_count: int = Field(default=0, ge=0)
    genes_affected: int = Field(default=0, ge=0)


class ReleaseSummary(BaseModel):
    release_version: str
    release_date: date
    variant_count: int = Field(default=0, ge=0)
    gene_count: int = Field(default=0, ge=0)
    mutant_line_count: int = Field(default=0, ge=0)


class TimeSeriesPoint(BaseModel):
    timestamp: datetime
    value: float
    label: str | None = None


class ChartSeries(BaseModel):
    name: str
    data: list[TimeSeriesPoint] = Field(default_factory=list)
    color: str | None = None


class ChartDataResponse(BaseModel):
    chart_type: str
    title: str
    description: str = ""
    x_label: str = ""
    y_label: str = ""
    series: list[ChartSeries] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Homepage / public stats contract
# ---------------------------------------------------------------------------


class HomepageStats(BaseModel):
    """Aggregate statistics shown on the public home page."""

    total_variants: int = Field(default=0, ge=0)
    snp_count: int = Field(default=0, ge=0)
    indel_count: int = Field(default=0, ge=0)
    sv_count: int = Field(default=0, ge=0)
    gene_count: int = Field(default=0, ge=0)
    mutant_line_count: int = Field(default=0, ge=0)
    release_count: int = Field(default=0, ge=0)
    assembly_count: int = Field(default=0, ge=0)
    seed_accessions: int = Field(default=0, ge=0)
    last_release_date: datetime | None = None
    last_release_name: str | None = None


class VariantTypeSummaryItem(BaseModel):
    """One entry of the variant-type distribution (``name``/``value`` shape)."""

    name: str
    value: int = Field(default=0, ge=0)


class ImpactSummaryItem(BaseModel):
    """Variant count for one predicted impact class."""

    impact: str
    count: int = Field(default=0, ge=0)


class ChromosomeDensitySummary(BaseModel):
    """Per-chromosome variant density summary."""

    chromosome: str
    variant_count: int = Field(default=0, ge=0)
    snp_count: int = Field(default=0, ge=0)
    indel_count: int = Field(default=0, ge=0)
    length_bp: int = Field(default=0, ge=0)
    density_per_kb: float = Field(default=0.0, ge=0.0)


class DiscoveryTrendPoint(BaseModel):
    """One point of the cumulative variant discovery trend."""

    date: str
    new_variants: int = Field(default=0, ge=0)
    cumulative: int = Field(default=0, ge=0)


class MutagenCount(BaseModel):
    """Mutant-line count grouped by mutagen."""

    mutagen: str
    count: int = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# Admin dashboard contract (camelCase over the wire)
# ---------------------------------------------------------------------------


class AdminDashboardStats(BaseModel):
    """System overview numbers for the admin dashboard.

    Serialised with camelCase keys (``totalUsers``, ``activeReleases``, …)
    to match the admin frontend contract.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    total_users: int = Field(default=0, ge=0)
    active_releases: int = Field(default=0, ge=0)
    total_variants: int = Field(default=0, ge=0)
    query_p95_ms: float = Field(default=0.0, ge=0.0)
    users_change: float = Field(default=0.0)
    releases_change: float = Field(default=0.0)
    variants_change: float = Field(default=0.0)
    query_p95_change: float = Field(default=0.0)


class ImportThroughputPoint(BaseModel):
    """Daily import task throughput (success vs. failure)."""

    date: str
    imported: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)


class QueryLatencyPoint(BaseModel):
    """Daily query-latency percentiles (ms)."""

    date: str
    p50: float = Field(default=0.0, ge=0.0)
    p95: float = Field(default=0.0, ge=0.0)
    p99: float = Field(default=0.0, ge=0.0)


class StorageGrowthPoint(BaseModel):
    """Daily storage growth in bytes."""

    date: str
    bytes: int = Field(default=0, ge=0)


class AdminDashboardSeries(BaseModel):
    """Time series data for the admin dashboard charts."""

    import_throughput: list[ImportThroughputPoint] = Field(default_factory=list)
    query_latency: list[QueryLatencyPoint] = Field(default_factory=list)
    storage_growth: list[StorageGrowthPoint] = Field(default_factory=list)
