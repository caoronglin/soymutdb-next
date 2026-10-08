"""BLAST task idempotency and job-status tests (no docker, no DB).

Runs the real ``run_blast`` task against a fake sync session and mocked
BLAST/S3 internals: re-deliveries of the same event (same idempotency key)
must be skipped, the job must advance pending -> running -> completed /
failed, and the payload contract must be validated.
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from soymutdb_worker.shared import BLAST_RUN_TASK, JobPayload
from soymutdb_worker.tasks import blast as blast_module


class _FakeResult:
    def __init__(self, rows: list, rowcount: int | None = None):
        self._rows = rows
        self.rowcount = rowcount

    def first(self):
        return self._rows[0] if self._rows else None


def _extract(value):
    """Unwrap BindParameter / enum members to plain values."""
    while hasattr(value, "value") and not isinstance(value, str):
        value = value.value
    return value


class FakeSession:
    def __init__(self, status: str | None = "pending", rowcount: int = 1):
        self.status = status
        self.rowcount = rowcount
        self.inserted_hits: list[dict] = []
        self.deleted_hits = 0
        # Every row update this fake was asked to persist, so a test can assert
        # what the job row will actually carry (error reason, query_len)
        # instead of inferring it from the task's return value.
        self.updates: list[dict] = []
        self.error: str | None = None
    def execute(self, stmt, params=None):
        table = getattr(stmt, "table", None)
        table_name = getattr(table, "name", None)
        if table_name == "blast_hits":
            if params:
                self.inserted_hits.extend(params)
            return _FakeResult([], rowcount=len(params) if params else 0)
        if table is not None:
            values = {
                getattr(key, "name", key): _extract(value)
                for key, value in dict(getattr(stmt, "_values", {}) or {}).items()
            }
            if values:
                self.updates.append(values)
            if "error_message" in values:
                self.error = values["error_message"]
            if "status" in values:
                self.status = values["status"]
                return _FakeResult([], rowcount=self.rowcount)
        return _FakeResult(
            [(self.status,)] if self.status is not None else [], rowcount=self.rowcount
        )


class FakeTask:
    def __init__(self):
        self.states = []

    def update_state(self, **kwargs):
        self.states.append(kwargs)


def _call_task(task: Any, *args, **kwargs):
    """Invoke the raw task function (bypassing Celery's bound-task wrapper)."""
    return task.run.__func__(*args, **kwargs)


def _payload(job_id: str | None = None, task_name: str = BLAST_RUN_TASK) -> dict:
    job_id = job_id or str(uuid.uuid4())
    now = datetime.now(UTC)
    p = JobPayload(
        job_id=job_id,
        task_name=task_name,
        payload={
            "job_id": job_id,
            "program": "blastp",
            "database": "williams82_prot",
            "sequence": "ATGCAAGCTTAGCTAGGCTAGGCTAGGC",
            "evalue": 0.001,
            "max_target_seqs": 10,
        },
        idempotency_key=f"blast:{job_id}",
        created_at=now,
        updated_at=now,
    )
    return p.model_dump(mode="json")


@contextmanager
def _fake_db(session: FakeSession):
    yield session


def _monkeypatch_execution(monkeypatch, *, fail: bool = False) -> None:
    monkeypatch.setattr(blast_module, "get_blast_db_path", lambda db, **kw: Path("/tmp/db"))
    monkeypatch.setattr(blast_module, "validate_diamond_parameters", lambda p: dict(p or {}))
    if fail:

        def boom(*args, **kwargs):
            raise RuntimeError("search binary exploded")

        monkeypatch.setattr(blast_module, "run_blast_command", boom)
    else:
        monkeypatch.setattr(blast_module, "run_blast_command", lambda **kw: None)
    monkeypatch.setattr(
        blast_module,
        "parse_diamond_tabular",
        lambda path: {"hits": [], "total_hits": 0, "query_len": 0},
    )
    monkeypatch.setattr(blast_module, "_result_file_metadata", lambda p: ("abc123", 12))
    monkeypatch.setattr(blast_module, "upload_file", lambda *a, **k: None)
    monkeypatch.setattr(
        blast_module, "generate_presigned_url", lambda *a, **k: "https://s3.example/x"
    )


def test_redelivery_of_completed_job_is_skipped(monkeypatch) -> None:
    """Idempotency: same event re-sent after completion must not re-run."""
    payload = _payload()
    session = FakeSession(status="completed")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    # If the task actually re-runs BLAST, this raises.
    _monkeypatch_execution(monkeypatch)

    result = _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert result["skipped"] is True
    assert session.status == "completed"


def test_cancelled_job_is_skipped(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="cancelled")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch)

    result = _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert result["skipped"] is True


