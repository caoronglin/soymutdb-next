"""Native PostgreSQL variant lookup with explicit release and assembly scopes.

This repository deliberately accepts a caller's transaction. Import finalization
and API reads therefore use the same authoritative database and visibility
rules, without a second database client or SQL dialect translation.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.variant import VariantFilterParams
from .release_context import ReleaseContext

_FIELDS = (
    "variant_id, release_id, assembly_key, chromosome, position, "
    "ref_allele, alt_allele, variant_type, gene_id, gene_symbol, "
    "variant_subtype, length, gene_surrogate_id, mutant_line_surrogate_id, "
    "consequence, consequence_id, impact, rs_id, quality_score, filter_status, "
    "read_depth, allele_frequency, hgvs_c, hgvs_p, zygosity"
)


def _predicates(
    filters: VariantFilterParams, context: ReleaseContext,
) -> tuple[str, dict[str, Any]]:
    conditions = ["release_id = :release_id"]
    values: dict[str, Any] = {"release_id": context.release_id}
    # These pairs are fixed identifiers, never column names supplied by a user.
    for field, column in (
        ("assembly", "assembly_key"), ("chromosome", "chromosome"),
        ("ref", "ref_allele"), ("alt", "alt_allele"), ("gene_id", "gene_id"),
        ("mutant_line_id", "mutant_line_surrogate_id"),
        ("variant_type", "variant_type"), ("consequence", "consequence"),
        ("impact", "impact"),
    ):
        value = getattr(filters, field)
        if value is not None:
            conditions.append(f"{column} = :{field}")
            values[field] = getattr(value, "value", value)
    for field, column, operator in (
        ("start", "position", ">="), ("end", "position", "<="),
        ("min_af", "allele_frequency", ">="),
        ("max_af", "allele_frequency", "<="),
    ):
        value = getattr(filters, field)
        if value is not None:
            conditions.append(f"{column} {operator} :{field}")
            values[field] = value
    return " AND ".join(conditions), values


class VariantRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def count(
        self, filters: VariantFilterParams, *, context: ReleaseContext,
    ) -> int:
        where, values = _predicates(filters, context)
        result = await self.db.execute(
            text("SELECT count(*) FROM variant_facts WHERE " + where), values,
        )
        return int(result.scalar_one())

    async def list(
        self, filters: VariantFilterParams, *, context: ReleaseContext,
        limit: int, cursor_key: tuple[int, int] | None = None,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 50000:
            raise ValueError("Variant page size must be between 1 and 50000")
        where, values = _predicates(filters, context)
        if cursor_key is not None:
            where += " AND (position, variant_id) > (:cursor_position, :cursor_variant_id)"
            values.update(cursor_position=cursor_key[0], cursor_variant_id=cursor_key[1])
        values["limit"] = limit
        result = await self.db.execute(
            text(f"SELECT {_FIELDS} FROM variant_facts WHERE {where} "
                 "ORDER BY position, variant_id LIMIT :limit"), values,
        )
        rows = []
        for record in result.mappings():
            row = dict(record)
            row["variant_id"] = int(row["variant_id"])
            # Keep the established response shape while storing a typed FK.
            row["release_key"] = str(row.pop("release_id"))
            rows.append(row)
        return rows
