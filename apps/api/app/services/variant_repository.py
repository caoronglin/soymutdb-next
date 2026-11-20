"""Native PostgreSQL variant lookup with explicit release and assembly scopes.

This repository deliberately accepts a caller's transaction. Import finalization
and API reads therefore use the same authoritative database and visibility
rules, without a second database client or SQL dialect translation.

Filtering, projection and response mapping each name their own columns.
``PROJECTED_COLUMNS`` derives the projection from the filter table plus the
declared extras, so a filterable column is always selected and a selected column
is always accounted for; ``assert_response_keys_are_projected`` binds the
response mappers to the same list. Both fail with the offending column named,
instead of a ``KeyError`` whose traceback does not say which layer lost it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, bindparam, column, func, select, table, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, operators

from ..schemas.variant import VariantFilterParams
from .release_context import ReleaseContext
from .variant_visibility import variant_fact_visibility

# --------------------------------------------------------------------------- #
# Column-name contract (filter layer → projection layer → response layer)
# --------------------------------------------------------------------------- #

# ``(param, column)`` and ``(param, column, operator)``: the only places a
# column name may enter the WHERE clause. Both are fixed module-level data, so
# no caller-supplied identifier ever becomes SQL.
EQUALITY_PREDICATES: tuple[tuple[str, str], ...] = (
    ("assembly", "assembly_key"),
    ("chromosome", "chromosome"),
    ("ref", "ref_allele"),
    ("alt", "alt_allele"),
    ("gene_id", "gene_id"),
    ("mutant_line_name", "mutant_line_name"),
    ("variant_type", "variant_type"),
    ("consequence", "consequence"),
    ("impact", "impact"),
)

RANGE_PREDICATES: tuple[tuple[str, str, str], ...] = (
    ("start", "position", ">="),
    ("end", "position", "<="),
    ("min_af", "allele_frequency", ">="),
    ("max_af", "allele_frequency", "<="),
)

# Every filterable column is also projectable: a filter that cannot be seen in
# the response cannot be explained to the caller.
FILTER_PREDICATES = EQUALITY_PREDICATES + tuple(
    (param, column) for param, column, _ in RANGE_PREDICATES
)

# Read by the response mappers but not filterable: the gene is selected and
# returned, never queried by symbol.
MAPPED_ONLY_FIELDS: tuple[str, ...] = ("gene_symbol",)

# Projected and mapped by ``VariantDetail`` only (list rows never read them,
# but ``_FIELDS`` is shared by the list and the detail statement).
DETAIL_ONLY_FIELDS: tuple[str, ...] = (
    "consequence_id",
    "gene_surrogate_id",
    "length",
    "mutant_line_surrogate_id",
    "rs_id",
    "variant_subtype",
    "read_depth",
    "hgvs_c",
    "hgvs_p",
    "zygosity",
)

# Filterable, therefore projected (see FILTER_PREDICATES), yet no mapper reads
# it today and the response models expose no such field. Whether to publish it
# is a product decision; this declaration keeps it an explicit one instead of an
# accident of hand-written SQL. Drop it here if the answer becomes "never".
UNUSED_PROJECTED_FIELDS: tuple[str, ...] = (
    "allele_frequency",
    "filter_status",
    "mutant_line_name",
    "quality_score",
)

# Released row identity: returned to callers as ``release_key``, never mapped
# onto a response model field.
RELEASE_SCOPE_COLUMN = "release_id"
PROJECTED_ALIASES: dict[str, str] = {RELEASE_SCOPE_COLUMN: "release_key"}


def _unique(names: tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(name, None)
    return tuple(seen)


PROJECTED_COLUMNS: tuple[str, ...] = _unique(
    ("variant_id",)
    + tuple(column for _, column in FILTER_PREDICATES)
    + MAPPED_ONLY_FIELDS
    + DETAIL_ONLY_FIELDS
    + UNUSED_PROJECTED_FIELDS
    + (RELEASE_SCOPE_COLUMN,)
)
_FIELDS = ", ".join(PROJECTED_COLUMNS)

# Failure must name the layer that lost the column, not just a bare KeyError.
assert set(column for _, column in FILTER_PREDICATES) <= set(PROJECTED_COLUMNS), (
    "a filterable column is missing from the projection:"
    f" {sorted(set(c for _, c in FILTER_PREDICATES) - set(PROJECTED_COLUMNS))}"
)
assert set(PROJECTED_ALIASES) <= set(PROJECTED_COLUMNS), (
    "an aliased column is not projected:"
    f" {sorted(set(PROJECTED_ALIASES) - set(PROJECTED_COLUMNS))}"
)


def assert_response_keys_are_projected(*field_sets: frozenset[str]) -> None:
    """Raise when a response mapper reads a key the SQL never selects.

    The response layer names its columns one ``row.get(...)`` at a time. This
    check binds that layer to ``PROJECTED_COLUMNS``, which the repository test
    also compares against the statement executed on a real database.
    """
    projected = set(PROJECTED_COLUMNS) | set(PROJECTED_ALIASES.values())
    for field_set in field_sets:
        missing = sorted(field_set - projected)
        assert not missing, f"response mapper reads unprojected columns: {missing}"


# The read surface these statements select from. Named here, never by a caller.
FACTS = table(
    "variant_facts",
    *(column(name) for name in PROJECTED_COLUMNS),
)


def _where_and_values(
    filters: VariantFilterParams, context: ReleaseContext,
) -> tuple[ColumnElement[Any], dict[str, Any]]:
    """Return the one WHERE clause ``count`` and ``list`` both build from.

    Both statements must keep using this single result: a predicate added on
    one side only would silently skew a page against its own total.
    """
    conditions: list[ColumnElement[Any]] = [
        FACTS.c.release_id == bindparam("release_id"),
        variant_fact_visibility(FACTS),
    ]
    values: dict[str, Any] = {"release_id": context.release_id}
    for field, column_name in EQUALITY_PREDICATES:
        value = getattr(filters, field)
        if value is not None:
            conditions.append(FACTS.c[column_name] == bindparam(field))
            values[field] = getattr(value, "value", value)
    for field, column_name, operator in RANGE_PREDICATES:
        value = getattr(filters, field)
        if value is not None:
            op = operators.ge if operator == ">=" else operators.le
            conditions.append(op(FACTS.c[column_name], bindparam(field)))
            values[field] = value
    return and_(*conditions), values


def _predicates(
    filters: VariantFilterParams, context: ReleaseContext,
) -> tuple[ColumnElement[Any], dict[str, Any]]:
    """The predicates bound into every read statement, plus their values."""
    return _where_and_values(filters, context)


class VariantRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def count(
        self, filters: VariantFilterParams, *, context: ReleaseContext,
    ) -> int:
        where, values = _where_and_values(filters, context)
        statement = select(func.count()).select_from(FACTS).where(where)
        return int((await self.db.execute(statement, values)).scalar_one())

    async def list(
        self, filters: VariantFilterParams, *, context: ReleaseContext,
        limit: int, cursor_key: tuple[int, int] | None = None,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 50000:
            raise ValueError("Variant page size must be between 1 and 50000")
        where, values = _where_and_values(filters, context)
        statement = select(*(FACTS.c[name] for name in PROJECTED_COLUMNS)).where(where)
        if cursor_key is not None:
            # Untyped binds on purpose: `variant_id` is unsigned (up to 2**64-1)
            # and a typed bind would be sent as int8, which no driver can carry.
            statement = statement.where(
                operators.gt(
                    tuple_(FACTS.c.position, FACTS.c.variant_id),
                    tuple_(*(
                        bindparam(name)
                        for name in ("cursor_position", "cursor_variant_id")
                    )),
                )
            )
            values.update(cursor_position=cursor_key[0], cursor_variant_id=cursor_key[1])
        statement = statement.order_by(FACTS.c.position, FACTS.c.variant_id)
        statement = statement.limit(limit)
        result = await self.db.execute(statement, values)
        rows = []
        for record in result.mappings():
            row = dict(record)
            row["variant_id"] = int(row["variant_id"])
            # Keep the established response shape while storing a typed FK.
            row["release_key"] = str(row.pop("release_id"))
            rows.append(row)
        return rows
