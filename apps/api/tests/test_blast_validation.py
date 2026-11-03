"""BLAST input validation tests (no docker: schema + service layer).

Covers: sequence alphabet (nucleotide vs. protein), length caps, database /
program whitelists and worker-safe parameter mapping.  Errors surface as the
unified envelope (``ValidationError`` / 422) rather than raw 500s.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.exceptions import NotFoundError
from app.core.exceptions import ValidationError as AppValidationError
from app.models.blast import BlastDatabase, BlastJob, BlastJobStatus
from app.schemas.blast import (
    BlastParameters,
    BlastSubmitProgram,
    BlastSubmitRequest,
    validate_sequence_charset,
)
from app.services.blast_service import BlastService, _worker_parameters
from app.services.release_context import ReleaseContext

#: A valid protein query; the only executable program is protein/protein.
PROTEIN_QUERY = "MKTIIALSYIFCLVFADYKDDDDKTRWQYNE"


def _context(release_id: int = 7) -> ReleaseContext:
    """Published release the fake session's rows belong to."""
    return ReleaseContext(release_id=release_id, assembly_id=1, assembly="Wm82.a2.v1")


def _make_request(**overrides: Any) -> BlastSubmitRequest:
    defaults: dict[str, Any] = dict(
        program=BlastSubmitProgram.BLASTP,
        database_id=1,
        query_sequence="MKTIIALSYIFCLVFADYKDDDDKTRWQYNE",
        parameters=BlastParameters(),
    )
    defaults.update(overrides)
    return BlastSubmitRequest(**defaults)


def _make_db(db_type: str = "prot") -> BlastDatabase:
    return BlastDatabase(
        id=1,
        name="williams82_cds",
        db_type=db_type,
        assembly_id=1,
        file_path="/data/dbs/williams82_cds",
        is_active=True,
        engine="diamond",
        build_status="ready",
        is_default=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


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
    """AsyncSession stand-in recording adds/commits for one transaction."""

    def __init__(self, blast_db: BlastDatabase | None = None):
        self.blast_db = blast_db
        self.added: list = []
        self.commits = 0
        self.flushes = 0

    async def execute(self, stmt, params=None):
        if "blast_databases" in str(stmt):
            return _Result([self.blast_db] if self.blast_db else [])
        return _Result([])

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj) -> None:
        pass


# ---------------------------------------------------------------------------
# Sequence alphabet
# ---------------------------------------------------------------------------


class TestSequenceAlphabet:
    def test_valid_protein_passes(self) -> None:
        request = _make_request(query_sequence="ACDEFGHIKLMNPQRSTVWYBZX*acdefghiklmnpqrstvwy" * 2)
        assert request.query_sequence

    def test_acgt_string_is_ambiguous_not_rejected(self) -> None:
        # A, T, G and C are all valid residues, so a bare ACGT string cannot be
        # refused by alphabet alone. The nucleotide programs that would have
        # made this meaningful no longer exist; see
        # TestOnlyProteinProteinIsSubmittable.
        assert _make_request(query_sequence="ACGTACGTACGTACGTACGTACGTACGTACGT").query_sequence

    def test_uracil_is_not_a_protein_residue(self) -> None:
        # The refusal is raised by the shared protein-FASTA contract, so the
        # message is code-prefixed; see test_blast_protein_fasta_contract.py
        # for the full edge-case matrix.
        with pytest.raises(ValidationError, match="protein_fasta_invalid_residue"):
            _make_request(query_sequence="MKTIIAUALSYIFCLVFADYKDDDDKTRWQYNE")

    def test_digit_rejected(self) -> None:
        with pytest.raises(ValidationError, match="protein_fasta_invalid_residue"):
            _make_request(query_sequence="MKTIIALSYIFCLVFADYKDDDDKTRWQYNE9")

    def test_default_program_is_protein_protein(self) -> None:
        request = _make_request(query_sequence=PROTEIN_QUERY)
        assert request.program == BlastSubmitProgram.BLASTP

    def test_fasta_header_ignored_by_alphabet_check(self) -> None:
        request = _make_request(query_sequence=f">my_gene with spaces\n{PROTEIN_QUERY}")
        assert request.query_sequence.startswith(">")

    def test_helper_rejects_bad_charset_directly(self) -> None:
        with pytest.raises(ValueError):
            validate_sequence_charset("ATGCN$", "blastp")


class TestOnlyProteinProteinIsSubmittable:
    def test_nucleotide_programs_are_rejected_at_the_schema(self) -> None:
        for program in ("blastn", "blastx", "tblastn", "tblastx"):
            with pytest.raises(ValidationError):
                BlastSubmitRequest(
                    program=program, query_sequence=PROTEIN_QUERY, parameters=BlastParameters()
                )

    @pytest.mark.parametrize("field,value", [
        ("word_size", 11), ("dust", True), ("soft_masking", False),
    ])
    def test_retired_blast_parameters_are_rejected(self, field, value) -> None:
        # Silently dropping them would misreport which search actually ran.
        with pytest.raises(ValidationError, match="retired NCBI BLAST option"):
            BlastSubmitRequest(
                program="blastp",
                query_sequence=PROTEIN_QUERY,
                parameters=BlastParameters(**{field: value}),
            )


