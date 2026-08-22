"""fastp task tests: execution, MinIO I/O, result_summary, failure paths.

No docker, no DB, no real fastp binary: ``subprocess.run`` is mocked to
write a realistic ``fastp.json`` / ``fastp.html`` into the temp dir, the S3
client is faked, and job status lives in a fake session.  Covers idempotent
re-delivery, single-/paired-end CLI construction, parameter whitelisting,
env isolation, scrubbed failures and the result_summary contract.
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import ClientError, EndpointConnectionError

from soymutdb_worker.shared import JobPayload
from soymutdb_worker.tasks.analyses import fastp as fastp_module
from soymutdb_worker.tasks.analyses.fastp import ANALYSIS_FASTP_TASK

FAKE_FASTQ_BYTES = b"fake fastq bytes"
FAKE_FASTQ_SHA256 = hashlib.sha256(FAKE_FASTQ_BYTES).digest()
INTEGRITY_ERROR = "analysis input failed integrity verification"
STORAGE_ERROR = "analysis object storage operation failed"

#: Realistic fastp >= 0.23 report (stats nested under ``summary``).
FASTP_JSON_FIXTURE = {
    "summary": {
        "before_filtering": {
            "total_reads": 1_000_000,
            "total_bases": 150_000_000,
            "q30_rate": 0.91,
            "duplication_rate": 0.12,
        },
        "after_filtering": {
            "total_reads": 900_000,
            "total_bases": 135_000_000,
            "q30_rate": 0.94,
        },
        "filtering_result": {
            "passed_filter_reads": 900_000,
            "low_quality_reads": 80_000,
            "too_many_N_reads": 5_000,
            "too_short_reads": 15_000,
        },
    }
}


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
    """Tracks status/result_summary writes against ``analysis_jobs``."""

    def __init__(self, status: str | None = "queued", rowcount: int = 1):
        self.status = status
        self.rowcount = rowcount
        self.result_summary: Any | None = None
        self.error_message: str | None = None

    def execute(self, stmt, params=None):
        table = getattr(stmt, "table", None)
        if table is not None and table.name == "analysis_jobs":
            values = {
                getattr(k, "name", k): _extract(v)
                for k, v in dict(getattr(stmt, "_values", {}) or {}).items()
            }
            if "status" in values:
                self.status = values["status"]
            if "result_summary" in values:
                self.result_summary = values["result_summary"]
            if "error_message" in values:
                self.error_message = values["error_message"]
            return _FakeResult([], rowcount=self.rowcount)
        return _FakeResult(
            [(self.status,)] if self.status is not None else [], rowcount=self.rowcount
        )


class FakeTask:
    def __init__(self):
        self.states = []

    def update_state(self, **kwargs):
        self.states.append(kwargs)


class FakeS3:
    """Stands in for the boto3 client: downloads write local files."""

    def __init__(self):
        self.downloads: list[tuple[str, str, str]] = []
        self.events: list[str] = []
        self.download_payloads: dict[str, bytes] = {}
        self.head_error: Exception | None = None
        self.download_error: Exception | None = None

    def head_object(self, *, Bucket: str, Key: str, ChecksumMode: str):
        self.events.append("head")
        if self.head_error is not None:
            raise self.head_error
        return {
            "ContentLength": len(FAKE_FASTQ_BYTES),
            "ContentType": "application/gzip",
            "ChecksumSHA256": base64.b64encode(FAKE_FASTQ_SHA256).decode("ascii"),
            "Metadata": {
                "declared-size": str(len(FAKE_FASTQ_BYTES)),
                "declared-content-type": "application/gzip",
                "declared-sha256": FAKE_FASTQ_SHA256.hex(),
            },
        }

    def download_file(self, bucket: str, key: str, local_path: str):
        self.events.append("download")
        self.downloads.append((bucket, key, local_path))
        if self.download_error is not None:
            raise self.download_error
        Path(local_path).write_bytes(
            self.download_payloads.get(key, FAKE_FASTQ_BYTES)
        )


def test_oversized_input_is_rejected_before_download(monkeypatch):
    s3 = FakeS3()
    s3.head_object = lambda **kwargs: {
        "ContentLength": fastp_module.MAX_ANALYSIS_INPUT_SIZE + 1,
        "ContentType": "application/gzip",
        "ChecksumSHA256": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=",
        "Metadata": {
            "declared-size": str(fastp_module.MAX_ANALYSIS_INPUT_SIZE + 1),
            "declared-content-type": "application/gzip",
        },
    }

    with pytest.raises(ValueError, match="exceeds"):
        fastp_module.validate_remote_input(s3, "analyses/u/s/input/a.fq.gz")

    assert s3.downloads == []


def test_mismatched_mime_is_rejected_before_download():
    s3 = FakeS3()
    s3.head_object = lambda **kwargs: {
        "ContentLength": 10,
        "ContentType": "text/plain",
        "ChecksumSHA256": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=",
        "Metadata": {
            "declared-size": "10",
            "declared-content-type": "application/gzip",
        },
    }

    with pytest.raises(ValueError, match="MIME"):
        fastp_module.validate_remote_input(s3, "analyses/u/s/input/a.fq.gz")

    assert s3.downloads == []


def test_mismatched_checksum_is_rejected_before_download():
    s3 = FakeS3()
    s3.head_object = lambda **kwargs: {
        "ContentLength": 10,
        "ContentType": "application/gzip",
        "ChecksumSHA256": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=",
        "Metadata": {
            "declared-size": "10",
            "declared-content-type": "application/gzip",
            "declared-sha256": "62" * 32,
        },
    }

    with pytest.raises(ValueError, match="checksum does not match"):
        fastp_module.validate_remote_input(s3, "analyses/u/s/input/a.fq.gz")

    assert s3.downloads == []


def _call_task(task: Any, *args, **kwargs):
    """Invoke the raw task function (bypassing Celery's bound-task wrapper)."""
    return task.run.__func__(*args, **kwargs)


def _input_key(
    user_id: str,
    filename: str = "abc-R1.fastq.gz",
    *,
    upload_session_id: str | None = None,
) -> str:
    session_id = upload_session_id or str(uuid.uuid4())
    return f"analyses/{user_id}/{session_id}/input/{filename}"


def _payload(
    job_id: str | None = None,
    task_name: str = ANALYSIS_FASTP_TASK,
    input_objects: list[str] | None = None,
    params: dict | None = None,
    analysis_type: str = "fastp",
    user_id: str | None = None,
) -> dict:
    job_id = job_id or str(uuid.uuid4())
    user_id = user_id or str(uuid.uuid4())
    now = datetime.now(UTC)
    keys = input_objects if input_objects is not None else [_input_key(user_id)]
    p = JobPayload(
        job_id=job_id,
        task_name=task_name,
        payload={
            "job_id": job_id,
            "user_id": user_id,
            "analysis_type": analysis_type,
            "input_objects": keys,
            "params": params or {},
        },
        idempotency_key=f"fastp:{job_id}",
        created_at=now,
        updated_at=now,
    )
    return p.model_dump(mode="json")


@contextmanager
def _fake_db(session: FakeSession):
    yield session


def _paths_from_cmd(cmd: list[str]) -> dict[str, Path]:
    """Extract file arguments for -i/-o/-I/-O/-j/-h from a fastp argv."""
    out: dict[str, Path] = {}
    i = 1
    while i < len(cmd):
        if cmd[i] in ("-i", "-o", "-I", "-O", "-j", "-h"):
            out[cmd[i]] = Path(cmd[i + 1])
            i += 2
        else:
            i += 1
    return out


def _monkeypatch_environment(
    monkeypatch,
    session: FakeSession,
    captured: dict | None = None,
    *,
    rc: int = 0,
    stderr: str = "",
    raise_timeout: bool = False,
    json_fixture: dict | None = None,
    fastp_missing: bool = False,
) -> dict:
    """Wire fakes for S3, DB and the fastp subprocess."""
    captured = captured if captured is not None else {}
    monkeypatch.setattr(fastp_module, "ANALYSES_BUCKET", "analyses")
    monkeypatch.setattr(fastp_module, "get_db", lambda: _fake_db(session))
    s3 = FakeS3()
    monkeypatch.setattr(fastp_module, "get_s3_client", lambda: s3)
    captured["s3"] = s3
    uploads = []
    monkeypatch.setattr(
        fastp_module, "upload_file", lambda local, s3path, **kw: uploads.append(s3path)
    )
    captured["uploads"] = uploads
    if fastp_missing:
        monkeypatch.setattr(fastp_module.shutil, "which", lambda name: None)
    else:
        monkeypatch.setattr(
            fastp_module.shutil, "which", lambda name: "/usr/bin/fastp"
        )

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        if raise_timeout:
            raise subprocess.TimeoutExpired(cmd[0], 600)
        paths = _paths_from_cmd(cmd)
        paths["-j"].write_text(
            json.dumps(json_fixture if json_fixture is not None else FASTP_JSON_FIXTURE)
        )
        paths["-h"].write_text("<html><body>fastp report</body></html>")
        for flag in ("-o", "-O"):
            if flag in paths:
                paths[flag].write_bytes(b"fake trimmed fastq")
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=stderr)

    monkeypatch.setattr(fastp_module.subprocess, "run", fake_run)
    return captured