def test_missing_job_row_is_skipped(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status=None)
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch)

    result = _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert result["skipped"] is True


def test_successful_run_advances_status_to_completed(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="pending")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch)

    result = _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert result["total_hits"] == 0
    assert result["result_s3_path"] == "blast-results/" + payload["payload"]["job_id"] + ".txt"
    # pending -> running -> completed
    assert session.status == "completed"


def test_failed_run_marks_job_failed(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="pending")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch, fail=True)

    with pytest.raises(RuntimeError, match="search binary exploded"):
        _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert session.status == "failed"


def test_wrong_task_name_in_payload_is_rejected() -> None:
    payload = _payload(task_name="soymutdb_worker.tasks.blast.run_blast.other")
    with pytest.raises(ValueError, match="does not match"):
        _call_task(blast_module.run_blast, FakeTask(), payload=payload)


def test_unknown_payload_version_is_rejected() -> None:
    payload = _payload()
    payload["payload_version"] = 999
    with pytest.raises(Exception):
        _call_task(blast_module.run_blast, FakeTask(), payload=payload)


def test_legacy_kwargs_dispatch_still_works(monkeypatch) -> None:
    """Direct dispatch with plain kwargs (pre-outbox callers) keeps working."""
    job_id = str(uuid.uuid4())
    session = FakeSession(status="pending")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch)

    result = _call_task(
        blast_module.run_blast,
        FakeTask(),
        job_id=job_id,
        program="blastp",
        database="williams82_prot",
        sequence="MKTIIALSYIFCLVFADYKDDDDKTRWQYNE",
    )

    assert result["total_hits"] == 0
    assert session.status == "completed"


def test_legacy_kwargs_require_job_id() -> None:
    with pytest.raises(TypeError):
        _call_task(blast_module.run_blast, FakeTask(), program="blastp")


# ---------------------------------------------------------------------------
# Result persistence, MinIO metadata and process isolation
# ---------------------------------------------------------------------------


def _hit_row(hsp_num: int = 1) -> dict:
    return {
        "hsp_num": hsp_num,
        "subject_id": f"Glyma.01G000100.{hsp_num}",
        "subject_title": "soybean gene",
        "percent_identity": 98.5,
        "alignment_length": 120,
        "mismatches": 1,
        "gap_opens": 1,
        "query_start": 1,
        "query_end": 120,
        "subject_start": 10,
        "subject_end": 129,
        "evalue": 1e-40,
        "bit_score": 200.5,
        "query_strand": "plus",
        "subject_strand": "plus",
    }


