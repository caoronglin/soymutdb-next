"""Unit tests for the stats aggregation endpoints (mocked query layer).

These tests call the endpoint functions directly with a mocked SQLAlchemy
session and a mocked ClickHouse service — no database / testcontainers
required.  They verify:

- every endpoint returns real aggregates derived from the mock rows;
- empty input yields the empty structure (zeros / empty lists);
- ClickHouse unavailability degrades gracefully to the PostgreSQL fallback.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1 import stats as stats_module
from app.api.v1.stats import (
    chromosome_density,
    chromosome_density_summary,
    discovery_trend,
    homepage_stats,
    impact_summary,
    mutagen_statistics,
    release_statistics,
    variant_type_summary,
)

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


class FakeResult:
    """Mimics the small slice of AsyncSession / result APIs used by the endpoints."""

    def __init__(self, rows=None, scalar=None, scalar_one_or_none=None):
        self._rows = rows or []
        self._scalar = scalar
        self._scalar_one_or_none = scalar_one_or_none

    def all(self):
        return self._rows

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self._scalar_one_or_none

    def one(self):
        return self._rows[0]


class FakeDB(AsyncMock):
    """AsyncMock with canned scalar/execute responses."""

    def __init__(self, scalars=None, results=None, **kwargs):
        super().__init__(**kwargs)
        self.scalar = AsyncMock(side_effect=scalars or [0] * 20)
        self.execute = AsyncMock(side_effect=results or [FakeResult()] * 20)


def _release_row(version: str, days_ago: int, variant_count: int) -> FakeResult:
    """Row for the discovery-trend / releases queries."""
    return FakeResult(
        rows=[
            (
                NOW - timedelta(days=days_ago),
                variant_count,
            )
        ]
    )


@pytest.mark.asyncio
async def test_dashboard_stats_uses_one_count_query_and_real_users():
    db = FakeDB(
        results=[
            # counts: genes, mutant lines, phenotypes, assemblies, active users
            FakeResult(rows=[(10, 4, 3, 2, 7)]),
            FakeResult(scalar_one_or_none=None),  # latest release
        ]
    )
    with patch.object(
        stats_module.ch_service,
        "get_dashboard_stats",
        new=AsyncMock(return_value={"total_variants": 42}),
    ):
        result = await stats_module._load_dashboard_stats(db)

    assert result["total_genes"] == 10
    assert result["total_users"] == 7
    assert db.execute.await_count == 2
    assert db.scalar.await_count == 0


@pytest.mark.asyncio
class TestHomepageStats:
    async def test_uses_clickhouse_when_available(self):
        db = FakeDB(
            scalars=[5, 4, 3, 2, 1],  # genes, lines, releases, assemblies, seeds
            results=[
                FakeResult(scalar_one_or_none=None),  # latest release
                FakeResult(rows=[]),  # PG fallback (not used)
            ],
        )
        with patch.object(
            stats_module.ch_service,
            "get_dashboard_stats",
            new=AsyncMock(
                return_value={
                    "total_variants": 100,
                    "snp_count": 60,
                    "ins_count": 20,
                    "del_count": 10,
                    "mnv_count": 5,
                    "sv_count": 5,
                }
            ),
        ):
            result = await homepage_stats(db=db)

        assert result.total_variants == 100
        assert result.snp_count == 60
        assert result.indel_count == 30  # INS + DEL
        assert result.sv_count == 5
        assert result.gene_count == 5
        assert result.mutant_line_count == 4
        assert result.release_count == 3
        assert result.assembly_count == 2
        assert result.seed_accessions == 1
        assert result.last_release_date is None
        assert result.last_release_name is None

    async def test_clickhouse_down_falls_back_to_postgres(self):
        db = FakeDB(
            scalars=[0, 0, 0, 0, 0],
            results=[
                FakeResult(scalar_one_or_none=None),  # latest release
                FakeResult(rows=[("SNP", 8), ("DEL", 2)]),  # PG variant counts
            ],
        )
        with patch.object(
            stats_module.ch_service,
            "get_dashboard_stats",
            new=AsyncMock(side_effect=RuntimeError("clickhouse unreachable")),
        ):
            result = await homepage_stats(db=db)

        assert result.total_variants == 10
        assert result.snp_count == 8
        assert result.indel_count == 2
        assert result.sv_count == 0

    async def test_clickhouse_down_and_pg_empty_returns_empty_structure(self):
        db = FakeDB(
            scalars=[0, 0, 0, 0, 0],
            results=[
                FakeResult(scalar_one_or_none=None),
                FakeResult(rows=[]),
            ],
        )
        with patch.object(
            stats_module.ch_service,
            "get_dashboard_stats",
            new=AsyncMock(side_effect=RuntimeError("clickhouse unreachable")),
        ):
            result = await homepage_stats(db=db)

        assert result.total_variants == 0
        assert result.snp_count == 0
        assert result.indel_count == 0
        assert result.sv_count == 0
        assert result.gene_count == 0

    async def test_includes_latest_release(self):
        release = SimpleNamespace(
            published_at=NOW - timedelta(days=10),
            version="v2.0",
        )
        db = FakeDB(
            scalars=[1, 1, 1, 1, 1],
            results=[FakeResult(scalar_one_or_none=release)],
        )
        with patch.object(
            stats_module.ch_service,
            "get_dashboard_stats",
            new=AsyncMock(return_value={"total_variants": 0}),
        ):
            result = await homepage_stats(db=db)

        assert result.last_release_date == release.published_at
        assert result.last_release_name == "v2.0"


@pytest.mark.asyncio
class TestVariantTypeSummary:
    async def test_groups_and_combines_indel_buckets(self):
        db = FakeDB(results=[FakeResult(rows=[("SNP", 5), ("INS", 2), ("DEL", 1), ("SV", 4)])])
        result = await variant_type_summary(db=db)
        assert [(item.name, item.value) for item in result] == [
            ("SNP", 5),
            ("Indel", 3),
            ("SV", 4),
        ]  # MNV omitted (zero)

    async def test_empty_table_returns_empty_list(self):
        db = FakeDB(results=[FakeResult(rows=[])])
        assert await variant_type_summary(db=db) == []


@pytest.mark.asyncio
class TestImpactSummary:
    async def test_returns_impact_classes_in_canonical_order(self):
        db = FakeDB(
            results=[FakeResult(rows=[("HIGH", 3), ("MODIFIER", 50)])]
        )
        result = await impact_summary(db=db)
        assert [(item.impact, item.count) for item in result] == [
            ("HIGH", 3),
            ("MODIFIER", 50),
        ]

    async def test_empty_returns_empty_list(self):
        db = FakeDB(results=[FakeResult(rows=[])])
        assert await impact_summary(db=db) == []


@pytest.mark.asyncio
class TestChromosomeDensitySummary:
    async def test_aggregates_per_chromosome_with_density(self):
        db = FakeDB(
            results=[
                FakeResult(
                    rows=[
                        ("Gm01", 100_000, "SNP", 10),
                        ("Gm01", 100_000, "DEL", 5),
                        ("Gm02", 50_000, "MNV", 3),
                    ]
                )
            ]
        )
        result = await chromosome_density_summary(db=db)
        by_name = {item.chromosome: item for item in result}
        assert by_name["Gm01"].variant_count == 15
        assert by_name["Gm01"].snp_count == 10
        assert by_name["Gm01"].indel_count == 5
        assert by_name["Gm01"].length_bp == 100_000
        assert by_name["Gm01"].density_per_kb == 0.15
        assert by_name["Gm02"].variant_count == 3
        assert by_name["Gm02"].snp_count == 0
        assert by_name["Gm02"].density_per_kb == 0.06

    async def test_zero_length_chromosome_has_zero_density(self):
        db = FakeDB(results=[FakeResult(rows=[("Gm00", 0, "SNP", 7)])])
        result = await chromosome_density_summary(db=db)
        assert result[0].variant_count == 7
        assert result[0].density_per_kb == 0.0


@pytest.mark.asyncio
class TestDiscoveryTrend:
    async def test_cumulative_across_releases(self):
        db = FakeDB(
            results=[
                FakeResult(rows=[(NOW - timedelta(days=20), 100), (NOW - timedelta(days=5), 50)])
            ]
        )
        result = await discovery_trend(db=db, days=30)
        assert [(p.date, p.new_variants, p.cumulative) for p in result] == [
            ((NOW - timedelta(days=20)).date().isoformat(), 100, 100),
            ((NOW - timedelta(days=5)).date().isoformat(), 50, 150),
        ]

    async def test_no_releases_returns_empty(self):
        db = FakeDB(results=[FakeResult(rows=[])])
        assert await discovery_trend(db=db, days=30) == []


@pytest.mark.asyncio
class TestReleaseStatistics:
    async def test_returns_release_summaries(self):
        release = SimpleNamespace(
            version="v2.0",
            published_at=NOW - timedelta(days=3),
            variant_count=100,
            gene_count=10,
            mutant_line_count=4,
        )
        db = FakeDB(results=[FakeResult(rows=[release])])
        result = await release_statistics(db=db)
        assert result[0].release_version == "v2.0"
        assert result[0].release_date == (NOW - timedelta(days=3)).date()
        assert result[0].variant_count == 100

    async def test_unpublished_releases_are_skipped(self):
        release = SimpleNamespace(
            version="v2.0",
            published_at=None,
            variant_count=100,
            gene_count=10,
            mutant_line_count=4,
        )
        db = FakeDB(results=[FakeResult(rows=[release])])
        assert await release_statistics(db=db) == []


@pytest.mark.asyncio
class TestMutagenStatistics:
    async def test_groups_by_mutagen(self):
        db = FakeDB(results=[FakeResult(rows=[("EMS", 7), ("NaN", 2)])])
        result = await mutagen_statistics(db=db)
        assert [(item.mutagen, item.count) for item in result] == [("EMS", 7), ("NaN", 2)]


@pytest.mark.asyncio
class TestChromosomeDensityEndpoint:
    """The density endpoint is ClickHouse-only, so its degraded path is 503.

    It must never fabricate a ``chromosome_length`` of 0 (the response model
    requires >= 1) — that violation previously surfaced as an unhandled 500
    with no capability information.
    """

    async def test_bins_derive_a_positive_chromosome_length(self):
        with patch.object(
            stats_module.ch_service,
            "get_chromosome_density",
            new=AsyncMock(
                return_value=[
                    {"bin_start": 0, "bin_end": 999, "count": 3},
                    {"bin_start": 1000, "bin_end": 1999, "count": 5},
                ]
            ),
        ):
            result = await chromosome_density(
                assembly="GmWm82.a4.v1", chromosome="chr01", bin_size=1000
            )
        assert result.total_variants == 8
        assert result.chromosome_length == 1999

    async def test_empty_bins_still_satisfy_the_response_model(self):
        with patch.object(
            stats_module.ch_service,
            "get_chromosome_density",
            new=AsyncMock(return_value=[]),
        ):
            result = await chromosome_density(
                assembly="GmWm82.a4.v1", chromosome="chr01", bin_size=1000
            )
        assert result.bins == []
        assert result.total_variants == 0
        assert result.chromosome_length >= 1

    async def test_unavailable_capability_propagates_as_service_unavailable(self):
        from app.core.exceptions import ServiceUnavailableError

        with patch.object(
            stats_module.ch_service,
            "get_chromosome_density",
            new=AsyncMock(side_effect=ServiceUnavailableError("unavailable")),
        ):
            with pytest.raises(ServiceUnavailableError):
                await chromosome_density(
                    assembly="GmWm82.a4.v1", chromosome="chr01", bin_size=1000
                )
