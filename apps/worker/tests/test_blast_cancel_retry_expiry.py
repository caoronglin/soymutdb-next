"""Cancellation, expiry and retry semantics on the BLAST worker path.

Uses the same narrow fake-session style as ``test_blast_task.py``: these
contracts are about guarded SQL and status decisions, not about a live PG
server. PostgreSQL-backed expiry is covered by the API integration suite.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from soymutdb_worker.repositories import BlastJobStore
from soymutdb_worker.tasks import blast as blast_module
from tests.test_blast_task import FakeTask, _payload


class _Result:
    def __init__(self, row=None, rowcount=1):
        self._row = row
        self.rowcount = rowcount

    def first(self):
        return self._row


class _ExpirySession:
    """Serves status/expires_at and records guarded UPDATEs."""

    def __init__(self, status="pending", expires_at=None, rowcount=1):
        self.status = status
        self.expires_at = expires_at
        self.rowcount = rowcount
        self.updates: list[dict] = []

    def execute(self, stmt, params=None):
        compiled = str(stmt)
        if compiled.strip().upper().startswith("SELECT"):
            if "expires_at" in compiled:
                return _Result((self.expires_at,))
            return _Result((self.status,))
        values = {
            getattr(key, "name", str(key)): getattr(value, "value", value)
            for key, value in dict(getattr(stmt, "_values", {}) or {}).items()
        }
        self.updates.append(values)
        # Emulate the guarded WHERE: an UPDATE conditioned on a status only
        # wins when the row's current status is that value. Bound parameters
        # carry the literal, not the compiled SQL string.
        expected = None
        clause = getattr(stmt, "whereclause", None)
        if clause is not None:
            from sqlalchemy.sql.elements import BindParameter
            def walk(node):
                for child in node.get_children():
                    if (isinstance(child, BindParameter)
                            and isinstance(child.value, str)
                            and child.value in {"failed", "pending", "running",
                                                "completed", "cancelled", "expired"}):
                        return child.value
                    found = walk(child)
                    if found:
                        return found
                return None
            expected = walk(clause)
        won = expected is None or expected == self.status
        if won and "status" in values:
            self.status = str(values["status"])
        return _Result(rowcount=self.rowcount if won else 0)


def _db(session):
    @contextmanager
    def factory():
        yield session
    return factory


class _NoDeadlineSession(_ExpirySession):
    """A legacy row whose ``expires_at`` is NULL: nothing may be invented."""

    def __init__(self, status="pending", rowcount=1):
        super().__init__(status=status, expires_at=None, rowcount=rowcount)


def test_expired_job_never_executes(monkeypatch):
    payload = _payload()
    session = _ExpirySession(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    monkeypatch.setattr(blast_module, "get_db", _db(session))
    monkeypatch.setattr(
        blast_module, "get_blast_db_path",
        lambda *a, **k: pytest.fail("expired job launched a search"),
    )
    result = blast_module.run_blast.run.__func__(FakeTask(), payload=payload)
    assert result["skipped"] is True
    assert result["reason"] == "cancelled_or_expired"
    assert session.status == "expired"


def test_cancelled_job_is_skipped_even_with_future_expiry(monkeypatch):
    payload = _payload()
    session = _ExpirySession(status="cancelled",
                             expires_at=datetime.now(UTC) + timedelta(days=1))
    monkeypatch.setattr(blast_module, "get_db", _db(session))
    monkeypatch.setattr(
        blast_module, "get_blast_db_path",
        lambda *a, **k: pytest.fail("cancelled job launched a search"),
    )
    result = blast_module.run_blast.run.__func__(FakeTask(), payload=payload)
    assert result["skipped"] is True and result["reason"] == "cancelled_or_expired"


def test_a_cancelled_row_is_never_rewritten_as_expired(monkeypatch):
    """Who ended the job stays readable: cancel is not clobbered by expiry.

    The worker closes *deadline* expiries only. Renaming a user's cancellation
    to ``expired`` with a system message is a false record of what happened.
    """
    payload = _payload()
    session = _NoDeadlineSession(status="cancelled")
    monkeypatch.setattr(blast_module, "get_db", _db(session))
    monkeypatch.setattr(
        blast_module, "get_blast_db_path",
        lambda *a, **k: pytest.fail("cancelled job launched a search"),
    )
    result = blast_module.run_blast.run.__func__(FakeTask(), payload=payload)
    assert result["skipped"] is True
    assert session.status == "cancelled", "the cancellation message was overwritten"
    assert session.updates == [], "a cancelled row must not be UPDATEd"


def _ncbi_payload(job_id: str | None = None) -> dict:
    """A payload for the NCBI engine, with the frozen index identity it needs.

    Cancellation and deadline expiry are decided on the job row, before any
    engine-specific argument handling, so the same guard has to hold for both
    backends. This payload is what makes that claim testable on the NCBI side
    instead of only on DIAMOND.
    """
    import uuid as _uuid
    from datetime import UTC, datetime

    from soymutdb_jobs.schemas import JobPayload

    from soymutdb_worker.tasks.blast import BLAST_RUN_TASK

    job_id = job_id or str(_uuid.uuid4())
    now = datetime.now(UTC)
    return JobPayload(
        job_id=job_id,
        task_name=BLAST_RUN_TASK,
        payload={
            "job_id": job_id,
            "program": "blastn",
            "database": "williams82_genome",
            "sequence": ">q\nACGTACGTACGTACGTACGT",
            "evalue": 1e-5,
            "max_target_seqs": 10,
            "engine": "ncbi_blast",
            "parameters": {
                "index_identity": "b" * 64,
                "fasta_sha256": "a" * 64,
                "database_type": "nucl",
                "release_id": 7,
                "assembly_id": 42,
            },
        },
        idempotency_key=f"blast:{job_id}",
        created_at=now,
        updated_at=now,
    ).model_dump(mode="json")


@pytest.mark.parametrize("status,expires_in", [
    ("cancelled", timedelta(days=1)),
    ("pending", -timedelta(seconds=1)),
])
def test_ncbi_jobs_are_guarded_before_the_engine_runs(monkeypatch, status, expires_in):
    """A cancelled or past-deadline NCBI job never reaches the aligner."""
    payload = _ncbi_payload()
    session = _ExpirySession(status=status, expires_at=datetime.now(UTC) + expires_in)
    monkeypatch.setattr(blast_module, "get_db", _db(session))
    monkeypatch.setattr(
        blast_module, "get_ncbi_db_path",
        lambda *a, **k: pytest.fail("a cancelled/expired NCBI job resolved an index"),
    )
    monkeypatch.setattr(
        blast_module, "run_blast_command",
        lambda *a, **k: pytest.fail("a cancelled/expired NCBI job launched a search"),
    )
    result = blast_module.run_blast.run.__func__(FakeTask(), payload=payload)
    assert result["skipped"] is True
    assert result["reason"] == "cancelled_or_expired"


def test_future_expiry_still_runs_and_caps_download_ttl(monkeypatch, tmp_path):
    payload = _payload()
    session = _ExpirySession(expires_at=datetime.now(UTC) + timedelta(seconds=10))
    monkeypatch.setattr(blast_module, "get_db", _db(session))
    monkeypatch.setattr(blast_module, "get_blast_db_path", lambda *a, **k: Path("/tmp/db"))
    monkeypatch.setattr(blast_module, "validate_diamond_parameters", lambda p: {})
    monkeypatch.setattr(blast_module, "run_blast_command", lambda **kw: None)
    monkeypatch.setattr(blast_module, "parse_diamond_tabular",
                        lambda p: {"hits": [], "total_hits": 0, "query_len": 0})
    monkeypatch.setattr(blast_module, "_result_file_metadata", lambda p: ("abc", 12))
    monkeypatch.setattr(blast_module, "upload_file", lambda *a, **k: None)
    signed: dict = {}
    monkeypatch.setattr(blast_module, "generate_presigned_url",
                        lambda *a, **k: signed.setdefault("expires_in", k["expires_in"]))
    monkeypatch.setattr(blast_module, "notify_completed", lambda *a, **k: None)
    result = blast_module.run_blast.run.__func__(FakeTask(), payload=payload)
    assert result["total_hits"] == 0
    assert 0 < signed["expires_in"] <= 10, "download link outlived the job deadline"


def test_retry_resets_only_failed_rows():
    failed = _ExpirySession(status="failed")
    assert BlastJobStore(failed).request_retry("job") is True
    assert failed.status == "pending"
    assert failed.updates[-1]["error_message"] is None
    assert failed.updates[-1]["result_path"] is None
    for status in ("completed", "cancelled", "expired", "running"):
        session = _ExpirySession(status=status)
        assert BlastJobStore(session).request_retry("job") is False


def test_download_ttl_is_capped_and_never_negative():
    store = BlastJobStore(_ExpirySession(expires_at=None))
    assert store.download_ttl_seconds("job", cap=86400) == 86400
    store = BlastJobStore(_ExpirySession(
        expires_at=datetime.now(UTC) + timedelta(seconds=10)))
    assert 0 < store.download_ttl_seconds("job", cap=86400) <= 10
    store = BlastJobStore(_ExpirySession(
        expires_at=datetime.now(UTC) - timedelta(seconds=10)))
    assert store.download_ttl_seconds("job", cap=86400) == 0


@pytest.mark.parametrize("value,expected", [
    (42, 42), ("42", 42), (" 42 ", 42),
    (None, None), ("", None), ("abc", None), (0, None), ("-1", None),
    (True, None), (42.5, None),
])
def test_frozen_provenance_ids_accept_only_positive_integers(value, expected):
    """The outbox payload is JSON: "42" and 42 both mean assembly 42, no more."""
    assert blast_module._frozen_id(value) == expected