def test_hits_persisted_and_uploaded_with_metadata(monkeypatch) -> None:
    """Completed run stores hits via BlastHitStore and uploads raw output
    to MinIO with checksum/size metadata (key contains the job id)."""
    payload = _payload()
    job_id = payload["payload"]["job_id"]
    session = FakeSession(status="pending")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    monkeypatch.setattr(blast_module, "get_blast_db_path", lambda db, **kw: "/tmp/db")
    monkeypatch.setattr(blast_module, "run_blast_command", lambda **kw: None)
    monkeypatch.setattr(
        blast_module,
        "parse_diamond_tabular",
        lambda path: {
            "hits": [_hit_row(1), _hit_row(2)],
            "total_hits": 2,
            "query_len": 120,
        },
    )
    monkeypatch.setattr(blast_module, "_result_file_metadata", lambda p: ("deadbeef", 42))
    uploads = {}
    monkeypatch.setattr(
        blast_module,
        "upload_file",
        lambda p, s3path, **kw: uploads.update({"path": p, "s3": s3path, **kw}),
    )
    monkeypatch.setattr(
        blast_module, "generate_presigned_url", lambda *a, **k: "https://s3.example/x"
    )

    result = _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert result["total_hits"] == 2
    assert result["hits_persisted"] == 2
    assert result["checksum"] == "deadbeef"
    # Raw output object: bucket/key — the key contains the job id and the
    # metadata carries checksum + size.
    assert uploads["s3"] == f"blast-dbs/blast-results/{job_id}.txt"
    assert uploads["metadata"] == {"checksum": "deadbeef", "size": "42"}
    # Hits were persisted (delete-then-insert) with job_id attached.
    assert len(session.inserted_hits) == 2
    assert all(hit["job_id"] == job_id for hit in session.inserted_hits)
    assert session.status == "completed"


def test_redelivery_replaces_hits_without_duplication(monkeypatch) -> None:
    """A second delivery of the same event re-inserts rows but never leaves
    two result sets behind (delete-then-insert per job)."""
    payload = _payload()
    job_id = payload["payload"]["job_id"]
    session = FakeSession(status="running")  # resume path after crash
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    monkeypatch.setattr(blast_module, "get_blast_db_path", lambda db, **kw: "/tmp/db")
    monkeypatch.setattr(blast_module, "run_blast_command", lambda **kw: None)
    monkeypatch.setattr(
        blast_module,
        "parse_diamond_tabular",
        lambda path: {"hits": [_hit_row(1)], "total_hits": 1, "query_len": 100},
    )
    monkeypatch.setattr(blast_module, "_result_file_metadata", lambda p: ("abc", 1))
    monkeypatch.setattr(blast_module, "upload_file", lambda *a, **k: None)
    monkeypatch.setattr(
        blast_module, "generate_presigned_url", lambda *a, **k: "https://s3.example/x"
    )

    _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert len(session.inserted_hits) == 1
    assert session.inserted_hits[0]["job_id"] == job_id
    assert session.status == "completed"


def test_result_file_metadata_sha256(tmp_path) -> None:
    """_result_file_metadata returns the real sha256 + byte size."""
    out = tmp_path / "results.json"
    out.write_bytes(b"hello world")
    checksum, size = blast_module._result_file_metadata(out)
    assert size == 11
    assert checksum == hashlib.sha256(b"hello world").hexdigest()


def test_run_blast_command_isolates_env_and_forbids_shell(monkeypatch, tmp_path) -> None:
    """subprocess.run gets a minimal env, no shell, and a pure arg list."""
    import subprocess

    diamond = tmp_path / "diamond"
    diamond.touch()
    diamond.chmod(0o755)
    monkeypatch.setattr(blast_module, "DIAMOND_BIN", diamond)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(blast_module.subprocess, "run", fake_run)

    blast_module.run_blast_command(
        "blastp",
        Path("/tmp/db"),
        Path("/tmp/q.fa"),
        Path("/tmp/out.txt"),
        evalue=0.01,
        extra_args={"gapopen": 5},
    )

    assert captured["kwargs"]["shell"] is False
    env = captured["kwargs"]["env"]
    assert env is not None
    assert "PATH" in env
    assert "HOME" in env
    # No ambient secrets from the parent environment.
    assert env.get("AWS_SECRET_ACCESS_KEY") is None
    cmd = captured["cmd"]
    assert cmd[0] == str(diamond)
    assert cmd[1] == "blastp"
    assert "--gapopen" in cmd and "5" in cmd
    # NCBI-only flags must never reach DIAMOND.
    assert "-dust" not in cmd and "--dust" not in cmd


