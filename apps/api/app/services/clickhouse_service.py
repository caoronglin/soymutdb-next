"""ClickHouse query service with parameterised queries.

CRITICAL SECURITY: every query uses ``parameters=`` from clickhouse-connect.
User input is NEVER interpolated into SQL via f-strings or ``%`` formatting.
The table name is hardcoded to ``variant_facts``.
"""

from __future__ import annotations

import time
from typing import Any, cast

from clickhouse_connect.driver.asyncclient import AsyncClient
from structlog import get_logger

from ..core.database import get_clickhouse_client
from ..core.metrics import CLICKHOUSE_QUERY_COUNT, CLICKHOUSE_QUERY_LATENCY
from ..schemas.variant import VariantFilterParams

logger = get_logger(__name__)

# Hardcoded table name – never user-controlled.
VARIANT_FACTS_TABLE = "variant_facts"

# ClickHouse table written by the analytics tracking service.
ANALYTICS_EVENTS_TABLE = "analytics_events"

# ``clickhouse_connect.get_async_client`` is a coroutine factory (its
# annotation in core.database lies); cast to Any so we can await it.
_async_client_factory = cast(Any, get_clickhouse_client)


class ClickHouseService:
    """Service for querying variant data from ClickHouse.

    All public methods build a WHERE clause from whitelisted column names and
    pass user values through ``parameters`` so that ClickHouse performs proper
    escaping.  No f-string / format string is ever used with user data.

    The async client is created lazily (and awaited) on first use —
    ``clickhouse_connect.get_async_client`` returns a coroutine, so module
    level instantiation would never produce a usable client.
    """

    def __init__(self) -> None:
        self._client: AsyncClient | None = None

    async def _get_client(self) -> AsyncClient:
        """Return the awaited async ClickHouse client (created on first use)."""
        if self._client is None:
            self._client = await _async_client_factory()
        assert self._client is not None
        return self._client

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_where(
        params: VariantFilterParams,
    ) -> tuple[str, dict[str, Any]]:
        """Build a parameterised WHERE clause.

        Returns ``(where_sql, query_params)``.  Column names are whitelisted
        literals; values are bound via ``%(name)s`` placeholders.
        """
        conditions: list[str] = []
        qp: dict[str, Any] = {}

        if params.assembly is not None:
            conditions.append("assembly_key = %(assembly)s")
            qp["assembly"] = params.assembly
        if params.chromosome is not None:
            conditions.append("chromosome = %(chromosome)s")
            qp["chromosome"] = params.chromosome
        if params.start is not None:
            conditions.append("position >= %(start)s")
            qp["start"] = params.start
        if params.end is not None:
            conditions.append("position <= %(end)s")
            qp["end"] = params.end
        if params.gene_id is not None:
            conditions.append("gene_id = %(gene_id)s")
            qp["gene_id"] = params.gene_id
        if params.mutant_line_id is not None:
            conditions.append("mutant_line_surrogate_id = %(ml_id)s")
            qp["ml_id"] = params.mutant_line_id
        if params.variant_type is not None:
            conditions.append("variant_type = %(vtype)s")
            qp["vtype"] = params.variant_type.value
        if params.impact is not None:
            conditions.append("impact = %(impact)s")
            qp["impact"] = params.impact.value
        if params.min_af is not None:
            conditions.append("allele_frequency >= %(min_af)s")
            qp["min_af"] = params.min_af
        if params.max_af is not None:
            conditions.append("allele_frequency <= %(max_af)s")
            qp["max_af"] = params.max_af

        where = " AND ".join(conditions) if conditions else "1=1"
        return where, qp

    # ------------------------------------------------------------------ #
    # Public query API
    # ------------------------------------------------------------------ #

    async def count_variants(self, params: VariantFilterParams) -> int:
        """Return the total number of variants matching *params*."""
        where, qp = self._build_where(params)
        query = f"SELECT count() AS total FROM {VARIANT_FACTS_TABLE} WHERE {where}"
        client = await self._get_client()
        CLICKHOUSE_QUERY_COUNT.labels(operation="count").inc()
        start = time.perf_counter()
        result = await client.query(query, parameters=qp)
        CLICKHOUSE_QUERY_LATENCY.labels(operation="count").observe(
            time.perf_counter() - start
        )
        if result.row_count == 0:
            return 0
        return int(result.first_row[0])

    async def query_variants(
        self,
        params: VariantFilterParams,
        limit: int,
        cursor_position: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query variants with keyset pagination.

        Pagination is performed on the ``position`` column (ascending).  The
        caller passes the last seen position as ``cursor_position``; we filter
        ``position > cursor_position``.  This avoids OFFSET entirely.
        """
        where, qp = self._build_where(params)

        if cursor_position is not None:
            conditions_extra = "position > %(cursor_pos)s"
            where = f"{where} AND {conditions_extra}" if where != "1=1" else conditions_extra
            qp["cursor_pos"] = cursor_position

        # ``limit`` is bound as a parameter too.
        qp["lim"] = limit
        query = f"""
        SELECT
            variant_id,
            chromosome,
            position,
            ref_allele,
            alt_allele,
            variant_type,
            consequence,
            impact,
            gene_id,
            gene_symbol,
            hgvs_p,
            hgvs_c,
            quality_score,
            filter_status,
            allele_frequency
        FROM {VARIANT_FACTS_TABLE}
        WHERE {where}
        ORDER BY position ASC
        LIMIT %(lim)s
        """
        client = await self._get_client()
        CLICKHOUSE_QUERY_COUNT.labels(operation="query_variants").inc()
        start = time.perf_counter()
        result = await client.query(query, parameters=qp)
        CLICKHOUSE_QUERY_LATENCY.labels(operation="query_variants").observe(
            time.perf_counter() - start
        )

        columns = result.column_names
        return [dict(zip(columns, row)) for row in result.result_rows]

    async def query_variants_by_region(
        self,
        assembly: str,
        chromosome: str,
        start: int,
        end: int,
        max_results: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query variants in a genomic region.

        ``assembly`` is a required parameter (never hardcoded).
        """
        query = f"""
        SELECT
            variant_id, chromosome, position, ref_allele, alt_allele,
            variant_type, consequence, impact, gene_id, gene_symbol,
            hgvs_p, hgvs_c, quality_score, filter_status, allele_frequency
        FROM {VARIANT_FACTS_TABLE}
        WHERE assembly_key = %(assembly)s
          AND chromosome = %(chromosome)s
          AND position >= %(start)s
          AND position <= %(end)s
        ORDER BY position ASC
        LIMIT %(max_results)s
        """
        qp = {
            "assembly": assembly,
            "chromosome": chromosome,
            "start": start,
            "end": end,
            "max_results": max_results,
        }
        client = await self._get_client()
        CLICKHOUSE_QUERY_COUNT.labels(operation="region").inc()
        start_t = time.perf_counter()
        result = await client.query(query, parameters=qp)
        CLICKHOUSE_QUERY_LATENCY.labels(operation="region").observe(
            time.perf_counter() - start_t
        )
        columns = result.column_names
        return [dict(zip(columns, row)) for row in result.result_rows]

    async def get_variant_by_id(self, variant_id: str) -> dict[str, Any] | None:
        """Fetch a single variant by its ID."""
        query = f"""
        SELECT
            variant_id, chromosome, position, ref_allele, alt_allele,
            variant_type, consequence, impact, gene_id, gene_symbol,
            hgvs_p, hgvs_c, quality_score, filter_status, allele_frequency,
            read_depth, zygosity
        FROM {VARIANT_FACTS_TABLE}
        WHERE variant_id = %(vid)s
        LIMIT 1
        """
        client = await self._get_client()
        result = await client.query(query, parameters={"vid": variant_id})
        if result.row_count == 0:
            return None
        columns = result.column_names
        return dict(zip(columns, result.first_row))

    async def get_dashboard_stats(self) -> dict[str, Any]:
        """Aggregate dashboard statistics."""
        query = f"""
        SELECT
            count() AS total_variants,
            uniqExact(gene_id) AS total_genes,
            uniqExact(mutant_line_surrogate_id) AS total_mutant_lines,
            sum(if(variant_type = 'SNP', 1, 0)) AS snp_count,
            sum(if(variant_type = 'INS', 1, 0)) AS ins_count,
            sum(if(variant_type = 'DEL', 1, 0)) AS del_count,
            sum(if(variant_type = 'MNV', 1, 0)) AS mnv_count,
            sum(if(variant_type = 'SV', 1, 0)) AS sv_count
        FROM {VARIANT_FACTS_TABLE}
        """
        client = await self._get_client()
        result = await client.query(query)
        if result.row_count == 0:
            return {}
        columns = result.column_names
        return dict(zip(columns, result.first_row))

    async def get_variant_type_distribution(
        self, assembly: str | None = None
    ) -> dict[str, int]:
        """Return variant type distribution."""
        client = await self._get_client()
        if assembly is not None:
            query = f"""
            SELECT variant_type, count() AS cnt
            FROM {VARIANT_FACTS_TABLE}
            WHERE assembly_key = %(assembly)s
            GROUP BY variant_type
            """
            result = await client.query(query, parameters={"assembly": assembly})
        else:
            query = f"""
            SELECT variant_type, count() AS cnt
            FROM {VARIANT_FACTS_TABLE}
            GROUP BY variant_type
            """
            result = await client.query(query)
        return {row[0]: int(row[1]) for row in result.result_rows}

    async def get_chromosome_density(
        self,
        assembly: str,
        chromosome: str,
        bin_size: int = 1_000_000,
    ) -> list[dict[str, Any]]:
        """Compute variant density bins for a chromosome."""
        query = f"""
        SELECT
            intDiv(position - 1, %(bin_size)s) * %(bin_size)s + 1 AS bin_start,
            count() AS variant_count
        FROM {VARIANT_FACTS_TABLE}
        WHERE assembly_key = %(assembly)s
          AND chromosome = %(chromosome)s
        GROUP BY bin_start
        ORDER BY bin_start
        """
        qp = {
            "assembly": assembly,
            "chromosome": chromosome,
            "bin_size": bin_size,
        }
        client = await self._get_client()
        result = await client.query(query, parameters=qp)
        return [
            {"bin_start": row[0], "bin_end": row[0] + bin_size - 1, "count": int(row[1])}
            for row in result.result_rows
        ]

    async def ping(self) -> bool:
        """Health-check: return True if ClickHouse responds."""
        try:
            client = await self._get_client()
            result = await client.query("SELECT 1")
            return result.first_row[0] == 1
        except Exception:
            return False

    async def get_query_latency_percentile(
        self, percentile: float = 0.95, days: int = 30
    ) -> float:
        """Return the *percentile* of analytics event durations over *days*.

        ``percentile`` is a code-level constant (never user input).  Returns
        0.0 when no events exist.
        """
        query = f"""
        SELECT quantile({percentile})(duration_ms)
        FROM {ANALYTICS_EVENTS_TABLE}
        WHERE timestamp >= now() - INTERVAL %(days)s DAY
        """
        result = await (await self._get_client()).query(
            query, parameters={"days": days}
        )
        if result.row_count == 0:
            return 0.0
        value = result.first_row[0]
        return float(value or 0.0)
    async def get_query_latency_series(
        self, days: int = 30
    ) -> list[dict[str, Any]]:
        """Return daily p50/p95/p99 query-latency percentiles (ms)."""
        query = f"""
        SELECT
            toDate(timestamp) AS d,
            quantile(0.50)(duration_ms) AS p50,
            quantile(0.95)(duration_ms) AS p95,
            quantile(0.99)(duration_ms) AS p99
        FROM {ANALYTICS_EVENTS_TABLE}
        WHERE timestamp >= now() - INTERVAL %(days)s DAY
        GROUP BY d
        ORDER BY d ASC
        """
        result = await (await self._get_client()).query(
            query, parameters={"days": days}
        )
        return [
            {
                "date": str(row[0]),
                "p50": float(row[1] or 0),
                "p95": float(row[2] or 0),
                "p99": float(row[3] or 0),
            }
            for row in result.result_rows
        ]
