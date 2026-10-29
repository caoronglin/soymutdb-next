"""Legacy ClickHouse query service — retained migration/test surface only.

This module is **not part of the runtime path**. The API reads the
authoritative PostgreSQL store natively (:class:`PostgresVariantService`), and
nothing under ``apps/api/app`` or the worker imports this service. It is kept
solely because the historical ClickHouse schema contract
(``infra/clickhouse/test_schema_contract.py``, run by ``scripts/smoke.sh``) and
the legacy-lane ablation tests still exercise it. Retire it together with that
``infra`` contract and the historical ClickHouse migration lane.

CRITICAL SECURITY: every query uses ``parameters=`` from clickhouse-connect.
User input is NEVER interpolated into SQL via f-strings or ``%`` formatting.
The table name is hardcoded to ``variant_facts``.
"""

from __future__ import annotations

import functools
import math
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

from structlog import get_logger

if TYPE_CHECKING:
    from clickhouse_connect.driver.asyncclient import AsyncClient

from ..core.database import get_clickhouse_client
from ..core.exceptions import ServiceUnavailableError
from ..core.metrics import CLICKHOUSE_QUERY_COUNT, CLICKHOUSE_QUERY_LATENCY
from ..schemas.variant import VariantFilterParams
from .release_context import ReleaseContext

logger = get_logger(__name__)

# Hardcoded table name – never user-controlled.
VARIANT_FACTS_TABLE = "variant_facts"

# ClickHouse table written by the analytics tracking service.
ANALYTICS_EVENTS_TABLE = "analytics_events"

# ``clickhouse_connect.get_async_client`` is a coroutine factory (its
# annotation in core.database lies); cast to Any so we can await it.
_async_client_factory = cast(Any, get_clickhouse_client)

#: Message shared by every capability-unavailable response. It names the
#: capability, never the host/port or a stack trace.
CLICKHOUSE_UNAVAILABLE_MESSAGE = (
    "Variant analytics projection (ClickHouse) is unavailable"
)


def _is_legacy_transport_error(exc: Exception) -> bool:
    """Inspect the optional driver only after a legacy operation fails."""
    if isinstance(exc, ModuleNotFoundError) and exc.name == "clickhouse_connect":
        return True
    try:
        from clickhouse_connect.driver.exceptions import ClickHouseError
    except ModuleNotFoundError:
        return False
    return isinstance(exc, ClickHouseError)


