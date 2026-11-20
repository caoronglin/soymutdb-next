"""The three column-name layers of the ``variant_facts`` read path stay aligned.

Filtering (``_predicates``), projection (``_FIELDS``) and the response mappers
each name their own columns. Nothing in the type system ties them together, so
these tests do: a filterable column that is never selected, or a mapper reading
a key the SQL never selects, fails here instead of at runtime as a bare
``KeyError`` whose traceback names no layer.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.schemas.variant import VariantFilterParams
from app.services.release_context import ReleaseContext
from app.services.variant_repository import (
    _FIELDS,
    DETAIL_ONLY_FIELDS,
    EQUALITY_PREDICATES,
    FACTS,
    FILTER_PREDICATES,
    MAPPED_ONLY_FIELDS,
    PROJECTED_ALIASES,
    PROJECTED_COLUMNS,
    RANGE_PREDICATES,
    UNUSED_PROJECTED_FIELDS,
    VariantRepository,
    _where_and_values,
    assert_response_keys_are_projected,
)
from app.services.variant_service import VariantService

CONTEXT = ReleaseContext(release_id=17, assembly_id=5)


def _rendered(filter_params: VariantFilterParams, context=CONTEXT) -> str:
    where, _ = _where_and_values(filter_params, context)
    return str(where.compile(dialect=postgresql.dialect()))


# --------------------------------------------------------------------------- #
# 1. filter layer ⊆ projection layer
# --------------------------------------------------------------------------- #


def test_every_filterable_column_is_projected():
    filterable = {column for _, column in FILTER_PREDICATES}
    projected = set(PROJECTED_COLUMNS)

    assert not filterable - projected, (
        "filterable but never selected (a filter the caller cannot see):",
        sorted(filterable - projected),
    )


def test_mutant_line_filter_matches_its_projection():
    # The concrete case this contract was written for: the public-id filter
    # resolves to ``mutant_line_name``, so the column must travel with the row.
    assert ("mutant_line_name", "mutant_line_name") in EQUALITY_PREDICATES
    assert "mutant_line_name" in PROJECTED_COLUMNS


def test_range_predicates_target_projected_columns():
    for _, column, operator in RANGE_PREDICATES:
        assert operator in {">=", "<="}
        assert column in PROJECTED_COLUMNS


def test_projection_has_no_duplicates():
    assert len(PROJECTED_COLUMNS) == len(set(PROJECTED_COLUMNS))


def test_projection_is_declared_exhaustively():
    # Every projected column is one of: identity, filterable, detail-only,
    # declared-unused, or aliased on the way out. Nothing sneaks in otherwise.
    declared = (
        {"variant_id"}
        | {column for _, column in FILTER_PREDICATES}
        | set(MAPPED_ONLY_FIELDS)
        | set(DETAIL_ONLY_FIELDS)
        | set(UNUSED_PROJECTED_FIELDS)
        | set(PROJECTED_ALIASES)
    )
    assert set(PROJECTED_COLUMNS) == declared


def test_fields_string_matches_the_declared_columns():
    assert _FIELDS.split(", ") == list(PROJECTED_COLUMNS)


# --------------------------------------------------------------------------- #
# 2. response layer ⊆ projection layer
# --------------------------------------------------------------------------- #


def test_response_mappers_only_read_projected_keys():
    assert_response_keys_are_projected(
        VariantService.RESPONSE_ROW_KEYS, VariantService.DETAIL_ROW_KEYS,
    )


def test_detail_keys_are_a_superset_of_list_keys():
    assert VariantService.RESPONSE_ROW_KEYS <= VariantService.DETAIL_ROW_KEYS


def test_the_alias_is_the_only_key_not_named_after_its_column():
    # ``release_id`` is renamed to ``release_key`` on the way out; that rename
    # is the one place a response key is not a column name.
    assert PROJECTED_ALIASES == {"release_id": "release_key"}
    assert "release_key" not in PROJECTED_COLUMNS


def test_assertion_rejects_a_key_outside_the_projection():
    # Negative control: the guard must actually fire.
    with pytest.raises(AssertionError, match="unprojected"):
        assert_response_keys_are_projected(frozenset({"definitely_not_a_column"}))


# --------------------------------------------------------------------------- #
# 3. count and list share one WHERE
# --------------------------------------------------------------------------- #


def test_count_and_list_render_the_same_where_clause():
    filters = VariantFilterParams(assembly="v4", chromosome="Chr01", min_af=0.1)

    async def capture():
        captured: list[str] = []

        class _Result:
            def scalar_one(self):
                return 0

            def mappings(self):
                return []

        class _Session:
            async def execute(self, statement, values):
                captured.append(str(statement.compile(dialect=postgresql.dialect())))
                return _Result()

        repository = VariantRepository(_Session())
        await repository.count(filters, context=CONTEXT)
        await repository.list(filters, context=CONTEXT, limit=10)
        return captured

    count_sql, list_sql = asyncio.run(capture())
    count_where = count_sql.split("WHERE ", 1)[1]
    list_where = list_sql.split("WHERE ", 1)[1].split(" ORDER BY", 1)[0]

    assert count_where == list_where


def test_filters_reach_both_statements():
    rendered = _rendered(VariantFilterParams(assembly="v4", gene_id="GLYMA_01G000100"))
    assert "variant_facts.assembly_key = " in rendered
    assert "variant_facts.gene_id = " in rendered


# --------------------------------------------------------------------------- #
# 4. the visibility predicate is an expression, not a string fragment
# --------------------------------------------------------------------------- #


def test_fact_visibility_is_a_sql_expression():
    from app.services.variant_visibility import (
        PUBLIC_FACT_VISIBILITY,
        variant_fact_visibility,
    )

    assert not isinstance(PUBLIC_FACT_VISIBILITY, str)
    assert hasattr(PUBLIC_FACT_VISIBILITY, "compile")
    assert not isinstance(variant_fact_visibility(FACTS), str)


def test_visibility_scope_cannot_absorb_injected_sql():
    # It is composed, never concatenated, so a hostile value stays a value.
    attack = "v4' OR 1=1 --"
    rendered = _rendered(VariantFilterParams(assembly=attack))
    assert attack not in rendered


def test_visibility_predicate_binds_the_release_status_typed():
    # ``releases.status`` is a native enum; PostgreSQL rejects an untyped bind
    # with "operator does not exist: release_status_enum = character varying".
    # The status literal must therefore carry the column's own type.
    where, _ = _where_and_values(VariantFilterParams(), CONTEXT)
    compiled = select(func.count()).select_from(FACTS).where(where).compile(
        dialect=postgresql.dialect(),
    )
    status_types = {
        type(bind.type).__name__
        for bind in compiled.binds.values()
        if getattr(bind.value, "__class__", None) is str
        and "published" in str(bind.value)
    }
    assert status_types == {"Enum"}


def test_the_text_form_stays_correlated_to_the_outer_row():
    """The aggregate text form must correlate, not re-declare ``variant_facts``.

    Rendered bare, the EXISTS subqueries put ``variant_facts`` in their own FROM
    list and the predicate stops filtering (it counted every row of the table).
    Correlation only happens inside a statement, so the text form is rendered
    from one - and the render must not contain the surface again.
    """
    from app.services.postgres_variant_service import PUBLIC_FACT_VISIBILITY_SQL

    assert "variant_facts.mutant_line_name" in PUBLIC_FACT_VISIBILITY_SQL
    assert "FROM releases, variant_facts" not in PUBLIC_FACT_VISIBILITY_SQL
    assert "FROM mutant_lines, variant_facts" not in PUBLIC_FACT_VISIBILITY_SQL
