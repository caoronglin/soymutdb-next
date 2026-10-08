"""Worker-side protein-FASTA contracts for the ``blastp`` task.

M1 scope on the worker: a Celery payload can reach this task without passing
through the API (direct dispatch, redelivery, a payload written by an older
API), so the task validates the query itself before touching the filesystem or
the search binary.

Measured DIAMOND 2.1.14 behaviour these tests pin down:

* an empty record fails only as ``Error: Missing fields in input line``, after
  the job is already running and the binary has been spawned;
* duplicate record ids are searched twice and return two indistinguishable hit
  rows.

The task therefore refuses both before spawning, with the same shared contract
the API validated with, and reports a query length that counts residues rather
than translation artifacts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from soymutdb_jobs.protein_fasta import (
    ProteinFastaError,
    parse_protein_fasta,
)

from soymutdb_worker.tasks import blast
from tests.test_blast_task import FakeSession, FakeTask, _call_task, _fake_db, _payload

PROTEIN = "MKTIIALSYIFCLVFADYKDDDDKTRWQYNE"


def _run_with_sequence(monkeypatch, sequence: str) -> dict:
    """Drive the task to completion with a fake engine, recording the query.

    Returns the task result and, under ``"_query_fasta"``, the exact bytes the
    task wrote for the search — the only way to assert what DIAMOND would have
    consumed without running it.
    """
    payload = _payload()
    payload["payload"]["sequence"] = sequence
    session = FakeSession(status="pending")
    monkeypatch.setattr(blast, "get_db", lambda: _fake_db(session))
    monkeypatch.setattr(blast, "get_blast_db_path", lambda db, **kw: Path("/tmp/db"))
    seen: dict = {}

    def fake_run(**kwargs):
        seen["query_fasta"] = Path(kwargs["query_path"]).read_text()
        Path(kwargs["output_path"]).write_text(
            "query_1\tsubject_1\t100.0\t200\t0\t0\t1\t200\t1\t200\t1e-50\t400.0\n"
        )

    monkeypatch.setattr(blast, "run_blast_command", fake_run)
    monkeypatch.setattr(blast, "_result_file_metadata", lambda p: ("deadbeef", 42))
    monkeypatch.setattr(blast, "upload_file", lambda *a, **k: None)
    monkeypatch.setattr(
        blast, "generate_presigned_url", lambda *a, **k: "https://s3.example/x"
    )
    result = _call_task(blast.run_blast, FakeTask(), payload=payload)
    result["_query_fasta"] = seen["query_fasta"]
    result["_session"] = session
    return result


class TestUnsearchablePayloadsFailBeforeTheEngine:
    """A queued job must not fail with an opaque engine error.

    The engine is asserted *not* to have been called: a refusal that still
    spawns DIAMOND would leave the operator with the same ``Missing fields in
    input line`` text this slice exists to remove.
    """

    @pytest.mark.parametrize(
        "label,sequence,code",
        [
            ("empty_record_first", f">empty\n>query_2\n{PROTEIN}", "protein_fasta_record_empty"),
            ("empty_record_last", f">query_1\n{PROTEIN}\n>empty", "protein_fasta_record_empty"),
            ("stop_only_record", ">query_1\n*", "protein_fasta_record_empty"),
            (
                "duplicate_ids",
                f">query_1\n{PROTEIN}\n>query_1\n{PROTEIN}",
                "protein_fasta_duplicate_id",
            ),
            ("digit_residue", f">query_1\n{PROTEIN}9", "protein_fasta_invalid_residue"),
        ],
        ids=[
            "empty_record_first",
            "empty_record_last",
            "stop_only_record",
            "duplicate_ids",
            "digit_residue",
        ],
    )
    def test_refused_without_spawning_the_search(
        self, monkeypatch, label: str, sequence: str, code: str
    ) -> None:
        payload = _payload()
        payload["payload"]["sequence"] = sequence
        session = FakeSession(status="pending")
        monkeypatch.setattr(blast, "get_db", lambda: _fake_db(session))
        monkeypatch.setattr(blast, "get_blast_db_path", lambda db, **kw: Path("/tmp/db"))

        def explode(**kwargs):  # pragma: no cover - must never run
            raise AssertionError("the search binary must not be reached")

        monkeypatch.setattr(blast, "run_blast_command", explode)
        monkeypatch.setattr(blast, "upload_file", lambda *a, **k: None)
        monkeypatch.setattr(
            blast, "generate_presigned_url", lambda *a, **k: "https://s3.example/x"
        )

        with pytest.raises(ValueError) as excinfo:
            _call_task(blast.run_blast, FakeTask(), payload=payload)
        # The job's stored error must name the reason, not just fail.
        assert code in str(excinfo.value)
        assert session.status == "failed"
        assert code in (session.error or "")

    def test_the_worker_agrees_with_the_shared_contract(self, monkeypatch) -> None:
        # Same table as the API-side parity test: what the contract refuses, the
        # task refuses, with the same code.
        cases = [
            f">empty\n>query_2\n{PROTEIN}",
            f">query_1\n{PROTEIN}\n>query_1\n{PROTEIN}",
            f">query_1\n{PROTEIN}9",
            ">query_1\n*",
            ">",
            *[f">query_1\nMKT{symbol}IIALSYIF" for symbol in ("ı", "ſ", "ß", "\u00a0")],
        ]
        for sequence in cases:
            with pytest.raises(ProteinFastaError) as contract_error:
                parse_protein_fasta(sequence)
            payload = _payload()
            payload["payload"]["sequence"] = sequence
            session = FakeSession(status="pending")
            monkeypatch.setattr(blast, "get_db", lambda: _fake_db(session))
            monkeypatch.setattr(blast, "get_blast_db_path", lambda db, **kw: Path("/tmp/db"))
            monkeypatch.setattr(blast, "run_blast_command", lambda **k: None)
            monkeypatch.setattr(blast, "upload_file", lambda *a, **k: None)
            with pytest.raises(ValueError) as task_error:
                _call_task(blast.run_blast, FakeTask(), payload=payload)
            assert str(contract_error.value) in str(task_error.value)


class TestAcceptedPayloadsReachTheEngine:
    def test_bare_sequence_gets_a_query_header(self, monkeypatch) -> None:
        result = _run_with_sequence(monkeypatch, PROTEIN)
        assert result["_query_fasta"] == f">query\n{PROTEIN}\n"
        assert result["query_len"] == len(PROTEIN)

    def test_multi_record_preserves_every_record(self, monkeypatch) -> None:
        result = _run_with_sequence(
            monkeypatch, f">query_1\n{PROTEIN}\n>query_2\n{PROTEIN}"
        )
        assert result["_query_fasta"] == f">query_1\n{PROTEIN}\n>query_2\n{PROTEIN}\n"
        assert result["query_len"] == 2 * len(PROTEIN)

    def test_ascii_tab_is_normalized_before_the_search(self, monkeypatch) -> None:
        result = _run_with_sequence(monkeypatch, ">query_1\nMKT\tIIALSYIF")
        assert result["_query_fasta"] == ">query_1\nMKTIIALSYIF\n"
        assert result["query_len"] == len("MKTIIALSYIF")

    def test_lowercase_is_normalized_before_the_search(self, monkeypatch) -> None:
        result = _run_with_sequence(monkeypatch, f">query_1\n{PROTEIN.lower()}")
        assert result["_query_fasta"] == f">query_1\n{PROTEIN}\n"

    def test_wrapped_input_is_unwrapped(self, monkeypatch) -> None:
        wrapped = ">query_1\n" + "\n".join(
            PROTEIN[i : i + 10] for i in range(0, len(PROTEIN), 10)
        )
        result = _run_with_sequence(monkeypatch, wrapped)
        assert result["_query_fasta"] == f">query_1\n{PROTEIN}\n"
        assert result["query_len"] == len(PROTEIN)

    def test_crlf_input_is_normalized(self, monkeypatch) -> None:
        result = _run_with_sequence(monkeypatch, f">query_1\r\n{PROTEIN}\r\n")
        assert result["_query_fasta"] == f">query_1\n{PROTEIN}\n"

    def test_header_description_is_dropped_from_the_search_bytes(self, monkeypatch) -> None:
        # The identifier is what identifies a hit; the description is not part
        # of the searched record.
        result = _run_with_sequence(
            monkeypatch, f">query_1 Glycine max transcript\n{PROTEIN}"
        )
        assert result["_query_fasta"] == f">query_1\n{PROTEIN}\n"


class TestQueryLengthIsResidueCount:
    def test_trailing_stop_is_not_counted_as_a_residue(self, monkeypatch) -> None:
        # len(record.seq) used to report 32 for a 31-residue protein.
        result = _run_with_sequence(monkeypatch, f">query_1\n{PROTEIN}*")
        assert result["query_len"] == len(PROTEIN)
        # The stop is still part of what the engine receives.
        assert result["_query_fasta"].endswith("*\n")

    def test_internal_stop_is_counted(self, monkeypatch) -> None:
        result = _run_with_sequence(monkeypatch, ">query_1\nMKT*IIA")
        assert result["query_len"] == len("MKT*IIA")

    def test_terminal_stop_is_excluded_per_record_in_a_multi_record_query(
        self, monkeypatch
    ) -> None:
        result = _run_with_sequence(
            monkeypatch, f">query_1\n{PROTEIN}*\n>query_2\n{PROTEIN}"
        )
        assert result["query_len"] == 2 * len(PROTEIN)

    def test_persisted_query_length_matches_the_reported_one(self, monkeypatch) -> None:
        result = _run_with_sequence(monkeypatch, f">query_1\n{PROTEIN}*")
        persisted = [
            update["query_len"]
            for update in result["_session"].updates
            if "query_len" in update
        ]
        assert persisted == [len(PROTEIN)]