class TestSequenceLength:
    def test_over_length_rejected_by_schema(self) -> None:
        with pytest.raises(ValidationError):
            _make_request(query_sequence="A" * 100_001)

    def test_under_min_length_rejected_by_schema(self) -> None:
        with pytest.raises(ValidationError):
            _make_request(query_sequence="ATGCA")

    def test_service_rejects_over_length_via_settings(self, monkeypatch) -> None:
        import asyncio

        from app.services import blast_service

        monkeypatch.setattr(blast_service.settings, "blast_max_length", 50)
        session = FakeDbSession(blast_db=_make_db())
        request = _make_request()  # valid short sequence, then override below
        # Bypass the pydantic cap (service is the second line of defense).
        request.query_sequence = "A" * 60
        with pytest.raises(AppValidationError, match="exceeds max length"):
            asyncio.run(
                blast_service.BlastService().submit_job(
                    session, uuid.uuid4(), request, release_context=_context()
                )
            )


# ---------------------------------------------------------------------------
# Program / database whitelist
# ---------------------------------------------------------------------------


class TestProgramDatabaseCompatibility:
    async def _submit(self, session: FakeDbSession, request: BlastSubmitRequest):
        return await BlastService().submit_job(
            session, uuid.uuid4(), request, release_context=_context()
        )

    def test_blastp_against_prot_db_ok(self) -> None:
        import asyncio

        session = FakeDbSession(blast_db=_make_db(db_type="prot"))
        response = asyncio.run(self._submit(session, _make_request()))
        assert response.job_id

    def test_blastp_against_nucl_db_rejected(self) -> None:
        import asyncio

        session = FakeDbSession(blast_db=_make_db(db_type="nucl"))
        with pytest.raises(NotFoundError):
            asyncio.run(self._submit(session, _make_request()))

    def test_missing_or_inactive_database_not_found(self) -> None:
        import asyncio

        session = FakeDbSession(blast_db=None)
        with pytest.raises(NotFoundError):
            asyncio.run(self._submit(session, _make_request()))

    def test_program_enum_is_whitelist(self) -> None:
        # Any value outside the enum is rejected by pydantic.
        with pytest.raises(ValidationError):
            BlastSubmitRequest(
                program="psiblast",  # type: ignore[arg-type]
                database_id=1,
                query_sequence="MKTIIALSYIFCLVFADYKDDDDKTRWQYNE",
            )


# ---------------------------------------------------------------------------
# Parameter ranges and worker mapping
# ---------------------------------------------------------------------------


class TestParameters:
    def test_matrix_whitelist(self) -> None:
        with pytest.raises(ValidationError, match="Unsupported substitution matrix"):
            _make_request(parameters=BlastParameters(matrix="BLOSUM999"))

    def test_matrix_normalized_to_upper(self) -> None:
        params = BlastParameters(matrix="blosum62")
        assert params.matrix == "BLOSUM62"

    def test_negative_gap_open_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_request(parameters=BlastParameters(gap_open=-1))

    def test_negative_gap_extend_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_request(parameters=BlastParameters(gap_extend=-1))

    def test_worker_parameter_mapping(self) -> None:
        mapped = _worker_parameters(
            BlastParameters(gap_open=5, gap_extend=2, matrix="BLOSUM62")
        )
        assert mapped == {"gapopen": 5, "gapextend": 2, "matrix": "BLOSUM62"}

    def test_worker_parameter_drops_percent_identity(self) -> None:
        # percent_identity is a client-side filter, not a BLAST CLI param.
        mapped = _worker_parameters(BlastParameters(percent_identity=90.0))
        assert "percent_identity" not in mapped

    def test_submitted_job_parameters_are_worker_safe(self) -> None:
        import asyncio

        session = FakeDbSession(blast_db=_make_db(db_type="prot"))
        request = _make_request(
            parameters=BlastParameters(gap_open=5, percent_identity=90.0)
        )
        asyncio.run(
            BlastService().submit_job(session, uuid.uuid4(), request, release_context=_context())
        )
        job = next(obj for obj in session.added if isinstance(obj, BlastJob))
        assert job.status == BlastJobStatus.PENDING
        params = job.parameters or {}
        assert "percent_identity" not in params
        assert params["gapopen"] == 5
        # No NCBI-only key may reach the worker: it would abort the search.
        assert not {"dust", "soft_masking", "word_size"} & set(params)