def test_run_blast_command_rejects_disallowed_parameter(monkeypatch, tmp_path) -> None:
    """Unknown parameters are rejected, never forwarded to the CLI."""
    diamond = _installed(tmp_path)
    monkeypatch.setattr(blast_module, "DIAMOND_BIN", diamond)

    with pytest.raises(ValueError, match="Disallowed DIAMOND parameter"):
        blast_module.run_blast_command(
            "blastp",
            Path("/tmp/db"),
            Path("/tmp/q.fa"),
            Path("/tmp/out.txt"),
            extra_args={"output": "/etc/passwd"},  # injection attempt
        )


def test_timeout_marks_job_failed(monkeypatch) -> None:
    """A wall-clock timeout advances the job to failed (not left running)."""
    import subprocess

    payload = _payload()
    session = FakeSession(status="pending")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    monkeypatch.setattr(blast_module, "get_blast_db_path", lambda db, **kw: "/tmp/db")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("diamond", 3600)

    monkeypatch.setattr(blast_module, "run_blast_command", timeout)
    monkeypatch.setattr(
        blast_module,
        "parse_diamond_tabular",
        lambda path: {"hits": [], "total_hits": 0, "query_len": 0},
    )

    with pytest.raises(subprocess.TimeoutExpired):
        _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert session.status == "failed"


def test_error_message_scrubs_query_sequence() -> None:
    """Persisted errors never echo the full query sequence."""
    seq = "ATGCAAGCTTAGCTAGGCTAGGCTAGGC"
    msg = blast_module.sanitize_error_message(
        f"BLAST died near {seq} in the alignment", query_sequence=seq
    )
    assert seq not in msg
    assert "<query-sequence>" in msg
    # Long errors are truncated.
    long_msg = blast_module.sanitize_error_message("x" * 5000)
    assert len(long_msg) <= blast_module.MAX_ERROR_LENGTH


# ---------------------------------------------------------------------------
# Multi-genome database whitelist / path mapping (Wave 2-D)
# ---------------------------------------------------------------------------


def test_get_blast_db_path_uses_whitelist_mapping(monkeypatch, tmp_path) -> None:
    """A versioned basename is preserved when resolving the DIAMOND index."""
    base = tmp_path / "wm82.a2.v1"
    Path(f"{base}.dmnd").write_text("index")
    monkeypatch.setattr(blast_module, "BLAST_DATABASE_PATHS", {"wm82.a2.v1": str(base)})
    assert blast_module.get_blast_db_path("wm82.a2.v1") == base


def test_get_blast_db_path_rejects_a_legacy_blast_index(monkeypatch, tmp_path) -> None:
    """A makeblastdb product is not a DIAMOND index and must not be used as one."""
    base = tmp_path / "wm82.a2.v1"
    for suffix in (".pin", ".phr", ".psq"):
        Path(f"{base}{suffix}").write_text("index")
    monkeypatch.setattr(blast_module, "BLAST_DATABASE_PATHS", {"wm82.a2.v1": str(base)})
    with pytest.raises(blast_module.DatabaseIndexUnavailable):
        blast_module.get_blast_db_path("wm82.a2.v1")


def test_get_blast_db_path_rejects_unlisted_database_when_whitelist_configured(
    monkeypatch,
) -> None:
    """Unlisted names — including traversal payloads — are refused outright."""
    monkeypatch.setattr(
        blast_module,
        "BLAST_DATABASE_PATHS",
        {"wm82.a2.v1": "/data/genomes/wm82.a2.v1/wm82.a2.v1"},
    )
    with pytest.raises(ValueError, match="whitelist"):
        blast_module.get_blast_db_path("hacked_db")
    with pytest.raises(ValueError, match="whitelist"):
        blast_module.get_blast_db_path("../../etc/passwd")
    with pytest.raises(ValueError, match="empty"):
        blast_module.get_blast_db_path("")


