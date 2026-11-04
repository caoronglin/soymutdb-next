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
from app.services.release_context import ReleaseContext

RELEASE_CONTEXT = ReleaseContext(
    release_id=7,
    assembly_id=1,
    assembly="Wm82.gnm2",
)
DEFAULT_GENE_PARAMS = GeneListParams()

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
    """Stand-in for SQLAlchemy's ``Result``.

    ``list_genes`` projects two columns (``select(Gene, variant_count)``) and
    reads whole rows through ``.all()``; ``get_gene`` projects one column and
    reads entities through ``.scalars()``.  Both shapes have to exist here, or
    the double silently forces a one-column assumption onto the service.
    """

    def __init__(self, rows: list):
        self._rows = rows

    def all(self) -> list:
        return self._rows

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
        *,
        variant_count: int = 0,
    ):
        self.genes = list(genes or [])
        self.assemblies = list(assemblies or [])
        self.chromosomes = list(chromosomes or [])
        self.variant_count = variant_count
        self.last_stmt = None
        self.statements: list[Any] = []

    async def execute(self, stmt, params=None):
        self.last_stmt = stmt
        self.statements.append(stmt)
        text = str(stmt)
        if "FROM genes" in text:
            return _Result(self._gene_rows(stmt))
        if "FROM assemblies" in text:
            return _Result(list(self.assemblies))
        if "FROM chromosomes" in text:
            return _Result(list(self.chromosomes))
        return _Result([])

    def _gene_rows(self, stmt) -> list:
        """Rows in the shape the statement's projection actually produces.

        ``column_descriptions`` carries one entry per selected entity, so it
        reports the row-tuple arity. ``selected_columns`` does not: it is the
        flattened column list (13 for a bare ``select(Gene)``), which would
        make every projection look multi-column.
        """
        descriptions = getattr(stmt, "column_descriptions", None)
        if descriptions is not None and len(descriptions) > 1:
            return [(gene, 0) for gene in self.genes]
        return list(self.genes)

    async def scalar(self, stmt):
        """A COUNT over genes for list paging, over variants for the detail stat.

        The two queries count different things; returning the gene count for
        both made a gene with no linked variants report a nonzero total.
        """
        if "variant_summaries" in str(stmt):
            return self.variant_count
        return len(self.genes)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def make_gene(
    accession: str = "Glyma.01G000100",
    *,
    gene_pk: int = 1,
    chromosome_id: int = 1,
    name: str = "Disease Resistance",
    biotype: str = "protein_coding",
    start: int = 1000,
    end: int = 5000,
    strand: str = "+",
    transcripts: list[Transcript] | None = None,
    aliases: list[GeneAlias] | None = None,
) -> Gene:
    gene = Gene(
        gene_pk=gene_pk,
        accession=accession,
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
    gene.chromosome = make_chromosome(chr_id=chromosome_id)
    gene.assembly = make_assembly(asm_id=1)
    return gene


def make_transcript(
    pk: int = 101,
    *,
    name: str | None = "Glyma.01G000100.1",
    gene_pk: int = 1,
    is_canonical: bool = True,
) -> Transcript:
    """A transcript whose public identity is its annotation name.

    ``id`` is the internal surrogate key and must never surface to anonymous
    callers; the published ``name`` is the public identity. Keeping the two
    distinct here is what makes the privacy assertion in
    ``test_found_returns_detail_with_transcripts_and_aliases`` meaningful.
    """
    return Transcript(
        id=pk,
        gene_id=gene_pk,
        name=name,
        biotype="mRNA",
        start=1000,
        end=5000,
        strand="+",
        is_canonical=is_canonical,
        exons=[Exon(id=1, transcript_id=pk, start=1000, end=2000, order=1)],
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
        cursor = encode_cursor(
            "Glyma.01G000100",
            1,
            release_context=RELEASE_CONTEXT,
            params=DEFAULT_GENE_PARAMS,
        )
        assert decode_cursor(
            cursor,
            release_context=RELEASE_CONTEXT,
            params=DEFAULT_GENE_PARAMS,
        ) == ("Glyma.01G000100", 1)

    def test_roundtrip_unicode_gene_id(self):
        cursor = encode_cursor(
            "Glyma.20G000100",
            2,
            release_context=RELEASE_CONTEXT,
            params=DEFAULT_GENE_PARAMS,
        )
        assert decode_cursor(
            cursor,
            release_context=RELEASE_CONTEXT,
            params=DEFAULT_GENE_PARAMS,
        ) == ("Glyma.20G000100", 2)

    def test_invalid_cursor_raises_validation_error(self):
        with pytest.raises(ValidationError):
            decode_cursor(
                "!!!not-base64!!!",
                release_context=RELEASE_CONTEXT,
                params=DEFAULT_GENE_PARAMS,
            )


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------


class TestListGenes:
    async def test_empty_returns_empty_response(self):
        session = FakeDbSession(genes=[])
        response = await GeneService().list_genes(
            session,
            GeneListParams(limit=50),
            release_context=RELEASE_CONTEXT,
        )
        assert response.items == []
        assert response.next_cursor is None
        assert response.has_more is False

    async def test_filters_are_encoded_in_sql(self):
        session = FakeDbSession(genes=[make_gene()])
        params_without_cursor = GeneListParams(
            assembly_id="1",
            chromosome="Gm01",
            biotype="protein_coding",
            search="Glyma",
            limit=10,
        )
        params = params_without_cursor.model_copy(
            update={
                "cursor": encode_cursor(
                    "Glyma.01G000050",
                    50,
                    release_context=RELEASE_CONTEXT,
                    params=params_without_cursor,
                )
            }
        )
        await GeneService().list_genes(
            session,
            params,
            release_context=RELEASE_CONTEXT,
        )
        sql = str(session.last_stmt)
        assert "assemblies.release_id" in sql
        assert "genes.assembly_id" in sql
        assert "chromosomes.name" in sql
        assert "genes.biotype" in sql
        assert "lower(genes.accession) LIKE" in sql
        assert "genes.accession >" in sql
        assert "ORDER BY genes.accession" in sql
        assert "LIMIT" in sql

    async def test_chromosome_filter_joins_chromosomes(self):
        session = FakeDbSession(genes=[make_gene()])
        await GeneService().list_genes(
            session,
            GeneListParams(chromosome="Gm01", limit=50),
            release_context=RELEASE_CONTEXT,
        )
        sql = str(session.last_stmt)
        assert "JOIN chromosomes" in sql
        assert "chromosomes.name" in sql

    async def test_chromosome_plus_assembly_scopes_join_to_assembly(self):
        session = FakeDbSession(genes=[make_gene()])
        await GeneService().list_genes(
            session,
            GeneListParams(assembly_id="1", chromosome="Gm01", limit=50),
            release_context=RELEASE_CONTEXT,
        )
        sql = str(session.last_stmt)
        assert "chromosomes.assembly_id" in sql

    async def test_has_more_when_rows_exceed_limit(self):
        genes = [
            make_gene(f"Glyma.01G00010{i}", gene_pk=i + 1, chromosome_id=1)
            for i in range(3)
        ]
        session = FakeDbSession(genes=genes)
        response = await GeneService().list_genes(
            session,
            GeneListParams(limit=2),
            release_context=RELEASE_CONTEXT,
        )
        assert response.has_more is True
        assert len(response.items) == 2
        assert response.next_cursor == encode_cursor(
            genes[1].accession,
            genes[1].gene_pk,
            release_context=RELEASE_CONTEXT,
            params=GeneListParams(limit=2),
        )

    async def test_no_next_cursor_when_exact_fit(self):
        genes = [make_gene(f"Glyma.01G00010{i}") for i in range(2)]
        session = FakeDbSession(genes=genes)
        response = await GeneService().list_genes(
            session,
            GeneListParams(limit=2),
            release_context=RELEASE_CONTEXT,
        )
        assert response.has_more is False
        assert response.next_cursor is None
        assert len(response.items) == 2

    async def test_response_items_are_mapped(self):
        gene = make_gene()
        gene.chromosome = make_chromosome(name="Gm01")
        session = FakeDbSession(genes=[gene])
        response = await GeneService().list_genes(
            session,
            GeneListParams(limit=50),
            release_context=RELEASE_CONTEXT,
        )
        item = response.items[0]
        assert item.gene_id == "Glyma.01G000100"
        assert item.chromosome == "Gm01"
        assert item.start_pos == 1000
        assert item.end_pos == 5000
        assert item.symbol == "Disease Resistance"


class TestGetGene:
    async def test_found_returns_detail_with_transcripts_and_aliases(self):
        gene = make_gene(
            transcripts=[make_transcript()],
            aliases=[GeneAlias(gene_id=1, alias="DR1")],
        )
        gene.chromosome = make_chromosome(name="Gm01")
        session = FakeDbSession(genes=[gene])
        detail = await GeneService().get_gene(
            session,
            "Glyma.01G000100",
            release_context=RELEASE_CONTEXT,
        )
        assert detail.gene_id == "Glyma.01G000100"
        assert detail.name == "Disease Resistance"
        assert len(detail.transcripts) == 1
        assert detail.transcripts[0].id == "Glyma.01G000100.1"
        assert detail.transcripts[0].is_canonical is True
        assert len(detail.transcripts[0].exons) == 1
        assert detail.transcripts[0].exons[0].start == 1000
        assert detail.aliases == ["DR1"]
        assert detail.variant_count == 0
        assert detail.chromosome == "Gm01"
        assert detail.start_pos == 1000
        assert detail.end_pos == 5000

    async def test_transcript_id_never_exposes_the_surrogate_key(self):
        """An unnamed transcript must not fall back to its BIGSERIAL key.

        The fallback is derived from public annotation fields, not the
        internal persistence key. This does not make it an opaque identifier.
        """
        gene = make_gene(transcripts=[make_transcript(pk=4242, name=None)])
        gene.chromosome = make_chromosome(name="Gm01")
        session = FakeDbSession(genes=[gene])

        detail = await GeneService().get_gene(
            session, "Glyma.01G000100", release_context=RELEASE_CONTEXT
        )

        transcript_id = detail.transcripts[0].id
        assert transcript_id == "transcript-Glyma.01G000100-1000-5000-+"
        assert "4242" not in transcript_id

    async def test_variant_count_is_reported_from_its_own_query(self):
        gene = make_gene()
        gene.chromosome = make_chromosome(name="Gm01")
        session = FakeDbSession(genes=[gene], variant_count=7)

        detail = await GeneService().get_gene(
            session, "Glyma.01G000100", release_context=RELEASE_CONTEXT
        )

        assert detail.variant_count == 7

    async def test_missing_raises_not_found(self):
        session = FakeDbSession(genes=[])
        with pytest.raises(NotFoundError):
            await GeneService().get_gene(
                session,
                "NONEXISTENT",
                release_context=RELEASE_CONTEXT,
            )


class TestListAssemblies:
    async def test_maps_rows_to_responses(self):
        session = FakeDbSession(assemblies=[make_assembly(1), make_assembly(2, name="Wm82.gnm4")])
        responses = await GeneService().list_assemblies(session, release_id=7)
        assert [r.name for r in responses] == ["Wm82.gnm2", "Wm82.gnm4"]
        assert responses[0].species == "Glycine max"
        assert responses[0].is_default is True

    async def test_orders_by_name(self):
        session = FakeDbSession(assemblies=[make_assembly()])
        await GeneService().list_assemblies(session, release_id=7)
        assert "ORDER BY assemblies.name" in str(session.last_stmt)
        assert "assemblies.release_id" in str(session.last_stmt)


class TestListChromosomes:
    async def test_maps_rows_to_responses(self):
        session = FakeDbSession(
            assemblies=[make_assembly(1)],
            chromosomes=[make_chromosome(1), make_chromosome(2, name="Gm02")],
        )
        responses = await GeneService().list_chromosomes(
            session, assembly_id=1, release_id=7
        )
        assert [r.name for r in responses] == ["Gm01", "Gm02"]
        assert responses[0].assembly_id == "1"
        assert responses[0].length == 50_000_000

    async def test_scopes_to_the_assembly_and_orders(self):
        session = FakeDbSession(assemblies=[make_assembly(1)], chromosomes=[make_chromosome()])
        await GeneService().list_chromosomes(
            session, assembly_id=1, release_id=7
        )
        sql = str(session.last_stmt)
        assert "chromosomes.assembly_id" in sql
        assert 'ORDER BY chromosomes."order"' in sql

    async def test_assembly_outside_the_release_is_not_found(self):
        """An empty list would claim "exists, has no chromosomes".

        Guarding the *assembly* (not only the rows) is what keeps an unpublished
        assembly indistinguishable from an id that was never issued: the same
        404, no row data, no fallback to another assembly. The PostgreSQL
        integration test asserts the same contract end to end.
        """
        session = FakeDbSession(assemblies=[], chromosomes=[make_chromosome()])
        with pytest.raises(NotFoundError):
            await GeneService().list_chromosomes(session, assembly_id=1, release_id=7)
