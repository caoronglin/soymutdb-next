"""SeqFetch sequence-extraction tests (mock-only: no docker / no S3).

Covers: gene→interval mapping, FASTA interval slicing (FAI byte-offset
arithmetic), batch missing-ID reporting, size truncation→download URL, and
region-format validation.  Uses the same FakeDbSession pattern as
``test_blast_validation.py``; S3/HTTP reads are replaced by a faithful
in-memory FASTA stand-in so the FAI offset math is exercised end-to-end.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ValidationError as AppValidationError
from app.models.genomic import Assembly, Chromosome, Gene
from app.schemas.seqfetch import SeqFetchRequest, SeqFetchResponse
from app.services import seqfetch_service
from app.services.seqfetch_service import (
    SeqFetchService,
    fai_byte_range,
    parse_fai,
    slice_fasta,
)

# ---------------------------------------------------------------------------
# Fixtures: in-memory FASTA + FAI
# ---------------------------------------------------------------------------

LINEBASES = 60
CHR_LENGTH = 100_000
CHR2_LENGTH = 50_000


def _build_sequence(length: int = CHR_LENGTH) -> str:
    """Deterministic ACGT pattern so slice positions are verifiable."""
    bases = "ACGT"
    return "".join(bases[i % 4] for i in range(length))


SEQUENCE = _build_sequence()
SEQUENCE2 = _build_sequence(CHR2_LENGTH)
# FASTA with 60 bases per line, "\n" line endings -> linewidth == 61.
# Byte layout mirrors a real file: ">chr1\n" header (6 bytes) precedes the
# first base, which the .fai records via the per-chromosome offset.
_CHR1_LINES = "\n".join(
    SEQUENCE[i : i + LINEBASES] for i in range(0, CHR_LENGTH, LINEBASES)
)
_CHR2_LINES = "\n".join(
    SEQUENCE2[i : i + LINEBASES] for i in range(0, CHR2_LENGTH, LINEBASES)
)
FASTA_BYTES = (
    b">chr1\n" + _CHR1_LINES.encode("ascii") + b"\n"
    b">chr2\n" + _CHR2_LINES.encode("ascii") + b"\n"
)
_CHR1_OFFSET = len(b">chr1\n")
_CHR2_OFFSET = _CHR1_OFFSET + len(_CHR1_LINES.encode("ascii")) + 1
FAI_TEXT = (
    f"chr1\t{CHR_LENGTH}\t{_CHR1_OFFSET}\t{LINEBASES}\t{LINEBASES + 1}\n"
    f"chr1A\t10000\t{_CHR1_OFFSET}\t{LINEBASES}\t{LINEBASES + 1}\n"
    f"chr2\t{CHR2_LENGTH}\t{_CHR2_OFFSET}\t{LINEBASES}\t{LINEBASES + 1}\n"
)


def _fake_read_bytes(path: str, byte_range: tuple[int, int] | None = None) -> bytes:
    """Stand-in for :func:`seqfetch_service.read_bytes`.

    Honours the requested byte range against the in-memory FASTA, which
    validates the FAI offset arithmetic exactly like a real ranged GET.
    """
    if path.endswith(".fai"):
        return FAI_TEXT.encode("ascii")
    if byte_range is None:
        return FASTA_BYTES
    b_start, b_end = byte_range
    return FASTA_BYTES[b_start : b_end + 1]


def _make_gene(
    gene_id: str,
    chromosome: Chromosome,
    assembly: Assembly,
    start: int,
    end: int,
    strand: str = "+",
) -> Gene:
    gene = Gene(
        id=gene_id,
        assembly_id=assembly.id,
        chromosome_id=chromosome.id,
        start=start,
        end=end,
        strand=strand,
    )
    gene.assembly = assembly
    gene.chromosome = chromosome
    return gene


@pytest.fixture()
def seq_env(monkeypatch):
    """Wire the in-memory FASTA into the service's I/O layer."""
    monkeypatch.setattr(seqfetch_service, "read_bytes", _fake_read_bytes)
    assembly = Assembly(
        id=1,
        name="GmWm82.a2.v1",
        version="a2.v1",
        fasta_url="s3://genomic-data/wm82.fa",
        fai_url="s3://genomic-data/wm82.fa.fai",
    )
    chr1 = Chromosome(id=1, assembly_id=1, name="chr1", length=CHR_LENGTH, order=1)
    chr2 = Chromosome(id=2, assembly_id=1, name="chr2", length=50_000, order=2)
    yield SimpleNamespace(
        assembly=assembly, chr1=chr1, chr2=chr2, monkeypatch=monkeypatch
    )


