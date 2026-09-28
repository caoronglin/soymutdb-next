"""Ablation guards for the public homolog API boundary.

``gene_homologs`` carries no release/assembly column, so the review found the
public surface was effectively release-free:

* both endpoints resolved the gene with ``release_context=None``;
* ``GET /homologs/search`` with no ``gene_id`` listed homolog rows from *every*
  release, because no join to the gene's assembly existed at all;
* the keyset cursor was a raw ``GeneHomolog.id`` and the public payload carried
  that persistence key as ``id``.

Unit-level guards (no PostgreSQL): the route coroutines are driven with a fake
session that records the compiled SQL.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.api.v1 import homolog as homolog_routes
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

    def scalar(self):
        return self._rows[0] if self._rows else 0


class _RecordingDb:
    def __init__(self, results: list[Any] | None = None) -> None:
        self.statements: list[Any] = []
        self._results = list(results or [])

    async def execute(self, statement: Any) -> _Rows:
        self.statements.append(statement)
        return _Rows([])

    async def scalar(self, statement: Any):
        self.statements.append(statement)
        return self._results.pop(0) if self._results else 0


def _where(statement: Any) -> str:
    return str(statement).split("WHERE", 1)[-1].split("ORDER BY", 1)[0]


class _Gene:
    gene_pk = 4242
    assembly_id = _ASSEMBLY_ID


@pytest.fixture()
def stub_gene(monkeypatch):
    async def _resolve(db, accession, *, release_context, assembly_id=None):
        assert release_context.release_id == _RELEASE_ID
        return _Gene()

    monkeypatch.setattr(homolog_routes._gene_service, "resolve_released_gene", _resolve)
    return _resolve


# ---------------------------------------------------------------------------
# 1. Every homolog read is bound to the published release.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gene_homologs_join_the_gene_assembly_and_release(stub_gene):
    """Ablation: without the gene→assembly join a released gene's homologs from
    a draft assembly remain reachable."""
    db = _RecordingDb()

    await homolog_routes.get_gene_homologs(
        gene_id="Glyma.01G000100",
        db=db,
        release_context=_context(),
        assembly_id=None,
        cursor=None,
        limit=10,
    )

    sql = str(db.statements[0])
    # Order-insensitive: SQLAlchemy may emit either operand order for the join.
    assert "JOIN genes ON" in sql and "gene_homologs.gene_id = genes.gene_pk" in sql, sql
    assert "JOIN assemblies ON" in sql and "genes.assembly_id = assemblies.id" in sql, sql
    assert "assemblies.release_id" in _where(db.statements[0]), sql


@pytest.mark.asyncio
async def test_homolog_search_without_a_gene_is_still_release_scoped():
    """The defect: an unfiltered search listed homologs from every release."""
    db = _RecordingDb([0])

    await homolog_routes.search_homologs(
        db=db,
        release_context=_context(),
        gene_id=None,
        assembly_id=None,
        homolog_species=None,
        homolog_type=None,
        page=1,
        page_size=20,
        cursor=None,
    )

    assert db.statements, "expected at least a count query"
    for statement in db.statements:
        sql = str(statement)
        assert "assemblies.release_id" in _where(statement), sql
        # The join is required for the predicate to be meaningful.
        assert "JOIN assemblies ON" in sql, sql
        assert "genes.assembly_id = assemblies.id" in sql, sql


@pytest.mark.asyncio
async def test_homolog_search_resolves_the_gene_inside_the_release(stub_gene):
    db = _RecordingDb([0])

    await homolog_routes.search_homologs(
        db=db,
        release_context=_context(),
        gene_id="Glyma.01G000100",
        assembly_id=None,
        homolog_species=None,
        homolog_type=None,
        page=1,
        page_size=20,
        cursor=None,
    )

    where = _where(db.statements[0])
    assert "gene_homologs.gene_id" in where, where
    assert "assemblies.release_id" in where, where


# ---------------------------------------------------------------------------
# 2. Cursor is opaque and bound to release + filters.
# ---------------------------------------------------------------------------


def test_homolog_cursor_round_trips_and_hides_the_row_id():
    from app.services.release_context import decode_bound_cursor, encode_bound_cursor

    filters = homolog_routes._cursor_filters(gene_id="G1", limit=100)
    cursor = encode_bound_cursor(
        kind="homolog",
        sort_key={"d": "918273"},
        release_context=_context(),
        filters=filters,
    )

    assert "918273" not in cursor
    payload = decode_bound_cursor(
        cursor, kind="homolog", release_context=_context(), filters=filters
    )
    assert payload["d"] == "918273"


def test_homolog_cursor_rejects_another_release_and_filter_set():
    from app.services.release_context import decode_bound_cursor, encode_bound_cursor

    filters = homolog_routes._cursor_filters(gene_id="G1", limit=100)
    cursor = encode_bound_cursor(
        kind="homolog",
        sort_key={"d": "1"},
        release_context=_context(release_id=7),
        filters=filters,
    )

    with pytest.raises(ValidationError):
        decode_bound_cursor(
            cursor,
            kind="homolog",
            release_context=_context(release_id=8),
            filters=filters,
        )

    with pytest.raises(ValidationError):
        decode_bound_cursor(
            cursor,
            kind="homolog",
            release_context=_context(release_id=7),
            filters=homolog_routes._cursor_filters(gene_id="G2", limit=100),
        )


def test_homolog_cursor_kind_is_not_interchangeable_with_expression():
    from app.services.release_context import decode_bound_cursor, encode_bound_cursor

    filters = homolog_routes._cursor_filters(gene_id="G1", limit=100)
    cursor = encode_bound_cursor(
        kind="expression",
        sort_key={"d": "1"},
        release_context=_context(),
        filters=filters,
    )

    with pytest.raises(ValidationError):
        decode_bound_cursor(
            cursor, kind="homolog", release_context=_context(), filters=filters
        )


def test_homolog_cursor_rejects_a_non_numeric_sort_key():
    from app.services.release_context import encode_bound_cursor

    filters = homolog_routes._cursor_filters(gene_id="G1", limit=100)
    cursor = encode_bound_cursor(
        kind="homolog",
        sort_key={"d": "not-a-row-id"},
        release_context=_context(),
        filters=filters,
    )

    with pytest.raises(ValidationError):
        homolog_routes._decode_cursor(
            cursor, release_context=_context(), filters=filters
        )


# ---------------------------------------------------------------------------
# 3. Public payload carries the natural identity, not the persistence key.
# ---------------------------------------------------------------------------


def test_public_homolog_item_omits_the_persistence_key():
    class _GeneRef:
        accession = "Glyma.01G000100"

    class _Homolog:
        id = 918273
        gene = _GeneRef()
        gene_id = 4242
        homolog_species = "Arabidopsis thaliana"
        homolog_gene_id = "AT1G01010"
        homolog_type = "ortholog"
        source = "EnsemblPlants"

    item = homolog_routes._public_item(_Homolog())

    assert item["gene_id"] == "Glyma.01G000100"
    assert item["homolog_gene_id"] == "AT1G01010"
    for forbidden in ("id", "gene_pk", "gene_id_pk"):
        assert forbidden not in item
    assert "918273" not in str(item)
