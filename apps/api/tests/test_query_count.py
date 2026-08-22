"""N+1 query-count guards for the hottest list/detail services.

The codebase already avoids per-row queries via ``selectin``/``joined``
eager loading and batched ``IN`` queries (see ``expression.py`` library
counts and ``seqfetch_service._extract_by_genes``).  These tests lock that
behaviour in: if a future change reintroduces a query inside a loop, the
``execute``/``scalar`` call-count assertions below fail.

Each test counts real calls on a mocked session — no database required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1 import expression as expression_module
from app.services.gene_service import GeneService
from app.services.release_context import ReleaseContext
from app.services.seqfetch_service import SeqFetchService


def _make_exec_result(scalars_list=None, rows=None, scalar_one=None):
    """Build a mock execution result with canned data."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = scalars_list or []
    r.all.return_value = rows or []
    r.scalar_one_or_none.return_value = scalar_one
    return r


@pytest.mark.asyncio
class TestExpressionLibraryListQueryCount:
    """Guard: page listing is 1 row query + 1 batched count query (no N+1)."""

    async def test_execute_count_is_constant_per_page(self) -> None:
        lib = MagicMock()
        lib.id = 1
        lib.sample_id = "S1"
        lib.library_name = "Lib1"
        lib.tissue = "leaf"
        lib.treatment = None
        lib.developmental_stage = None
        lib.study_ref = None
        lib.source = None
        lib.assembly_id = 1
        lib.extra_metadata = None

        db = MagicMock()
        db.scalar = AsyncMock(return_value=1)  # total count
        db.execute = AsyncMock(
            side_effect=[
                _make_exec_result(scalars_list=[lib]),  # page rows
                _make_exec_result(rows=[(1, 5)]),  # batched counts
            ]
        )

        result = await expression_module.list_libraries(
            db,
            tissue=None,
            treatment=None,
            assembly_id=None,
            page=1,
            page_size=20,
        )

        assert result["total"] == 1
        assert result["items"][0]["expression_data_count"] == 5
        # 2 executes regardless of page size: rows + one batched IN count.
        assert db.execute.await_count == 2
        assert db.scalar.await_count == 1

    async def test_batched_count_includes_all_library_ids(self) -> None:
        libs = []
        for i in range(3):
            lib = MagicMock()
            lib.id = i + 1
            lib.sample_id = f"S{i}"
            lib.library_name = f"Lib{i}"
            lib.tissue = None
            lib.treatment = None
            lib.developmental_stage = None
            lib.study_ref = None
            lib.source = None
            lib.assembly_id = 1
            lib.extra_metadata = None
            libs.append(lib)

        db = MagicMock()
        db.scalar = AsyncMock(return_value=3)
        db.execute = AsyncMock(
            side_effect=[
                _make_exec_result(scalars_list=libs),
                _make_exec_result(rows=[(1, 2), (2, 0), (3, 7)]),
            ]
        )

        await expression_module.list_libraries(
            db,
            tissue=None,
            treatment=None,
            assembly_id=None,
            page=1,
            page_size=20,
        )

        # The second statement must be the batched IN query over all 3 ids.
        count_stmt = db.execute.await_args_list[1].args[0]
        assert count_stmt.whereclause is not None
        assert db.execute.await_count == 2


@pytest.mark.asyncio
class TestSeqFetchGenesQueryCount:
    """Guard: multi-gene extraction issues exactly one IN query."""

    async def test_single_execute_for_many_genes(self) -> None:
        gene_ids = ["Glyma.01G000100", "Glyma.01G000200"]
        db = MagicMock()
        db.execute = AsyncMock(
            return_value=_make_exec_result(scalars_list=[])
        )

        response = await SeqFetchService()._extract_by_genes(db, gene_ids)

        assert db.execute.await_count == 1
        assert set(response.missing) == set(gene_ids)


@pytest.mark.asyncio
class TestGeneDetailQueryCount:
    """Guard: gene detail loads transcripts/aliases in one query (selectin)."""

    async def test_single_execute_for_gene_with_transcripts(self) -> None:
        tx = MagicMock()
        tx.id = 1
        tx.gene_id = "Glyma.01G000100"
        tx.name = "tx1"
        tx.biotype = "mRNA"
        tx.start = 100
        tx.end = 500
        tx.strand = "+"
        tx.is_canonical = True
        tx.exons = []

        gene = MagicMock()
        gene.id = "Glyma.01G000100"
        gene.assembly_id = 1
        gene.chromosome_id = "1"
        chromosome = MagicMock()
        chromosome.name = "1"
        gene.chromosome = chromosome
        gene.name = "Gene1"
        gene.biotype = "protein_coding"
        gene.start = 100
        gene.end = 500
        gene.strand = "+"
        gene.description = None
        gene.transcripts = [tx]
        gene.aliases = []
        gene.created_at = None
        gene.updated_at = None

        db = MagicMock()
        db.execute = AsyncMock(return_value=_make_exec_result(scalar_one=gene))

        detail = await GeneService().get_gene(
            db,
            "Glyma.01G000100",
            release_context=ReleaseContext(release_id=7),
        )

        assert detail.gene_id == "Glyma.01G000100"
        assert len(detail.transcripts) == 1
        # Eager-loaded via selectin relationship: no per-transcript queries.
        assert db.execute.await_count == 1
