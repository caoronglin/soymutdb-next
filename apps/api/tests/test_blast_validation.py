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
    BlastProgram,
    BlastSubmitRequest,
    validate_sequence_charset,
)
from app.services.blast_service import BlastService, _worker_parameters


def _make_request(**overrides: Any) -> BlastSubmitRequest:
    defaults: dict[str, Any] = dict(
        program=BlastProgram.BLASTN,
        database_id=1,
        query_sequence="ATGCAAGCTTAGCTAGGCTAGGCTAGGC",
        parameters=BlastParameters(),
    )
    defaults.update(overrides)
    return BlastSubmitRequest(**defaults)


def _make_db(db_type: str = "nucl") -> BlastDatabase:
    return BlastDatabase(
        id=1,
        name="williams82_cds",
        db_type=db_type,
        assembly_id=1,
        file_path="/data/dbs/williams82_cds",
        is_active=True,
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
    def test_valid_nucleotide_passes(self) -> None:
        request = _make_request(query_sequence="ACGTUNRYSWKMBDHVXacgtunryswkmbdhvx-" * 2)
        assert request.query_sequence

    def test_invalid_nucleotide_character_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid characters"):
            _make_request(query_sequence="ATGCAAGCTTAGCTAGGCTAGGCTAGGZ")

    def test_digit_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid characters"):
            _make_request(query_sequence="ATGCAAGCTTAGCTAGGCTAGGCTAGG9")

    def test_protein_alphabet_for_blastp(self) -> None:
        request = _make_request(
            program=BlastProgram.BLASTP,
            query_sequence="MKTIIALSYIFCLVFADYKDDDDK",
        )
        assert request.program == BlastProgram.BLASTP

    def test_protein_program_rejects_nucleotide_only_chars(self) -> None:
        # 'U' is not a standard protein residue.
        with pytest.raises(ValidationError, match="Invalid characters"):
            _make_request(
                program=BlastProgram.BLASTP,
                query_sequence="MKTIIAUALSYIFCLVFADYKDDDDK",
            )

    def test_tblastn_query_is_protein(self) -> None:
        request = _make_request(
            program=BlastProgram.TBLASTN,
            query_sequence="MKTIIALSYIFCLVFADYKDDDDK",
        )
        assert request.query_sequence

    def test_fasta_header_ignored_by_alphabet_check(self) -> None:
        request = _make_request(
            query_sequence=">my_gene with spaces\nATGCAAGCTTAGCTAGGCTAGGCTAGGC"
        )
        assert request.query_sequence.startswith(">")

    def test_helper_rejects_bad_charset_directly(self) -> None:
        with pytest.raises(ValueError):
            validate_sequence_charset("ATGCN$", "blastn")


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
                    session, uuid.uuid4(), request
                )
            )


# ---------------------------------------------------------------------------
# Program / database whitelist
# ---------------------------------------------------------------------------


class TestProgramDatabaseCompatibility:
    async def _submit(self, session: FakeDbSession, request: BlastSubmitRequest):
        return await BlastService().submit_job(session, uuid.uuid4(), request)

    def test_blastn_against_nucl_db_ok(self) -> None:
        import asyncio

        session = FakeDbSession(blast_db=_make_db(db_type="nucl"))
        response = asyncio.run(self._submit(session, _make_request()))
        assert response.job_id

    def test_blastn_against_protein_db_rejected(self) -> None:
        import asyncio

        session = FakeDbSession(blast_db=_make_db(db_type="prot"))
        with pytest.raises(AppValidationError, match="cannot search"):
            asyncio.run(self._submit(session, _make_request()))

    def test_blastp_against_nucl_db_rejected(self) -> None:
        import asyncio

        session = FakeDbSession(blast_db=_make_db(db_type="nucl"))
        with pytest.raises(AppValidationError, match="cannot search"):
            asyncio.run(
                self._submit(
                    session,
                    _make_request(
                        program=BlastProgram.BLASTP,
                        query_sequence="MKTIIALSYIFCLVFADYKDDDDK",
                    ),
                )
            )

    def test_blastp_against_prot_db_ok(self) -> None:
        import asyncio

        session = FakeDbSession(blast_db=_make_db(db_type="prot"))
        response = asyncio.run(
            self._submit(
                session,
                _make_request(
                    program=BlastProgram.BLASTP,
                    query_sequence="MKTIIALSYIFCLVFADYKDDDDK",
                ),
            )
        )
        assert response.job_id

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
                query_sequence="ATGCAAGCTTAGCTAGGCTAGGCTAGGC",
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
            BlastParameters(
                gap_open=5,
                gap_extend=2,
                matrix="BLOSUM62",
                dust=False,
                soft_masking=True,
            )
        )
        assert mapped == {
            "gapopen": 5,
            "gapextend": 2,
            "matrix": "BLOSUM62",
            "dust": "no",
            "soft_masking": "yes",
        }

    def test_worker_parameter_drops_percent_identity(self) -> None:
        # percent_identity is a client-side filter, not a BLAST CLI param.
        mapped = _worker_parameters(BlastParameters(percent_identity=90.0))
        assert "percent_identity" not in mapped

    def test_submitted_job_parameters_are_worker_safe(self) -> None:
        import asyncio

        session = FakeDbSession(blast_db=_make_db(db_type="nucl"))
        request = _make_request(
            parameters=BlastParameters(gap_open=5, dust=False, percent_identity=90.0)
        )
        asyncio.run(BlastService().submit_job(session, uuid.uuid4(), request))
        job = next(obj for obj in session.added if isinstance(obj, BlastJob))
        assert job.status == BlastJobStatus.PENDING
        params = job.parameters or {}
        assert "percent_identity" not in params
        assert params["gapopen"] == 5
        assert params["dust"] == "no"
