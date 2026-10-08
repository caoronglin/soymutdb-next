"""Protein-FASTA submission regressions at the API boundary.

M1 scope: the queries this deployment can actually search. ``blastp`` is the
only executable program, so every submission is protein. These tests pin two
things:

1. Inputs that DIAMOND cannot search are refused here with a 422, instead of
   being queued and then failing as an opaque ``Missing fields in input
   line`` from the worker.
2. The API's accept/refuse decision is exactly the shared contract's decision.
   The worker validates against that same owner, so agreement here is what
   makes API and worker consistent; asserting it directly prevents the two
   boundaries from drifting apart.

The parser's own edge cases are covered in
``packages/jobs-py/tests/test_protein_fasta.py``, which the root gate now runs.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from soymutdb_jobs.protein_fasta import (
    ProteinFastaError,
    parse_protein_fasta,
)

from app.schemas.blast import (
    PROTEIN_ALPHABET,
    BlastJobResponse,
    BlastParameters,
    BlastResultResponse,
    BlastSubmitProgram,
    BlastSubmitRequest,
    validate_sequence_charset,
)

PROTEIN = "MKTIIALSYIFCLVFADYKDDDDKTRWQYNE"


def _request(**overrides: object) -> BlastSubmitRequest:
    defaults: dict[str, object] = dict(
        program=BlastSubmitProgram.BLASTP,
        database_id=1,
        query_sequence=PROTEIN,
        parameters=BlastParameters(),
    )
    defaults.update(overrides)
    return BlastSubmitRequest(**defaults)  # type: ignore[arg-type]


#: (label, query) pairs shared by the acceptance and the parity assertions.
EDGE_CASES: list[tuple[str, str]] = [
    ("bare_sequence", PROTEIN),
    ("single_record", f">query_1\n{PROTEIN}"),
    ("multi_record", f">query_1\n{PROTEIN}\n>query_2\n{PROTEIN}"),
    ("lowercase", f">query_1\n{PROTEIN.lower()}"),
    ("ascii_tab", ">query_1\nMKT\tIIALSYIF"),
    ("indented_header", f">query_1\n{PROTEIN}\n  >query_2\n{PROTEIN}"),
    ("crlf", f">query_1\r\n{PROTEIN}\r\n"),
    (
        "wrapped",
        ">query_1\n"
        + "\n".join(PROTEIN[i : i + 10] for i in range(0, len(PROTEIN), 10)),
    ),
    ("ambiguous_residues", ">query_1\nMKTBBXXZZXMKT"),
    ("internal_stop", ">query_1\nMKT*IIA"),
    ("trailing_stop", f">query_1\n{PROTEIN}*"),
    ("header_with_description", f">query_1 some description\n{PROTEIN}"),
    ("nucleotide_looking", ">query_1\n" + "ATGC" * 8),
]

#: Inputs that must never become a queued job.
REJECTED_CASES: list[tuple[str, str, str]] = [
    ("empty", "", "protein_fasta_empty"),
    ("whitespace_only", "   \n  ", "protein_fasta_empty"),
    ("header_without_sequence", ">query_1", "protein_fasta_record_empty"),
    (
        "empty_record_first",
        f">empty\n>query_2\n{PROTEIN}",
        "protein_fasta_record_empty",
    ),
    (
        "empty_record_between_records",
        f">query_1\n{PROTEIN}\n>hole\n>query_2\n{PROTEIN}",
        "protein_fasta_record_empty",
    ),
    (
        "stop_only_record",
        ">query_1\n*",
        "protein_fasta_record_empty",
    ),
    (
        "duplicate_id",
        f">query_1\n{PROTEIN}\n>query_1\n{PROTEIN}",
        "protein_fasta_duplicate_id",
    ),
    (
        "duplicate_id_with_different_description",
        f">query_1 first\n{PROTEIN}\n>query_1 second\n{PROTEIN}",
        "protein_fasta_duplicate_id",
    ),
    (
        "digit_is_not_a_residue",
        f">query_1\n{PROTEIN}9",
        "protein_fasta_invalid_residue",
    ),
    (
        "selenocysteine_is_outside_the_alphabet",
        ">query_1\nMKTIUC",
        "protein_fasta_invalid_residue",
    ),
    *[
        (f"non_ascii_{ord(symbol)}", f">query_1\nMKT{symbol}IIALSYIF",
         "protein_fasta_invalid_residue")
        for symbol in ("ı", "ſ", "ß", "\u00a0", "\v", "\f")
    ],
    (
        "header_without_identifier",
        ">\nMKTIIA",
        "protein_fasta_record_id_missing",
    ),
]


class TestAcceptedProteinQueries:
    @pytest.mark.parametrize("label,query", EDGE_CASES, ids=[c[0] for c in EDGE_CASES])
    def test_edge_case_is_accepted(self, label: str, query: str) -> None:
        assert _request(query_sequence=query).query_sequence == query.strip()

    def test_multi_record_is_not_truncated_to_the_first_record(self) -> None:
        request = _request(query_sequence=f">a\n{PROTEIN}\n>b\n{PROTEIN}")
        assert request.query_sequence.count(">") == 2

    def test_protein_alphabet_is_the_shared_one(self) -> None:
        # The API must not keep a private copy that can drift from the owner
        # the worker validates with.
        from soymutdb_jobs.protein_fasta import PROTEIN_ALPHABET as SHARED

        assert PROTEIN_ALPHABET is SHARED


class TestUnsearchableQueriesAreRefusedAtSubmission:
    @pytest.mark.parametrize(
        "label,query,code",
        REJECTED_CASES,
        ids=[c[0] for c in REJECTED_CASES],
    )
    def test_rejected_with_422(self, label: str, query: str, code: str) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _request(query_sequence=query)
        # The message must name the reason, because this text is what the user
        # sees and what the worker copies into the job error.
        assert code in str(excinfo.value)

    def test_empty_record_error_reaches_the_caller(self) -> None:
        # The specific defect this slice closes: the old validator only
        # inspected the first header, so a later empty record passed and DIAMOND
        # failed it with "Missing fields in input line" after the job started.
        with pytest.raises(ValidationError) as excinfo:
            _request(query_sequence=f">empty\n>query_2\n{PROTEIN}")
        assert "empty" in str(excinfo.value).lower()

    def test_duplicate_ids_are_refused_not_merged(self) -> None:
        with pytest.raises(ValidationError, match="appears more than once"):
            _request(query_sequence=f">query_1\n{PROTEIN}\n>query_1\n{PROTEIN}")


class TestApiAgreesWithTheSharedContract:
    """API and worker must not disagree about what is searchable.

    The worker calls :func:`parse_protein_fasta` directly, so equality with
    the contract is worker parity. Re-deriving the rule here instead would be
    exactly the duplicate owner this slice is meant to avoid.
    """

    @pytest.mark.parametrize("label,query", EDGE_CASES, ids=[c[0] for c in EDGE_CASES])
    def test_api_accepts_exactly_what_the_contract_accepts(
        self, label: str, query: str
    ) -> None:
        parse_protein_fasta(query)  # must not raise
        # BlastService.submit_job rechecks using this helper; it must share
        # the same structural and normalization rules as schema and worker.
        assert validate_sequence_charset(query, "blastp") == query
        assert _request(query_sequence=query).query_sequence

    @pytest.mark.parametrize(
        "label,query,code",
        REJECTED_CASES,
        ids=[c[0] for c in REJECTED_CASES],
    )
    def test_api_refuses_exactly_what_the_contract_refuses(
        self, label: str, query: str, code: str
    ) -> None:
        with pytest.raises(ProteinFastaError) as contract_error:
            parse_protein_fasta(query)
        assert contract_error.value.code == code
        with pytest.raises(ProteinFastaError) as service_error:
            validate_sequence_charset(query, "blastp")
        assert service_error.value.code == code
        with pytest.raises(ValidationError) as api_error:
            _request(query_sequence=query)
        assert str(contract_error.value) in str(api_error.value)

    def test_length_caps_still_apply_around_the_structural_rules(self) -> None:
        # The new structural validation must not have displaced the existing
        # length contract.
        with pytest.raises(ValidationError):
            _request(query_sequence="A" * 100_001)


class TestHistoricalResultsStayReadable:
    """Submission rules are new; stored rows predate them and must not break.

    Jobs completed before this slice can hold a ``query_sequence`` the new
    contract refuses (duplicate record ids, an empty record) and a
    ``query_len`` counted by the old stop-inclusive rule. Reading them must
    return what was stored, not re-validate and not recompute — otherwise
    tightening the submission path would retroactively invalidate finished
    work.
    """

    def _legacy_job(self, **overrides: object):
        base: dict[str, object] = dict(
            job_id="legacy-job",
            id=1,
            status="completed",
            program="blastp",
            database_id=1,
            database="williams82_prot",
            query_sequence=f">query_1\n{PROTEIN}\n>query_1\n{PROTEIN}",
            parameters={},
            hit_count=2,
            submitted_at="2026-10-01T00:00:00Z",
            started_at="2026-10-01T00:00:01Z",
            completed_at="2026-10-01T00:00:09Z",
            error_message=None,
            result_url="blast-results/legacy.txt",
            # Old rule: the trailing stop symbol was counted as a residue.
            query_len=len(PROTEIN) + 1,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_stored_query_len_is_returned_unchanged(self) -> None:
        # BlastResultResponse is the read envelope the service builds from the
        # stored row; it must report the number that was persisted, not a
        # recomputed one.
        result = BlastResultResponse(
            job_id="legacy-job",
            status="completed",
            program="blastp",
            database_id=1,
            # Old rule: the trailing stop symbol was counted as a residue.
            query_len=len(PROTEIN) + 1,
        )
        assert result.query_len == len(PROTEIN) + 1

    def test_stored_query_that_the_new_rules_refuse_is_still_readable(self) -> None:
        job = self._legacy_job()
        response = BlastJobResponse.model_validate(job)
        assert response.query_sequence == job.query_sequence
        assert response.status.value == "completed"

    # These are schema smoke tests only. Historical compatibility through the
    # real reading service is covered in test_blast_results.py.
