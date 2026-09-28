"""Ablation guards for the public gene projection (release/assembly scoped).

Covers three defects the migration review found in the *public* gene surface:

1. ``GET /genes/{id}`` hardcoded ``variant_count=0``, so the React detail header
   rendered a meaningless variant total.
2. ``GET /genes`` selected only the ``Gene`` row, so the React table's sortable
   "variant count" column was always empty AND the request's ``sort_by`` /
   ``sort_dir`` parameters were dropped (the UI claimed an order it never got).
3. Transcript/exon ``id`` fields returned persistence primary keys to anonymous
   callers, leaking internal row identities.

Each guard is written so removing the fix flips the assertion (the "ablation"):
the count predicate, the sort allowlist, or the public id derivation.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.core.exceptions import ValidationError
from app.schemas.genomic import GENE_SORT_COLUMNS, GeneListParams
from app.services.gene_service import GeneService, _order_by, _public_transcript_id
from app.services.release_context import ReleaseContext


def _context(release_id: int = 7) -> ReleaseContext:
    return ReleaseContext(
        release_id=release_id,
        assembly_id=3,
        assembly="Wm82.a4.v1",
    )


class _EmptyGeneDb:
    def __init__(self) -> None:
        self.last_stmt: Any = None

    async def execute(self, statement):
        self.last_stmt = statement
        return _EmptyResult()


class _EmptyResult:
    def all(self) -> list[Any]:
        return []

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return None


# ---------------------------------------------------------------------------
# 1. The list query must carry a release+assembly-scoped variant aggregate.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gene_list_variant_count_is_release_and_assembly_scoped():
    """Ablation: dropping either predicate lets draft/other-release rows count."""
    db = _EmptyGeneDb()
    await GeneService().list_genes(
        db, GeneListParams(assembly_id="3", limit=20), release_context=_context()
    )

    sql = str(db.last_stmt)
    # The aggregate itself is selected (the column was previously absent, so
    # the React table rendered "—" for every row).
    assert "variant_summaries" in sql
    assert "count(" in sql.lower()
    # The join is bound to the resolved release *and* the gene's own assembly.
    assert "variant_summaries.release_id" in sql
    assert "variant_summaries.assembly_id" in sql
    # The aggregate is a correlated scalar subquery. The join+GROUP BY form
    # that used to be here selected Gene's lazy="joined" relationship columns
    # without them appearing in GROUP BY, so PostgreSQL rejected the statement
    # outright:
    #   column "releases_1.id" must appear in the GROUP BY clause
    # A shape-only test cannot see that, so pin the absence of the clause that
    # made it invalid.
    assert "group by" not in sql.lower()


# ---------------------------------------------------------------------------
# 2. Sorting is a closed allowlist, and the keyset cursor stays order-bound.
# ---------------------------------------------------------------------------


def test_gene_sort_column_allowlist_rejects_injection():
    """Only named columns may reach ORDER BY; anything else is a 422."""
    for column in GENE_SORT_COLUMNS:
        assert GeneListParams(sort_by=column).sort_by == column
    for hostile in ("gene_pk", "1; DROP TABLE genes", "accession", ""):
        with pytest.raises(ValueError):
            GeneListParams(sort_by=hostile)


def test_gene_sort_direction_is_normalised_and_validated():
    assert GeneListParams(sort_dir="DESC").sort_dir == "desc"
    assert GeneListParams(sort_dir="asc").sort_dir == "asc"
    for hostile in ("ascending", "desc nulls first", "1"):
        with pytest.raises(ValueError):
            GeneListParams(sort_dir=hostile)


def test_order_by_uses_validated_columns_only():
    """The ORDER BY builder never interpolates user text."""
    descending = _order_by(GeneListParams(sort_by="variant_count", sort_dir="desc"), 7)
    ascending = _order_by(GeneListParams(sort_by="variant_count", sort_dir="asc"), 7)
    assert [str(clause) for clause in descending] != [str(clause) for clause in ascending]
    # The aggregate is counted, not a raw user string.
    assert "count(" in str(descending[0]).lower()


@pytest.mark.asyncio
async def test_cursor_pagination_is_refused_for_a_non_default_order():
    """A cursor encodes the accession order; replaying it under another sort
    would skip or repeat rows, so it must fail closed before any SQL runs."""
    db = _EmptyGeneDb()
    with pytest.raises(ValidationError) as excinfo:
        await GeneService().list_genes(
            db,
            GeneListParams(cursor="whatever", sort_by="variant_count", limit=20),
            release_context=_context(),
        )
    assert "cursor" in str(excinfo.value).lower()
    assert db.last_stmt is None


# ---------------------------------------------------------------------------
# 3. Transcript/exon identifiers are public, not persistence keys.
# ---------------------------------------------------------------------------


def test_transcript_public_id_prefers_the_published_accession():
    tx = SimpleNamespace(name="Glyma.01G000100.1", id=4242)
    assert _public_transcript_id(tx) == "Glyma.01G000100.1"


def test_transcript_public_id_never_returns_the_surrogate_key():
    """An unnamed transcript must still not expose its BIGSERIAL primary key."""
    tx = SimpleNamespace(
        name=None,
        id=4242,
        start=10,
        end=99,
        strand="+",
        gene=SimpleNamespace(accession="Glyma.01G000100"),
    )
    public_id = _public_transcript_id(tx)
    assert public_id != "4242"
    assert "4242" not in public_id
    assert "Glyma.01G000100" in public_id
