"""Lifecycle of an owner-scoped variant export.

The export record (owner, status, artifact key, expiry) lives in PostgreSQL
and is owned by the API; the worker advances it.  These tests pin the
worker's side of that contract:

* a delivery claims the record before it works, so a re-delivered event
  cannot produce a second artifact;
* a finished export is never re-run;
* a failure reaches a final state instead of leaving the submitter waiting;
* the artifact key and the expiry window are the shared contract, not two
  independent derivations on the two sides.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from soymutdb_jobs.export_artifact import (
    build_export_artifact_key,
    build_export_filename,
)

from soymutdb_worker.repositories import EXPORT_CLAIM_LEASE_SECONDS, VariantExportStore
from soymutdb_worker.shared import JobStatus
from soymutdb_worker.tasks import export as export_task


class _FakeSession:
    """Records the statements the store issues, with a mutable status."""

    def __init__(
        self, status: str | None = "pending", started_at: datetime | None = None
    ) -> None:
        self.status = status
        self.started_at = started_at
        self.updates: list[dict] = []

    def execute(self, query, parameters=None, **kwargs):
        statement = str(query)
        if "variant_exports" not in statement:
            raise AssertionError(f"unexpected statement: {statement}")
        if statement.upper().startswith("UPDATE"):
            try:
                params = dict(query.compile().params)
            except Exception:  # pragma: no cover — defensive
                params = {}
            self.updates.append(params)
            if "status" in params:
                self.status = params["status"]
            if "started_at" in params:
                self.started_at = params["started_at"]
            return _Result(rowcount=1)
        if not self.status:
            return _Result(rowcount=0, row=None)
        return _Result(rowcount=0, row=(self.status, self.started_at))

    def commit(self) -> None:
        pass


class _Result:
    def __init__(self, rowcount: int = 0, row: tuple | None = None) -> None:
        self.rowcount = rowcount
        self._row = row

    def first(self):
        return self._row


def test_claim_moves_a_pending_export_to_running() -> None:
    session = _FakeSession("pending")
    store = VariantExportStore(session)

    assert store.begin_run("export-1") == "run"
    assert session.status == JobStatus.RUNNING.value
    assert session.updates[0]["status"] == JobStatus.RUNNING.value
    assert session.updates[0]["started_at"] is not None


def test_a_finished_export_is_never_claimed_again() -> None:
    for terminal in ("succeeded", "failed"):
        session = _FakeSession(terminal)
        store = VariantExportStore(session)

        assert store.begin_run("export-1") == "skip"
        assert session.updates == []


def test_an_unknown_export_is_reported_as_missing() -> None:
    """A command without a record must be loud, not a silent skip."""
    session = _FakeSession(None)
    store = VariantExportStore(session)

    assert store.begin_run("export-missing") == "missing"
    assert session.updates == []


def test_a_running_export_is_not_claimed_while_its_lease_holds() -> None:
    """A duplicate dispatch must not start a second run of the same request."""
    session = _FakeSession("running", started_at=datetime.now(UTC))
    store = VariantExportStore(session)

    assert store.begin_run("export-1") == "skip"
    assert session.updates == []


def test_an_expired_lease_fails_closed() -> None:
    """A redelivery never starts a second execution after lease expiry."""
    stale = datetime.now(UTC) - timedelta(seconds=EXPORT_CLAIM_LEASE_SECONDS + 60)
    session = _FakeSession("running", started_at=stale)
    store = VariantExportStore(session)

    assert store.begin_run("export-1") == "expired"
    assert session.status == "failed"
    assert session.started_at == stale
    assert session.updates[-1]["error_message"] == export_task.EXPORT_FAILED_MESSAGE


def test_success_records_the_artifact_key_and_the_expiry_window() -> None:
    session = _FakeSession("running")
    store = VariantExportStore(session)
    expires_at = datetime.now(UTC) + timedelta(days=7)

    assert store.mark_succeeded(
        "export-1",
        artifact_path="exports/export-1/file.tsv.gz",
        record_count=42,
        file_size=1024,
        expires_at=expires_at,
    )
    assert session.status == JobStatus.SUCCEEDED.value
    written = session.updates[-1]
    assert written["artifact_path"] == "exports/export-1/file.tsv.gz"
    assert written["record_count"] == 42
    assert written["file_size"] == 1024
    assert written["expires_at"] == expires_at


def test_failure_reaches_a_final_state() -> None:
    session = _FakeSession("running")
    store = VariantExportStore(session)

    assert store.mark_failed("export-1", error="ValueError: boom")
    assert session.status == JobStatus.FAILED.value
    assert "boom" in session.updates[-1]["error_message"]


def test_a_terminal_export_cannot_be_overwritten_by_a_late_success() -> None:
    session = _FakeSession("succeeded")
    store = VariantExportStore(session)

    assert not store.mark_succeeded(
        "export-1",
        artifact_path="exports/export-1/other.tsv",
        record_count=1,
        file_size=1,
        expires_at=datetime.now(UTC),
    )
    assert session.updates == []


def test_the_task_never_reexecutes_an_expired_export(monkeypatch) -> None:
    stale = datetime.now(UTC) - timedelta(seconds=EXPORT_CLAIM_LEASE_SECONDS + 60)
    session = _FakeSession("running", started_at=stale)
    monkeypatch.setattr(export_task, "get_db", _ctx(session))
    monkeypatch.setattr(export_task, "_run_export",
                        lambda *a, **k: pytest.fail("expired record must not execute"))
    result = export_task.export_variants.run("export-1", {"release_key": "7"}, "tsv", True)
    assert result["status"] == "skipped"
    assert session.status == "failed"


def test_the_task_skips_an_export_it_may_not_claim(monkeypatch) -> None:
    """A record that is finished must not produce a new artifact."""
    session = _FakeSession("succeeded")
    monkeypatch.setattr(export_task, "get_db", _ctx(session))
    monkeypatch.setattr(
        export_task,
        "upload_large_file",
        lambda *a, **k: pytest.fail("must not upload for an unclaimable export"),
    )

    result = export_task.export_variants.run(
        "export-1", {"release_key": "7"}, "tsv", True
    )

    assert result["status"] == "skipped"


def test_the_task_fails_loudly_when_the_record_is_missing(monkeypatch) -> None:
    """A command without a record must not disappear as a success."""
    session = _FakeSession(None)
    monkeypatch.setattr(export_task, "get_db", _ctx(session))
    monkeypatch.setattr(
        export_task,
        "upload_large_file",
        lambda *a, **k: pytest.fail("must not upload without a record"),
    )

    with pytest.raises(export_task.ExportRecordMissingError):
        export_task.export_variants.run(
            "export-1", {"release_key": "7"}, "tsv", True
        )


def test_a_failing_claim_still_reaches_a_final_state(monkeypatch) -> None:
    """A claim that itself fails must not strand the record in ``pending``.

    The submitter polls the record; a record that stays ``pending`` is
    exactly the state that is never resolved. The claim is part of the work,
    so a failure in it has to drive the record to a final state too.
    """
    session = _FakeSession("pending")
    monkeypatch.setattr(export_task, "get_db", _ctx(session))

    def _boom(*args, **kwargs):
        raise RuntimeError("the claim could not be recorded")

    monkeypatch.setattr(export_task, "_claim_export", _boom)

    with pytest.raises(RuntimeError):
        export_task.export_variants.run("export-1", {"release_key": "7"}, "tsv", True)

    assert session.status == JobStatus.FAILED.value


def test_the_task_records_the_failure_state_before_reraising(monkeypatch, caplog) -> None:
    session = _FakeSession("pending")
    monkeypatch.setattr(export_task, "get_db", _ctx(session))

    def _boom(*args, **kwargs):
        raise ValueError("SELECT internal_id FROM mutants WHERE token='private-secret'")

    monkeypatch.setattr(export_task, "build_export_query", _boom)

    with pytest.raises(ValueError):
        export_task.export_variants.run("export-1", {"release_key": "7"}, "tsv", True)

    assert session.status == JobStatus.FAILED.value
    message = session.updates[-1]["error_message"]
    assert message == export_task.EXPORT_FAILED_MESSAGE
    assert "SELECT" not in message
    assert "private-secret" not in message
    assert "internal_id" not in message
    # Diagnostics remain available to operators, correlated by the export id.
    records = [r for r in caplog.records if r.name == export_task.logger.name]
    failure = next(r for r in records if r.getMessage() == "Export export-1 failed")
    assert failure.exc_info is not None
    assert "private-secret" in str(failure.exc_info[1])


def test_the_artifact_key_and_filename_follow_the_shared_contract() -> None:
    export_id = "3f1b2c4d-0000-4000-8000-000000000000"
    filename = build_export_filename(export_id, "tsv", True)
    assert filename == f"soymutdb_export_{export_id}.tsv.gz"
    assert build_export_artifact_key(export_id, filename) == (
        f"exports/{export_id}/{filename}"
    )
    # The API re-derives the same name when it signs a download URL.
    assert build_export_filename(export_id, "tsv", False).endswith(".tsv")


def test_the_artifact_content_is_json_lines(monkeypatch, tmp_path: Path) -> None:
    """The produced file is the public artifact: no internal join keys."""
    captured: dict = {}

    class _Rows:
        def __iter__(self):
            return iter([_row()])

        def close(self):
            pass

    class _DataSession(_FakeSession):
        def execute(self, query, parameters=None, **kwargs):
            if "variant_exports" in str(query):
                return super().execute(query, parameters, **kwargs)
            return _Rows()

    data_session = _DataSession("pending")
    monkeypatch.setattr(export_task, "get_db", _ctx(data_session))
    monkeypatch.setattr(export_task, "get_setting", lambda *a, **k: "exports")
    monkeypatch.setattr(
        export_task,
        "upload_large_file",
        lambda local, key: captured.update(local=local, key=key),
    )
    monkeypatch.setattr(export_task.export_variants, "update_state", lambda **k: None)
    # The produced file must survive the call for the assertion below.
    monkeypatch.setattr(
        export_task.tempfile, "TemporaryDirectory", lambda: _TmpDir(tmp_path)
    )

    export_task.export_variants.run(
        "export-1", {"release_key": "7", "assembly": "Wm82.a4.v1"}, "json", False
    )

    lines = Path(captured["local"]).read_text(encoding="utf-8").strip().splitlines()
    record = json.loads(lines[0])
    assert record["release_key"] == "7"
    assert "gene_surrogate_id" not in record
    assert "mutant_line_surrogate_id" not in record
    # The object lives in the export bucket under the shared key contract;
    # the API signs exactly this path when it hands out a download link.
    assert captured["key"].endswith(
        "exports/export-1/soymutdb_export_export-1.json"
    )


class _TmpDir:
    """Minimal TemporaryDirectory stand-in so the artifact survives the call."""

    def __init__(self, path: Path) -> None:
        self.name = str(path)

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, *exc: object) -> bool:
        return False


def _row(**overrides) -> tuple:
    values = {
        "release_key": "7",
        "assembly_key": "Wm82.a4.v1",
        "chromosome": "chr01",
        "position": 1000,
        "variant_id": "12610413239088682210",
        "ref_allele": "A",
        "alt_allele": "G",
        "variant_type": "SNP",
        "variant_subtype": "SNV",
        "impact": "MODERATE",
        "quality_score": 99.0,
        "allele_frequency": 0.25,
        "zygosity": "het",
        "gene_id": "Glyma.01G000100",
        "gene_symbol": "Glyma.01G000100",
        "mutant_public_id": "MUT-000042",
        "hgvs_c": "c.1A>G",
        "hgvs_p": "p.Met1Val",
        "read_depth": 42,
        "filter_status": "PASS",
    }
    values.update(overrides)
    return tuple(values[column] for column in export_task.EXPORT_COLUMNS)


def _ctx(session):
    from contextlib import contextmanager

    @contextmanager
    def database():
        yield session

    return database