class SimpleNamespace:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


# ---------------------------------------------------------------------------
# Fake DB session
# ---------------------------------------------------------------------------


class _Scalars:
    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return self._items


class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDbSession:
    """AsyncSession stand-in that routes by table name."""

    def __init__(
        self,
        genes: list[Gene] | None = None,
        assemblies: list[Assembly] | None = None,
        chromosomes: list[Chromosome] | None = None,
    ) -> None:
        self.genes = genes or []
        self.assemblies = assemblies or []
        self.chromosomes = chromosomes or []

    async def execute(self, stmt, params=None):  # noqa: ANN001
        table = str(stmt)
        name_value = None
        try:
            bound = stmt.compile().params
        except Exception:  # noqa: BLE001 – best-effort bound-param extraction
            bound = {}
        if params:
            bound.update(params)
        for key, value in bound.items():
            if key.startswith("name"):
                name_value = value
        if "FROM genes" in table:
            return _Result(self.genes)
        if "FROM assemblies" in table:
            return _Result(self._filter_by_name(self.assemblies, name_value))
        if "FROM chromosomes" in table:
            return _Result(self._filter_by_name(self.chromosomes, name_value))
        return _Result([])

    @staticmethod
    def _filter_by_name(rows: list, name_value: Any):
        """Apply the ``<table>.name = :name`` predicate when present."""
        if name_value is None:
            return rows
        return [row for row in rows if row.name == name_value]


def _run(coro):
    return asyncio.run(coro)


def _inline(response: SeqFetchResponse) -> str:
    """Return the inline FASTA, asserting the response is not truncated."""
    assert response.sequence is not None, "expected inline sequence"
    return response.sequence


# ---------------------------------------------------------------------------
# FAI parsing / byte-offset arithmetic
# ---------------------------------------------------------------------------


class TestFaiArithmetic:
    def test_parse_fai_records(self) -> None:
        index = parse_fai(FAI_TEXT)
        rec = index["chr1"]
        assert rec.length == CHR_LENGTH
        assert rec.offset == _CHR1_OFFSET
        assert rec.linebases == LINEBASES
        assert rec.linewidth == LINEBASES + 1

    def test_parse_fai_skips_malformed_lines(self) -> None:
        index = parse_fai("chr1\t100\t0\t60\t61\nbogus-line\nchr2\t50\t100\t60\t61\n")
        assert set(index) == {"chr1", "chr2"}

    def test_fai_byte_range_first_line(self) -> None:
        rec = parse_fai(FAI_TEXT)["chr1"]
        # 1-based bases 1..10 sit on the first line: bytes 6..15 (after the
        # 6-byte ">chr1\n" header).
        assert fai_byte_range(rec, 1, 10) == (_CHR1_OFFSET, _CHR1_OFFSET + 9)

    def test_fai_byte_range_across_lines(self) -> None:
        rec = parse_fai(FAI_TEXT)["chr1"]
        # Base 60 is the last base of line 1; base 61 is the first base of
        # line 2, one byte later (the "\n" at the end of line 1).
        assert fai_byte_range(rec, 60, 61) == (
            _CHR1_OFFSET + 59,
            _CHR1_OFFSET + 61,
        )

    def test_slice_fasta_matches_expected_sequence(self) -> None:
        rec = parse_fai(FAI_TEXT)["chr1"]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(seqfetch_service, "read_bytes", _fake_read_bytes)
            result = slice_fasta(rec, "s3://genomic-data/wm82.fa", 1000, 1200)
        assert result == SEQUENCE[999:1200]

    def test_slice_fasta_single_base(self) -> None:
        rec = parse_fai(FAI_TEXT)["chr1"]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(seqfetch_service, "read_bytes", _fake_read_bytes)
            assert slice_fasta(rec, "s3://genomic-data/wm82.fa", 61, 61) == SEQUENCE[60]


# ---------------------------------------------------------------------------
# Gene → interval mapping + batch extraction
# ---------------------------------------------------------------------------