def test_get_blast_db_path_legacy_fallback_uses_cache(monkeypatch, tmp_path) -> None:
    """Empty whitelist keeps the legacy cache behaviour for valid names."""
    monkeypatch.setattr(blast_module, "BLAST_DATABASE_PATHS", {})
    monkeypatch.setattr(blast_module, "BLAST_CACHE_DIR", tmp_path)
    (tmp_path / "williams82_prot.dmnd").write_text("index")

    assert blast_module.get_blast_db_path("williams82_prot") == tmp_path / "williams82_prot"


def test_get_blast_db_path_legacy_still_rejects_traversal(monkeypatch) -> None:
    monkeypatch.setattr(blast_module, "BLAST_DATABASE_PATHS", {})
    with pytest.raises(ValueError, match="Invalid BLAST database name"):
        blast_module.get_blast_db_path("../../etc/passwd")


def test_run_blast_forwards_payload_database_to_path_resolver(monkeypatch) -> None:
    """The payload ``database`` (name) reaches get_blast_db_path unchanged."""
    payload = _payload()
    payload["payload"]["database"] = "wm82.a2.v1"
    session = FakeSession(status="pending")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        blast_module,
        "get_blast_db_path",
        lambda db, **kw: captured.setdefault("db", db) or "/tmp/db",
    )
    monkeypatch.setattr(blast_module, "run_blast_command", lambda **kw: None)
    monkeypatch.setattr(
        blast_module,
        "parse_diamond_tabular",
        lambda path: {"hits": [], "total_hits": 0, "query_len": 0},
    )
    monkeypatch.setattr(blast_module, "_result_file_metadata", lambda p: ("abc", 1))
    monkeypatch.setattr(blast_module, "upload_file", lambda *a, **k: None)
    monkeypatch.setattr(
        blast_module, "generate_presigned_url", lambda *a, **k: "https://s3.example/x"
    )

    result = _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert captured["db"] == "wm82.a2.v1"
    assert result["total_hits"] == 0


def test_run_blast_with_unlisted_database_fails_job(monkeypatch) -> None:
    """The worker refuses unwhitelisted databases and marks the job failed."""
    payload = _payload()
    payload["payload"]["database"] = "not_whitelisted"
    session = FakeSession(status="pending")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    monkeypatch.setattr(
        blast_module,
        "BLAST_DATABASE_PATHS",
        {"williams82_prot": "/data/dbs/williams82_prot"},
    )
    # get_blast_db_path is NOT mocked: the real whitelist check must reject.

    with pytest.raises(ValueError, match="whitelist"):
        _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert session.status == "failed"


# ---------------------------------------------------------------------------
# DIAMOND backend
# ---------------------------------------------------------------------------
# DIAMOND is the default for the programs it implements, because it answers the
# same question 100-1000x faster. Two things differ from BLAST and both are
# silent when wrong: the flags (`--max-target-seqs`, not `-max_target_seqs`) and
# the output format (there is no `-outfmt 15`).


def test_diamond_command_uses_diamond_flags_and_explicit_columns(tmp_path) -> None:
    """The argv is built as a list, with DIAMOND's own spelling of every flag."""
    cmd = blast_module.build_diamond_command(
        "blastp",
        Path("/db/wm82.dmnd"),
        Path("/tmp/q.faa"),
        Path("/tmp/out.txt"),
        evalue=1e-5,
        max_target_seqs=50,
        num_threads=4,
        extra_args=None,
    )

    assert cmd[0] == str(blast_module.DIAMOND_BIN)
    assert cmd[1] == "blastp"
    assert "--db" in cmd and "--query" in cmd and "--out" in cmd
    # BLAST's single-dash spelling would make DIAMOND exit rc=1.
    assert "-db" not in cmd
    assert cmd[cmd.index("--evalue") + 1] == "1e-05"
    assert cmd[cmd.index("--max-target-seqs") + 1] == "50"
    assert cmd[cmd.index("--threads") + 1] == "4"
    # Columns are requested explicitly so a DIAMOND release that reorders its
    # default output cannot shift every parsed field by one.
    outfmt = cmd.index("--outfmt")
    assert cmd[outfmt + 1] == "6"
    columns = blast_module.DIAMOND_OUTFMT6_COLUMNS
    assert tuple(cmd[outfmt + 2 : outfmt + 2 + len(columns)]) == columns


