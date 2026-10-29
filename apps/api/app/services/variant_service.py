"""Release-scoped variant service with stable keyset cursor pagination."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NotFoundError, ServiceUnavailableError, ValidationError
from ..schemas.variant import (
    VariantDetail,
    VariantFilterParams,
    VariantListResponse,
    VariantResponse,
)
from .postgres_variant_service import PostgresVariantService
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

    Reads PostgreSQL facts and implements release-bound cursor pagination.
    """

    def __init__(self, variant_service: PostgresVariantService | None = None) -> None:
        self.variant_service = variant_service or PostgresVariantService()

    async def list_variants(
        self,
        db: AsyncSession,
        params: VariantFilterParams,
        *,
        release_context: ReleaseContext,
    ) -> VariantListResponse:
        """Return a cursor-paginated list of variants.

        The caller's session is forwarded to the store, so the page is read
        through the connection the request already holds. One request never
        checks out a second pooled connection for the same read.
        """
        cursor_key: tuple[int, int] | None = None
        if params.cursor:
            cursor_key = decode_cursor(
                params.cursor,
                release_context=release_context,
                params=params,
            )

        rows = await self._variant_query(
            self._with_session(
                db,
                self.variant_service.query_variants,
                params=params,
                release_context=release_context,
                limit=params.limit + 1,  # fetch one extra to detect has_more
                cursor_key=cursor_key,
            )
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
        """Fetch one variant from the authoritative release-scoped store."""
        row = await self._variant_query(
            self.variant_service.get_variant_by_id(
                variant_id,
                release_context=release_context,
            )
        )
        if row is None:
            raise NotFoundError(f"Variant {variant_id} not found")
        return self._row_to_detail(row)

    async def get_variants_by_region(
        self,
        db: AsyncSession,
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
        rows = await self._variant_query(
            self._with_session(
                db,
                self.variant_service.query_variants_by_region,
                release_context=release_context,
                assembly=assembly,
                chromosome=chromosome,
                start=start,
                end=end,
                max_results=max_results,
            )
        )
        return [self._row_to_response(r) for r in rows]

    async def get_variant_count(
        self,
        params: VariantFilterParams,
        *,
        release_context: ReleaseContext,
    ) -> int:
        """Return the total count of matching variants (best-effort)."""
        return await self._variant_query(
            self.variant_service.count_variants(
                params,
                release_context=release_context,
            )
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _with_session(db: AsyncSession | None, call, **kwargs):
        """Invoke a store query, forwarding the caller's session.

        The session is forwarded whenever the caller owns one: the store
        then reads through the connection the request already holds instead
        of checking out a second one. A caller without a session (a store
        that manages its own) is called without the extra argument, so the
        store's own session lifecycle stays in charge of that path.
        """
        if db is None:
            return call(**kwargs)
        return call(db=db, **kwargs)

    @staticmethod
    async def _variant_query(coro):
        """Run a variant projection query with capability-aware failure.

        The analytics projection (H01) is a required capability in extended
        deployments but may be absent in baseline/disposable environments.
        Transport errors must surface as ``503 service_unavailable`` with a
        clear message (no stack trace / host details), never as ``500`` —
        the endpoint reports capability state instead of crashing.
        """
        try:
            return await coro
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            raise ServiceUnavailableError("Variant data is unavailable") from exc

    @staticmethod
    def _row_to_response(row: dict[str, Any]) -> VariantResponse:
        return VariantResponse(
            id=str(row.get("variant_id", "")),
            variant_id=str(row.get("variant_id", "")),
            assembly_id="",
            assembly=str(row.get("assembly_key", "")) or None,
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
            # Native unannotated facts store empty strings, not enum values.
            consequence=row.get("consequence") or None,
            impact=row.get("impact") or None,
        )

    @staticmethod
    def _row_to_detail(row: dict[str, Any]) -> VariantDetail:
        now = datetime.now(UTC)
        return VariantDetail(
            id=str(row.get("variant_id", "")),
            variant_id=str(row.get("variant_id", "")),
            assembly_id="",
            assembly=str(row.get("assembly_key", "")) or None,
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
            # Native unannotated facts store empty strings, not enum values.
            consequence=row.get("consequence") or None,
            impact=row.get("impact") or None,
            hgvs_c=row.get("hgvs_c"),
            hgvs_p=row.get("hgvs_p"),
            depth=int(row.get("read_depth") or 0) or None,
            genotype=row.get("zygosity"),
            created_at=now,
            updated_at=now,
        )