# ---------------------------------------------------------------------------
# Idempotency / claim behaviour
# ---------------------------------------------------------------------------


def test_redelivery_of_succeeded_job_is_skipped(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="succeeded")
    _monkeypatch_environment(monkeypatch, session)

    result = _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert result["skipped"] is True
    assert session.status == "succeeded"


def test_cancelled_job_is_skipped(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="cancelled")
    _monkeypatch_environment(monkeypatch, session)

    result = _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert result["skipped"] is True


def test_missing_job_row_is_skipped(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status=None)
    _monkeypatch_environment(monkeypatch, session)

    result = _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert result["skipped"] is True


# ---------------------------------------------------------------------------
# Success paths
# ---------------------------------------------------------------------------


def test_successful_single_end_run_uploads_and_summarizes(monkeypatch) -> None:
    """SE run: outputs uploaded under analyses/{job}/output/, summary parsed
    and persisted to result_summary, status advanced to succeeded."""
    payload = _payload()
    job_id = payload["payload"]["job_id"]
    session = FakeSession(status="queued")
    captured = _monkeypatch_environment(monkeypatch, session)

    result = _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert result["skipped"] is False
    assert result["json_object"] == f"analyses/{job_id}/output/fastp.json"
    assert result["html_object"] == f"analyses/{job_id}/output/fastp.html"
    # Both outputs uploaded to the analyses bucket under the job output prefix.
    assert captured["uploads"] == [
        f"analyses/analyses/{job_id}/output/fastp.json",
        f"analyses/analyses/{job_id}/output/fastp.html",
    ]
    # Single-end CLI: exactly one -i / -o pair.
    cmd = captured["cmd"]
    assert cmd[0] == "/usr/bin/fastp"
    assert "-I" not in cmd and "-O" not in cmd
    assert captured["s3"].downloads[0][1] == payload["payload"]["input_objects"][0]
    assert captured["s3"].events[:2] == ["head", "download"]
    # Result summary persisted on the job row.
    assert session.status == "succeeded"
    assert session.result_summary is not None
    assert session.result_summary["before_filtering"]["reads"] == 1_000_000
    assert session.result_summary["before_filtering"]["bases"] == 150_000_000
    assert session.result_summary["before_filtering"]["q30_rate"] == pytest.approx(0.91)
    assert session.result_summary["before_filtering"]["duplication"] == pytest.approx(
        0.12
    )
    assert session.result_summary["after_filtering"]["reads"] == 900_000
    assert session.result_summary["after_filtering"]["q30_rate"] == pytest.approx(0.94)
    assert session.result_summary["filtering_result"]["passed_filter_reads"] == 900_000
    assert session.result_summary["output"] == {
        "html": f"analyses/{job_id}/output/fastp.html",
        "json": f"analyses/{job_id}/output/fastp.json",
    }