class TestGenesMode:
    def test_extract_by_gene_id(self, seq_env) -> None:
        gene = _make_gene(
            "Glyma.01G000100", seq_env.chr1, seq_env.assembly, start=1000, end=1200
        )
        session = FakeDbSession(genes=[gene])
        request = SeqFetchRequest(genes=["Glyma.01G000100"])

        response: SeqFetchResponse = _run(SeqFetchService().extract(session, request))

        assert response.format == "fasta"
        assert response.count == 1
        assert response.truncated is False
        assert response.missing == []
        assert response.download_url is None
        header, body = _inline(response).split("\n", 1)
        assert header == ">Glyma.01G000100"
        assert body.strip() == SEQUENCE[999:1200]

    def test_batch_missing_ids_reported_not_404(self, seq_env) -> None:
        gene = _make_gene(
            "Glyma.01G000100", seq_env.chr1, seq_env.assembly, start=1, end=50
        )
        session = FakeDbSession(genes=[gene])
        request = SeqFetchRequest(
            genes=["Glyma.01G000100", "Glyma.99G999999", "Glyma.98G888888"]
        )

        response = _run(SeqFetchService().extract(session, request))

        assert response.count == 1
        assert response.missing == ["Glyma.99G999999", "Glyma.98G888888"]
        assert _inline(response).startswith(">Glyma.01G000100")

    def test_batch_preserves_request_order_and_dedupes(self, seq_env) -> None:
        g2 = _make_gene(
            "Glyma.02G000200", seq_env.chr2, seq_env.assembly, start=10, end=20
        )
        g1 = _make_gene(
            "Glyma.01G000100", seq_env.chr1, seq_env.assembly, start=1000, end=1010
        )
        session = FakeDbSession(genes=[g1, g2])
        request = SeqFetchRequest(
            genes=["Glyma.02G000200", "Glyma.01G000100", "Glyma.02G000200"]
        )

        response = _run(SeqFetchService().extract(session, request))

        assert response.count == 2
        headers = [line for line in _inline(response).splitlines() if line.startswith(">")]
        assert headers == [">Glyma.02G000200", ">Glyma.01G000100"]

    def test_all_missing_returns_empty_fasta(self, seq_env) -> None:
        session = FakeDbSession(genes=[])
        request = SeqFetchRequest(genes=["Glyma.99G999999"])
        response = _run(SeqFetchService().extract(session, request))
        assert response.count == 0
        assert _inline(response) == ""
        assert response.missing == ["Glyma.99G999999"]

    def test_genes_without_sequence_files_are_missing(self, seq_env) -> None:
        assembly_no_files = Assembly(
            id=2, name="NoFiles", version="v1", fasta_url=None, fai_url=None
        )
        gene = _make_gene(
            "Glyma.03G000300", seq_env.chr1, assembly_no_files, start=1, end=10
        )
        session = FakeDbSession(genes=[gene])
        request = SeqFetchRequest(genes=["Glyma.03G000300"])
        response = _run(SeqFetchService().extract(session, request))
        assert response.count == 0
        assert response.missing == ["Glyma.03G000300"]


# ---------------------------------------------------------------------------
# Region mode
# ---------------------------------------------------------------------------


class TestRegionMode:
    def test_extract_region(self, seq_env) -> None:
        session = FakeDbSession(
            assemblies=[seq_env.assembly],
            chromosomes=[seq_env.chr1],
        )
        request = SeqFetchRequest(assembly="GmWm82.a2.v1", region="chr1:1000-1200")

        response = _run(SeqFetchService().extract(session, request))

        assert response.count == 1
        assert response.truncated is False
        header, body = _inline(response).split("\n", 1)
        assert header == ">GmWm82.a2.v1:chr1:1000-1200"
        assert body.strip() == SEQUENCE[999:1200]

    @pytest.mark.parametrize(
        "region",
        [
            "chr1:abc-def",
            "chr1:1000",
            "chr1:2000-1000",  # end < start
            "chr1:",
            "1000-2000",
            "chr 1:1000-2000",
            "chr1:1000-2000:extra",
        ],
    )
    def test_invalid_region_rejected(self, seq_env, region: str) -> None:
        session = FakeDbSession(
            assemblies=[seq_env.assembly], chromosomes=[seq_env.chr1]
        )
        request = SeqFetchRequest(assembly="GmWm82.a2.v1", region=region)
        with pytest.raises(AppValidationError, match="region"):
            _run(SeqFetchService().extract(session, request))

    def test_chr1a_style_name_accepted(self, seq_env) -> None:
        chr1a = Chromosome(id=3, assembly_id=1, name="chr1A", length=10_000, order=3)
        session = FakeDbSession(
            assemblies=[seq_env.assembly], chromosomes=[chr1a]
        )
        request = SeqFetchRequest(assembly="GmWm82.a2.v1", region="chr1A:1-10")
        response = _run(SeqFetchService().extract(session, request))
        assert response.count == 1
        assert _inline(response).startswith(">GmWm82.a2.v1:chr1A:1-10")

    def test_unknown_assembly_rejected(self, seq_env) -> None:
        session = FakeDbSession(assemblies=[], chromosomes=[seq_env.chr1])
        request = SeqFetchRequest(assembly="Nope.v9", region="chr1:1-10")
        with pytest.raises(AppValidationError, match="Unknown assembly"):
            _run(SeqFetchService().extract(session, request))

    def test_chromosome_not_in_assembly_rejected(self, seq_env) -> None:
        session = FakeDbSession(
            assemblies=[seq_env.assembly], chromosomes=[seq_env.chr1]
        )
        request = SeqFetchRequest(assembly="GmWm82.a2.v1", region="chr9:1-10")
        with pytest.raises(AppValidationError, match="not found"):
            _run(SeqFetchService().extract(session, request))

    def test_region_out_of_bounds_rejected(self, seq_env) -> None:
        session = FakeDbSession(
            assemblies=[seq_env.assembly], chromosomes=[seq_env.chr1]
        )
        request = SeqFetchRequest(
            assembly="GmWm82.a2.v1", region=f"chr1:1-{CHR_LENGTH + 1}"
        )
        with pytest.raises(AppValidationError, match="out of bounds"):
            _run(SeqFetchService().extract(session, request))

    def test_region_over_size_limit_rejected(self, seq_env) -> None:
        session = FakeDbSession(
            assemblies=[seq_env.assembly], chromosomes=[seq_env.chr1]
        )
        big = seqfetch_service.MAX_REGION_BP + 1
        request = SeqFetchRequest(
            assembly="GmWm82.a2.v1", region=f"chr1:1-{big}"
        )
        with pytest.raises(AppValidationError, match="limit"):
            _run(SeqFetchService().extract(session, request))


