"""Variant service with keyset cursor pagination (base64-encoded).

The cursor is a base64-encoded JSON payload containing the last seen sort key
(``position``).  This is a true keyset pagination – never OFFSET.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NotFoundError, ValidationError
from ..models.genomic import Assembly, Chromosome
from ..models.variant import VariantSummary
from ..schemas.variant import (
    VariantDetail,
    VariantFilterParams,
    VariantListResponse,
    VariantResponse,
)
from .clickhouse_service import ClickHouseService


def encode_cursor(position: int) -> str:
    """Encode a sort key into an opaque base64 cursor string."""
    payload = json.dumps({"p": position}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> int:
    """Decode a base64 cursor back into the sort key.

    Raises :class:`ValidationError` if the cursor is malformed.
    """
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        return int(payload["p"])
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
    ) -> VariantListResponse:
        """Return a cursor-paginated list of variants."""
        cursor_position: int | None = None
        if params.cursor:
            cursor_position = decode_cursor(params.cursor)

        rows = await self.ch.query_variants(
            params=params,
            limit=params.limit + 1,  # fetch one extra to detect has_more
            cursor_position=cursor_position,
        )

        has_more = len(rows) > params.limit
        if has_more:
            rows = rows[: params.limit]

        items = [self._row_to_response(r) for r in rows]
        next_cursor = encode_cursor(rows[-1]["position"]) if has_more and rows else None

        return VariantListResponse(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            total_count=None,  # omitted for large result sets
        )

    async def get_variant(self, variant_id: str) -> VariantDetail:
        """Fetch a single variant detail from ClickHouse."""
        row = await self.ch.get_variant_by_id(variant_id)
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
    ) -> list[VariantResponse]:
        """Region query – ``assembly`` is required (never hardcoded)."""
        if not assembly:
            raise ValidationError("assembly parameter is required for region queries")
        rows = await self.ch.query_variants_by_region(
            assembly=assembly,
            chromosome=chromosome,
            start=start,
            end=end,
            max_results=max_results,
        )
        return [self._row_to_response(r) for r in rows]

    async def get_variant_count(self, params: VariantFilterParams) -> int:
        """Return the total count of matching variants (best-effort)."""
        return await self.ch.count_variants(params)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _row_to_response(row: dict[str, Any]) -> VariantResponse:
        return VariantResponse(
            id=str(row.get("variant_id", "")),
            variant_id=row.get("variant_id"),
            assembly_id="",
            chromosome=str(row.get("chromosome", "")),
            position=int(row.get("position", 0)),
            ref_allele=str(row.get("ref_allele", "")),
            alt_allele=str(row.get("alt_allele", "")),
            variant_type=row.get("variant_type", "SNP"),
            quality=float(row.get("quality_score") or 0) or None,
            filter_status=str(row.get("filter_status", "PASS")),
            allele_frequency=float(row.get("allele_frequency") or 0) or None,
        )

    @staticmethod
    def _row_to_detail(row: dict[str, Any]) -> VariantDetail:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        return VariantDetail(
            id=str(row.get("variant_id", "")),
            variant_id=row.get("variant_id"),
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