def test_paired_end_run_builds_r1_r2_cli(monkeypatch) -> None:
    """Two upload sessions form one paired-end task without sharing job_id."""
    job_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    payload = _payload(
        job_id=job_id,
        user_id=user_id,
        input_objects=[
            _input_key(user_id, "abc-R1.fastq.gz"),
            _input_key(user_id, "abc-R2.fastq.gz"),
        ],
    )
    session = FakeSession(status="queued")
    captured = _monkeypatch_environment(monkeypatch, session)

    result = _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert result["skipped"] is False
    cmd = captured["cmd"]
    assert "-i" in cmd and "-o" in cmd and "-I" in cmd and "-O" in cmd
    assert cmd[cmd.index("-i") + 1].endswith("input_R1.fastq.gz")
    assert cmd[cmd.index("-I") + 1].endswith("input_R2.fastq.gz")
    assert session.status == "succeeded"


def test_downloaded_input_checksum_mismatch_fails_before_pipeline(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="queued")
    captured = _monkeypatch_environment(monkeypatch, session)
    key = payload["payload"]["input_objects"][0]
    captured["s3"].download_payloads[key] = b"X" * len(FAKE_FASTQ_BYTES)

    with pytest.raises(ValueError, match=f"^{INTEGRITY_ERROR}$"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "failed"
    assert session.error_message == INTEGRITY_ERROR
    assert "cmd" not in captured
    assert captured["uploads"] == []


def test_downloaded_input_size_mismatch_fails_before_pipeline(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="queued")
    captured = _monkeypatch_environment(monkeypatch, session)
    key = payload["payload"]["input_objects"][0]
    captured["s3"].download_payloads[key] = FAKE_FASTQ_BYTES + b"!"

    with pytest.raises(ValueError, match=f"^{INTEGRITY_ERROR}$"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "failed"
    assert session.error_message == INTEGRITY_ERROR
    assert "cmd" not in captured
    assert captured["uploads"] == []


def test_paired_end_second_input_integrity_mismatch_fails_before_pipeline(
    monkeypatch,
) -> None:
    user_id = str(uuid.uuid4())
    input_objects = [
        _input_key(user_id, "abc-R1.fastq.gz"),
        _input_key(user_id, "abc-R2.fastq.gz"),
    ]
    payload = _payload(user_id=user_id, input_objects=input_objects)
    session = FakeSession(status="queued")
    captured = _monkeypatch_environment(monkeypatch, session)
    captured["s3"].download_payloads[input_objects[1]] = b"X" * len(
        FAKE_FASTQ_BYTES
    )

    with pytest.raises(ValueError, match=f"^{INTEGRITY_ERROR}$"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert [item[1] for item in captured["s3"].downloads] == input_objects
    assert session.status == "failed"
    assert session.error_message == INTEGRITY_ERROR
    assert "cmd" not in captured
    assert captured["uploads"] == []


def test_param_whitelist_mapping(monkeypatch) -> None:
    """Known params map to fastp flags; unknown params are rejected."""
    payload = _payload(
        params={
            "trim_front1": 10,
            "trim_tail1": 5,
            "quality_phred": 20,
            "thread": 4,
            "cut_front": True,
            "cut_tail": False,
            "min_length": 36,
        }
    )
    session = FakeSession(status="queued")
    captured = _monkeypatch_environment(monkeypatch, session)

    _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    cmd = captured["cmd"]
    assert "--trim_front1" in cmd
    assert cmd[cmd.index("--trim_front1") + 1] == "10"
    assert "--qualified_quality_phred" in cmd
    assert cmd[cmd.index("--qualified_quality_phred") + 1] == "20"
    assert "--thread" in cmd
    assert cmd[cmd.index("--thread") + 1] == "4"
    # Boolean flags: bare when true, absent when false.
    assert "--cut_front" in cmd
    assert "--cut_tail" not in cmd
    assert session.status == "succeeded"


def test_disallowed_param_is_rejected(monkeypatch) -> None:
    """Unknown parameters never reach the CLI; the job lands in failed."""
    payload = _payload(params={"output": "/etc/passwd"})
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    with pytest.raises(ValueError, match="Disallowed fastp parameter"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    # Validation failures are rejected before the job is claimed (fail-fast,
    # mirroring the BLAST task): the status is left untouched.
    assert session.status == "queued"


def test_input_key_without_uuid_upload_session_is_rejected(monkeypatch) -> None:
    user_id = str(uuid.uuid4())
    payload = _payload(
        user_id=user_id,
        input_objects=[f"analyses/{user_id}/not-a-session/input/other.fastq.gz"],
    )
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    with pytest.raises(ValueError, match="upload session"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "queued"


def test_input_key_owned_by_another_user_is_rejected(monkeypatch) -> None:
    user_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())
    payload = _payload(
        user_id=user_id,
        input_objects=[_input_key(other_user_id, "stolen.fastq.gz")],
    )
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    with pytest.raises(ValueError, match="does not belong"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "queued"


def test_legacy_unscoped_input_key_is_rejected(monkeypatch) -> None:
    payload = _payload(
        input_objects=[f"analyses/{uuid.uuid4()}/input/legacy.fastq.gz"]
    )
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    with pytest.raises(ValueError, match="user UUID"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "queued"


def test_payload_without_user_id_is_rejected(monkeypatch) -> None:
    payload = _payload()
    payload["payload"].pop("user_id")
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    with pytest.raises(ValueError, match="user_id"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "queued"


def test_three_input_objects_rejected(monkeypatch) -> None:
    job_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    payload = _payload(
        job_id=job_id,
        user_id=user_id,
        input_objects=[
            _input_key(user_id, "a.fq.gz"),
            _input_key(user_id, "b.fq.gz"),
            _input_key(user_id, "c.fq.gz"),
        ],
    )
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    with pytest.raises(ValueError, match="exactly 1 .* or 2"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "queued"


def test_wrong_task_name_in_payload_is_rejected() -> None:
    payload = _payload(task_name="soymutdb_worker.tasks.analyses.run_scanpy")
    with pytest.raises(ValueError, match="does not match"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)


def test_wrong_analysis_type_is_rejected(monkeypatch) -> None:
    payload = _payload(analysis_type="scanpy")
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    with pytest.raises(ValueError, match="not handled by run_fastp"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "queued"


def test_legacy_kwargs_dispatch_still_works(monkeypatch) -> None:
    job_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    result = _call_task(
        fastp_module.run_fastp,
        FakeTask(),
        job_id=job_id,
        user_id=user_id,
        input_objects=[_input_key(user_id, "legacy.fq.gz")],
        params={"quality_phred": 15},
    )

    assert result["skipped"] is False
    assert session.status == "succeeded"


def test_legacy_kwargs_without_user_id_are_rejected(monkeypatch) -> None:
    job_id = str(uuid.uuid4())
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    with pytest.raises(TypeError, match="user_id"):
        _call_task(
            fastp_module.run_fastp,
            FakeTask(),
            job_id=job_id,
            input_objects=[_input_key(str(uuid.uuid4()), "legacy.fq.gz")],
            params={},
        )

    assert session.status == "queued"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_head_client_error_is_redacted_before_persistence(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="queued")
    captured = _monkeypatch_environment(monkeypatch, session)
    secret = "INTERNAL_SENTINEL s3.internal:9000"
    captured["s3"].head_error = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": secret}},
        "HeadObject",
    )

    with pytest.raises(RuntimeError, match=f"^{STORAGE_ERROR}$"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "failed"
    assert session.error_message == STORAGE_ERROR
    assert secret not in (session.error_message or "")
    assert "cmd" not in captured
    assert captured["uploads"] == []


def test_download_botocore_error_is_redacted_before_persistence(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="queued")
    captured = _monkeypatch_environment(monkeypatch, session)
    secret = "INTERNAL_SENTINEL-download"
    captured["s3"].download_error = EndpointConnectionError(
        endpoint_url=f"https://{secret}"
    )

    with pytest.raises(RuntimeError, match=f"^{STORAGE_ERROR}$"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "failed"
    assert session.error_message == STORAGE_ERROR
    assert secret not in (session.error_message or "")
    assert "cmd" not in captured
    assert captured["uploads"] == []


def test_output_upload_error_is_redacted_before_persistence(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)
    secret = "INTERNAL_SENTINEL-output-upload"

    def fail_upload(*args, **kwargs):
        raise S3UploadFailedError(
            f"Failed to upload /tmp/private to analyses/private-key: {secret}"
        )

    monkeypatch.setattr(fastp_module, "upload_file", fail_upload)

    with pytest.raises(RuntimeError, match=f"^{STORAGE_ERROR}$"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "failed"
    assert session.error_message == STORAGE_ERROR
    assert secret not in (session.error_message or "")


def test_failed_run_marks_job_failed_with_scrubbed_error(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="queued")
    _monkeypatch_environment(
        monkeypatch, session, rc=1, stderr="\x00\x01boom \t\t  truncated log\n\n\n"
    )

    with pytest.raises(RuntimeError, match="fastp execution failed"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "failed"
    assert session.error_message is not None
    assert "boom" in session.error_message
    # Control characters / raw log layout are scrubbed from the stored error.
    assert "\x00" not in session.error_message
    assert "\x01" not in session.error_message
    assert "  " not in session.error_message


def test_timeout_marks_job_failed(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session, raise_timeout=True)

    with pytest.raises(subprocess.TimeoutExpired):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "failed"
    assert "timed out" in (session.error_message or "").lower() or "after" in (
        session.error_message or ""
    )


def test_missing_fastp_binary_marks_job_failed(monkeypatch) -> None:
    """No fastp in PATH → clear RuntimeError and a failed job (not a crash)."""
    payload = _payload()
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session, fastp_missing=True)

    with pytest.raises(RuntimeError, match="fastp binary not found"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "failed"
    assert session.error_message is not None
    assert "fastp binary not found" in session.error_message


def test_oversized_json_report_marks_job_failed(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="queued")
    captured = _monkeypatch_environment(monkeypatch, session)
    monkeypatch.setattr(fastp_module, "FASTP_MAX_JSON_SIZE", 10)

    with pytest.raises(RuntimeError, match="parsing cap"):
        _call_task(fastp_module.run_fastp, FakeTask(), payload=payload)

    assert session.status == "failed"
    # Outputs were uploaded only after successful parsing — nothing stored.
    assert captured["uploads"] == []


# ---------------------------------------------------------------------------
# Command construction / process isolation
# ---------------------------------------------------------------------------


def test_run_fastp_command_isolates_env_and_forbids_shell(monkeypatch) -> None:
    """subprocess.run gets a minimal env, no shell and a pure arg list."""
    import os

    os.environ["AWS_SECRET_ACCESS_KEY"] = "topsecret"
    monkeypatch.setattr(fastp_module.shutil, "which", lambda name: "/usr/bin/fastp")
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(fastp_module.subprocess, "run", fake_run)

    fastp_module.run_fastp_command(
        input_paths=[Path("/tmp/in1.fq.gz"), Path("/tmp/in2.fq.gz")],
        output_paths=[Path("/tmp/out1.fq.gz"), Path("/tmp/out2.fq.gz")],
        json_path=Path("/tmp/fastp.json"),
        html_path=Path("/tmp/fastp.html"),
        params={"quality_phred": 20, "thread": 2},
    )

    assert captured["kwargs"]["shell"] is False
    env = captured["kwargs"]["env"]
    assert env is not None
    assert "PATH" in env
    # No ambient secrets from the parent environment leak into the child.
    assert env.get("AWS_SECRET_ACCESS_KEY") is None
    cmd = captured["cmd"]
    assert cmd[0] == "/usr/bin/fastp"
    assert "-i" in cmd and "-I" in cmd and "-o" in cmd and "-O" in cmd
    assert "-j" in cmd and "-h" in cmd
    assert "--qualified_quality_phred" in cmd


def test_parse_fastp_json_handles_legacy_top_level_layout(tmp_path) -> None:
    """Pre-0.23 reports keep before/after filtering at the top level."""
    legacy = {
        "before_filtering": {
            "total_reads": 500_000,
            "total_bases": 75_000_000,
            "q30_rate": 0.88,
            "duplication_rate": 0.2,
        },
        "after_filtering": {
            "total_reads": 450_000,
            "total_bases": 67_000_000,
            "q30_rate": 0.92,
        },
    }
    path = tmp_path / "fastp.json"
    path.write_text(json.dumps(legacy))
    parsed = fastp_module.parse_fastp_json(path)
    assert parsed["before_filtering"]["reads"] == 500_000
    assert parsed["after_filtering"]["q30_rate"] == pytest.approx(0.92)
    assert parsed["before_filtering"]["duplication"] == pytest.approx(0.2)


def test_sanitize_error_message_strips_control_chars() -> None:
    msg = fastp_module.sanitize_error_message("a\x00b\x01c\n\nd\t   e")
    assert msg == "abc d e"
    long_msg = fastp_module.sanitize_error_message("x" * 5000)
    assert len(long_msg) <= fastp_module.MAX_ERROR_LENGTH