# ---------------------------------------------------------------------------
# Size truncation → pre-signed download URL
# ---------------------------------------------------------------------------


class TestSizeTruncation:
    def test_large_result_returns_download_url(self, seq_env, monkeypatch) -> None:
        monkeypatch.setattr(seqfetch_service, "MAX_INLINE_BYTES", 100)
        monkeypatch.setattr(
            seqfetch_service,
            "_upload_result_file",
            lambda fasta_text: f"https://minio.local/seqfetch/{len(fasta_text)}.fa",
        )
        gene = _make_gene(
            "Glyma.01G000100", seq_env.chr1, seq_env.assembly, start=1000, end=2000
        )
        session = FakeDbSession(genes=[gene])
        request = SeqFetchRequest(genes=["Glyma.01G000100"])

        response = _run(SeqFetchService().extract(session, request))

        assert response.truncated is True
        assert response.sequence is None
        assert response.download_url is not None
        assert response.download_url.startswith("https://minio.local/seqfetch/")
        assert response.expires_in == seqfetch_service.SEQFETCH_EXPIRES_IN
        assert response.count == 1

    def test_small_result_stays_inline(self, seq_env) -> None:
        gene = _make_gene(
            "Glyma.01G000100", seq_env.chr1, seq_env.assembly, start=1000, end=1100
        )
        session = FakeDbSession(genes=[gene])
        request = SeqFetchRequest(genes=["Glyma.01G000100"])
        response = _run(SeqFetchService().extract(session, request))
        assert response.truncated is False
        assert response.download_url is None
        assert response.sequence is not None


# ---------------------------------------------------------------------------
# Request schema validation
# ---------------------------------------------------------------------------


class TestRequestSchema:
    def test_genes_and_region_together_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="not both"):
            SeqFetchRequest(genes=["g1"], assembly="a", region="chr1:1-10")

    def test_neither_mode_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="provide either"):
            SeqFetchRequest()

    def test_region_without_assembly_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="together"):
            SeqFetchRequest(region="chr1:1-10")

    def test_assembly_without_region_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="together"):
            SeqFetchRequest(assembly="GmWm82.a2.v1")

    def test_over_200_genes_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            SeqFetchRequest(genes=[f"g{i}" for i in range(201)])

    def test_empty_genes_list_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="provide either"):
            SeqFetchRequest(genes=[])

    def test_service_rejects_over_200_genes(self, seq_env) -> None:
        session = FakeDbSession(genes=[])
        request = SeqFetchRequest(genes=[f"g{i}" for i in range(200)])
        # Bypass the pydantic cap (service is the second line of defense).
        request.genes = [f"g{i}" for i in range(201)]
        with pytest.raises(AppValidationError, match="200"):
            _run(SeqFetchService().extract(session, request))
