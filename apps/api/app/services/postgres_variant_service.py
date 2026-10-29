"""Variant facts and operational aggregates in the authoritative PostgreSQL database."""

from __future__ import annotations

import functools
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_session_factory
from ..core.exceptions import ServiceUnavailableError, ValidationError
from ..schemas.variant import VariantFilterParams
from .release_context import ReleaseContext
from .variant_repository import _FIELDS, VariantRepository
from .variant_visibility import PUBLIC_FACT_VISIBILITY


def _guard(operation):
    @functools.wraps(operation)
    async def wrapped(*args, **kwargs):
        try:
            return await operation(*args, **kwargs)
        except (SQLAlchemyError, OSError, TimeoutError) as error:
            raise ServiceUnavailableError("Variant data is unavailable") from error
    return wrapped


def _release_scope(
    release_key: str | None, *, public_only: bool = True,
) -> tuple[str, dict[str, Any]]:
    conditions = [PUBLIC_FACT_VISIBILITY] if public_only else []
    values: dict[str, Any] = {}
    if release_key is not None:
        conditions.append("release_id = :release_id")
        values["release_id"] = int(release_key)
    return ("WHERE " + " AND ".join(conditions) if conditions else ""), values


def _cutoff(days: int) -> datetime:
    if not 1 <= days <= 365:
        raise ValueError("Analytics window must be between 1 and 365 days")
    return datetime.now(UTC) - timedelta(days=days)


def _finite(value) -> float:
    number = float(value or 0)
    return number if math.isfinite(number) else 0.0


