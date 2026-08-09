"""GeneService unit tests — no docker / no testcontainers.

Covers the service layer extracted from the genes routes with a fake
AsyncSession (same pattern as ``test_news_api.py``):
- cursor encode/decode (pure functions)
- ``list_genes``: filter WHERE clauses, keyset pagination, has_more
- ``get_gene``: transcript/alias mapping, NotFoundError
- ``list_assemblies`` / ``list_chromosomes``: row -> response mapping
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.models.genomic import Assembly, Chromosome, Exon, Gene, GeneAlias, Transcript
from app.schemas.genomic import GeneListParams
from app.services.gene_service import GeneService, decode_cursor, encode_cursor

# ---------------------------------------------------------------------------
# Fake database session (unit-level, no docker)
# ---------------------------------------------------------------------------


class _Scalars:
    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDbSession:
    """AsyncSession stand-in: returns fake rows for any genomic query."""

    def __init__(
        self,
        genes: list[Gene] | None = None,
        assemblies: list[Assembly] | None = None,
        chromosomes: list[Chromosome] | None = None,
    ):
        self.genes = list(genes or [])
        self.assemblies = list(assemblies or [])
        self.chromosomes = list(chromosomes or [])
        self.last_stmt = None
        self.statements: list[Any] = []

    async def execute(self, stmt, params=None):
        self.last_stmt = stmt
        self.statements.append(stmt)
        text = str(stmt)
        if "FROM genes" in text:
            return _Result(list(self.genes))
        if "FROM assemblies" in text:
            return _Result(list(self.assemblies))
        if "FROM chromosomes" in text:
            return _Result(list(self.chromosomes))
        return _Result([])


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def make_gene(
    gene_id: str = "Glyma.01G000100",
    *,
    chromosome_id: int = 1,
    name: str = "Disease Resistance",
    biotype: str = "protein_coding",
    start: int = 1000,
    end: int = 5000,
    strand: str = "+",
    transcripts: list[Transcript] | None = None,
    aliases: list[GeneAlias] | None = None,
) -> Gene:
    return Gene(
        id=gene_id,
        assembly_id=1,
        chromosome_id=chromosome_id,
        name=name,
        biotype=biotype,
        start=start,
        end=end,
        strand=strand,
        description=None,
        created_at=_now(),
        updated_at=_now(),
        transcripts=transcripts or [],
        aliases=aliases or [],
    )


def make_transcript(
    tx_id: str = "Glyma.01G000100.1",
    *,
    gene_id: str = "Glyma.01G000100",
    is_canonical: bool = True,
) -> Transcript:
    return Transcript(
        id=tx_id,
        gene_id=gene_id,
        name=None,
        biotype="mRNA",
        start=1000,
        end=5000,
        strand="+",
        is_canonical=is_canonical,
        exons=[Exon(id=1, transcript_id=tx_id, start=1000, end=2000, order=1)],
    )


def make_assembly(asm_id: int = 1, *, name: str = "Wm82.gnm2") -> Assembly:
    return Assembly(
        id=asm_id,
        name=name,
        species="Glycine max",
        version="2",
        description=None,
        is_default=True,
        created_at=_now(),
        updated_at=_now(),
    )


def make_chromosome(
    chr_id: int = 1, *, assembly_id: int = 1, name: str = "Gm01"
) -> Chromosome:
    return Chromosome(id=chr_id, assembly_id=assembly_id, name=name, length=50_000_000, order=0)


# ---------------------------------------------------------------------------
# Cursor helpers (pure functions)
# ---------------------------------------------------------------------------


class TestCursor:
    def test_roundtrip(self):
        assert decode_cursor(encode_cursor("Glyma.01G000100")) == "Glyma.01G000100"

    def test_roundtrip_unicode_gene_id(self):
        assert decode_cursor(encode_cursor("Glyma.20G000100")) == "Glyma.20G000100"

    def test_invalid_cursor_raises_validation_error(self):
        with pytest.raises(ValidationError):
            decode_cursor("!!!not-base64!!!")


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------


class TestListGenes:
    async def test_empty_returns_empty_response(self):
        session = FakeDbSession(genes=[])
        response = await GeneService().list_genes(session, GeneListParams(limit=50))
        assert response.items == []
        assert response.next_cursor is None
        assert response.has_more is False

    async def test_filters_are_encoded_in_sql(self):
        session = FakeDbSession(genes=[make_gene()])
        params = GeneListParams(
            assembly_id="1",
            chromosome="Gm01",
            biotype="protein_coding",
            search="Glyma",
            cursor=encode_cursor("Glyma.01G000050"),
            limit=10,
        )
        await GeneService().list_genes(session, params)
        sql = str(session.last_stmt)
        assert "genes.assembly_id" in sql
        assert "chromosomes.name" in sql
        assert "genes.biotype" in sql
        assert "lower(genes.id) LIKE" in sql
        assert "genes.id >" in sql
        assert "ORDER BY genes.id" in sql
        assert "LIMIT" in sql

    async def test_chromosome_filter_joins_chromosomes(self):
        session = FakeDbSession(genes=[make_gene()])
        await GeneService().list_genes(
            session, GeneListParams(chromosome="Gm01", limit=50)
        )
        sql = str(session.last_stmt)
        assert "JOIN chromosomes" in sql
        assert "chromosomes.name" in sql

    async def test_chromosome_plus_assembly_scopes_join_to_assembly(self):
        session = FakeDbSession(genes=[make_gene()])
        await GeneService().list_genes(
            session, GeneListParams(assembly_id="1", chromosome="Gm01", limit=50)
        )
        sql = str(session.last_stmt)
        assert "chromosomes.assembly_id" in sql

    async def test_has_more_when_rows_exceed_limit(self):
        genes = [
            make_gene(f"Glyma.01G00010{i}", chromosome_id=1)
            for i in range(3)
        ]
        session = FakeDbSession(genes=genes)
        response = await GeneService().list_genes(session, GeneListParams(limit=2))
        assert response.has_more is True
        assert len(response.items) == 2
        assert response.next_cursor == encode_cursor(genes[1].id)

    async def test_no_next_cursor_when_exact_fit(self):
        genes = [make_gene(f"Glyma.01G00010{i}") for i in range(2)]
        session = FakeDbSession(genes=genes)
        response = await GeneService().list_genes(session, GeneListParams(limit=2))
        assert response.has_more is False
        assert response.next_cursor is None
        assert len(response.items) == 2

    async def test_response_items_are_mapped(self):
        session = FakeDbSession(genes=[make_gene()])
        response = await GeneService().list_genes(session, GeneListParams(limit=50))
        item = response.items[0]
        assert item.gene_id == "Glyma.01G000100"
        assert item.chromosome == "1"  # chromosome_id string, unchanged contract


class TestGetGene:
    async def test_found_returns_detail_with_transcripts_and_aliases(self):
        gene = make_gene(
            transcripts=[make_transcript()],
            aliases=[GeneAlias(gene_id="Glyma.01G000100", alias="DR1")],
        )
        session = FakeDbSession(genes=[gene])
        detail = await GeneService().get_gene(session, "Glyma.01G000100")
        assert detail.gene_id == "Glyma.01G000100"
        assert detail.name == "Disease Resistance"
        assert len(detail.transcripts) == 1
        assert detail.transcripts[0].id == "Glyma.01G000100.1"
        assert detail.transcripts[0].is_canonical is True
        assert len(detail.transcripts[0].exons) == 1
        assert detail.transcripts[0].exons[0].start == 1000
        assert detail.aliases == ["DR1"]
        assert detail.variant_count == 0

    async def test_missing_raises_not_found(self):
        session = FakeDbSession(genes=[])
        with pytest.raises(NotFoundError):
            await GeneService().get_gene(session, "NONEXISTENT")


class TestListAssemblies:
    async def test_maps_rows_to_responses(self):
        session = FakeDbSession(assemblies=[make_assembly(1), make_assembly(2, name="Wm82.gnm4")])
        responses = await GeneService().list_assemblies(session)
        assert [r.name for r in responses] == ["Wm82.gnm2", "Wm82.gnm4"]
        assert responses[0].species == "Glycine max"
        assert responses[0].is_default is True

    async def test_orders_by_name(self):
        session = FakeDbSession(assemblies=[make_assembly()])
        await GeneService().list_assemblies(session)
        assert "ORDER BY assemblies.name" in str(session.last_stmt)


class TestListChromosomes:
    async def test_maps_rows_to_responses(self):
        session = FakeDbSession(chromosomes=[make_chromosome(1), make_chromosome(2, name="Gm02")])
        responses = await GeneService().list_chromosomes(session, assembly_id=1)
        assert [r.name for r in responses] == ["Gm01", "Gm02"]
        assert responses[0].assembly_id == "1"
        assert responses[0].length == 50_000_000

    async def test_filters_by_assembly_and_orders(self):
        session = FakeDbSession(chromosomes=[make_chromosome()])
        await GeneService().list_chromosomes(session, assembly_id=1)
        sql = str(session.last_stmt)
        assert "chromosomes.assembly_id" in sql
        assert 'ORDER BY chromosomes."order"' in sql