def test_diamond_command_rejects_blast_only_parameters() -> None:
    """`-dust` means nothing to DIAMOND; forwarding it aborts the run."""
    with pytest.raises(ValueError, match="Disallowed DIAMOND parameter"):
        blast_module.build_diamond_command(
            "blastp",
            Path("/db/x.dmnd"),
            Path("/tmp/q.faa"),
            Path("/tmp/out.txt"),
            evalue=1e-5,
            max_target_seqs=50,
            num_threads=1,
            extra_args={"dust": "no"},
        )


def test_diamond_command_rejects_unsupported_word_size() -> None:
    with pytest.raises(ValueError, match="Disallowed DIAMOND parameter"):
        blast_module.build_diamond_command(
            "blastp",
            Path("/db/x.dmnd"),
            Path("/tmp/q.faa"),
            Path("/tmp/out.txt"),
            evalue=1e-5,
            max_target_seqs=50,
            num_threads=1,
            extra_args={"word_size": 5},
        )


def test_parse_diamond_tabular_maps_columns_without_recomputing_identity(tmp_path) -> None:
    """`pident` is already a percentage; dividing it by alignment length is the
    bug this test exists to catch (it reported ~0.05% identity)."""
    out = tmp_path / "results.txt"
    out.write_text(
        "q1\tGlyma.01G000100.Wm82.a6.v1\t98.734\t158\t2\t0\t1\t158\t103572\t103729\t1e-95\t342.0\n"
        "q1\tGlyma.01G000200.Wm82.a6.v1\t71.000\t100\t29\t0\t5\t104\t900\t999\t3e-20\t88.5\n",
        encoding="utf-8",
    )

    parsed = blast_module.parse_diamond_tabular(out)

    assert parsed["total_hits"] == 2
    assert parsed["query_id"] == "q1"
    first = parsed["hits"][0]
    assert first["subject_id"] == "Glyma.01G000100.Wm82.a6.v1"
    assert first["percent_identity"] == pytest.approx(98.734)
    assert first["alignment_length"] == 158
    assert first["mismatches"] == 2
    assert first["evalue"] == pytest.approx(1e-95)
    assert first["bit_score"] == pytest.approx(342.0)
    assert first["subject_start"] == 103572
    assert first["subject_strand"] == "plus"


def test_parse_diamond_tabular_derives_strand_from_coordinates(tmp_path) -> None:
    """outfmt 6 has no strand column; a descending subject range is minus."""
    out = tmp_path / "results.txt"
    out.write_text(
        "q1\ts1\t90.0\t100\t10\t0\t1\t100\t999\t900\t1e-30\t150.0\n",
        encoding="utf-8",
    )

    hit = blast_module.parse_diamond_tabular(out)["hits"][0]

    assert hit["subject_strand"] == "minus"
    assert hit["query_strand"] == "plus"


def test_parse_diamond_tabular_rejects_a_truncated_row(tmp_path) -> None:
    out = tmp_path / "results.txt"
    out.write_text("q1\ts1\t90.0\t100\n", encoding="utf-8")

    with pytest.raises(ValueError, match="expected"):
        blast_module.parse_diamond_tabular(out)


def test_parse_diamond_tabular_accepts_an_empty_result(tmp_path) -> None:
    """No hits is a valid answer, not a parse failure."""
    out = tmp_path / "results.txt"
    out.write_text("", encoding="utf-8")

    parsed = blast_module.parse_diamond_tabular(out)

    assert parsed["total_hits"] == 0
    assert parsed["hits"] == []


def _installed(tmp_path) -> Path:
    """A present, executable DIAMOND stand-in."""
    binary = tmp_path / "diamond"
    binary.touch()
    binary.chmod(0o755)
    return binary
