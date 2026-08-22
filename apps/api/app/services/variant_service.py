"""Release-scoped variant service with stable keyset cursor pagination."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NotFoundError, ValidationError
from ..schemas.variant import (
    VariantDetail,
    VariantFilterParams,
    VariantListResponse,
    VariantResponse,
)
from .clickhouse_service import ClickHouseService
from .release_context import (
    ReleaseContext,
    decode_bound_cursor,
    encode_bound_cursor,
)


def _cursor_filters(params: VariantFilterParams) -> dict[str, Any]:
    return params.model_dump(
        mode="json",
        exclude={"cursor", "limit"},
        exclude_none=True,
    )


def encode_cursor(
    position: int,
    variant_id: int,
    *,
    release_context: ReleaseContext,
    params: VariantFilterParams,
) -> str:
    """Encode an authenticated ``(position, variant_id)`` cursor."""
    return encode_bound_cursor(
        kind="variant",
        sort_key={"p": position, "i": variant_id},
        release_context=release_context,
        filters=_cursor_filters(params),
    )


def decode_cursor(
    cursor: str,
    *,
    release_context: ReleaseContext,
    params: VariantFilterParams,
) -> tuple[int, int]:
    """Verify and decode a ``(position, variant_id)`` keyset cursor.

    Raises :class:`ValidationError` if the cursor is malformed.
    """
    try:
        payload = decode_bound_cursor(
            cursor,
            kind="variant",
            release_context=release_context,
            filters=_cursor_filters(params),
        )
        position = payload["p"]
        variant_id = payload["i"]
        if type(position) is not int or position < 0:
            raise ValueError("position must be a non-negative integer")
        if type(variant_id) is not int or variant_id < 0:
            raise ValueError("variant id must be a non-negative integer")
        return position, variant_id
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"Invalid cursor: {exc}") from exc


class VariantService:
    """High-level variant query service.

    Combines ClickHouse (bulk variant facts) with PostgreSQL (relational
    metadata) and implements cursor pagination.
    """

    def __init__(self, ch: ClickHouseService | None = None) -> None:
        self.ch = ch or ClickHouseService()

    async def list_variants(
        self,
        db: AsyncSession,
        params: VariantFilterParams,
        *,
        release_context: ReleaseContext,
    ) -> VariantListResponse:
        """Return a cursor-paginated list of variants."""
        cursor_key: tuple[int, int] | None = None
        if params.cursor:
            cursor_key = decode_cursor(
                params.cursor,
                release_context=release_context,
                params=params,
            )

        rows = await self.ch.query_variants(
            params=params,
            release_context=release_context,
            limit=params.limit + 1,  # fetch one extra to detect has_more
            cursor_key=cursor_key,
        )

        has_more = len(rows) > params.limit
        if has_more:
            rows = rows[: params.limit]

        items = [self._row_to_response(r) for r in rows]
        next_cursor = (
            encode_cursor(
                int(rows[-1]["position"]),
                int(rows[-1]["variant_id"]),
                release_context=release_context,
                params=params,
            )
            if has_more and rows
            else None
        )

        return VariantListResponse(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            total_count=None,  # omitted for large result sets
        )

    async def get_variant(
        self,
        variant_id: str,
        *,
        release_context: ReleaseContext,
    ) -> VariantDetail:
        """Fetch a single variant detail from ClickHouse."""
        row = await self.ch.get_variant_by_id(
            variant_id,
            release_context=release_context,
        )
        if row is None:
            raise NotFoundError(f"Variant {variant_id} not found")
        return self._row_to_detail(row)

    async def get_variants_by_region(
        self,
        assembly: str,
        chromosome: str,
        start: int,
        end: int,
        max_results: int = 1000,
        *,
        release_context: ReleaseContext,
    ) -> list[VariantResponse]:
        """Region query – ``assembly`` is required (never hardcoded)."""
        if not assembly:
            raise ValidationError("assembly parameter is required for region queries")
        rows = await self.ch.query_variants_by_region(
            release_context=release_context,
            assembly=assembly,
            chromosome=chromosome,
            start=start,
            end=end,
            max_results=max_results,
        )
        return [self._row_to_response(r) for r in rows]

    async def get_variant_count(
        self,
        params: VariantFilterParams,
        *,
        release_context: ReleaseContext,
    ) -> int:
        """Return the total count of matching variants (best-effort)."""
        return await self.ch.count_variants(
            params,
            release_context=release_context,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _row_to_response(row: dict[str, Any]) -> VariantResponse:
        return VariantResponse(
            id=str(row.get("variant_id", "")),
            variant_id=str(row.get("variant_id", "")),
            assembly_id="",
            chromosome=str(row.get("chromosome", "")),
            position=int(row.get("position", 0)),
            ref_allele=str(row.get("ref_allele", "")),
            alt_allele=str(row.get("alt_allele", "")),
            variant_type=row.get("variant_type", "SNP"),
            quality=float(row.get("quality_score") or 0) or None,
            filter_status=str(row.get("filter_status", "PASS")),
            allele_frequency=float(row.get("allele_frequency") or 0) or None,
            gene_id=row.get("gene_id"),
            gene_symbol=row.get("gene_symbol"),
            consequence=row.get("consequence"),
            impact=row.get("impact"),
        )

    @staticmethod
    def _row_to_detail(row: dict[str, Any]) -> VariantDetail:
        now = datetime.now(UTC)
        return VariantDetail(
            id=str(row.get("variant_id", "")),
            variant_id=str(row.get("variant_id", "")),
            assembly_id="",
            chromosome=str(row.get("chromosome", "")),
            position=int(row.get("position", 0)),
            ref_allele=str(row.get("ref_allele", "")),
            alt_allele=str(row.get("alt_allele", "")),
            variant_type=row.get("variant_type", "SNP"),
            quality=float(row.get("quality_score") or 0) or None,
            filter_status=str(row.get("filter_status", "PASS")),
            allele_frequency=float(row.get("allele_frequency") or 0) or None,
            gene_id=row.get("gene_id"),
            gene_symbol=row.get("gene_symbol"),
            consequence=row.get("consequence"),
            impact=row.get("impact"),
            hgvs_c=row.get("hgvs_c"),
            hgvs_p=row.get("hgvs_p"),
            depth=int(row.get("read_depth") or 0) or None,
            genotype=row.get("zygosity"),
            created_at=now,
            updated_at=now,
        )