class PostgresVariantService:
    """Small transaction-scoped queries; no independently managed analytics client."""

    @_guard
    async def count_variants(
        self, params: VariantFilterParams, *, release_context: ReleaseContext,
    ) -> int:
        async with get_session_factory()() as db:
            return await VariantRepository(db).count(params, context=release_context)

    @_guard
    async def query_variants(
        self, params: VariantFilterParams, limit: int, *, release_context: ReleaseContext,
        cursor_key: tuple[int, int] | None = None,
        db: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        """Read one variant page, optionally inside the caller's session.

        A caller that already owns a session (the request-scoped one) passes
        it in: the repository then reads through that session, so the request
        holds a single pooled connection instead of checking out a second
        one for the same page.
        """
        if db is not None:
            return await VariantRepository(db).list(
                params, context=release_context, limit=limit, cursor_key=cursor_key,
            )
        async with get_session_factory()() as session:
            return await VariantRepository(session).list(
                params, context=release_context, limit=limit, cursor_key=cursor_key,
            )

    async def query_variants_by_region(
        self, assembly: str, chromosome: str, start: int, end: int,
        max_results: int = 1000, *, release_context: ReleaseContext | None = None,
        db: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        if release_context is None:
            raise ServiceUnavailableError("Release context is required")
        if not assembly:
            raise ValidationError("Assembly is required")
        params = VariantFilterParams(
            assembly=assembly, chromosome=chromosome, start=start, end=end,
        )
        if db is not None:
            return await self.query_variants(
                params, max_results, release_context=release_context, db=db,
            )
        async with get_session_factory()() as session:
            return await self.query_variants(
                params, max_results, release_context=release_context, db=session,
            )

    @_guard
    async def get_variant_by_id(
        self, variant_id: str, *, release_context: ReleaseContext,
    ) -> dict[str, Any] | None:
        try:
            identity = int(variant_id)
        except ValueError:
            return None
        if not 0 <= identity <= 18446744073709551615:
            return None
        async with get_session_factory()() as db:
            result = await db.execute(text(
                f"SELECT {_FIELDS} FROM variant_facts "
                "WHERE release_id = :release_id AND variant_id = :variant_id AND "
                + PUBLIC_FACT_VISIBILITY
            ), {"release_id": release_context.release_id, "variant_id": identity})
            record = result.mappings().one_or_none()
            if record is None:
                return None
            row = dict(record)
            row["variant_id"] = int(row["variant_id"])
            row["release_key"] = str(row.pop("release_id"))
            return row

    @_guard
    async def get_dashboard_stats(
        self, release_key: str | None = None, *, public_only: bool = True,
    ) -> dict[str, Any]:
        """Return the cheap release-scoped variant counters.

        The two distinct counts (``total_genes`` / ``total_mutant_lines``) are
        deliberately **not** part of this aggregate any more: every caller
        discards them, and each one costs a full scan of ``variant_facts``
        plus a DISTINCT sort that no index supports (migration 0047). They
        stay available through :meth:`get_dashboard_distinct_counts`, which
        pays that price only when a caller explicitly asks for them.
        """
        # Only the role-checked admin overview opts out of public visibility.
        where, values = _release_scope(release_key, public_only=public_only)
        sql = (
            "SELECT count(*) AS total_variants, "
            "count(*) FILTER (WHERE variant_type = 'SNP') AS snp_count, "
            "count(*) FILTER (WHERE variant_type = 'INS') AS ins_count, "
            "count(*) FILTER (WHERE variant_type = 'DEL') AS del_count, "
            "count(*) FILTER (WHERE variant_type = 'MNV') AS mnv_count, "
            "count(*) FILTER (WHERE variant_type = 'SV') AS sv_count "
            "FROM variant_facts " + where
        )
        async with get_session_factory()() as db:
            return dict((await db.execute(text(sql), values)).mappings().one())

    @_guard
    async def get_dashboard_distinct_counts(
        self, release_key: str | None = None,
    ) -> dict[str, int]:
        """Return the distinct gene / mutant-line counts for one release.

        This is the expensive aggregate the dashboard no longer computes
        implicitly: both numbers need a full scan of ``variant_facts`` and a
        DISTINCT sort, and no index supports either one. It is therefore an
        explicit, separately billed call — a caller that wants the numbers
        asks for them here instead of paying for them on every cache miss.

        The release scope is the same as :meth:`get_dashboard_stats`: a
        ``release_key`` restricts the counts to that release.
        """
        where, values = _release_scope(release_key)
        sql = (
            "SELECT count(DISTINCT (assembly_id, gene_id)) FILTER "
            "(WHERE gene_id <> '') AS total_genes, "
            "count(DISTINCT mutant_line_surrogate_id) FILTER "
            "(WHERE mutant_line_surrogate_id <> 0) AS total_mutant_lines "
            "FROM variant_facts " + where
        )
        async with get_session_factory()() as db:
            row = (await db.execute(text(sql), values)).mappings().one()
        return {
            "total_genes": int(row["total_genes"] or 0),
            "total_mutant_lines": int(row["total_mutant_lines"] or 0),
        }

    @_guard
    async def get_variant_type_distribution(
        self, assembly: str | None = None, release_key: str | None = None,
    ) -> dict[str, int]:
        where, values = _release_scope(release_key)
        if assembly is not None:
            where += (" AND " if where else "WHERE ") + "assembly_key = :assembly"
            values["assembly"] = assembly
        async with get_session_factory()() as db:
            result = await db.execute(text(
                "SELECT variant_type, count(*) FROM variant_facts "
                + where + " GROUP BY variant_type"
            ), values)
            return {str(kind): int(count) for kind, count in result}

    @_guard
    async def get_chromosome_density(
        self, assembly: str, chromosome: str, bin_size: int = 1_000_000,
        release_key: str | None = None,
    ) -> list[dict[str, Any]]:
        if bin_size < 1:
            raise ValueError("Density bin size must be positive")
        where, values = _release_scope(release_key)
        where += (" AND " if where else "WHERE ") + (
            "assembly_key = :assembly AND chromosome = :chromosome"
        )
        values.update(assembly=assembly, chromosome=chromosome, bin_size=bin_size)
        async with get_session_factory()() as db:
            result = await db.execute(text(
                "SELECT ((position - 1) / CAST(:bin_size AS bigint)) "
                "* CAST(:bin_size AS bigint) + 1 AS bin_start, count(*) "
                "FROM variant_facts " + where + " GROUP BY bin_start ORDER BY bin_start"
            ), values)
            return [{"bin_start": int(start), "bin_end": int(start) + bin_size - 1,
                     "count": int(count)} for start, count in result]

    async def ping(self) -> bool:
        try:
            async with get_session_factory()() as db:
                return (await db.execute(text("SELECT 1"))).scalar_one() == 1
        except (SQLAlchemyError, OSError, TimeoutError):
            return False

    @_guard
    async def get_query_latency_percentile(
        self, percentile: float = 0.95, days: int = 30,
    ) -> float:
        if not 0 <= percentile <= 1:
            raise ValueError("Percentile must be between 0 and 1")
        async with get_session_factory()() as db:
            result = await db.execute(text(
                "SELECT percentile_cont(:percentile) WITHIN GROUP (ORDER BY duration_ms) "
                "FROM analytics_events WHERE timestamp >= :cutoff"
            ), {"percentile": percentile, "cutoff": _cutoff(days)})
            return _finite(result.scalar_one())

    @_guard
    async def get_query_latency_series(self, days: int = 30) -> list[dict[str, Any]]:
        async with get_session_factory()() as db:
            result = await db.execute(text(
                "SELECT (timestamp AT TIME ZONE 'UTC')::date AS day, "
                "percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms), "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms), "
                "percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms) "
                "FROM analytics_events WHERE timestamp >= :cutoff "
                "GROUP BY day ORDER BY day"
            ), {"cutoff": _cutoff(days)})
            return [{"date": str(day), "p50": _finite(p50), "p95": _finite(p95),
                     "p99": _finite(p99)} for day, p50, p95, p99 in result]