def _capability_guarded[T](
    func: Callable[..., Awaitable[T]],
) -> Callable[..., Awaitable[T]]:
    """Translate ClickHouse driver/transport failures into 503.

    ClickHouse is a *required capability* in extended deployments and an
    *absent capability* in baseline/disposable ones. A connection failure,
    timeout, or driver error must surface as ``503 service_unavailable`` with a
    capability-level message — never as an unhandled ``500`` and never with
    host/port details. Callers that deliberately degrade (e.g. the dashboard
    counters) catch ``ServiceUnavailableError`` explicitly.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            if not _is_legacy_transport_error(exc):
                raise
            logger.warning(
                "clickhouse_capability_unavailable",
                operation=func.__name__,
            )
            raise ServiceUnavailableError(CLICKHOUSE_UNAVAILABLE_MESSAGE) from exc

    return wrapper


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

    async def insert_release_variants(self, rows: list[dict[str, Any]]) -> None:
        """Insert importer rows using the fixed variant table and bound values."""
        if not rows:
            return
        columns = tuple(rows[0].keys())
        if "variant_id" not in columns or "release_key" not in columns:
            raise ValueError("variant_id and release_key are required")
        if any(set(row) != set(columns) for row in rows):
            raise ValueError("variant rows must have a stable shape")
        client = await self._get_client()
        await client.insert(
            VARIANT_FACTS_TABLE,
            [tuple(row[column] for column in columns) for row in rows],
            column_names=list(columns),
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_where(
        params: VariantFilterParams,
        release_context: ReleaseContext,
    ) -> tuple[str, dict[str, Any]]:
        """Build a parameterised WHERE clause.

        Returns ``(where_sql, query_params)``.  Column names are whitelisted
        literals; values are bound via ``%(name)s`` placeholders.
        """
        conditions = ["release_key = %(release_key)s"]
        qp: dict[str, Any] = {"release_key": release_context.release_key}

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
        if params.ref is not None:
            conditions.append("ref_allele = %(ref)s")
            qp["ref"] = params.ref
        if params.alt is not None:
            conditions.append("alt_allele = %(alt)s")
            qp["alt"] = params.alt
        if params.gene_id is not None:
            conditions.append("gene_id = %(gene_id)s")
            qp["gene_id"] = params.gene_id
        if params.mutant_line_name is not None:
            conditions.append("mutant_line_name = %(ml_name)s")
            qp["ml_name"] = params.mutant_line_name
        if params.variant_type is not None:
            conditions.append("variant_type = %(vtype)s")
            qp["vtype"] = params.variant_type.value
        if params.consequence is not None:
            conditions.append("consequence = %(consequence)s")
            qp["consequence"] = params.consequence.value
        if params.impact is not None:
            conditions.append("impact = %(impact)s")
            qp["impact"] = params.impact.value
        if params.min_af is not None:
            conditions.append("allele_frequency >= %(min_af)s")
            qp["min_af"] = params.min_af
        if params.max_af is not None:
            conditions.append("allele_frequency <= %(max_af)s")
            qp["max_af"] = params.max_af

        return " AND ".join(conditions), qp

    # ------------------------------------------------------------------ #
    # Public query API
    # ------------------------------------------------------------------ #

    @_capability_guarded
    async def count_variants(
        self,
        params: VariantFilterParams,
        *,
        release_context: ReleaseContext,
    ) -> int:
        """Return the total number of variants matching *params*."""
        where, qp = self._build_where(params, release_context)
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

    @_capability_guarded
    async def query_variants(
        self,
        params: VariantFilterParams,
        limit: int,
        *,
        release_context: ReleaseContext,
        cursor_key: tuple[int, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Query variants with keyset pagination.

        Pagination uses ``(position, variant_id)`` ascending so variants that
        share a genomic position cannot be skipped between pages.
        """
        where, qp = self._build_where(params, release_context)

        if cursor_key is not None:
            cursor_position, cursor_variant_id = cursor_key
            where = (
                f"{where} AND (position > %(cursor_pos)s OR "
                "(position = %(cursor_pos)s AND "
                "variant_id > %(cursor_variant_id)s))"
            )
            qp["cursor_pos"] = cursor_position
            qp["cursor_variant_id"] = cursor_variant_id

        # ``limit`` is bound as a parameter too.
        qp["lim"] = limit
        query = f"""
        SELECT
            variant_id, release_key, assembly_key, chromosome, position,
            ref_allele, alt_allele, variant_type, gene_id, gene_symbol,
            variant_subtype, length, gene_surrogate_id, mutant_line_surrogate_id,
            consequence, consequence_id, impact, rs_id, quality_score,
            filter_status, read_depth, allele_frequency, hgvs_c, hgvs_p, zygosity
        FROM {VARIANT_FACTS_TABLE}
        WHERE {where}
        ORDER BY position ASC, variant_id ASC
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

    @_capability_guarded
    async def query_variants_by_region(
        self,
        assembly: str,
        chromosome: str,
        start: int,
        end: int,
        max_results: int = 1000,
        *,
        release_context: ReleaseContext | None = None,
    ) -> list[dict[str, Any]]:
        """Query variants in a genomic region.

        ``assembly`` is a required parameter (never hardcoded).
        """
        if release_context is None:
            raise ServiceUnavailableError("Release context is required")
        query = f"""
        SELECT
            variant_id, release_key, assembly_key, chromosome, position,
            ref_allele, alt_allele, variant_type, gene_id, gene_symbol,
            variant_subtype, length, gene_surrogate_id, mutant_line_surrogate_id,
            consequence, consequence_id, impact, rs_id, quality_score,
            filter_status, read_depth, allele_frequency, hgvs_c, hgvs_p, zygosity
        FROM {VARIANT_FACTS_TABLE}
        WHERE release_key = %(release_key)s
          AND assembly_key = %(assembly)s
          AND chromosome = %(chromosome)s
          AND position >= %(start)s
          AND position <= %(end)s
        ORDER BY position ASC, variant_id ASC
        LIMIT %(max_results)s
        """
        qp = {
            "release_key": release_context.release_key,
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

    @_capability_guarded
    async def get_variant_by_id(
        self,
        variant_id: str,
        *,
        release_context: ReleaseContext,
    ) -> dict[str, Any] | None:
        """Fetch a single variant by its ID."""
        query = f"""
        SELECT
            variant_id, release_key, assembly_key, chromosome, position,
            ref_allele, alt_allele, variant_type, gene_id, gene_symbol,
            variant_subtype, length, gene_surrogate_id, mutant_line_surrogate_id,
            consequence, consequence_id, impact, rs_id, quality_score,
            filter_status, read_depth, allele_frequency, hgvs_c, hgvs_p, zygosity
        FROM {VARIANT_FACTS_TABLE}
        WHERE release_key = %(release_key)s
          AND variant_id = %(vid)s
        LIMIT 1
        """
        client = await self._get_client()
        result = await client.query(
            query,
            parameters={
                "release_key": release_context.release_key,
                "vid": variant_id,
            },
        )
        if result.row_count == 0:
            return None
        columns = result.column_names
        return dict(zip(columns, result.first_row))

    @_capability_guarded
    async def get_dashboard_stats(self, release_key: str | None = None) -> dict[str, Any]:
        """Aggregate dashboard statistics for one release.

        ``release_key`` is required for a public aggregate: without it the
        query spans every release's facts, so a dashboard could show
        unpublished variant counts. It is a bound parameter, never interpolated.
        """
        where = ""
        parameters: dict[str, Any] = {}
        if release_key is not None:
            where = "WHERE release_key = %(release_key)s"
            parameters["release_key"] = release_key
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
        {where}
        """
        client = await self._get_client()
        result = await client.query(query, parameters=parameters)
        if result.row_count == 0:
            return {}
        columns = result.column_names
        return dict(zip(columns, result.first_row))

    @_capability_guarded
    async def get_variant_type_distribution(
        self, assembly: str | None = None, release_key: str | None = None
    ) -> dict[str, int]:
        """Return variant type distribution for one release.

        ``release_key`` is required on public surfaces: without it the
        aggregate spans every release's facts.
        """
        client = await self._get_client()
        if assembly is not None or release_key is not None:
            clauses = []
            parameters: dict[str, Any] = {}
            if assembly is not None:
                clauses.append("assembly_key = %(assembly)s")
                parameters["assembly"] = assembly
            if release_key is not None:
                clauses.append("release_key = %(release_key)s")
                parameters["release_key"] = release_key
            where = " AND ".join(clauses)
            query = f"""
            SELECT variant_type, count() AS cnt
            FROM {VARIANT_FACTS_TABLE}
            WHERE {where}
            GROUP BY variant_type
            """
            result = await client.query(query, parameters=parameters)
        else:
            query = f"""
            SELECT variant_type, count() AS cnt
            FROM {VARIANT_FACTS_TABLE}
            GROUP BY variant_type
            """
            result = await client.query(query)
        return {row[0]: int(row[1]) for row in result.result_rows}

    @_capability_guarded
    async def get_chromosome_density(
        self,
        assembly: str,
        chromosome: str,
        bin_size: int = 1_000_000,
        release_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """Compute variant density bins for a chromosome in one release.

        ``release_key`` is required on public surfaces: an unbounded density
        mixes every release's facts for the same assembly/chromosome.
        """
        release_clause = ""
        if release_key is not None:
            release_clause = "AND release_key = %(release_key)s"
        query = f"""
        SELECT
            intDiv(position - 1, %(bin_size)s) * %(bin_size)s + 1 AS bin_start,
            count() AS variant_count
        FROM {VARIANT_FACTS_TABLE}
        WHERE assembly_key = %(assembly)s
          AND chromosome = %(chromosome)s
          {release_clause}
        GROUP BY bin_start
        ORDER BY bin_start
        """
        qp = {
            "assembly": assembly,
            "chromosome": chromosome,
            "bin_size": bin_size,
            **({"release_key": release_key} if release_key is not None else {}),
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

    @_capability_guarded
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
        if value is None:
            return 0.0
        number = float(value)
        # An ungrouped aggregate always returns exactly one row, so
        # `row_count == 0` never fires for an empty window: ClickHouse answers
        # `quantile()` over zero rows with NaN. `float(value or 0.0)` does not
        # catch it either -- bool(nan) is True -- so NaN escaped into the
        # response model, whose `ge=0` bound turned the admin dashboard into a
        # 500. The docstring already promised 0.0 for "no events"; this makes
        # that true.
        return number if math.isfinite(number) else 0.0
    @_capability_guarded
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
