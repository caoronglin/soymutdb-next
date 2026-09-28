"""Ablation guards for the public expression API boundary.

The review found the public expression surface was wholly outside
``ReleaseContext``:

* ``GET /expression/libraries`` and ``/libraries/{id}`` listed any library in
  any assembly/release and accepted the persistence key as the locator;
* gene expression resolved the gene with ``release_context=None`` and joined
  libraries without constraining ``ExpressionLibrary.assembly_id`` to the
  gene's assembly, so a v4 library could attach data to a v5 gene;
* the keyset cursor was a raw ``ExpressionData.id``, which is enumerable and
  could be replayed under a different release/filter set;
* public payloads carried ``ExpressionLibrary.id`` / ``ExpressionData.id``.

These are unit-level guards (no PostgreSQL): the route coroutines are driven
with a fake session that records the compiled SQL and returns canned rows.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.api.v1 import expression as expression_routes
from app.core.exceptions import ValidationError
from app.services.release_context import ReleaseContext

_RELEASE_ID = 7
_ASSEMBLY_ID = 3


def _context(release_id: int = _RELEASE_ID) -> ReleaseContext:
    return ReleaseContext(release_id=release_id, assembly_id=_ASSEMBLY_ID, assembly="Wm82.a4.v1")


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def scalars(self) -> _Rows:
        return self

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0] if self._rows else None


class _RecordingDb:
    """Records every statement and returns a scripted sequence of results."""

    def __init__(self, results: list[Any] | None = None) -> None:
        self.statements: list[Any] = []
        self._results = list(results or [])

    async def execute(self, statement: Any) -> _Rows:
        self.statements.append(statement)
        if self._results:
            return _Rows([self._results.pop(0)])
        return _Rows([])

    async def scalar(self, statement: Any):
        self.statements.append(statement)
        return self._results.pop(0) if self._results else 0

    def sql(self, index: int = -1) -> str:
        return str(self.statements[index])


# ---------------------------------------------------------------------------
# 1. Library reads are release-scoped and keyed by the public sample id.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_library_list_is_always_release_scoped():
    """Ablation: dropping `_library_scope` widens the list to every release."""
    db = _RecordingDb([0])
    await expression_routes.list_libraries(
        db=db,
        release_context=_context(),
        page=1,
        page_size=20,
        tissue=None,
        treatment=None,
        assembly_id=None,
    )

    for statement in db.statements:
        sql = str(statement)
        assert "assemblies.release_id" in sql, sql
        assert "expression_libraries.assembly_id = assemblies.id" in sql, sql


@pytest.mark.asyncio
async def test_library_detail_resolves_by_public_id_within_the_release():
    """The persistence key is not a locator, and the release is enforced."""
    db = _RecordingDb([0])

    class _Lib:
        id = 99  # surrogate — must never be the accepted locator
        sample_id = "SRR_SAMPLE_1"
        library_name = "leaf control"
        tissue = "leaf"
        treatment = "control"
        developmental_stage = None
        study_ref = None
        source = None
        assembly = None
        extra_metadata = None

    import app.api.v1.expression as mod

    original = mod._resolve_library

    async def _stub(db_, public_id, *, release_context):
        assert public_id == "SRR_SAMPLE_1"
        assert release_context.release_id == _RELEASE_ID
        return _Lib()

    mod._resolve_library = _stub
    try:
        payload = await expression_routes.get_library(
            public_id="SRR_SAMPLE_1", db=db, release_context=_context()
        )
    finally:
        mod._resolve_library = original

    assert payload["public_id"] == "SRR_SAMPLE_1"
    assert payload["sample_id"] == "SRR_SAMPLE_1"
    # The surrogate key must not be in the public projection under any name.
    assert "id" not in payload
    assert payload.get("assembly_id") is None


# ---------------------------------------------------------------------------
# 2. Gene expression is bound to the release AND the gene's own assembly.
# ---------------------------------------------------------------------------


class _Gene:
    gene_pk = 4242
    assembly_id = _ASSEMBLY_ID


@pytest.mark.asyncio
async def test_gene_expression_constrains_library_to_the_gene_assembly():
    """Ablation: dropping `ExpressionLibrary.assembly_id == gene.assembly_id`
    lets a v4 library attach observations to a v5 gene."""
    db = _RecordingDb()

    import app.api.v1.expression as mod

    original = mod._resolve_release_gene

    async def _stub(db_, gene_id, *, assembly_id, release_context):
        return _Gene()

    mod._resolve_release_gene = _stub
    try:
        await expression_routes.get_gene_expression(
            gene_id="Glyma.01G000100",
            db=db,
            release_context=_context(),
            assembly_id=None,
            tissue=None,
            treatment=None,
            library=None,
            min_fpkm=None,
            max_fpkm=None,
            cursor=None,
            limit=10,
        )
    finally:
        mod._resolve_release_gene = original

    sql = db.sql()
    where_clause = sql.split("WHERE", 1)[1].split("ORDER BY", 1)[0]
    # The predicate exists and is bound to the resolved gene's assembly value
    # (SQLAlchemy parameterises the Python-side operand, so the assertion is on
    # the predicate plus its bound value rather than on inlined SQL text).
    assert "expression_libraries.assembly_id" in where_clause, sql
    assert "assemblies.release_id" in where_clause, sql
    bound = set(db.statements[0].compile().params.values())
    assert _ASSEMBLY_ID in bound, bound
    assert _RELEASE_ID in bound, bound


@pytest.mark.asyncio
async def test_gene_expression_is_404_when_the_gene_is_not_in_the_release():
    db = _RecordingDb()

    import app.api.v1.expression as mod

    original = mod._resolve_release_gene

    async def _missing(db_, gene_id, *, assembly_id, release_context):
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"Gene {gene_id} not found")

    mod._resolve_release_gene = _missing
    try:
        from app.core.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await expression_routes.get_gene_expression(
                gene_id="DRAFTGENE",
                db=db,
                release_context=_context(),
                assembly_id=None,
                tissue=None,
                treatment=None,
                library=None,
                min_fpkm=None,
                max_fpkm=None,
                cursor=None,
                limit=10,
            )
    finally:
        mod._resolve_release_gene = original
    # Fail closed before any expression SQL runs.
    assert db.statements == []


# ---------------------------------------------------------------------------
# 3. The cursor is opaque and release/filter bound.
# ---------------------------------------------------------------------------


def test_expression_cursor_round_trips_and_binds_release_and_filters():
    from app.services.release_context import decode_bound_cursor, encode_bound_cursor

    filters = expression_routes._expression_cursor_filters(
        gene_id="Glyma.01G000100", limit=100
    )
    cursor = encode_bound_cursor(
        kind="expression",
        sort_key={"d": "500"},
        release_context=_context(),
        filters=filters,
    )

    # Opaque: the row id is not readable in the token.
    assert "500" not in cursor

    payload = decode_bound_cursor(
        cursor, kind="expression", release_context=_context(), filters=filters
    )
    assert payload["d"] == "500"


def test_expression_cursor_is_rejected_under_another_release():
    from app.services.release_context import decode_bound_cursor, encode_bound_cursor

    filters = expression_routes._expression_cursor_filters(gene_id="G1", limit=100)
    cursor = encode_bound_cursor(
        kind="expression",
        sort_key={"d": "1"},
        release_context=_context(release_id=7),
        filters=filters,
    )

    with pytest.raises(ValidationError):
        decode_bound_cursor(
            cursor,
            kind="expression",
            release_context=_context(release_id=8),
            filters=filters,
        )


def test_expression_cursor_is_rejected_under_another_filter_set():
    from app.services.release_context import decode_bound_cursor, encode_bound_cursor

    cursor = encode_bound_cursor(
        kind="expression",
        sort_key={"d": "1"},
        release_context=_context(),
        filters=expression_routes._expression_cursor_filters(gene_id="G1", limit=100),
    )

    with pytest.raises(ValidationError):
        decode_bound_cursor(
            cursor,
            kind="expression",
            release_context=_context(),
            filters=expression_routes._expression_cursor_filters(gene_id="G2", limit=100),
        )


def test_expression_cursor_rejects_a_non_numeric_sort_key():
    from app.services.release_context import encode_bound_cursor

    filters = expression_routes._expression_cursor_filters(gene_id="G1", limit=100)
    cursor = encode_bound_cursor(
        kind="expression",
        sort_key={"d": "not-a-row-id"},
        release_context=_context(),
        filters=filters,
    )

    with pytest.raises(ValidationError):
        expression_routes._decode_expression_cursor(
            cursor, release_context=_context(), filters=filters
        )


# ---------------------------------------------------------------------------
# 4. Library projections never carry persistence keys.
# ---------------------------------------------------------------------------


def test_library_payload_omits_surrogate_keys():
    class _Assembly:
        name = "Wm82.a4.v1"

    class _Lib:
        id = 12345
        sample_id = "SAMPLE_A"
        library_name = "leaf"
        tissue = "leaf"
        treatment = "control"
        developmental_stage = "V3"
        study_ref = "PMID:1"
        source = "GEO"
        assembly = _Assembly()
        extra_metadata = {"batch": "1"}

    payload = expression_routes._library_payload(_Lib(), expression_data_count=4)

    assert payload["public_id"] == "SAMPLE_A"
    assert payload["assembly_name"] == "Wm82.a4.v1"
    assert payload["expression_data_count"] == 4
    for forbidden in ("id", "assembly_id", "library_id"):
        assert forbidden not in payload
    # The surrogate value must not appear anywhere in the serialized payload.
    assert "12345" not in str(payload)
